"""Nastavení aplikace.

- Běžné nastavení: <data>/settings.json (sdílené GUI, CLI i Telegramem).
- Citlivé údaje (token bota, hash hesla): <data>/secrets.json s právy 600.
- Proměnné prostředí mají přednost a v GUI se zobrazují jako zamčené.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets as pysecrets
import sys
import threading
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("VIDDOWN_DATA")
    if env:
        p = Path(env)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home())) / "VidDown"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "VidDown"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "viddown"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_download_dir() -> str:
    """Výchozí cílová složka. VIDDOWN_DEFAULT_DOWNLOAD_DIR ji jen předvyplní (v GUI zůstane měnitelná),
    VIDDOWN_DOWNLOAD_DIR ji naopak pevně zamkne."""
    return os.environ.get("VIDDOWN_DEFAULT_DOWNLOAD_DIR") or str(Path.home() / "Downloads" / "VidDown")


DEFAULTS: dict = {
    # stahování
    "download_dir": default_download_dir(),
    "temp_dir": "",
    "min_free_gb": 2.0,
    "concurrency": 2,
    "quality": "max",               # max | compat
    "audio_only": False,
    "audio_format": "mp3",          # mp3 | m4a
    "channel_tabs": ["videos"],     # videos | shorts | streams
    "playlist_confirm_threshold": 50,
    "subscription_check_hours": 6,  # jak často se kontrolují odběry (kanály, playlisty)
    "live_from_start": False,
    "subtitles": False,
    "subtitle_langs": "cs,en",
    "auto_subtitles": False,
    "embed_metadata": False,
    "methods": ["ytdlp", "sniffer"],
    "sniff_timeout": 40,
    "probe_concurrency": 2,
    # pojmenování a složky
    "name_template": "{název}",
    "channel_name_template": "{kanál}_{název}",
    "playlist_folder": True,
    "channel_folder": True,
    # rychlost a plánování
    "rate_limit_enabled": False,
    "rate_limit_mbps": 10.0,
    "schedule_enabled": False,
    "schedule_start": "22:00",
    "schedule_end": "06:00",
    "schedule_days": [0, 1, 2, 3, 4, 5, 6],
    "sleep_min": 5,
    "sleep_max": 15,
    "retries": 5,
    "auto_retry_attempts": 2,
    # přístup a síť
    "cookies_mode": "none",         # none | file | browser
    "cookies_browser": "chrome",
    "proxy": "",
    "network_access": False,
    "port": 8765,
    # telegram
    "telegram_chat_id": "",
    "telegram_after_probe": "download",  # download | ask
    "telegram_notify": "errors",         # errors | all
    # enginy
    "engine_auto_update": True,
    "engine_update_hours": 24,
    "keep_engine_versions": 3,
    "selftest_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    # vzhled, logy, historie
    "language": "cs",               # cs | en
    "theme": "system",              # light | dark | system
    "log_level": "INFO",
    "history_days": 0,              # 0 = neomezeně
}

CHOICES = {
    "quality": ["max", "compat"],
    "audio_format": ["mp3", "m4a"],
    "cookies_mode": ["none", "file", "browser"],
    "telegram_after_probe": ["download", "ask"],
    "telegram_notify": ["errors", "all"],
    "language": ["cs", "en"],
    "theme": ["light", "dark", "system"],
    "log_level": ["DEBUG", "INFO", "WARNING", "ERROR"],
}

ENV_MAP = {
    "VIDDOWN_DOWNLOAD_DIR": "download_dir",
    "VIDDOWN_TEMP_DIR": "temp_dir",
    "VIDDOWN_CONCURRENCY": "concurrency",
    "VIDDOWN_PORT": "port",
    "VIDDOWN_LANGUAGE": "language",
    "VIDDOWN_TELEGRAM_CHAT_ID": "telegram_chat_id",
    "VIDDOWN_NETWORK_ACCESS": "network_access",
}

_lock = threading.RLock()


def _coerce(default, value):
    """Převede hodnotu na typ výchozí hodnoty. Vyhodí ValueError při nesmyslu."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "ano", "on")
    if isinstance(default, int):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    if isinstance(default, list):
        if isinstance(value, list):
            items = value
        else:
            items = [x.strip() for x in str(value).split(",") if x.strip()]
        if default and isinstance(default[0], int):
            return [int(x) for x in items]
        return [str(x) for x in items]
    return "" if value is None else str(value)


class Settings:
    """Nastavení se čte ze souboru při každé změně souboru (sdílení mezi procesy)."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"
        self._cache: dict | None = None
        self._mtime = None

    def _read_file(self) -> dict:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return {}
        if self._cache is not None and self._mtime == st.st_mtime_ns:
            return self._cache
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        self._cache, self._mtime = raw, st.st_mtime_ns
        return raw

    def locked_keys(self) -> dict:
        return {key: env for env, key in ENV_MAP.items() if os.environ.get(env)}

    def all(self) -> dict:
        with _lock:
            out = copy.deepcopy(DEFAULTS)
            for k, v in self._read_file().items():
                if k in DEFAULTS:
                    try:
                        out[k] = _coerce(DEFAULTS[k], v)
                    except (TypeError, ValueError):
                        pass
            for env, key in ENV_MAP.items():
                if os.environ.get(env):
                    try:
                        out[key] = _coerce(DEFAULTS[key], os.environ[env])
                    except (TypeError, ValueError):
                        pass
            out["concurrency"] = max(1, min(16, out["concurrency"]))
            return out

    def __getitem__(self, key):
        return self.all()[key]

    def get(self, key, default=None):
        return self.all().get(key, default)

    def update(self, changes: dict) -> dict:
        """Uloží změny. Vrací nové nastavení. Neznámé nebo neplatné hodnoty vyhodí ValueError."""
        with _lock:
            current = dict(self._read_file())
            for k, v in changes.items():
                if k not in DEFAULTS:
                    raise ValueError(f"unknown setting: {k}")
                val = _coerce(DEFAULTS[k], v)
                if k in CHOICES and val not in CHOICES[k]:
                    raise ValueError(f"invalid value for {k}: {val}")
                if k in ("schedule_start", "schedule_end"):
                    h, m = val.split(":")
                    if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                        raise ValueError(f"invalid time: {val}")
                    val = f"{int(h):02d}:{int(m):02d}"
                if k == "methods":
                    if not val or any(x not in ("ytdlp", "sniffer") for x in val):
                        raise ValueError("methods must be ytdlp/sniffer")
                if k == "channel_tabs" and any(x not in ("videos", "shorts", "streams") for x in val):
                    raise ValueError("channel_tabs must be videos/shorts/streams")
                current[k] = val
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            self._cache = None
            return self.all()

    def export(self) -> dict:
        return {k: v for k, v in self.all().items()}


class Secrets:
    """Citlivé údaje mimo běžné nastavení. Soubor má práva 600."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "secrets.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self, d: dict) -> None:
        with _lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)

    # --- telegram
    @property
    def telegram_token(self) -> str:
        return os.environ.get("VIDDOWN_TELEGRAM_TOKEN") or self._load().get("telegram_token", "")

    def set_telegram_token(self, token: str) -> None:
        d = self._load()
        d["telegram_token"] = token.strip()
        self._save(d)

    # --- heslo do GUI
    def has_password(self) -> bool:
        return bool(os.environ.get("VIDDOWN_PASSWORD") or self._load().get("password_hash"))

    def set_password(self, password: str) -> None:
        d = self._load()
        if not password:
            d.pop("password_hash", None)
            d.pop("password_salt", None)
        else:
            salt = pysecrets.token_hex(16)
            d["password_salt"] = salt
            d["password_hash"] = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
        self._save(d)

    def check_password(self, password: str) -> bool:
        env = os.environ.get("VIDDOWN_PASSWORD")
        if env:
            return pysecrets.compare_digest(env, password)
        d = self._load()
        if not d.get("password_hash"):
            return False
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(d["password_salt"]), 200_000).hex()
        return pysecrets.compare_digest(h, d["password_hash"])

    def session_key(self) -> str:
        d = self._load()
        if not d.get("session_key"):
            d["session_key"] = pysecrets.token_hex(32)
            self._save(d)
        return d["session_key"]


def cookies_path() -> Path:
    return data_dir() / "cookies.txt"
