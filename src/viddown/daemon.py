"""Démon: jeden proces se zámkem – fronta + webový server + Telegram bot."""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__, appupdate, autobackup, backup, catalog, catalogdetails, updater
from .config import Secrets, Settings, data_dir
from .db import DB
from .engines import EngineManager
from .runner import Runner
from .util import env_flag, in_docker

log = logging.getLogger("viddown")


# ------------------------------------------------------------ zámek
class Lock:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True

    def write(self, info: dict) -> None:
        info_path = self.path.with_suffix(".json")
        info_path.write_text(json.dumps(info))

    def release(self) -> None:
        if self.fh:
            try:
                if sys.platform != "win32":
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None


def running_info() -> dict | None:
    """Vrátí {pid, port, host} běžícího démona, nebo None."""
    d = data_dir()
    lk = Lock(d / "daemon.lock")
    if lk.acquire():
        lk.release()
        return None
    try:
        return json.loads((d / "daemon.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def setup_logging(data: Path, level: str) -> None:
    logs = data / "logs"
    logs.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(logs / "viddown.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    root.setLevel(getattr(logging, level, logging.INFO))
    for noisy in ("httpx", "httpcore", "uvicorn.access", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class AppState:
    def __init__(self):
        self.data = data_dir()
        self.settings = Settings()
        self.secrets = Secrets()
        self.db = DB(self.data / "viddown.db")
        self.bot = None
        self.engines = EngineManager(self.data, self.settings, self.db, notify=self._engine_notify)
        self.runner = Runner(self.db, self.settings, self.engines, self.data)
        self._eng_cache = (0.0, [])
        self.chromium_busy = False
        self.stopping = False
        self.restart = False     # po ukončení se má aplikace spustit znovu
        self.stop = None         # asyncio.Event hlavní smyčky

    def _engine_notify(self, key, **kw):
        if self.bot:
            self.bot.notify_threadsafe(key, **kw)

    def engines_cache(self) -> list[dict]:
        t0, val = self._eng_cache
        if time.time() - t0 > 30 or not val:
            val = self.engines.status()
            self._eng_cache = (time.time(), val)
        return val


def bind_host(settings: Settings, secrets: Secrets) -> str:
    env = os.environ.get("VIDDOWN_HOST")
    if env:
        return env
    if settings.get("network_access"):
        if secrets.has_password() or env_flag("VIDDOWN_ALLOW_NO_PASSWORD"):
            return "0.0.0.0"
        log.warning("Přístup ze sítě je zapnutý, ale chybí heslo – poslouchám jen na 127.0.0.1")
    return "127.0.0.1"


def serve(open_browser: bool = False, host: str | None = None, port: int | None = None) -> int:
    data = data_dir()
    lock = Lock(data / "daemon.lock")
    if not lock.acquire():
        info = running_info() or {}
        url = f"http://127.0.0.1:{info.get('port', 8765)}/"
        print(f"VidDown už běží (PID {info.get('pid', '?')}) na {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    restored = backup.apply_pending(data)       # obnova ze zálohy se provádí před otevřením databáze
    st = AppState()
    setup_logging(data, st.settings.get("log_level", "INFO"))
    if restored:
        if restored.get("ok"):
            log.info("Obnova ze zálohy dokončena (předchozí stav: %s)", restored.get("before"))
        else:
            log.error("Obnova ze zálohy selhala, zůstala stará data: %s", restored.get("error"))
    host = host or bind_host(st.settings, st.secrets)
    port = int(port or os.environ.get("VIDDOWN_PORT") or st.settings.get("port", 8765))
    if host not in ("127.0.0.1", "localhost", "::1") and not st.secrets.has_password() and not env_flag("VIDDOWN_ALLOW_NO_PASSWORD"):
        log.error("Naslouchání na %s bez hesla není povoleno. Nastavte heslo (viddown password) nebo VIDDOWN_ALLOW_NO_PASSWORD=1.", host)
        lock.release()
        return 2
    lock.write({"pid": os.getpid(), "port": port, "host": host, "started": time.time(), "version": __version__})
    log.info("VidDown %s – data: %s – GUI: http://%s:%s/", __version__, data, "127.0.0.1" if host == "0.0.0.0" else host, port)
    try:
        asyncio.run(_main(st, host, port, open_browser))
    except KeyboardInterrupt:
        pass
    finally:
        lock.release()
        try:
            (data / "daemon.json").unlink()
        except OSError:
            pass
    if st.restart and not in_docker():
        # mimo Docker se spustí nový proces (v Dockeru se kontejner restartuje sám díky `restart: unless-stopped`)
        argv = [sys.executable, *getattr(sys, "orig_argv", sys.argv)[1:]]
        log.info("Restart: %s", argv)
        if sys.platform == "win32":
            subprocess.Popen(argv)
        else:
            os.execv(argv[0], argv)
    return 0


async def _main(st: AppState, host: str, port: int, open_browser: bool) -> None:
    import uvicorn

    from .server import create_app
    from .telegram import TelegramBot

    stop = asyncio.Event()
    st.stop = stop
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    updater.startup(st)           # po restartu kvůli aktualizaci obnoví frontu, kterou jsme před restartem pozastavili
    st.bot = TelegramBot(st.runner, st.db, st.settings, st.secrets, st.engines)
    st.bot.app = st               # příkaz /aplikace
    st.runner.listeners.append(st.bot)
    app = create_app(st)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False, lifespan="off",
                            timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # signály řešíme sami

    # doinstalovat chybějící enginy na pozadí (první spuštění)
    threading.Thread(target=st.engines.ensure, name="engines-ensure", daemon=True).start()

    tasks = [asyncio.create_task(st.runner.run(stop), name="runner"),
             asyncio.create_task(st.bot.run(stop), name="telegram"),
             asyncio.create_task(server.serve(), name="http"),
             asyncio.create_task(appupdate.health_task(st.data, stop), name="app-health"),
             asyncio.create_task(autobackup.task(st, stop), name="auto-backup"),
             asyncio.create_task(updater.task(st, stop), name="app-updater"),
             asyncio.create_task(catalog.task(st, stop), name="catalog"),
             asyncio.create_task(catalogdetails.task(st, stop), name="catalog-details")]
    if open_browser:
        async def _open():
            for _ in range(50):
                if server.started:
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                    return
                await asyncio.sleep(0.2)
        asyncio.create_task(_open())
    await stop.wait()
    log.info("Ukončuji…")
    st.stopping = True
    server.should_exit = True
    await asyncio.gather(*tasks, return_exceptions=True)
