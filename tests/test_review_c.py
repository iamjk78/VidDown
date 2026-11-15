"""Dávka C po hloubkové revizi (GUI a jeho API): chybějící miniatura se nehledá při každém překreslení, hromadný výběr podle filtru se nerozroste,
statické kontroly app.js (bezpečné odkazy, vrstvení oken, přístupnost)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_catalog import e, fake, playlist, rt as _unused, scan  # noqa: F401
from tests.test_runner import rt  # noqa: F401
from tests.test_catalog_download import St, load
from viddown import catalog, thumbs
from viddown.server import create_app

APP_JS = Path(__file__).resolve().parent.parent / "src" / "viddown" / "web" / "app.js"


def test_missing_thumbnail_is_not_fetched_again_on_every_request(rt, data, monkeypatch):
    from tests.test_subscriptions import State
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    s = State(rt, data)
    s.bot, s.engines_cache = None, (lambda: [])
    c = TestClient(create_app(s))
    jid, _ = rt.add("https://x.example/v")
    rt.db.update(jid, thumb_url="https://x.example/t.jpg")
    calls = []
    monkeypatch.setattr(thumbs, "ensure_cached", lambda d, j: calls.append(j["id"]) or None)
    for _ in range(3):
        r = c.get(f"/api/thumb/{jid}")
        assert r.status_code == 404 and "max-age" in r.headers.get("cache-control", "")
    assert calls == [jid]                                                   # zdroj se oslovil jen jednou, ostatní dotazy vyřídila záporná cache


def test_filter_selection_that_grew_after_confirmation_is_refused(rt, data, fake, monkeypatch):
    from tests.test_subscriptions import State
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    s = State(rt, data)
    s.bot, s.engines_cache = None, (lambda: [])
    c = TestClient(create_app(s))
    load(St(rt), fake, [e(f"v{i}", f"Video {i}") for i in range(4)])
    body = {"action": "download", "filter": {"q": "video"}}
    r = c.post("/api/catalog/items/action", json={**body, "expect": 2})        # uživatel potvrdil 2, filtr teď vrací 4
    assert r.status_code == 409 and rt.db.query("select count(*) n from jobs")[0]["n"] == 0
    r = c.post("/api/catalog/items/action", json={**body, "expect": 4})
    assert r.status_code == 200 and r.json()["queued"] == 4


# ------------------------------------------------------------ statické kontroly GUI
def js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_external_urls_in_links_go_through_safe_href():
    src = js()
    assert "const safeHref" in src
    hrefs = re.findall(r'href="\$\{esc\((?!safeHref)[^)]*url[^)]*\)\}"', src)
    assert hrefs == []                                                       # žádný href z cizí adresy bez ochrany před `javascript:`


def test_modals_stack_and_trap_focus():
    src = js()
    body = src[src.index("function modal("):src.index("async function openDirPicker")]
    assert "appendChild(wrap)" in body and "root.innerHTML" not in body      # druhé okno nesmí zničit první
    assert "e.key === 'Tab'" in body and "prev.focus" in body


def test_missing_queue_thumbnails_are_remembered_and_selection_skips_running():
    src = js()
    assert "thumbBad" in src and 'onerror="this.remove()"' not in src[src.index("function thumbHtml"):src.index("function thumbHtml") + 700]
    assert "j.status === 'running') continue" in src                          # „Vybrat zobrazené“ nevybírá běžící úlohy


def test_page_subscription_pattern_belongs_to_the_previewed_url():
    src = js()
    assert "det.for = url" in src and "det.for === url" in src


def test_card_download_and_remove_keep_the_other_selected_videos():
    src = js()
    assert "catDownload({ ids: [+b.dataset.id] }, again, true)" in src and "catRemove({ ids: [+b.dataset.id] }, 1, true)" in src
    assert "if (keepSel) (spec.ids || []).forEach(id => CAT.sel.delete(id)); else catClearSel();" in src
