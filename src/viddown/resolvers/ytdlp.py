"""Metoda yt-dlp: kontrola URL (metadata) a stažení s průběhem."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from ..util import classify_error
from . import Cancelled, Ctx, ProcHolder, ResolveError, subprocess_kwargs

log = logging.getLogger("viddown.ytdlp")

PROG = ("download:VDPROG %(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.format_id)s")


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
    elif s.get("cookies_mode") == "browser":
        cmd += ["--cookies-from-browser", s.get("cookies_browser") or "chrome"]
    if s.get("proxy"):
        cmd += ["--proxy", s["proxy"]]
    return cmd


def _error_from(out: str) -> str:
    errs = [l[6:].strip() for l in out.splitlines() if l.startswith("ERROR:")]
    if errs:
        return errs[-1]
    tail = [l for l in out.strip().splitlines() if l.strip()]
    return tail[-1] if tail else "neznámá chyba yt-dlp"


async def _run_json(cmd: list[str], timeout: float) -> dict:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                **subprocess_kwargs())
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ResolveError("vypršel časový limit kontroly", "network")
    text = out.decode("utf-8", "replace")
    etext = err.decode("utf-8", "replace")
    if proc.returncode != 0 and not text.strip().startswith("{"):
        msg = _error_from(etext + "\n" + text)
        raise ResolveError(msg, classify_error(msg))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        msg = _error_from(etext)
        raise ResolveError(msg, classify_error(msg))


async def probe(url: str, ctx: Ctx, timeout: float = 300, playlist_end: int | None = None) -> dict:
    """Metadata bez stahování. Playlist/kanál vrací plochý seznam položek (volitelně jen prvních `playlist_end`)."""
    cmd = base_cmd(ctx) + ["-J", "--flat-playlist"]
    if playlist_end:
        cmd += ["--playlist-end", str(int(playlist_end))]
    cmd.append(url)
    return await _run_json(cmd, timeout)


async def full_info(url: str, ctx: Ctx, timeout: float = 180) -> dict:
    cmd = base_cmd(ctx) + ["-J", "--no-playlist", *format_args(ctx.settings), url]
    return await _run_json(cmd, timeout)


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
    s = ctx.settings
    staging.mkdir(parents=True, exist_ok=True)
    cmd = base_cmd(ctx) + format_args(s, audio_only)
    cmd += ["-P", str(staging), "-o", name.replace("%", "%%") + ".%(ext)s",
            "--no-playlist", "--no-mtime", "--newline", "--progress", "--progress-template", PROG,
            "--no-simulate", "--print", "after_move:VDFILE %(filepath)s",
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
    cmd.append(url)

    # odhad celkové velikosti přes všechny části (video + audio)
    parts: dict[str, list] = {}
    for f in (info or {}).get("requested_formats") or []:
        parts[str(f.get("format_id"))] = [0, int(f.get("filesize") or f.get("filesize_approx") or 0)]

    log.debug("yt-dlp cmd: %s", cmd)
    holder.check()
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                **subprocess_kwargs())
    await holder.attach(proc)
    filepath = None
    skipped = None
    tail: list[str] = []
    last_emit = 0.0
    assert proc.stdout
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
        if line.startswith("VDFILE "):
            filepath = line[7:].strip()
            continue
        if "has already been recorded in the archive" in line:
            skipped = "archive"
        elif "does not pass filter" in line and "is_live" in line:
            skipped = "live"
        tail.append(line)
        tail = tail[-40:]
    code = await proc.wait()
    holder.proc = None
    if holder.stopped:
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
        raise ResolveError(msg, classify_error(msg))
    fp = Path(filepath)
    thumb = fp.with_suffix(".jpg")
    if not thumb.exists():
        jpgs = [p for p in staging.glob("*.jpg")]
        thumb = jpgs[0] if jpgs else None
    return {"file": fp, "thumb": thumb, "log": "\n".join(tail)}
