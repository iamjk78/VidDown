"""Bezpečné stahování cizích adres (animace, storyboardy): jen veřejné adresy, ruční přesměrování s kontrolou každého skoku,
omezení velikosti i celkové doby. Adresy pocházejí od cizích webů (metadata yt-dlp, HTML stránky), proto se nesmí dát přes ně
sahat do domácí sítě ani na správcovská rozhraní. Pro zkoušky na místní síti: `VIDDOWN_ALLOW_PRIVATE_PREVIEW=1`.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from .util import env_flag

MAX_HOPS = 5
_EXOTIC_IP = re.compile(r"^[0-9a-fx.:]+$", re.I)          # 127.1, 0177.0.0.1, 0x7f.1, 2130706433 …


class ProxyError(OSError):
    """Nastavená proxy se nedá použít (chybí podpora SOCKS, neznámé schéma): raději žádný dotaz než dotaz mimo proxy (prozradil by IP)."""


def proxy_kw(proxy: str | None) -> dict:
    """Parametr `proxy` pro `httpx` z nastavení: `http(s)://…` i `socks5://…` (potřebuje balíček socksio); adresa bez schématu se bere
    jako HTTP proxy. Nepoužitelná proxy vyhodí `ProxyError`, dotaz se nikdy tiše neodešle přímo."""
    p = (proxy or "").strip()
    if not p:
        return {}
    if "://" not in p:
        p = "http://" + p
    scheme = urlsplit(p).scheme.lower()
    if scheme in ("http", "https"):
        return {"proxy": p}
    if scheme in ("socks5", "socks5h", "socks4"):
        import importlib.util
        if importlib.util.find_spec("socksio") is None:
            raise ProxyError("proxy SOCKS vyžaduje balíček socksio (pip install 'httpx[socks]')")
        return {"proxy": p}
    raise ProxyError(f"nepodporované schéma proxy: {scheme}")


def allow_private() -> bool:
    return env_flag("VIDDOWN_ALLOW_PRIVATE_PREVIEW")


def _connect_host(url: str) -> str | None:
    """Jméno, na které se `httpx` skutečně připojí (IDNA 2008, malá písmena); jiný převod než v `getaddrinfo` (IDNA 2003) by dovolil
    obejít kontrolu (`evilß.com` → `evilss.com` při kontrole, `xn--evil-yna.com` při připojení). Neplatná adresa → None."""
    try:
        return httpx.URL(url).raw_host.decode("ascii").lower() or None
    except (httpx.InvalidURL, UnicodeError, ValueError):
        return None


def _global_ip(addr: ipaddress._BaseAddress) -> bool:
    """Veřejná adresa; u IPv6 s vloženou IPv4 (mapovaná, NAT64 64:ff9b::/96, 6to4 2002::/16) musí být veřejná i ta vložená."""
    if not addr.is_global:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return _global_ip(addr.ipv4_mapped)
        packed = addr.packed
        if packed[:12] == bytes.fromhex("0064ff9b0000000000000000"):
            return _global_ip(ipaddress.IPv4Address(packed[12:]))
        if packed[:2] == b"\x20\x02":
            return _global_ip(ipaddress.IPv4Address(packed[2:6]))
    return True


def literal_ok(url: str) -> bool:
    """Bez DNS: http(s), hostitel se jménem nebo veřejnou IP. Zakázané: localhost, jména bez tečky nebo s koncovou tečkou, `.local`,
    `.internal`, `.lan`, jakýkoli tvar IP, který není přesně zapsaná veřejná adresa (127.1, osmičková čísla…)."""
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    host = _connect_host(url) if u.scheme in ("http", "https") else None
    if not host:
        return False
    if allow_private():
        return True
    if host == "localhost" or host.endswith(".") or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".corp")):
        return False
    try:
        return _global_ip(ipaddress.ip_address(host))
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
    host = _connect_host(url) or ""
    try:
        ipaddress.ip_address(host)
        return True                                          # IP už ověřil literal_ok
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    addrs = {i[4][0].split("%")[0] for i in infos}
    try:
        return bool(addrs) and all(_global_ip(ipaddress.ip_address(a)) for a in addrs)
    except ValueError:
        return False


def _pin_address(host: str) -> str:
    """Adresa, na kterou se smí připojit. Kontroluje se při KAŽDÉM připojení (ne jen při předběžné kontrole), takže se DNS mezi
    kontrolou a spojením nemůže přepnout na místní síť (DNS rebinding). Všechny adresy jména musí být veřejné."""
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError) as e:
            raise httpcore.ConnectError(f"jméno nejde přeložit: {host}") from e
        addrs = [i[4][0].split("%")[0] for i in infos]
    if not addrs:
        raise httpcore.ConnectError(f"jméno nejde přeložit: {host}")
    if not allow_private():
        for a in addrs:
            try:
                ok = _global_ip(ipaddress.ip_address(a))
            except ValueError:
                ok = False
            if not ok:
                raise httpcore.ConnectError(f"adresa mimo veřejný internet ({host})")
    return addrs[0]


class _PinnedSyncBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        # TLS (SNI, ověření certifikátu) dál používá jméno z URL; mění se jen cíl připojení
        return super().connect_tcp(_pin_address(host), port, timeout=timeout, local_address=local_address, socket_options=socket_options)


class _PinnedAsyncBackend(httpcore.AnyIOBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ip = await asyncio.to_thread(_pin_address, host)
        return await super().connect_tcp(ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options)


class _PinnedTransport(httpx.HTTPTransport):
    def __init__(self):
        super().__init__()
        self._pool = httpcore.ConnectionPool(ssl_context=httpx.create_ssl_context(), network_backend=_PinnedSyncBackend(), http1=True, http2=False)


class _PinnedAsyncTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__()
        self._pool = httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(), network_backend=_PinnedAsyncBackend(), http1=True, http2=False)


def client_kw(proxy: str | None, asynchronous: bool = False) -> dict:
    """Parametry klienta httpx pro cizí adresy. Bez proxy se připojuje jen na ověřené adresy (`_pin_address`); s proxy se jméno
    přeloží až v proxy, takže tam kontrola připojení nejde a platí jen předběžná kontrola `host_ok`."""
    kw = proxy_kw(proxy)
    if not kw:
        kw["transport"] = _PinnedAsyncTransport() if asynchronous else _PinnedTransport()
    return kw


def fetch_limited(url: str, headers: dict, max_bytes: int, proxy: str | None = None, total_timeout: float = 60.0) -> tuple[int, dict, bytes] | None:
    """GET s ručními přesměrováními (nejvýš 5, každý skok se kontroluje), čtením po částech a celkovým časovým limitem.
    Vrací (stav, hlavičky, tělo), nebo None, když adresa není veřejná, přesměrování je moc, tělo přesáhne `max_bytes`
    nebo vyprší čas. Těla přesměrování se nečtou."""
    deadline = time.monotonic() + total_timeout
    try:
        return _fetch_limited(url, headers, max_bytes, proxy, deadline, total_timeout)
    except (httpx.InvalidURL, UnicodeError):                 # vadná adresa z cizího HTML nesmí shodit volající smyčku
        return None


def _fetch_limited(url: str, headers: dict, max_bytes: int, proxy: str | None, deadline: float, total_timeout: float):
    kw = client_kw(proxy)
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
