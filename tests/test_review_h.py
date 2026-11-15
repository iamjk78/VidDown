"""Dávka H po hloubkové revizi: /api/stats s nesmyslnými parametry, jedna operace s enginy najednou."""
import threading
import time

from tests.test_api import client  # noqa: F401


def test_stats_with_huge_or_invalid_ranges_stays_bounded(client):
    c, st = client
    t = time.time()
    r = c.get("/api/stats", params={"t0": -1e15, "t1": 1e15, "tz": 99999})
    assert r.status_code == 200 and len(r.json()["series"]) <= 5000 and time.time() - t < 5
    assert c.get("/api/stats", params={"t0": "nan"}).status_code in (400, 422)


def test_only_one_engine_operation_at_a_time(client, monkeypatch):
    c, st = client
    release = threading.Event()
    monkeypatch.setattr(st.engines, "update_all", lambda: release.wait(5), raising=False)
    monkeypatch.setattr(st.engines, "busy", False, raising=False)
    monkeypatch.setattr(st.engines, "engines", {"yt-dlp": None}, raising=False)
    with c:                                                              # jedna smyčka událostí pro všechny požadavky (úloha na pozadí žije dál)
        assert c.post("/api/engines/check").status_code == 200
        try:
            assert c.post("/api/engines/check").status_code == 409
            assert c.post("/api/engines/yt-dlp/update").status_code == 409
            assert c.post("/api/engines/chromium/install").status_code == 409
        finally:
            release.set()
