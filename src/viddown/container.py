"""Změna kontejneru po stažení: MKV → MP4 bez jakéhokoli kódování (PLAN.md kap. 24).

yt-dlp skládá obraz a zvuk do MKV, když je MP4 nepodporuje (typicky AV1 nebo VP9 s Opusem z YouTube). Safari soubory MKV vůbec
nepřehraje, MP4 ano. ffmpeg proto po stažení všechny proudy (obraz, zvuk, titulky, obálku, kapitoly) jen zkopíruje do MP4
(`-c copy`; text titulků se převede do formátu MP4 `mov_text`). Obraz ani zvuk se nekódují, kvalita ani rozlišení se nemění
a trvá to sekundy (omezuje jen disk). Když by přebalení z jakéhokoli důvodu selhalo, zůstane původní MKV beze změny.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .resolvers import subprocess_kwargs

log = logging.getLogger("viddown.container")


def _cmd(ffmpeg: str, src: Path, tmp: Path, subs: bool, threads: int | None) -> list[str]:
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin"]
    if threads:
        cmd += ["-threads", str(threads)]
    cmd += ["-i", str(src), "-map", "0:v", "-map", "0:a?"]
    cmd += ["-map", "0:s?", "-c", "copy", "-c:s", "mov_text"] if subs else ["-sn", "-c", "copy"]
    return cmd + ["-movflags", "+faststart", "-f", "mp4", str(tmp)]


async def remux_mkv_to_mp4(ffmpeg: str | None, src: Path, holder=None, threads: int | None = None) -> Path | None:
    """Přebalí `src` (.mkv) do `.mp4` vedle něj a původní soubor smaže. Vrací nový soubor, nebo None (zůstává původní). Nejdřív se
    zkusí se všemi stopami včetně titulků, při neúspěchu bez titulků."""
    if not ffmpeg or src.suffix.lower() != ".mkv" or not src.is_file():
        return None
    dst = src.with_suffix(".mp4")
    if dst.exists():                                                   # cizí soubor se stejným názvem se nepřepisuje
        return None
    tmp = src.with_name(src.stem + ".remux.part")
    try:
        for subs in (True, False):
            tmp.unlink(missing_ok=True)
            proc = await asyncio.create_subprocess_exec(*_cmd(ffmpeg, src, tmp, subs, threads), stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.PIPE, **subprocess_kwargs())
            if holder is not None:
                await holder.attach(proc)
            _, err = await proc.communicate()
            if holder is not None:
                holder.proc = None
                holder.check()                                         # zrušení uživatelem: vyhodí Cancelled, přerušené se uklidí níže
            if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
                tmp.replace(dst)
                src.unlink(missing_ok=True)
                return dst
            log.warning("přebalení %s do MP4 (%s titulky) selhalo: %s", src.name, "s" if subs else "bez", err.decode("utf-8", "replace")[-200:])
    except OSError as e:
        log.warning("přebalení %s do MP4 selhalo: %s", src.name, e)
    finally:
        tmp.unlink(missing_ok=True)
    return None
