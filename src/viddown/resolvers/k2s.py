"""Keep2Share přes oficiální API (https://keep2share.github.io/api/).

Stahování jde jen přes veřejné API. Odpočet (chyba 41) a captchu (chyba 30) nikdy neobcházíme:
captchu vyřeší člověk (odpověď přijde zvenku, např. z Telegramu) a odpočet se jen počká.
Bez přihlášení se volá anonymně, s přihlášením (auth_token) jen když ho uživatel vyplnil.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from . import ResolveError

log = logging.getLogger("viddown.k2s")

API = "https://keep2share.cc/api/v2"
TIMEOUT = 30.0

# chybové kódy z dokumentace API (jen ty, které aplikace rozlišuje)
E_FREE_LIMIT_COUNT = 1       # počet stažení na účet vyčerpán
E_FREE_LIMIT_TRAFFIC = 2     # provoz vyčerpán
E_FREE_LIMIT_SIZE = 3        # soubor je pro volný účet příliš velký
E_PREMIUM_ONLY = 7           # jen prémiové stahování
E_PRIVATE = 8                # soukromý soubor
E_CAPTCHA_REQUIRED = 30      # je nutná captcha
E_CAPTCHA_INVALID = 31       # captcha špatně
E_LOGIN_RECAPTCHA = 33       # přihlášení vyžaduje ověření
E_FREE_KEY_WRONG = 40        # chybný klíč pro volné stahování
E_WAIT_FREE = 41             # čekání před volným stahováním
E_FILE_NOT_FOUND = 20        # soubor neexistuje


class K2SError(ResolveError):
    """Chyba API. `kind` slouží k rozhodování ve frontě, `code` je kód z API."""

    def __init__(self, message: str, code: int | None, kind: str, wait_seconds: float | None = None):
        super().__init__(message, kind)
        self.code = code
        self.wait_seconds = wait_seconds      # u čekání na volné stahování: doba z odpovědi (time_wait), pokud přišla


@dataclass
class Challenge:
    challenge: str
    captcha_url: str | None = None


_FILE_RE = re.compile(r"/(?:file|f)/([0-9a-zA-Z]+)", re.I)


def file_id_of(url: str) -> str | None:
    """Vytáhne file_id z adresy typu https://k2s.cc/file/<id>/<název>. Jiné adresy vrací None."""
    u = urlparse(url)
    if not u.netloc.lower().endswith(("k2s.cc", "keep2share.cc")):
        return None
    m = _FILE_RE.search(u.path)
    return m.group(1) if m else None


def _code_of(data: dict) -> int | None:
    # dokumentace uvádí errorCode; některé příklady používají code
    for k in ("errorCode", "code"):
        v = data.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _classify(code: int | None) -> str:
    return {
        E_FREE_LIMIT_COUNT: "limit_daily",
        E_FREE_LIMIT_TRAFFIC: "limit_daily",
        E_FREE_LIMIT_SIZE: "unsupported",
        E_PREMIUM_ONLY: "unsupported",
        E_PRIVATE: "gone",
        E_CAPTCHA_REQUIRED: "captcha",
        E_CAPTCHA_INVALID: "captcha",
        E_LOGIN_RECAPTCHA: "captcha",
        E_WAIT_FREE: "wait",
        E_FREE_KEY_WRONG: "wait",
        E_FILE_NOT_FOUND: "gone",
    }.get(code, "other")


class Client:
    """Tenký klient nad API. `transport` jde nahradit v testech (httpx.MockTransport)."""

    def __init__(self, transport: httpx.BaseTransport | None = None, base: str = API):
        self._http = httpx.Client(base_url=base, timeout=TIMEOUT, transport=transport,
                                  headers={"User-Agent": "VidDown"})
        self.free_key: str | None = None        # klíč pro volné stahování, který server vrátí místo odkazu (viz get_url)

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self._http.post(path, json=body)
        except httpx.HTTPError as e:
            raise K2SError(f"Keep2Share nedostupný: {e}", None, "network") from e
        try:
            data = r.json()
        except ValueError:
            raise K2SError(f"Keep2Share vrátil neplatnou odpověď (HTTP {r.status_code})", None, "network")
        if r.status_code == 429:
            raise K2SError("Keep2Share omezil dotazy", None, "rate")
        if str(data.get("status", "")).lower() != "success" and data.get("status") != 200:
            code = _code_of(data)
            msg = data.get("message") or data.get("errorMessage") or f"chyba API {code}"
            raise K2SError(str(msg), code, _classify(code))
        return data

    def login(self, username: str, password: str) -> str:
        try:
            data = self._post("/login", {"username": username, "password": password})
        except K2SError as e:
            if e.code == E_LOGIN_RECAPTCHA:                                  # přihlášení vyžaduje ověření člověka: nezkouší se znovu
                raise K2SError("přihlášení vyžaduje ověření člověka (Keep2Share), přihlaste se v prohlížeči", e.code, "login")
            raise
        token = data.get("auth_token")
        if not token:
            raise K2SError("přihlášení nevrátilo token", None, "login")
        return token

    def get_url(self, file_id: str, auth_token: str | None = None, free_download_key: str | None = None,
                captcha: Challenge | None = None, captcha_response: str | None = None) -> str:
        body: dict = {"file_id": file_id}
        if auth_token:
            body["auth_token"] = auth_token
        free_download_key = free_download_key or self.free_key
        if free_download_key:
            body["free_download_key"] = free_download_key
        if captcha and captcha_response:
            body["captcha_challenge"] = captcha.challenge
            body["captcha_response"] = captcha_response
        try:
            data = self._post("/getUrl", body)
        except K2SError as e:
            if e.code == E_FREE_KEY_WRONG:                                   # klíč neplatí: příště se bez něj začíná znovu
                self.free_key = None
            raise
        url = data.get("url")
        if not url:
            # server nevrátil odkaz: buď volné stahování čeká (vrátí klíč a odpočet), nebo je odpověď jiná než v dokumentaci
            log.info("getUrl bez odkazu, pole odpovědi: %s", sorted(data))
            if data.get("free_download_key"):
                self.free_key = str(data["free_download_key"])
                try:
                    wait = float(data.get("time_wait") or 0) or None      # time_wait: počet sekund (ověřeno v logu z 21. 11. 2026, ověřte jednotku při dalším běhu)
                except (TypeError, ValueError):
                    wait = None
                raise K2SError("čeká se na volné stahování", E_WAIT_FREE, "wait", wait_seconds=wait)
            raise K2SError(f"odpověď bez odkazu (pole: {', '.join(sorted(data))})", None, "other")
        return url

    def request_captcha(self) -> Challenge:
        data = self._post("/requestCaptcha", {})
        ch = data.get("challenge")
        if not ch:
            raise K2SError("captcha nebyla vydána", None, "other")
        return Challenge(challenge=ch, captcha_url=data.get("captcha_url"))

    def captcha_image(self, challenge: Challenge) -> bytes:
        """Obrázek captchy (GET /captcha?id=…). Vrací surová data obrázku."""
        try:
            r = self._http.get("/captcha", params={"id": challenge.challenge})
        except httpx.HTTPError as e:
            raise K2SError(f"captcha nejde stáhnout: {e}", None, "network") from e
        if r.status_code != 200 or not r.content:
            raise K2SError("captcha nejde stáhnout", None, "other")
        return r.content


_REPLY_RE = re.compile(r"^\s*#?(\d+)\s+(\S{1,32})\s*$")


def parse_captcha_reply(text: str) -> tuple[int, str] | None:
    """Odpověď na captchu z chatu: „#12 abc“ nebo „12 abc“ → (12, "abc"). Ostatní text vrací None."""
    m = _REPLY_RE.match(text or "")
    return (int(m.group(1)), m.group(2)) if m else None


async def fetch_file(url: str, dest, on_progress, check, transport=None) -> int:
    """Stáhne soubor z odkazu z `getUrl` do `dest`. `check()` vyhodí Cancelled při pauze nebo zrušení.
    Vrací velikost v bajtech. Průběh se hlásí jako v ostatních metodách (downloaded, total, speed, eta, progress)."""
    import time as _time
    from .sniffer import UA
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=120.0), follow_redirects=True,
                                 headers={"User-Agent": UA}, transport=transport) as c:
        try:
            async with c.stream("GET", url) as r:
                if r.status_code != 200:
                    raise K2SError(f"stažení selhalo (HTTP {r.status_code})", None, "network")
                total = int(r.headers.get("content-length") or 0) or None
                done, t0, last = 0, _time.monotonic(), 0.0
                with open(dest, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        check()
                        f.write(chunk)
                        done += len(chunk)
                        now = _time.monotonic()
                        if now - last >= 0.5:
                            last = now
                            el = max(now - t0, 1e-6)
                            speed = done / el
                            eta = (total - done) / speed if total and speed > 0 else None
                            on_progress(downloaded=done, total=total, speed=speed, eta=eta,
                                        progress=(done / total) if total else None)
        except httpx.HTTPError as e:
            raise K2SError(f"stahování přerušeno: {e}", None, "network") from e
    return done
