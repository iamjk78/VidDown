"""Metoda yt-dlp: kontrola URL (metadata) a stažení s průběhem."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from .. import container
from ..util import classify_error, host_key, is_http_url, mask_proxy
from . import Cancelled, Ctx, ProcHolder, ResolveError, cookiepolicy, spawn_proc

PENDING = ".viddown-pending.json"      # hotové stažení čekající na přesun do cílové složky (nebo přerušené po zápisu do archivu yt-dlp)


def save_pending(staging: Path, file: Path, thumb: Path | None, log_text: str, method: str = "ytdlp") -> None:
    """Zapíše značku, že `file` je hotové: další spuštění úlohy ho jen přesune, místo aby ho yt-dlp označil za „už staženo“ (archiv)
    a úloha pak smazala dočasnou složku i s videem."""
    try:
        (staging / PENDING).write_text(json.dumps({"file": str(file), "thumb": str(thumb) if thumb else None, "method": method, "log": log_text or ""}))
    except OSError as e:
        log.warning("značku hotového souboru %s nelze zapsat: %s", file, e)


log = logging.getLogger("viddown.ytdlp")

PROG = ("download:VDPROG %(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.format_id)s")


def _checked(url: str) -> str:
    if not is_http_url(url):
        raise ResolveError("adresa není platná http(s) adresa", "unsupported")
    return url.strip()


def base_cmd(ctx: Ctx) -> list[str]:
    exe = ctx.engines.get("yt-dlp").bin_path()
    if not exe:
        raise ResolveError("yt-dlp není nainstalován (Enginy › Aktualizovat)", "engine")
    cmd = [exe, "--ignore-config", "--no-colors", "--no-warnings"]
    deno = ctx.engines.get("deno").bin_path()
    if deno:
        cmd += ["--js-runtimes", f"deno:{deno}"]
    ff = ctx.engines.get("ffmpeg").bin_path()
    if ff:
        cmd += ["--ffmpeg-location", ff]
    s = ctx.settings
    if ctx.cookies_file:
        cmd += ["--cookies", str(ctx.cookies_file)]
    elif s.get("cookies_mode") == "browser" and not ctx.no_cookies:
        cmd += ["--cookies-from-browser", s.get("cookies_browser") or "chrome"]
    if s.get("proxy"):
        cmd += ["--proxy", s["proxy"]]
    return cmd


def cookie_copy(ctx: Ctx) -> Path | None:
    """Soukromá kopie cookies.txt pro jeden běh: yt-dlp si soubor po skončení přepisuje a souběžné procesy
    by hlavní soubor poškodily nebo vrátily na starší hodnoty."""
    src = ctx.cookies_file
    if not src or ctx.cookies_override is not None:
        return None
    tmp = ctx.data / "ck"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("ck-*.txt"):                    # zbytky po násilně ukončeném běhu
        try:
            if time.time() - old.stat().st_mtime > 86400:
                old.unlink()
        except OSError:
            pass
    fd, name = tempfile.mkstemp(prefix="ck-", suffix=".txt", dir=str(tmp))        # práva 0600
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as f:
            shutil.copyfileobj(f, out)
    except OSError:
        Path(name).unlink(missing_ok=True)
        return None
    return Path(name)


def _drop(path: Path | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


def with_copy(ctx: Ctx) -> tuple[Ctx, Path | None]:
    ck = cookie_copy(ctx)
    return (dataclasses.replace(ctx, cookies_override=ck) if ck else ctx), ck


COOKIES_STALE = "Nahrané cookies už YouTube neuznává"
AGE_RE = re.compile(r"confirm your age|confirm you.re not a bot|age[- ]restricted", re.I)


def cookie_hint(msg: str, ctx: Ctx) -> str:
    """YouTube s nahranými cookies pořád chce přihlášení: cookies přestala platit (zneplatnil je YouTube)."""
    if msg and "[youtube" in msg and AGE_RE.search(msg) and (ctx.cookies_file or (ctx.settings.get("cookies_mode") == "browser" and not ctx.no_cookies)):
        return (msg.split(" Use --cookies")[0].rstrip(". ") + f". {COOKIES_STALE}: "
                "exportujte je znovu z anonymního okna prohlížeče a nahrajte je v Nastavení.")
    return msg


def _error_from(out: str) -> str:
    errs = [l[6:].strip() for l in out.splitlines() if l.startswith("ERROR:")]
    if errs:
        return errs[-1]
    tail = [l for l in out.strip().splitlines() if l.strip()]
    return tail[-1] if tail else "neznámá chyba yt-dlp"

# zpracování po stažení (ffmpeg: metadata, miniatura, titulky) – u velkých souborů na síťovém disku trvá minuty
POST = "postprocess:VDPOST %(progress.status)s|%(progress.postprocessor)s"


async def _run_json(cmd: list[str], timeout: float, ctx: Ctx | None = None, ck: Path | None = None) -> dict:
    try:
        return await _run_json_inner(cmd, timeout, ctx)
    finally:
        _drop(ck)


async def _run_json_inner(cmd: list[str], timeout: float, ctx: Ctx | None) -> dict:
    proc = await spawn_proc(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ResolveError("vypršel časový limit kontroly", "network")
    except asyncio.CancelledError:      # zrušení (např. vypnutí aplikace) nesmí nechat yt-dlp běžet dál
        proc.kill()
        raise
    text = out.decode("utf-8", "replace")
    etext = err.decode("utf-8", "replace")
    if proc.returncode != 0 and not text.strip().startswith("{"):
        msg = _error_from(etext + "\n" + text)
        raise ResolveError(cookie_hint(msg, ctx) if ctx else msg, classify_error(msg))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        msg = _error_from(etext)
        raise ResolveError(cookie_hint(msg, ctx) if ctx else msg, classify_error(msg))


async def probe(url: str, ctx: Ctx, timeout: float = 300, playlist_end: int | None = None) -> dict:
    """Metadata bez stahování. Playlist/kanál vrací plochý seznam položek (volitelně jen prvních `playlist_end`)."""
    return await cookiepolicy.attempt(ctx, url, lambda c: _probe(url, c, timeout, playlist_end))


async def _probe(url: str, ctx: Ctx, timeout: float, playlist_end: int | None) -> dict:
    cctx, ck = with_copy(ctx)
    try:
        cmd = base_cmd(cctx) + ["-J", "--flat-playlist"]
        if playlist_end:
            cmd += ["--playlist-end", str(int(playlist_end))]
        cmd += ["--", _checked(url)]
    except BaseException:                                              # kopie cookies se při chybě sestavení příkazu uklidí
        _drop(ck)
        raise
    return await _run_json(cmd, timeout, ctx, ck)


def polite_args(url: str) -> list[str]:
    """YouTube omezuje relace, které posílají dotazy příliš rychle: yt-dlp mezi svými dotazy krátce počká."""
    return ["--sleep-requests", "1.5"] if host_key(url) == "youtube.com" else []


async def full_info(url: str, ctx: Ctx, timeout: float = 180) -> dict:
    return await cookiepolicy.attempt(ctx, url, lambda c: _full_info(url, c, timeout))


async def _full_info(url: str, ctx: Ctx, timeout: float) -> dict:
    cctx, ck = with_copy(ctx)
    try:
        cmd = base_cmd(cctx) + ["-J", "--no-playlist", *polite_args(url), *format_args(ctx.settings), "--", _checked(url)]
    except BaseException:
        _drop(ck)
        raise
    return await _run_json(cmd, timeout, ctx, ck)


def format_args(s: dict, audio_only: bool | None = None) -> list[str]:
    if audio_only if audio_only is not None else s.get("audio_only"):
        return ["-f", "ba/b", "-x", "--audio-format", s.get("audio_format") or "mp3"]
    if s.get("quality") == "compat":
        return ["-S", "vcodec:h264,res,acodec:m4a", "-f", "bv*+ba/b", "--merge-output-format", "mp4"]
    return ["-f", "bv*+ba/b", "--merge-output-format", "mp4/mkv"]


def best_height(info: dict) -> int | None:
    h = info.get("height")
    if h:
        return int(h)
    for f in info.get("requested_formats") or []:
        if f.get("height"):
            return int(f["height"])
    return None


def size_estimate(info: dict) -> int | None:
    fs = info.get("requested_formats") or [info]
    total = 0
    for f in fs:
        total += int(f.get("filesize") or f.get("filesize_approx") or 0)
    return total or None


from ..cpu import MODES  # noqa: E402


async def download(url: str, info: dict | None, ctx: Ctx, staging: Path, name: str, rate_bps: int | None,
                   on_progress, holder: ProcHolder, audio_only: bool | None = None, no_subs: bool = False) -> dict:
    """Stáhne video do staging. Vrací {"file": Path, "thumb": Path|None} nebo {"skipped": důvod}."""
    return await cookiepolicy.attempt(ctx, url, lambda c: _download_copy(url, info, c, staging, name, rate_bps, on_progress, holder,
                                                                         audio_only, no_subs))


async def _download_copy(url, info, ctx: Ctx, staging, name, rate_bps, on_progress, holder, audio_only, no_subs) -> dict:
    cctx, ck = with_copy(ctx)
    try:
        return await _download(url, info, cctx, staging, name, rate_bps, on_progress, holder, audio_only, no_subs, ctx)
    finally:
        _drop(ck)


async def _download(url, info, ctx: Ctx, staging: Path, name: str, rate_bps, on_progress, holder: ProcHolder,
                    audio_only, no_subs, orig: Ctx) -> dict:
    s = ctx.settings
    staging.mkdir(parents=True, exist_ok=True)
    cmd = base_cmd(ctx) + polite_args(url) + format_args(s, audio_only)
    cmd += ["-P", str(staging), "-o", name.replace("%", "%%") + ".%(ext)s",
            "--no-playlist", "--no-mtime", "--newline", "--progress", "--progress-template", PROG,
            "--no-simulate", "--print", "after_move:VDFILE %(filepath)s",
            "--progress-template", POST,
            "-R", str(s.get("retries", 5)), "--fragment-retries", str(s.get("retries", 5)),
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "--download-archive", str(ctx.data / "archive.txt")]
    if s.get("embed_metadata"):
        cmd += ["--embed-thumbnail", "--embed-metadata", "--embed-chapters"]
    use_subs = bool(s.get("subtitles")) and not no_subs
    if use_subs:
        cmd += ["--write-subs", "--sub-langs", s.get("subtitle_langs") or "cs,en", "--embed-subs"]
        if s.get("auto_subtitles"):
            cmd += ["--write-auto-subs"]
    if s.get("live_from_start"):
        cmd += ["--live-from-start"]
    else:
        cmd += ["--match-filter", "!is_live"]
    if rate_bps:
        cmd += ["-r", str(int(rate_bps))]
    threads = MODES.get(s.get("perf_mode", "full"), MODES["full"])[1]
    if threads:
        cmd += ["--postprocessor-args", f"ffmpeg:-threads {threads}"]
    cmd += ["--", _checked(url)]

    # odhad celkové velikosti přes všechny části (video + audio)
    parts: dict[str, list] = {}
    for f in (info or {}).get("requested_formats") or []:
        parts[str(f.get("format_id"))] = [0, int(f.get("filesize") or f.get("filesize_approx") or 0)]

    log.debug("yt-dlp cmd: %s", [mask_proxy(c) if "://" in c and "@" in c else c for c in cmd])
    holder.check()
    proc = await spawn_proc(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    await holder.attach(proc)
    filepath = None
    skipped = None
    tail: list[str] = []
    last_emit = 0.0
    assert proc.stdout
    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith("VDPROG "):
                st, dl, tot, est, spd, eta, fid = (line[7:].split("|") + [""] * 7)[:7]
                num = lambda x: float(x) if x not in ("NA", "None", "") else None  # noqa: E731
                dlv, totv = num(dl) or 0, num(tot) or num(est) or 0
                p = parts.setdefault(fid, [0, 0])
                p[0] = dlv
                if totv:
                    p[1] = max(p[1], int(totv)) if st != "finished" else int(dlv or totv)
                now = time.monotonic()
                if now - last_emit > 0.5 or st == "finished":
                    last_emit = now
                    done = sum(x[0] for x in parts.values())
                    total = sum(x[1] for x in parts.values())
                    on_progress(downloaded=int(done), total=int(total) or None,
                                progress=(min(done / total, 1.0) if total else None),
                                speed=num(spd), eta=int(num(eta)) if num(eta) is not None else None)
                continue
            if line.startswith("VDPOST "):
                if line.startswith("VDPOST started"):   # stažení je hotové, běží ffmpeg: ukázat 100 % bez rychlosti
                    done = int(sum(x[0] for x in parts.values()) or sum(x[1] for x in parts.values()) or 0)
                    on_progress(progress=1.0, speed=None, eta=None, phase="post", **({"downloaded": done, "total": done} if done else {}))
                continue
            if line.startswith("VDFILE "):
                filepath = line[7:].strip()
                continue
            if "has already been recorded in the archive" in line:
                skipped = "archive"
            elif "does not pass filter" in line and "is_live" in line:
                skipped = "live"
            tail.append(line)
            tail = tail[-40:]
    except BaseException:                                               # chyba při čtení výstupu nesmí nechat yt-dlp běžet dál
        if proc.returncode is None:
            proc.kill()
        raise
    code = await proc.wait()
    holder.proc = None
    if holder.stopped:
        if filepath and Path(filepath).is_file():                       # yt-dlp už video zapsal do archivu: soubor se musí dokončit později
            save_pending(staging, Path(filepath), None, "\n".join(tail))
        raise Cancelled()
    if skipped:
        return {"skipped": skipped}
    if code == 0 and not filepath and not any(l.startswith("ERROR") for l in tail):
        # --print vypíná hlášky yt-dlp: úspěšný konec bez souboru = video už je v archivu stažených
        return {"skipped": "archive"}
    if code != 0 or not filepath:
        msg = _error_from("\n".join(tail))
        if code != 0 or not tail:
            log.warning("yt-dlp skončil s kódem %s, souborem %r; poslední řádky: %s", code, filepath, " | ".join(tail[-6:]))
        if use_subs and "subtitle" in msg.lower():
            # titulky jsou doplněk (YouTube je často omezuje – HTTP 429): video stáhneme i bez nich
            log.warning("titulky se nepodařilo stáhnout (%s), zkouším bez titulků", msg)
            return await download(url, info, ctx, staging, name, rate_bps, on_progress, holder, audio_only, no_subs=True)
        raise ResolveError(cookie_hint(msg, orig), classify_error(msg))
    fp = Path(filepath)
    # yt-dlp už zapsal ID do archivu: hotový soubor se označí hned, aby pád před přesunem nezpůsobil ztrátu (další běh by ho přeskočil)
    save_pending(staging, fp, None, "\n".join(tail))
    if s.get("mkv_to_mp4", True) and fp.suffix.lower() == ".mkv":       # jen změna kontejneru (kopie proudů), nic se nekóduje
        on_progress(progress=1.0, speed=None, eta=None, phase="post")
        ff = None
        try:
            ff = ctx.engines.get("ffmpeg").bin_path()
        except Exception:  # noqa: BLE001
            ff = None
        try:
            remuxed = await container.remux_mkv_to_mp4(str(ff) if ff else shutil.which("ffmpeg"), fp, holder, MODES.get(s.get("perf_mode", "full"), MODES["full"])[1] or None)
        except Cancelled:                                               # přerušení uprostřed přebalení: video je už v archivu, musí se dokončit později
            save_pending(staging, fp if fp.is_file() else Path(filepath), None, "\n".join(tail))
            raise
        if remuxed:
            fp = remuxed
        if holder.stopped:
            save_pending(staging, fp if fp.is_file() else Path(filepath), None, "\n".join(tail))       # přebalení přerušeno: video je v archivu, soubor zůstane k dokončení
            raise Cancelled()
    thumb = fp.with_suffix(".jpg")
    if not thumb.exists():
        jpgs = [p for p in staging.glob("*.jpg")]
        thumb = jpgs[0] if jpgs else None
    save_pending(staging, fp, thumb, "\n".join(tail))                  # po přebalení je finální soubor, s miniaturou
    return {"file": fp, "thumb": thumb, "log": "\n".join(tail)}
