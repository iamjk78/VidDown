"""Správce verzovaných enginů: yt-dlp, Deno, ffmpeg.

Každá verze leží ve vlastní složce <data>/engines/<engine>/<verze>/ a soubor `current`
určuje aktivní verzi. Aktualizace: stáhnout vedle staré verze -> otestovat novou i starou
-> přepnout jen když nová projde. Selžou-li obě, je to síť nebo web a nic se nemění.
Když spravovaná verze neexistuje, použije se program ze systémové PATH.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("viddown.engines")

EXE = ".exe" if sys.platform == "win32" else ""
UA = "VidDown/0.1 (+https://github.com/iamjk78/VidDown)"


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    return "x64"


def _http_json(url: str, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _download(url: str, dest: Path, timeout=600) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 1024)


def _vkey(v: str) -> tuple:
    """Porovnatelný klíč verze: '9.0.1' > '6.1.1', '2026.11.05' > '2026.10.26'."""
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4]) or (0,)


def _chmod_x(p: Path) -> None:
    try:
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _run(cmd: list[str], timeout=60, env=None) -> tuple[int, str]:
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                           encoding="utf-8", errors="replace", creationflags=flags)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except OSError as e:
        return -1, str(e)


@dataclass
class Release:
    version: str
    assets: dict = field(default_factory=dict)  # name -> url


class Engine:
    name = ""
    repo = ""
    binaries: tuple[str, ...] = ()
    description = ""

    def __init__(self, root: Path, manager: "EngineManager"):
        self.root = root / self.name
        self.root.mkdir(parents=True, exist_ok=True)
        self.mgr = manager

    # ---------------------------------------------------- verze na disku
    def versions(self) -> list[dict]:
        out = []
        for p in self.root.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                meta = {}
                mf = p / "meta.json"
                if mf.exists():
                    try:
                        meta = json.loads(mf.read_text())
                    except json.JSONDecodeError:
                        pass
                out.append({"version": p.name, "installed_at": meta.get("installed_at", p.stat().st_mtime),
                            "tested_ok": meta.get("tested_ok"), "tested_at": meta.get("tested_at")})
        out.sort(key=lambda x: x["installed_at"], reverse=True)
        return out

    def current(self) -> str | None:
        f = self.root / "current"
        if f.exists():
            v = f.read_text().strip()
            if v and (self.root / v).is_dir():
                return v
        return None

    def set_current(self, version: str) -> None:
        tmp = self.root / "current.tmp"
        tmp.write_text(version)
        os.replace(tmp, self.root / "current")

    def bin_path(self, binary: str | None = None, version: str | None = None) -> str | None:
        """Cesta k binárce aktivní (nebo zadané) verze, jinak ze systémové PATH."""
        binary = binary or self.binaries[0]
        v = version or self.current()
        if v:
            p = self.root / v / (binary + EXE)
            if p.exists():
                return str(p)
        if version:
            return None
        return shutil.which(binary)

    def is_system(self) -> bool:
        return self.current() is None and self.bin_path() is not None

    def system_version(self) -> str | None:
        p = shutil.which(self.binaries[0])
        if not p:
            return None
        code, out = _run([p, *self.version_args()], timeout=30)
        return self.parse_version(out) if code == 0 else None

    def version_args(self) -> list[str]:
        return ["--version"]

    def parse_version(self, out: str) -> str:
        return out.strip().splitlines()[0].strip() if out.strip() else "?"

    def _write_meta(self, version: str, **kw) -> None:
        mf = self.root / version / "meta.json"
        meta = {}
        if mf.exists():
            try:
                meta = json.loads(mf.read_text())
            except json.JSONDecodeError:
                pass
        meta.update(kw)
        mf.write_text(json.dumps(meta))

    # ---------------------------------------------------- vydání
    def latest_release(self) -> Release:
        d = _http_json(f"https://api.github.com/repos/{self.repo}/releases/latest")
        return Release(self.normalize_version(d["tag_name"]), {a["name"]: a["browser_download_url"] for a in d.get("assets", [])})

    def normalize_version(self, tag: str) -> str:
        return tag.lstrip("v")

    def install_release(self, rel: Release, target: Path) -> None:
        raise NotImplementedError

    # ---------------------------------------------------- test
    def test(self, version: str | None) -> tuple[bool, str]:
        raise NotImplementedError

    # ---------------------------------------------------- instalace
    def install(self, rel: Release) -> str:
        target = self.root / rel.version
        if target.exists() and self.bin_path(version=rel.version):
            return rel.version
        stage = Path(tempfile.mkdtemp(prefix=f".stage-{rel.version}-", dir=self.root))
        try:
            self.install_release(rel, stage)
            for b in self.binaries:
                p = stage / (b + EXE)
                if not p.exists():
                    raise RuntimeError(f"{self.name}: chybí {b} po instalaci")
                _chmod_x(p)
                if sys.platform == "darwin":
                    _run(["xattr", "-d", "com.apple.quarantine", str(p)], timeout=10)
            (stage / "meta.json").write_text(json.dumps({"installed_at": time.time()}))
            if target.exists():
                shutil.rmtree(target)
            os.replace(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
        return rel.version

    def remove(self, version: str) -> None:
        # jen nainstalovaná verze: jinak by `root / version` (absolutní cesta, „..“, prázdný řetězec) smazalo cizí složku
        if not isinstance(version, str) or version not in [v["version"] for v in self.versions()]:
            raise ValueError(f"Verze {version!r} není nainstalovaná")
        if version == self.current():
            raise ValueError("Aktivní verzi nelze smazat")
        shutil.rmtree(self.root / version, ignore_errors=True)

    def prune(self, keep: int) -> None:
        cur = self.current()
        vs = [v["version"] for v in self.versions()]
        for v in vs[keep:]:
            if v != cur:
                shutil.rmtree(self.root / v, ignore_errors=True)


class YtDlp(Engine):
    name = "yt-dlp"
    repo = "yt-dlp/yt-dlp"
    binaries = ("yt-dlp",)
    description = "YouTube a tisíce dalších webů"

    def _asset(self) -> str:
        if sys.platform == "darwin":
            return "yt-dlp_macos"
        if sys.platform == "win32":
            return "yt-dlp_arm64.exe" if _arch() == "arm64" else "yt-dlp.exe"
        musl = Path("/etc/alpine-release").exists()
        base = "yt-dlp_musllinux" if musl else "yt-dlp_linux"
        return base + ("_aarch64" if _arch() == "arm64" else "")

    def install_release(self, rel, target):
        a = self._asset()
        if a not in rel.assets:
            raise RuntimeError(f"yt-dlp: vydání {rel.version} nemá soubor {a}")
        _download(rel.assets[a], target / ("yt-dlp" + EXE))

    def test(self, version):
        exe = self.bin_path(version=version) if version else self.bin_path()
        if not exe:
            return False, "yt-dlp nenalezen"
        code, out = _run([exe, "--version"], timeout=120)
        if code != 0:
            return False, f"--version selhalo: {out[-300:]}"
        url = self.mgr.settings.get("selftest_url")
        if url and not str(url).lower().startswith(("http://", "https://")):
            return False, "adresa kontrolního videa musí začínat http(s)://"
        if not url:
            return True, f"--version OK ({out.strip()})"
        cmd = [exe, "--ignore-config", "--no-warnings", "-J", "--skip-download", "--no-playlist", "--", url]
        deno = self.mgr.get("deno").bin_path()
        if deno:
            cmd[1:1] = ["--js-runtimes", f"deno:{deno}"]
        ff = self.mgr.get("ffmpeg").bin_path()
        if ff:
            cmd[1:1] = ["--ffmpeg-location", ff]
        code, out2 = _run(cmd, timeout=180)
        if code != 0:
            err = next((l for l in out2.splitlines() if l.startswith("ERROR")), out2.strip()[-300:])
            return False, f"metadata testovací URL: {err}"
        try:
            j = json.loads(out2[out2.index("{"):])
            if not j.get("id"):
                return False, "metadata bez id"
        except (ValueError, json.JSONDecodeError):
            return False, "neplatný JSON"
        return True, "OK"


class Deno(Engine):
    name = "deno"
    repo = "denoland/deno"
    binaries = ("deno",)
    description = "JavaScript runtime pro YouTube"

    def _asset(self) -> str:
        arch = "aarch64" if _arch() == "arm64" else "x86_64"
        triple = {"darwin": "apple-darwin", "win32": "pc-windows-msvc"}.get(sys.platform, "unknown-linux-gnu")
        return f"deno-{arch}-{triple}.zip"

    def parse_version(self, out):
        m = re.search(r"deno (\S+)", out)
        return m.group(1) if m else super().parse_version(out)

    def install_release(self, rel, target):
        a = self._asset()
        if a not in rel.assets:
            raise RuntimeError(f"deno: vydání {rel.version} nemá soubor {a}")
        z = target / a
        _download(rel.assets[a], z)
        with zipfile.ZipFile(z) as zf:
            zf.extract("deno" + EXE, target)
        z.unlink()

    def test(self, version):
        exe = self.bin_path(version=version) if version else self.bin_path()
        if not exe:
            return False, "deno nenalezen"
        code, out = _run([exe, "--version"], timeout=60)
        if code != 0:
            return False, f"--version selhalo: {out[-200:]}"
        code, out = _run([exe, "eval", "console.log(6*7)"], timeout=60)
        if code != 0 or "42" not in out:
            return False, f"eval selhal: {out[-200:]}"
        return True, "OK"


class FFmpeg(Engine):
    name = "ffmpeg"
    repo = "eugeneware/ffmpeg-static"
    binaries = ("ffmpeg", "ffprobe")
    description = "Spojování a převod videa"

    @staticmethod
    def prefer_system() -> bool:
        """Na Linuxu (Docker) má přednost systémový ffmpeg: staticky sestavený ffmpeg z eugeneware/ffmpeg-static
        neumí překládat názvy serverů (DNS), takže nestáhne nic ze sítě (HLS, přímé odkazy)."""
        return sys.platform.startswith("linux") and shutil.which("ffmpeg") is not None

    def bin_path(self, binary: str | None = None, version: str | None = None) -> str | None:
        if not version and self.prefer_system():
            return shutil.which(binary or self.binaries[0])
        return super().bin_path(binary, version)

    def version_args(self):
        return ["-version"]

    def parse_version(self, out):
        m = re.search(r"ffmpeg version (\S+)", out)
        return m.group(1) if m else "?"

    def normalize_version(self, tag):
        return tag.lstrip("bv")

    def _plat(self) -> str:
        p = {"darwin": "darwin", "win32": "win32"}.get(sys.platform, "linux")
        return f"{p}-{_arch()}"

    def install_release(self, rel, target):
        for b in self.binaries:
            a = f"{b}-{self._plat()}.gz"
            if a not in rel.assets:
                raise RuntimeError(f"ffmpeg: vydání {rel.version} nemá soubor {a}")
            gz = target / a
            _download(rel.assets[a], gz)
            with gzip.open(gz) as src, open(target / (b + EXE), "wb") as dst:
                shutil.copyfileobj(src, dst)
            gz.unlink()

    def test(self, version):
        ff = self.bin_path("ffmpeg", version) if version else self.bin_path("ffmpeg")
        fp = self.bin_path("ffprobe", version) if version else self.bin_path("ffprobe")
        if not ff:
            return False, "ffmpeg nenalezen"
        code, out = _run([ff, "-version"], timeout=60)
        if code != 0:
            return False, "-version selhalo"
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.mkv", Path(td) / "b.mp4"
            code, out = _run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=128x72:rate=10",
                              "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(a)], timeout=120)
            if code != 0:
                return False, f"generování vzorku selhalo: {out[-200:]}"
            code, out = _run([ff, "-y", "-v", "error", "-i", str(a), "-c", "copy", str(b)], timeout=120)
            if code != 0 or not b.exists():
                return False, f"spojení vzorku selhalo: {out[-200:]}"
            if fp:
                code, out = _run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(b)], timeout=60)
                if code != 0:
                    return False, "ffprobe selhal"
        return True, "OK"


class EngineManager:
    ORDER = ("ffmpeg", "deno", "yt-dlp")

    def __init__(self, data: Path, settings, db=None, notify=None):
        self.root = data / "engines"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.db = db
        self.notify = notify  # callable(text_key, **kw)
        self.engines = {e.name: e for e in (FFmpeg(self.root, self), Deno(self.root, self), YtDlp(self.root, self))}
        self._lock = threading.Lock()
        self.busy: str | None = None

    def get(self, name: str) -> Engine:
        return self.engines[name]

    # ---------------------------------------------------- protokol
    def log(self, engine: str, msg: str) -> None:
        line = {"t": time.time(), "engine": engine, "msg": msg}
        log.info("%s: %s", engine, msg)
        if self.db is not None:
            lines = self.db.kv_get("engine_log", [])
            lines.append(line)
            self.db.kv_set("engine_log", lines[-300:])

    def status(self) -> list[dict]:
        out = []
        last = (self.db.kv_get("engine_last_check", {}) if self.db else {}) or {}
        for name in ("yt-dlp", "deno", "ffmpeg"):
            e = self.engines[name]
            cur = e.current()
            vers = e.versions()
            info = {"name": name, "description": e.description, "current": cur,
                    "system": None, "versions": vers, "path": e.bin_path(),
                    "last": last.get(name)}
            if not cur:
                info["system"] = e.system_version()
            out.append(info)
        return out

    # ---------------------------------------------------- operace
    def ensure(self) -> None:
        """Při startu doinstaluje chybějící enginy (systémové se nechají). Se zámkem – aktualizace počká."""
        with self._lock:
            self.busy = "install"
            try:
                self._ensure()
            finally:
                self.busy = None

    def _ensure(self) -> None:
        for name in self.ORDER:
            e = self.engines[name]
            if e.current() or e.bin_path():
                continue
            try:
                self.log(name, "není nainstalován, instaluji nejnovější verzi")
                rel = e.latest_release()
                v = e.install(rel)
                ok, msg = e.test(v) if name != "yt-dlp" else self._ytdlp_quick(v)
                e._write_meta(v, tested_ok=ok, tested_at=time.time())
                if ok:
                    e.set_current(v)
                    self.log(name, f"nainstalována verze {v}")
                else:
                    self.log(name, f"verze {v} neprošla testem: {msg}")
            except Exception as ex:  # noqa: BLE001
                self.log(name, f"instalace selhala: {ex}")
        try:
            self.ensure_chromium()
        except Exception as ex:  # noqa: BLE001
            self.log("chromium", f"instalace selhala: {ex}")

    def _ytdlp_quick(self, v):
        exe = self.engines["yt-dlp"].bin_path(version=v)
        code, out = _run([exe, "--version"], timeout=120)
        return code == 0, out.strip()

    def test(self, name: str, version: str | None = None) -> tuple[bool, str]:
        e = self.engines[name]
        ok, msg = e.test(version or e.current())
        v = version or e.current()
        if v:
            e._write_meta(v, tested_ok=ok, tested_at=time.time())
        self.log(name, f"test {v or 'systém'}: {'OK' if ok else 'CHYBA – ' + msg}")
        return ok, msg

    def update(self, name: str) -> dict:
        """Aktualizace s testem a automatickým návratem k předchozí funkční verzi."""
        with self._lock:
            self.busy = name
            try:
                return self._update(name)
            finally:
                self.busy = None

    def _update(self, name: str) -> dict:
        e = self.engines[name]
        old = e.current()
        try:
            rel = e.latest_release()
        except Exception as ex:  # noqa: BLE001
            self.log(name, f"nelze zjistit nejnovější verzi: {ex}")
            return {"status": "error", "message": str(ex)}
        self._record_check(name, rel.version)
        if name == "ffmpeg" and e.prefer_system():
            self.log(name, "na Linuxu se používá systémový ffmpeg (stažená statická verze neumí DNS) – aktualizace přeskočena")
            return {"status": "up-to-date", "version": f"{e.system_version()} (systém)"}
        if old is None:
            sysv = e.system_version()
            if sysv and _vkey(sysv) >= _vkey(rel.version):
                self.log(name, f"systémová verze {sysv} je stejná nebo novější než {rel.version} – ponechávám systémovou")
                return {"status": "up-to-date", "version": f"{sysv} (systém)"}
        if old == rel.version:
            self.log(name, f"aktuální verze {old} je nejnovější")
            return {"status": "up-to-date", "version": old}
        self.log(name, f"nalezena nová verze {rel.version}, stahuji")
        try:
            new = e.install(rel)
        except Exception as ex:  # noqa: BLE001
            self.log(name, f"stažení {rel.version} selhalo: {ex}")
            return {"status": "error", "message": str(ex)}
        ok_new, msg_new = e.test(new)
        e._write_meta(new, tested_ok=ok_new, tested_at=time.time())
        self.log(name, f"test {new}: {'OK' if ok_new else 'CHYBA – ' + msg_new}")
        if ok_new:
            e.set_current(new)
            e.prune(int(self.settings.get("keep_engine_versions", 3)))
            self.log(name, f"aktivní verze je nyní {new}")
            return {"status": "updated", "version": new, "previous": old}
        # nová selhala -> otestovat starou
        ok_old, msg_old = e.test(old) if old or e.bin_path() else (False, "žádná předchozí verze")
        self.log(name, f"test {old or 'systém'}: {'OK' if ok_old else 'CHYBA – ' + msg_old}")
        shutil.rmtree(e.root / new, ignore_errors=True)
        if ok_old:
            self.log(name, f"nová verze selhala, stará prošla → ponechána {old or 'systémová'}, {new} smazána")
            if self.notify:
                self.notify("engine_fail", engine=name, new=new, old=old or "systémová")
            return {"status": "rolled-back", "version": old, "rejected": new, "message": msg_new}
        self.log(name, "selhala nová i stará verze (síť nebo web) → nic se nemění")
        if self.notify:
            self.notify("engine_both_fail", engine=name)
        return {"status": "inconclusive", "version": old, "message": msg_new}

    def rollback(self, name: str, version: str | None = None) -> str:
        e = self.engines[name]
        cur = e.current()
        vs = [v["version"] for v in e.versions() if v["version"] != cur]
        if version:
            if version not in [v["version"] for v in e.versions()]:
                raise ValueError(f"Verze {version} není nainstalovaná")
            target = version
        elif vs:
            target = vs[0]
        else:
            raise ValueError("Není k dispozici jiná verze")
        e.set_current(target)
        self.log(name, f"ruční návrat: aktivní verze {cur} → {target}")
        return target

    def update_all(self) -> dict:
        return {n: self.update(n) for n in self.ORDER}

    def _record_check(self, name, latest):
        if self.db is None:
            return
        d = self.db.kv_get("engine_last_check", {}) or {}
        d[name] = {"t": time.time(), "latest": latest}
        self.db.kv_set("engine_last_check", d)
        self.db.kv_set("engine_last_auto", time.time())

    # ---------------------------------------------------- Chromium (Playwright)
    @staticmethod
    def chromium_present() -> bool:
        env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if env and env != "0":
            base = Path(env)
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Caches" / "ms-playwright"
        elif sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ms-playwright"
        return any(base.glob("chromium_headless_shell-*")) or any(base.glob("chromium-*"))

    def ensure_chromium(self) -> None:
        if self.chromium_present():
            return
        self.log("chromium", "prohlížeč pro sniffer chybí, instaluji (jednorázově, cca 100 MB)")
        ok, msg = self.chromium_install()
        self.log("chromium", "instalace OK" if ok else f"instalace selhala: {msg}")

    @staticmethod
    def chromium_status() -> dict:
        try:
            from playwright._repo_version import version as pw
        except Exception:  # noqa: BLE001
            return {"installed": False, "playwright": None}
        return {"installed": True, "playwright": pw}

    @staticmethod
    def chromium_install() -> tuple[bool, str]:
        try:
            from playwright._impl._driver import compute_driver_executable, get_driver_env
        except Exception as ex:  # noqa: BLE001
            return False, f"Playwright není k dispozici: {ex}"
        exe = compute_driver_executable()
        cmd = list(exe) if isinstance(exe, tuple) else [str(exe)]
        code, out = _run([*cmd, "install", "chromium-headless-shell"], timeout=900, env=get_driver_env())
        return code == 0, out[-500:]
