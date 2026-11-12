from viddown.resolvers.sniffer import parse_netscape_cookies


def test_cookie_expiry_in_milliseconds_is_converted(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tTRUE\t1794769255661\tms\tv1\n"      # milisekundy (Firefox)
        ".example.com\tTRUE\t/\tFALSE\t1794769255\tsec\tv2\n"        # sekundy
        ".example.com\tTRUE\t/\tFALSE\t0\tsession\tv3\n"             # relační
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t1794769255\thttp\tv4\n")
    c = {x["name"]: x for x in parse_netscape_cookies(f)}
    assert c["ms"]["expires"] == 1794769255
    assert c["sec"]["expires"] == 1794769255
    assert "expires" not in c["session"]
    assert c["http"]["domain"] == ".example.com" and c["http"]["secure"] is True


def test_story_url_detection_and_link_pick():
    from viddown.resolvers import pages
    assert pages.is_story_url("https://www.facebook.com/stories/100000000000001/AAAAAAAAAAAA/?view_single=1")
    assert not pages.is_story_url("https://www.facebook.com/reel/100000000000002/")
    hrefs = ["https://www.facebook.com/reel/?s=tab", "https://www.facebook.com/",
             "https://www.facebook.com/reel/100000000000002/?__tn__=-R",
             "https://www.facebook.com/watch/?v=999"]
    assert pages.pick_video_link(hrefs) == "https://www.facebook.com/reel/100000000000002/"
    assert pages.pick_video_link(["https://www.facebook.com/watch/?v=999"]).endswith("v=999")
    assert pages.pick_video_link(["https://www.facebook.com/", "https://x.com/reel/5"]) is None


def test_probe_resolves_story_to_embedded_video(monkeypatch):
    import asyncio
    from viddown import probe
    from viddown.resolvers import ResolveError

    async def fake_resolve(url, ctx):
        return {"link": "https://www.facebook.com/reel/1/"}

    async def fake_ytdlp(url, ctx):
        assert url == "https://www.facebook.com/reel/1/"
        return {"type": "video", "method": "ytdlp", "title": "R", "info": {"id": "1"}}

    class Ctx:
        class settings:  # noqa: N801
            @staticmethod
            def get(k, d=None):
                return ["ytdlp"] if k == "methods" else d
    monkeypatch.setattr(probe.pages, "open_story", fake_resolve)
    monkeypatch.setattr(probe, "_probe_ytdlp", fake_ytdlp)
    story = "https://www.facebook.com/stories/1/abc/"
    res = asyncio.run(probe.probe_url(story, Ctx()))
    assert res["resolved_url"] == "https://www.facebook.com/reel/1/" and res["info"]["origin_url"] == story

    async def fail_resolve(url, ctx):
        raise ResolveError("žádný odkaz", "unsupported")
    monkeypatch.setattr(probe.pages, "open_story", fail_resolve)
    assert asyncio.run(probe.probe_url(story, Ctx()))["type"] == "none"


def test_story_media_helpers():
    import base64
    import json
    from viddown.resolvers import pages

    def efg(tag):
        return base64.urlsafe_b64encode(json.dumps({"vencode_tag": tag}).encode()).decode().rstrip("=")
    base = "https://scontent.x/o1/v/a.mp4?_nc_cat=1&efg=%s&bytestart=0&byteend=906&oh=abc"
    assert pages.stream_kind(base % efg("dash_ln_heaac_vbr3_audio")) == "audio"
    assert pages.stream_kind(base % efg("dash_av1_540p_video")) == "video"
    assert pages.stream_kind("https://x/a.mp4") == "video"
    u = pages.whole_file_url(base % "E")
    assert "bytestart" not in u and "byteend" not in u and "oh=abc" in u and "_nc_cat=1" in u
    assert pages.story_author("Počet nepřečtených upozornění\n18\nRadio Kiss\n15 h\nPošlete zprávu") == "Radio Kiss"
    assert pages.story_author("nic") is None


def test_junk_direct_placeholder_and_ads():
    from viddown.resolvers.sniffer import is_junk_direct
    assert is_junk_direct("https://cdn.player.example/img/black2.mp4", 2238)
    assert is_junk_direct("https://cdn.player.example/img/black2.mp4", 0)
    assert is_junk_direct("https://cdn.flashtalking.com/1/ad.mp4", 1_800_000)
    assert is_junk_direct("https://example.com/tiny.mp4", 3000)
    assert not is_junk_direct("https://example.com/video.mp4", 0)
    assert not is_junk_direct("https://example.com/video.mp4", 80_000_000)


def test_implausible_size():
    from viddown.resolvers.sniffer import implausible_size
    assert implausible_size(2246, 2000)
    assert implausible_size(2_000_000, 1800)       # 2 MB na 30 minut
    assert implausible_size(500_000, None) is None  # bez znalosti délky stačí minimum
    assert implausible_size(300_000_000, 1800) is None
