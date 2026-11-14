"""Bezpečné stahování cizích adres (animace, storyboardy): jen veřejné adresy, ruční přesměrování s kontrolou každého skoku,
omezení velikosti i celkové doby. Adresy pocházejí od cizích webů (metadata yt-dlp, HTML stránky), proto se nesmí dát přes ně
sahat do domácí sítě ani na správcovská rozhraní. Pro zkoušky na místní síti: `VIDDOWN_ALLOW_PRIVATE_PREVIEW=1`.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from .util import env_flag

MAX_HOPS = 5
_EXOTIC_IP = re.compile(r"^[0-9a-fx.:]+$", re.I)          # 127.1, 0177.0.0.1, 0x7f.1, 2130706433 …


def allow_private() -> bool:
    return env_flag("VIDDOWN_ALLOW_PRIVATE_PREVIEW")


def literal_ok(url: str) -> bool:
    """Bez DNS: http(s), hostitel se jménem nebo veřejnou IP. Zakázané: localhost, jména bez tečky nebo s koncovou tečkou, `.local`,
    `.internal`, `.lan`, jakýkoli tvar IP, který není přesně zapsaná veřejná adresa (127.1, osmičková čísla…)."""
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not host:
        return False
    if allow_private():
        return True
    if host == "localhost" or host.endswith(".") or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".corp")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if _EXOTIC_IP.match(host):                               # vypadá jako číslo, ale není to přesná IP: odmítnout
        return False
    return "." in host


def host_ok(url: str) -> bool:
    """`literal_ok` a navíc všechny adresy, na které se jméno přeloží, musí být veřejné (jinak by jméno mohlo mířit do sítě)."""
    if not literal_ok(url):
        return False
    if allow_private():
        return True
    host = urlsplit(url).hostname or ""
    try:
        ipaddress.ip_address(host)
        return True                                          # IP už ověřil literal_ok
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    addrs = {i[4][0].split("%")[0] for i in infos}
    try:
        return bool(addrs) and all(ipaddress.ip_address(a).is_global for a in addrs)
    except ValueError:
        return False


def fetch_limited(url: str, headers: dict, max_bytes: int, proxy: str | None = None, total_timeout: float = 60.0) -> tuple[int, dict, bytes] | None:
    """GET s ručními přesměrováními (nejvýš 5, každý skok se kontroluje), čtením po částech a celkovým časovým limitem.
    Vrací (stav, hlavičky, tělo), nebo None, když adresa není veřejná, přesměrování je moc, tělo přesáhne `max_bytes`
    nebo vyprší čas. Těla přesměrování se nečtou."""
    deadline = time.monotonic() + total_timeout
    kw = {"proxy": proxy} if proxy and proxy.startswith("http") else {}
    with httpx.Client(follow_redirects=False, timeout=min(30.0, total_timeout), headers=headers, **kw) as c:
        for _ in range(MAX_HOPS + 1):
            if not host_ok(url):
                return None
            with c.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                hdr = {k.lower(): v for k, v in r.headers.items()}
                try:
                    if int(hdr.get("content-length") or 0) > max_bytes:
                        return None
                except ValueError:
                    return None
                body = bytearray()
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > max_bytes or time.monotonic() > deadline:
                        return None
                return r.status_code, hdr, bytes(body)
    return None
