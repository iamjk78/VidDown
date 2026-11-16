"""Nastavení aplikace.

- Běžné nastavení: <data>/settings.json (sdílené GUI, CLI i Telegramem).
- Citlivé údaje (token bota, hash hesla): <data>/secrets.json s právy 600.
- Proměnné prostředí mají přednost a v GUI se zobrazují jako zamčené.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import secrets as pysecrets
import shutil
import sys
import threading
from pathlib import Path

from . import schedule


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


def valid_repo(repo: str) -> bool:
    """GitHub repozitář ve tvaru vlastník/název (bez `.` a `..`, které by změnily cestu v URL)."""
    parts = (repo or "").split("/")
    return len(parts) == 2 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", x) and set(x) != {"."} for x in parts)


AUTO_BACKUP_HOURS = (6, 12, 24, 72, 168)
APP_UPDATE_HOURS = (6, 12, 24, 72, 168)      # nabídka intervalu kontroly nových verzí aplikace     # nabídka intervalu automatických záloh

DEFAULTS: dict = {
    # stahování
    "download_dir": default_download_dir(),
    "temp_dir": "",
    "min_free_gb": 2.0,
    "concurrency": 2,
    "queue_previews": True,         # u položek ve frontě na pozadí doplnit název a náhled (po jedné, s odstupem)
    "perf_mode": "full",            # full | balanced | eco – omezení výkonu (priorita, vlákna, souběžnost)
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
    "mkv_to_mp4": True,             # po stažení přebalit MKV do MP4 (kopie proudů, bez kódování), aby šlo přehrát i v Safari
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
    "schedule_rules": [],                  # pravidla rozvrhu: [{days: [1, 3], windows: [["02:00", "05:00"], ["19:00", "21:00"]]}]
    "schedule_scope": ["queue"],           # co se rozvrhem řídí: queue | subscriptions | catalog
    "schedule_finish_running": False,      # na konci okna nechat rozpracovaná stahování doběhnout (jinak se přeruší)
    "sleep_min": 5,
    "sleep_max": 15,
    "sleep_youtube_min": 30,               # pauza mezi stahováním videí z YouTube (s); YouTube omezuje relace, které stahují příliš rychle
    "sleep_youtube_max": 60,
    "retries": 5,
    "auto_retry_attempts": 2,
    # přístup a síť
    "cookies_mode": "none",         # none | file | browser
    "cookies_browser": "chrome",
    "cookies_use": "always",        # always | needed (nejdřív bez cookies, s nimi až když web chce přihlášení)
    "cookies_always_hosts": "",     # weby (čárkami), které při „needed“ dostávají cookies vždy
    "proxy": "",
    "network_access": False,
    "port": 8765,
    # telegram
    "telegram_chat_id": "",
    "telegram_user_ids": "",               # skupinový chat: ID uživatelů (čárkami), kteří smějí bota ovládat; prázdné = skupina se ignoruje
    "telegram_after_probe": "download",  # download | ask
    "telegram_notify": "errors",         # errors | all
    # enginy
    "engine_auto_update": True,
    "engine_update_hours": 24,
    "keep_engine_versions": 3,
    "selftest_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    # automatické zálohy (šifrované soubory .dtb)
    "auto_backup": False,
    "auto_backup_hours": 24,        # jak často (hodiny): 6 | 12 | 24 | 72 | 168
    "auto_backup_dir": "",          # prázdné = <data>/backups
    "auto_backup_keep": 5,          # kolik záloh uchovat; po úspěšné záloze se starší smažou
    # katalog (PLAN.md kap. 20)
    "catalog_thumbs_dir": "",               # složka miniatur katalogu; prázdné = <data>/catalog/thumbs
    "catalog_proxy_fallback": "",           # záložní proxy pro Katalog: zkusí se jednou po chybě spojení nebo serveru (ne po omezení 429)
    "catalog_hour_limit": 600,              # nejvýš tolik dotazů na jeden web za hodinu při zjišťování podrobností a stránek (0 = bez stropu)
    "catalog_gap": 3,                       # pauza mezi dotazy na stejný web při zjišťování podrobností (s, 0–60)
    "catalog_auto": False,                  # automaticky hledat nová videa ve zdrojích (jen nenabídnutá; v rozvrhu, je-li zapnutý)
    "catalog_auto_hours": 24,               # jak často (hodiny): 6 | 12 | 24 | 72 | 168
    "catalog_anim": False,                  # stahovat animované náhledy (gif, webp, mp4), které web nabízí (přehrají se po najetí myší)
    "catalog_anim_pages": True,             # při zapnutých animacích hledat náhled i na stránce videa (jeden dotaz navíc na video)
    "catalog_anim_max_mb": 5,               # největší povolená velikost jedné animace (MB, 1–20)
    "catalog_slow_browser": True,           # u webů bez podpory yt-dlp zjišťovat podrobnosti i prohlížečem (až nakonec)
    # aktualizace aplikace zevnitř (PLAN.md kap. 18)
    "app_update_repo": "iamjk78/VidDown",    # GitHub repozitář s vydáními (vlastník/název)
    "app_update_mode": "notify",             # off | notify (jen oznámit) | auto (stáhnout, otestovat a po doběhnutí stahování restartovat)
    "app_update_hours": 24,                  # jak často se kontroluje nová verze
    # vzhled, logy, historie
    "language": "cs",               # cs | en
    "theme": "system",              # light | dark | system
    "log_level": "INFO",
    "history_days": 0,              # 0 = neomezeně
}

CHOICES = {
    "perf_mode": ["full", "balanced", "eco"],
    "quality": ["max", "compat"],
    "audio_format": ["mp3", "m4a"],
    "cookies_mode": ["none", "file", "browser"],
    "cookies_use": ["always", "needed"],
    "telegram_after_probe": ["download", "ask"],
    "telegram_notify": ["errors", "all"],
    "app_update_mode": ["off", "notify", "auto"],
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

RANGES = {"port": (1, 65535), "probe_concurrency": (1, 16)}           # další meze se přidávají sem; mimo rozsah = chyba při ukládání, oříznutí při čtení


def _coerce(default, value):
    """Převede hodnotu na typ výchozí hodnoty. Vyhodí ValueError při nesmyslu."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "ano", "on")
    if isinstance(default, int):
        try:
            return int(float(value))
        except OverflowError:                                          # „1e309“ → inf
            raise ValueError("číslo je mimo rozsah")
    if isinstance(default, float):
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            raise ValueError("číslo je mimo rozsah")
        return f
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
            if not isinstance(raw, dict):
                raise ValueError("nastavení nejsou objekt")
        except (ValueError, OSError):
            _keep_corrupt(self.path)
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
                    if k == "schedule_rules":
                        out[k] = schedule.normalize_rules_safe(v)
                        continue
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
            for k, (lo, hi) in RANGES.items():
                out[k] = max(lo, min(hi, out[k]))
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
                val = schedule.normalize_rules(v) if k == "schedule_rules" else _coerce(DEFAULTS[k], v)
                if k == "schedule_scope":
                    val = [x for x in dict.fromkeys(val)]
                    if not val or any(x not in schedule.SCOPES for x in val):
                        raise ValueError(f"schedule_scope must be a non-empty subset of {schedule.SCOPES}")
                if k in RANGES and not (RANGES[k][0] <= val <= RANGES[k][1]):
                    raise ValueError(f"{k} must be between {RANGES[k][0]} and {RANGES[k][1]}")
                if k in CHOICES and val not in CHOICES[k]:
                    raise ValueError(f"invalid value for {k}: {val}")
                if k in ("schedule_start", "schedule_end"):
                    h, m = val.split(":")
                    if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                        raise ValueError(f"invalid time: {val}")
                    val = f"{int(h):02d}:{int(m):02d}"
                if k == "app_update_repo" and val and not valid_repo(val):
                    raise ValueError("app_update_repo must look like owner/name")
                if k == "catalog_anim_max_mb" and not 1 <= val <= 20:
                    raise ValueError("catalog_anim_max_mb must be 1-20")
                if k == "catalog_gap" and not 0 <= val <= 60:
                    raise ValueError("catalog_gap must be 0-60")
                if k in ("sleep_youtube_min", "sleep_youtube_max") and not 0 <= val <= 600:
                    raise ValueError(f"{k} must be 0-600")
                if k == "catalog_hour_limit" and not (val == 0 or 60 <= val <= 5000):
                    raise ValueError("catalog_hour_limit must be 0 or 60-5000")
                if k == "cookies_always_hosts":
                    from .resolvers.cookiepolicy import parse_hosts
                    if len(str(val or "")) > 4000:
                        raise ValueError("cookies_always_hosts is too long")
                    val = ", ".join(parse_hosts(str(val or "")))
                if k == "catalog_proxy_fallback":
                    val = str(val or "").strip()
                    if val and not re.fullmatch(r"(?:(?:https?|socks5h?|socks4)://)?[^\s/]+(?::\d{1,5})?/?", val):
                        raise ValueError("catalog_proxy_fallback must look like socks5://host:port or http://host:port")
                if k == "app_update_hours" and val not in APP_UPDATE_HOURS:
                    raise ValueError(f"app_update_hours must be one of {APP_UPDATE_HOURS}")
                if k == "auto_backup_hours" and val not in AUTO_BACKUP_HOURS:
                    raise ValueError(f"auto_backup_hours must be one of {AUTO_BACKUP_HOURS}")
                if k == "catalog_auto_hours" and val not in AUTO_BACKUP_HOURS:
                    raise ValueError(f"catalog_auto_hours must be one of {AUTO_BACKUP_HOURS}")
                if k == "auto_backup_keep" and not 1 <= val <= 100:
                    raise ValueError("auto_backup_keep must be 1-100")
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


def _keep_corrupt(path: Path) -> None:
    """Poškozený soubor (ruční úprava, přerušený zápis) se jednou uloží vedle jako `<název>.corrupt`, ať první uložení výchozích hodnot
    nesmaže všechno ostatní navždy."""
    try:
        bak = path.with_name(path.name + ".corrupt")
        if path.exists() and not bak.exists():
            shutil.copy2(path, bak)
            logging.getLogger("viddown.config").error("Soubor %s je poškozený, kopie je v %s; používají se výchozí hodnoty.", path, bak)
    except OSError:
        pass


class Secrets:
    """Citlivé údaje mimo běžné nastavení. Soubor má práva 600."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "secrets.json"
        self._cache: dict | None = None          # poslední úspěšně načtený obsah
        self._unreadable = False                 # soubor teď nejde přečíst (a nemáme z čeho vycházet)

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("tajemství nejsou objekt")
        except FileNotFoundError:
            d = {}
        except OSError:                          # přechodná chyba čtení: nic se nepřepisuje a heslo se nevypíná
            if self._cache is not None:
                return dict(self._cache)
            self._unreadable = True
            return {}
        except ValueError:
            _keep_corrupt(self.path)
            d = {}
        self._unreadable = False
        self._cache = dict(d)
        return d

    def _save(self, d: dict) -> None:
        if self._unreadable:                     # soubor se nepodařilo přečíst: zápis by smazal hash hesla a tokeny
            raise OSError("tajemství nelze přečíst, zápis se odmítá")
        with _lock:
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # práva od vzniku, ne až dodatečně
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(d))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        self._cache = dict(d)

    # --- telegram
    @property
    def telegram_token(self) -> str:
        return os.environ.get("VIDDOWN_TELEGRAM_TOKEN") or self._load().get("telegram_token", "")

    def set_telegram_token(self, token: str) -> None:
        d = self._load()
        d["telegram_token"] = token.strip()
        self._save(d)

    # --- token pro čtení vydání aplikace z (soukromého) GitHub repozitáře
    @property
    def app_update_token(self) -> str:
        return os.environ.get("VIDDOWN_APP_UPDATE_TOKEN") or self._load().get("app_update_token", "")

    def set_app_update_token(self, token: str) -> None:
        d = self._load()
        if token.strip():
            d["app_update_token"] = token.strip()
        else:
            d.pop("app_update_token", None)
        self._save(d)

    # --- heslo do GUI
    def has_password(self) -> bool:
        if os.environ.get("VIDDOWN_PASSWORD"):
            return True
        d = self._load()
        return bool(d.get("password_hash")) or self._unreadable             # nečitelný soubor: raději heslo vyžadovat

    def set_password(self, password: str) -> None:
        d = self._load()
        if not password:
            d.pop("password_hash", None)
            d.pop("password_salt", None)
        else:
            salt = pysecrets.token_hex(16)
            d["password_salt"] = salt
            d["password_hash"] = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
        d["session_key"] = pysecrets.token_hex(32)                      # změna hesla zneplatní stará sezení
        self._save(d)

    def check_password(self, password: str) -> bool:
        env = os.environ.get("VIDDOWN_PASSWORD")
        if env:
            return pysecrets.compare_digest(env.encode(), password.encode())            # bajty: str s diakritikou by vyhodil TypeError
        d = self._load()
        if not d.get("password_hash"):
            return False
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(d["password_salt"]), 200_000).hex()
        return pysecrets.compare_digest(h.encode(), d["password_hash"].encode())

    def rotate_session(self) -> None:
        """Nový klíč sezení: všechny dosud vydané cookies přestanou platit (změna hesla, odhlášení)."""
        d = self._load()
        d["session_key"] = pysecrets.token_hex(32)
        self._save(d)

    def session_key(self) -> str:
        d = self._load()
        if self._unreadable:                                          # nečitelný soubor: nikdo se nepřihlásí a nic se nezapisuje
            return pysecrets.token_hex(32)
        if not d.get("session_key"):
            d["session_key"] = pysecrets.token_hex(32)
            self._save(d)
        return d["session_key"]


def cookies_path() -> Path:
    return data_dir() / "cookies.txt"
