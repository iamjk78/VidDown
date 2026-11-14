"""Cookies pro yt-dlp: každý běh dostane soukromou kopii a hlavní soubor zůstane beze změny; neplatné YouTube cookies se hlásí srozumitelně."""
import asyncio
import os
import stat

from viddown.resolvers import Ctx, ytdlp

SECRET = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t2000000000\tsid\tabc\n"


def make_ctx(tmp_path, mode="file", exists=True):
    if exists:
        (tmp_path / "cookies.txt").write_text(SECRET)
    return Ctx(settings={"cookies_mode": mode}, engines=None, data=tmp_path)


def test_copy_is_private_identical_and_separate_from_the_master(tmp_path):
    ctx = make_ctx(tmp_path)
    cctx, ck = ytdlp.with_copy(ctx)
    assert ck and ck != tmp_path / "cookies.txt" and ck.read_text() == SECRET
    assert cctx.cookies_file == ck and stat.S_IMODE(os.stat(ck).st_mode) == 0o600
    ck.write_text("přepsáno yt-dlp")                               # yt-dlp svou kopii po běhu přepisuje
    assert (tmp_path / "cookies.txt").read_text() == SECRET
    ytdlp._drop(ck)
    assert not ck.exists() and (tmp_path / "cookies.txt").read_text() == SECRET


def test_no_copy_without_cookie_file_or_in_other_modes(tmp_path):
    assert ytdlp.with_copy(make_ctx(tmp_path, exists=False))[1] is None
    assert ytdlp.with_copy(make_ctx(tmp_path, mode="none"))[1] is None
    cctx, ck = ytdlp.with_copy(make_ctx(tmp_path))
    assert ytdlp.with_copy(cctx)[1] is None                         # kopie se nekopíruje znovu
    ytdlp._drop(ck)


def test_copy_is_removed_after_failed_run(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.engines = type("E", (), {"get": lambda self, n: type("B", (), {"bin_path": lambda s: "/nonexistent/yt-dlp"})()})()
    try:
        asyncio.run(ytdlp.full_info("https://example.com/v", ctx, timeout=5))
    except Exception:  # noqa: BLE001
        pass
    assert not list((tmp_path / "ck").glob("ck-*.txt"))


def test_hint_for_age_check_with_cookies(tmp_path):
    msg = "[youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users. Use --cookies-from-browser or --cookies for the authentication."
    out = ytdlp.cookie_hint(msg, make_ctx(tmp_path))
    assert "anonymního okna" in out and "--cookies-from-browser" not in out
    assert ytdlp.cookie_hint(msg, make_ctx(tmp_path, mode="none", exists=False)) == msg        # bez cookies hlášení zůstává
    other = "[example] x: Sign in to confirm your age"
    assert ytdlp.cookie_hint(other, make_ctx(tmp_path)) == other
