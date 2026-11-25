"""Metody získání videa: yt-dlp a vlastní HLS sniffer."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path


class ResolveError(Exception):
    """Chyba metody s klasifikací (viz util.classify_error)."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


class Cancelled(Exception):
    """Proces byl zastaven (pauza, zrušení, konec časového okna)."""


@dataclass
class Ctx:
    """Kontext pro metody: nastavení, enginy, datová složka."""
    settings: dict
    engines: object
    data: Path
    cookies_override: Path | None = None        # soukromá kopie cookies pro jeden běh yt-dlp (viz ytdlp.with_cookie_copy)
    no_cookies: bool | None = None              # None = rozhodne cookiepolicy, True = tento pokus bez cookies, False = s cookies

    @property
    def cookies_file(self) -> Path | None:
        if self.no_cookies:
            return None
        if self.cookies_override is not None:
            return self.cookies_override
        p = self.data / "cookies.txt"
        return p if self.settings.get("cookies_mode") == "file" and p.exists() else None


class ProcHolder:
    """Drží běžící podproces, aby ho runner mohl zastavit."""

    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None
        self.stopped = False

    def check(self) -> None:
        """Vyhodí Cancelled, pokud mezitím přišla pauza nebo zrušení (např. během načítání metadat)."""
        if self.stopped:
            raise Cancelled()

    async def attach(self, proc) -> None:
        """Zaregistruje podproces. Pokud už přišel pokyn k zastavení, hned ho ukončí."""
        self.proc = proc
        if self.stopped:
            await self.stop()

    async def stop(self):
        self.stopped = True
        p = self.proc
        if p and p.returncode is None:
            try:
                p.terminate()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(p.wait(), 8)
            except asyncio.TimeoutError:
                try:
                    p.kill()
                except ProcessLookupError:
                    pass


async def spawn_proc(*cmd, **kw):
    """Spustí podproces; na Windows bez okna a s prioritou z režimu výkonu. Prioritu nastaví rodič hned po spuštění."""
    from .. import cpu
    if sys.platform == "win32":
        import subprocess
        kw.setdefault("creationflags", subprocess.CREATE_NO_WINDOW | cpu.win_flags())
    proc = await asyncio.create_subprocess_exec(*cmd, **kw)
    cpu.apply_nice(proc.pid)
    return proc
