"""Integrační test snifferu: lokální HTTP server s HLS streamem (master + varianty + samostatné audio),
skutečné Chromium (Playwright) a ffmpeg. Přeskočí se, když chybí ffmpeg nebo Chromium."""
import asyncio
import functools
import http.server
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from viddown.config import Settings
from viddown.engines import EngineManager
from viddown.resolvers import Ctx, ProcHolder
from viddown.resolvers import sniffer

FF = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not FF, reason="ffmpeg není k dispozici")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Testovací video</title>
<meta property="og:image" content="/poster.jpg"></head><body>
<video id="v" controls width="640" poster="/poster.jpg"></video>
<script>
  // simulace HLS přehrávače (hls.js) – stáhne master playlist přes fetch
  fetch('/hls/master.m3u8').then(r => r.text()).then(t => document.title = 'Testovací video');
</script></body></html>"""


def _make_hls(root: Path):
    hls = root / "hls"
    hls.mkdir()
    for name, size in (("v360", "640x360"), ("v720", "1280x720")):
        subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration=4:size={size}:rate=25",
                        "-c:v", "libx264" if _has_x264() else "mpeg4", "-g", "25", "-f", "hls", "-hls_time", "1",
                        "-hls_playlist_type", "vod", "-hls_segment_filename", str(hls / f"{name}_%02d.ts"),
                        str(hls / f"{name}.m3u8")], check=True)
    subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:a", "aac",
                    "-f", "hls", "-hls_time", "1", "-hls_playlist_type", "vod",
                    "-hls_segment_filename", str(hls / "a_%02d.ts"), str(hls / "audio.m3u8")], check=True)
    (hls / "master.m3u8").write_text(
        "#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=\"aud\",NAME=\"cz\",DEFAULT=YES,URI=\"audio.m3u8\"\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,AUDIO=\"aud\"\nv360.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,AUDIO=\"aud\"\nv720.m3u8\n")
    subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:size=320x180", "-frames:v", "1", str(root / "poster.jpg")], check=True)
    (root / "index.html").write_text(PAGE, encoding="utf-8")


def _has_x264():
    out = subprocess.run([FF, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return "libx264" in out


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def guess_type(self, path):
        if str(path).endswith(".m3u8"):
            return "application/vnd.apple.mpegurl"
        return super().guess_type(path)


@pytest.fixture()
def site(tmp_path):
    _make_hls(tmp_path)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path)))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _chromium_ok():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def test_sniff_finds_best_variant_and_downloads(site, data, tmp_path):
    if not _chromium_ok():
        pytest.skip("Chromium (Playwright) není nainstalováno")
    s = Settings()
    s.update({"sniff_timeout": 20})
    ctx = Ctx(s.all(), EngineManager(data, s), data)
    sn = asyncio.run(sniffer.sniff(site + "/index.html", ctx))
    assert sn["title"] == "Testovací video"
    assert sn["thumbnail"].endswith("/poster.jpg")
    best = sn["candidates"][0]
    assert best["kind"] == "hls" and best["height"] == 720 and best["url"].endswith("v720.m3u8")
    assert best["audio"].endswith("audio.m3u8")
    # varianty z master playlistu se nepočítají jako další videa
    assert len([c for c in sn["candidates"] if c["kind"] != "direct"]) == 1

    progress = []
    out = asyncio.run(sniffer.download(sn, ctx, tmp_path / "stage", "Testovací video",
                                       lambda **kw: progress.append(kw), ProcHolder()))
    f = out["file"]
    assert f.exists() and f.stat().st_size > 10_000
    probe = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,height",
                            "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout
    assert "video,720" in probe and "audio" in probe
