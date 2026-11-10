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
        return "https://www.facebook.com/reel/1/"

    async def fake_ytdlp(url, ctx):
        assert url == "https://www.facebook.com/reel/1/"
        return {"type": "video", "method": "ytdlp", "title": "R", "info": {"id": "1"}}

    class Ctx:
        class settings:  # noqa: N801
            @staticmethod
            def get(k, d=None):
                return ["ytdlp"] if k == "methods" else d
    monkeypatch.setattr(probe.pages, "resolve_embedded", fake_resolve)
    monkeypatch.setattr(probe, "_probe_ytdlp", fake_ytdlp)
    story = "https://www.facebook.com/stories/1/abc/"
    res = asyncio.run(probe.probe_url(story, Ctx()))
    assert res["resolved_url"] == "https://www.facebook.com/reel/1/" and res["info"]["origin_url"] == story

    async def fail_resolve(url, ctx):
        raise ResolveError("žádný odkaz", "unsupported")
    monkeypatch.setattr(probe.pages, "resolve_embedded", fail_resolve)
    assert asyncio.run(probe.probe_url(story, Ctx()))["type"] == "none"
