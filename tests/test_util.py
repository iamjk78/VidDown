import time

from viddown import util


def test_sanitize_filename_windows_safe():
    assert util.sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "a b c d e f g h i j"
    assert util.sanitize_filename("CON") == "_CON"
    assert util.sanitize_filename("  tečka na konci.  ") == "tečka na konci"
    assert util.sanitize_filename("") == "video"
    long = "ž" * 200
    assert len(util.sanitize_filename(long).encode()) <= 150


def test_render_template_tokens_and_separators():
    info = {"title": "Islandské fjordy", "channel": "Nordic", "upload_date": "20261105", "height": 2160, "id": "abc"}
    assert util.render_template("{kanál}_{název}", info) == "Nordic_Islandské fjordy"
    assert util.render_template("{datum} {title} [{id}]", info) == "2026-11-05 Islandské fjordy [abc]"
    assert util.render_template("{název} [{id}]", {"title": "X"}) == "X"
    assert util.render_template("{rozlišení} - {název}", info) == "2160p - Islandské fjordy"
    # chybějící token se vypustí i s oddělovačem
    assert util.render_template("{kanál}_{název}", {"title": "X"}) == "X"
    assert util.render_template("{playlist} - {název}", {"title": "X"}) == "X"


def test_unique_target_pairs_video_and_thumbnail(tmp_path):
    (tmp_path / "Video.mp4").write_text("x")
    p = util.unique_target(tmp_path, "Video", ".mp4")
    assert p.name == "Video (2).mp4"
    (tmp_path / "Jiné.jpg").write_text("x")  # existuje jen miniatura -> taky obsazeno
    assert util.unique_target(tmp_path, "Jiné", ".mkv").name == "Jiné (2).mkv"


def test_extract_urls():
    t = "Mrkni na https://youtu.be/abc?t=1, a taky (https://example.com/video.m3u8)."
    assert util.extract_urls(t) == ["https://youtu.be/abc?t=1", "https://example.com/video.m3u8"]


def test_is_hls_response():
    assert util.is_hls_response("https://x/a.m3u8?token=1", "")
    assert util.is_hls_response("https://x/play", "application/vnd.apple.mpegurl; charset=utf-8")
    assert not util.is_hls_response("https://x/?file=a.m3u8", "text/html")
    assert not util.is_hls_response("https://x/seg1.ts", "video/mp2t")


def test_error_classification_and_rules():
    assert util.classify_error("ERROR: Unsupported URL: https://x") == "unsupported"
    assert util.classify_error("Private video. Sign in if you've been granted access") == "login"
    assert util.classify_error("This video is DRM protected") == "drm"
    assert util.classify_error("Read timed out") == "network"
    assert util.fallback_allowed("unsupported") and not util.fallback_allowed("login")
    assert util.retry_allowed("network") and not util.retry_allowed("removed")


def test_youtube_channel_base():
    assert util.youtube_channel_base("https://www.youtube.com/@nejaky-kanal") == "https://www.youtube.com/@nejaky-kanal"
    assert util.youtube_channel_base("https://youtube.com/@x/videos") == "https://www.youtube.com/@x"
    assert util.youtube_channel_base("https://www.youtube.com/channel/UC123") == "https://www.youtube.com/channel/UC123"
    assert util.youtube_channel_base("https://www.youtube.com/watch?v=1") is None
    assert util.youtube_channel_base("https://www.youtube.com/@x/playlists") is None


def _ts(h, m, wday_offset=0):
    lt = time.localtime()
    base = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
    return base + wday_offset * 86400


def test_schedule_window_over_midnight():
    s = {"schedule_enabled": True, "schedule_start": "22:00", "schedule_end": "06:00", "schedule_days": [0, 1, 2, 3, 4, 5, 6]}
    assert util.in_schedule(s, _ts(23, 0))
    assert util.in_schedule(s, _ts(3, 0))
    assert not util.in_schedule(s, _ts(12, 0))
    s2 = dict(s, schedule_start="08:00", schedule_end="17:00")
    assert util.in_schedule(s2, _ts(9, 0)) and not util.in_schedule(s2, _ts(18, 0))
    assert util.in_schedule({"schedule_enabled": False}, _ts(12, 0))


def test_check_dir_writable(tmp_path):
    ok, msg = util.check_dir_writable(str(tmp_path / "nova" / "slozka"), docker=False)
    assert ok and (tmp_path / "nova" / "slozka").is_dir()
    assert not list((tmp_path / "nova" / "slozka").iterdir())  # zkušební soubor uklizen
    ok, msg = util.check_dir_writable("relativni/cesta", docker=False)
    assert not ok and "absolutní" in msg
    ro = tmp_path / "jen-cteni"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        ok, msg = util.check_dir_writable(str(ro / "pod"), docker=False)
        assert not ok and "platnou cestu" in msg
    finally:
        ro.chmod(0o700)
    f = tmp_path / "soubor.txt"
    f.write_text("x")
    assert not util.check_dir_writable(str(f), docker=False)[0]


def test_cookies_error_classified_before_login():
    msg = "could not find firefox cookies database in '/data/.mozilla/firefox'"
    assert util.classify_error(msg) == "cookies"
    assert not util.fallback_allowed("cookies") and not util.retry_allowed("cookies")
    assert util.classify_error("Sign in to confirm you're not a bot. Use --cookies") == "login"


def test_free_space_unreliable_for_docker_desktop_volumes(tmp_path, monkeypatch):
    monkeypatch.setattr(util, "_mount_source", lambda p: "/run/host_mark/Volumes")
    assert util.free_space(tmp_path) == (None, False)
    monkeypatch.setattr(util, "_mount_source", lambda p: "/run/host_mark/Users")
    free, ok = util.free_space(tmp_path)
    assert ok and free > 0
