"""Dávka E po hloubkové revizi: sniffer (živý přenos, DRM v DASH, chybové odpovědi, přímé odkazy, podepsané adresy, opakování)."""
import asyncio
import json
import time

import pytest

from tests.test_runner import probe_video, rt, run_until  # noqa: F401
from viddown import probe
from viddown import runner as runner_mod
from viddown.resolvers import Ctx, ResolveError, sniffer

MEDIA_VOD = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.0,\na.ts\n#EXTINF:6.0,\nb.ts\n#EXT-X-ENDLIST\n"
MEDIA_LIVE = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:120\n#EXTINF:6.0,\na.ts\n#EXTINF:6.0,\nb.ts\n"


def test_live_hls_is_recognised():
    assert sniffer.parse_m3u8(MEDIA_VOD, "https://x.example/v.m3u8")["live"] is False
    assert sniffer.parse_m3u8(MEDIA_LIVE, "https://x.example/v.m3u8")["live"] is True
    master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=640x360\nv.m3u8\n"
    assert sniffer.parse_m3u8(master, "https://x.example/m.m3u8")["live"] is False          # o živosti rozhoduje až playlist varianty


def test_dash_drm_and_direct_links_and_masking():
    assert sniffer.DASH_DRM_RE.search('<ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>')
    assert not sniffer.DASH_DRM_RE.search('<ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011" value="cenc"/>')
    assert sniffer.media_kind("https://x.example/a/v.m3u8?t=1") == "hls"
    assert sniffer.media_kind("https://x.example/a/v.mpd") == "dash"
    assert sniffer.media_kind("https://x.example/a/v.MP4") == "direct"
    assert sniffer.media_kind("https://x.example/a/stranka") is None
    msg = "https://cdn.example/v/1.m3u8?token=TAJNE&exp=1: Server returned 403"
    assert "TAJNE" not in sniffer.mask_urls(msg) and "https://cdn.example/v/1.m3u8?…" in sniffer.mask_urls(msg)


def test_live_candidates_are_not_downloaded(tmp_path):
    class E:
        def get(self, n):
            return type("B", (), {"bin_path": lambda s, *a: "/bin/false"})()
    sn = {"candidates": [{"kind": "hls", "url": "https://x.example/live.m3u8", "live": True, "rank": 2}], "referer": "https://x.example/p",
          "cookies": [], "title": "", "thumbnail": None, "drm": False}
    ctx = Ctx({"live_from_start": False}, E(), tmp_path)
    with pytest.raises(ResolveError) as ei:
        asyncio.run(sniffer.download(sn, ctx, tmp_path / "stg", "v", lambda **k: None, None))
    assert ei.value.kind == "live"


def test_failed_sniffer_download_forces_a_fresh_sniff_next_time(rt, monkeypatch):
    rt.settings.update({"methods": ["sniffer"], "auto_retry_attempts": 0})
    sn = {"candidates": [{"kind": "direct", "url": "https://x.example/v.mp4", "rank": 3}], "referer": "https://x.example/p", "cookies": [],
          "title": "V", "thumbnail": None, "drm": False}

    async def p(url, ctx):
        return {"type": "video", "method": "sniffer", "title": "V", "count": 1, "info": {"sniff": sn, "sniffed_at": time.time(), "title": "V"}}
    monkeypatch.setattr(runner_mod, "probe_url", p)

    async def dl(*a, **k):
        raise ResolveError("Server returned 403 Forbidden", "other")
    monkeypatch.setattr(runner_mod.sniffer, "download", dl)
    jid, _ = rt.add("https://x.example/p")
    asyncio.run(run_until(rt, lambda: rt.db.get(jid)["status"] == "failed"))
    info = json.loads(rt.db.get(jid)["info"])
    assert info.get("sniffed_at") == 0                                         # příští pokus stránku načte znovu (adresy mohly vypršet)


def test_story_with_own_video_respects_disabled_browser_method(monkeypatch):
    async def story(url, ctx):
        return {"sniff": {"candidates": [{"kind": "direct", "url": "https://x.example/v.mp4"}], "drm": False, "title": "", "thumbnail": None}}
    monkeypatch.setattr(probe.pages, "open_story", story)

    class C:
        settings = {"methods": ["ytdlp"]}
    res = asyncio.run(probe.probe_url("https://www.facebook.com/stories/1/abc/", C()))
    assert res["type"] == "none" and "Prohlížeč" in res["error"]
