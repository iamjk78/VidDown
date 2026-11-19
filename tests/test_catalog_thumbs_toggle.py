"""Přepínač „Miniatury“ v hlavičce katalogu: jen zobrazení (jako u fronty), stahování miniatur zůstává."""
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_switch_is_a_per_browser_display_pref_not_a_server_setting():
    from viddown.config import DEFAULTS
    assert "catalog_show_thumbs" not in DEFAULTS
    js = (ROOT / "src/viddown/web/app.js").read_text()
    assert 'id="catth"' in js and "catThumbLabel()" in js
    assert "catPref('thumbs', '1', ['0', '1']) === '1'" in js
    assert "catSetPref('thumbs'" in js
    assert "CAT.showThumbs === false ? { ...item, thumb: null, anim: null }" in js


def test_server_download_code_does_not_read_the_switch():
    for name in ("src/viddown/catalogdetails.py", "src/viddown/catalog.py", "src/viddown/server.py"):
        assert "showThumbs" not in (ROOT / name).read_text()
