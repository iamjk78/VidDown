"""Přebalení MKV → MP4 po stažení: jen kopie proudů, nikdy kódování; při selhání zůstane původní soubor."""
import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from viddown import container
from viddown.config import DEFAULTS
from viddown.resolvers import Cancelled, ProcHolder

FF = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FF, reason="ffmpeg není nainstalován")


def probe(path):
    out = subprocess.run([FF.replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    return [x for x in out.split() if x]


def make_mkv(tmp_path, name="v.mkv", subs=True, audio="libopus", video="libx264"):
    srt = tmp_path / "s.vtt"
    srt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nAhoj\n")
    cmd = [FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=10", "-f", "lavfi", "-i", "sine=duration=2"]
    if subs:
        cmd += ["-i", str(srt)]
    cmd += ["-map", "0:v", "-map", "1:a", *(["-map", "2:s"] if subs else []), "-c:v", video, "-c:a", audio, *(["-c:s", "webvtt"] if subs else []), "-shortest", "-t", "2",
            str(tmp_path / name)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL, timeout=60)
    return tmp_path / name


@needs_ffmpeg
def test_remux_copies_every_stream_without_encoding(tmp_path):
    src = make_mkv(tmp_path)
    before = probe(src)
    out = asyncio.run(container.remux_mkv_to_mp4(FF, src))
    assert out == tmp_path / "v.mp4" and out.is_file() and not src.exists()                 # původní MKV se smaže až po úspěchu
    after = probe(out)
    assert any("h264" in x and "640,360" in x for x in after) and any("opus" in x for x in after) and any("mov_text" in x for x in after)
    assert any("h264" in x for x in before) and not list(tmp_path.glob("*.part"))


@needs_ffmpeg
def test_remux_is_a_pure_copy_of_the_video_and_audio_packets(tmp_path):
    src = make_mkv(tmp_path, subs=False)
    def md5(p, kind):
        r = subprocess.run([FF, "-v", "error", "-i", str(p), "-map", f"0:{kind}:0", "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return r.stdout.strip()
    v, a = md5(src, "v"), md5(src, "a")
    out = asyncio.run(container.remux_mkv_to_mp4(FF, src))
    assert md5(out, "v") == v and md5(out, "a") == a                                         # stejné pakety obrazu i zvuku, nic se nepřekódovalo


@needs_ffmpeg
def test_remux_without_subtitles_works_and_non_mkv_is_left_alone(tmp_path):
    src = make_mkv(tmp_path, subs=False)
    assert asyncio.run(container.remux_mkv_to_mp4(FF, src)).suffix == ".mp4"
    other = tmp_path / "x.webm"
    other.write_bytes(b"abc")
    assert asyncio.run(container.remux_mkv_to_mp4(FF, other)) is None and other.exists()
    assert asyncio.run(container.remux_mkv_to_mp4(FF, tmp_path / "chybi.mkv")) is None
    assert asyncio.run(container.remux_mkv_to_mp4(None, tmp_path / "x.mkv")) is None       # bez ffmpeg se nic neděje


@needs_ffmpeg
def test_remux_failure_keeps_the_original_and_cleans_up(tmp_path):
    broken = tmp_path / "bad.mkv"
    broken.write_bytes(b"to neni video" * 100)
    assert asyncio.run(container.remux_mkv_to_mp4(FF, broken)) is None
    assert broken.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["bad.mkv"]
    src = make_mkv(tmp_path, "keep.mkv", subs=False)
    (tmp_path / "keep.mp4").write_bytes(b"cizi soubor")
    assert asyncio.run(container.remux_mkv_to_mp4(FF, src)) is None                          # cizí MP4 se stejným názvem se nepřepisuje
    assert src.exists() and (tmp_path / "keep.mp4").read_bytes() == b"cizi soubor"


def test_remux_retries_without_subtitles_when_the_first_attempt_fails(tmp_path, monkeypatch):
    calls = []
    src = tmp_path / "v.mkv"
    src.write_bytes(b"mkv")
    fake = tmp_path / "ff.sh"
    fake.write_text('#!/bin/sh\nfor a in "$@"; do last="$a"; done\ncase "$*" in *mov_text*) echo "boom" >&2; exit 1;; esac\nprintf mp4data > "$last"\n')
    fake.chmod(0o755)
    out = asyncio.run(container.remux_mkv_to_mp4(str(fake), src))
    assert out == tmp_path / "v.mp4" and out.read_bytes() == b"mp4data" and not src.exists()   # druhý pokus bez titulků uspěl


def test_remux_command_never_encodes(tmp_path):
    for subs in (True, False):
        cmd = " ".join(container._cmd("ffmpeg", tmp_path / "a.mkv", tmp_path / "o.part", subs, 2))
        assert "-c copy" in cmd and "-threads 2" in cmd and "-movflags +faststart" in cmd
        for forbidden in ("libx264", "libx265", "libsvtav1", "libvpx", "aac", "-crf", "-vf", "scale"):
            assert forbidden not in cmd, forbidden
    assert "-c:s mov_text" in " ".join(container._cmd("ffmpeg", tmp_path / "a.mkv", tmp_path / "o.part", True, None))


def test_cancel_during_remux_raises_and_cleans_up(tmp_path):
    src = tmp_path / "v.mkv"
    src.write_bytes(b"mkv")
    slow = tmp_path / "ff.sh"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    holder = ProcHolder()

    async def go():
        t = asyncio.create_task(container.remux_mkv_to_mp4(str(slow), src, holder))
        await asyncio.sleep(0.5)
        await holder.stop()
        return await t
    with pytest.raises(Cancelled):
        asyncio.run(go())
    assert src.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["ff.sh", "v.mkv"]


def test_setting_default_is_on():
    assert DEFAULTS["mkv_to_mp4"] is True


# ------------------------------------------------------------ zapojení do stahování (yt-dlp)
def _fake_download_ctx(tmp_path, template, **settings):
    from viddown.resolvers import Ctx
    script = tmp_path / "yt-dlp"
    script.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do case "$1" in -P) d="$2"; shift;; esac; shift; done\n'
                      f'mkdir -p "$d"; cp "{template}" "$d/video.mkv"; echo "VDFILE $d/video.mkv"\n')
    script.chmod(0o755)

    class Eng:
        def get(self, name):
            path = {"yt-dlp": str(script), "ffmpeg": FF}.get(name)
            return type("E", (), {"bin_path": lambda self_: path})()
    return Ctx(settings={"retries": 1, "perf_mode": "full", **settings}, engines=Eng(), data=tmp_path)


@needs_ffmpeg
def test_download_turns_mkv_into_mp4_when_enabled(tmp_path):
    from viddown.resolvers import ytdlp
    tpl = make_mkv(tmp_path, "tpl.mkv")
    ctx = _fake_download_ctx(tmp_path, tpl)
    holder = ProcHolder()
    res = asyncio.run(ytdlp.download("https://v/x", None, ctx, tmp_path / "stg", "video", None, lambda **kw: None, holder))
    assert res["file"] == tmp_path / "stg" / "video.mp4" and res["file"].is_file() and not (tmp_path / "stg" / "video.mkv").exists()
    assert any("h264" in x for x in probe(res["file"]))


@needs_ffmpeg
def test_download_keeps_mkv_when_the_setting_is_off(tmp_path):
    from viddown.resolvers import ytdlp
    tpl = make_mkv(tmp_path, "tpl.mkv")
    ctx = _fake_download_ctx(tmp_path, tpl, mkv_to_mp4=False)
    res = asyncio.run(ytdlp.download("https://v/x", None, ctx, tmp_path / "stg", "video", None, lambda **kw: None, ProcHolder()))
    assert res["file"].suffix == ".mkv" and res["file"].is_file()


@needs_ffmpeg
def test_download_keeps_mkv_when_remux_fails(tmp_path):
    from viddown.resolvers import ytdlp
    bad = tmp_path / "bad.mkv"
    bad.write_bytes(b"neni video" * 50)
    ctx = _fake_download_ctx(tmp_path, bad)
    res = asyncio.run(ytdlp.download("https://v/x", None, ctx, tmp_path / "stg", "video", None, lambda **kw: None, ProcHolder()))
    assert res["file"].suffix == ".mkv" and res["file"].is_file()                          # stažení se kvůli přebalení nikdy nezahodí
