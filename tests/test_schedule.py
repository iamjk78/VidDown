"""Časový rozvrh: pravidla s více okny, řízení fronty, odběrů a katalogu, dočasná výjimka, převod starého nastavení."""
import asyncio
import json
import random
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_catalog import e, fake, playlist, rt as _rt_unused  # noqa: F401
from tests.test_runner import fake_download, probe_video, rt, run_until  # noqa: F401
from tests.test_subscriptions import State
from viddown import catalog, schedule, util
from viddown import runner as runner_mod
from viddown.config import Settings
from viddown.db import DB
from viddown.server import create_app

# 16. 11. 2026 je pondělí
MON, TUE, WED, THU, FRI, SAT, SUN = (datetime(2026, 11, 16 + i).date() for i in range(7))


def ts(day, h=0, m=0):
    return datetime(day.year, day.month, day.day, h, m).timestamp()


def cfg(rules=None, scope=("queue",), enabled=True, **kw):
    return {"schedule_enabled": enabled, "schedule_rules": rules or [], "schedule_scope": list(scope), **kw}


EXAMPLE = [{"days": [1, 3], "windows": [["02:00", "05:00"], ["19:00", "21:00"]]}]      # úterý a čtvrtek 2–5 a 19–21


# ------------------------------------------------------------ pravidla
def test_normalize_rules_canonical_form():
    r = schedule.normalize_rules([{"days": [3, 1, 1], "windows": [["19:00", "21:00"], ["2:00", "05:00"]]}])
    assert r == [{"days": [1, 3], "windows": [["02:00", "05:00"], ["19:00", "21:00"]]}]
    assert schedule.normalize_rules(None) == [] and schedule.normalize_rules("") == [] and schedule.normalize_rules([]) == []


@pytest.mark.parametrize("bad", [
    "text", {"days": [1]}, [1], [{"days": [], "windows": [["01:00", "02:00"]]}], [{"days": [7], "windows": [["01:00", "02:00"]]}],
    [{"days": [-1], "windows": [["01:00", "02:00"]]}], [{"days": [True], "windows": [["01:00", "02:00"]]}], [{"days": "1", "windows": [["01:00", "02:00"]]}],
    [{"days": [1], "windows": []}], [{"days": [1]}], [{"days": [1], "windows": [["01:00"]]}], [{"days": [1], "windows": ["01:00-02:00"]}],
    [{"days": [1], "windows": [["24:00", "02:00"]]}], [{"days": [1], "windows": [["01:60", "02:00"]]}], [{"days": [1], "windows": [["7", "02:00"]]}],
    [{"days": [1], "windows": [[1, 2]]}], [{"days": [1], "windows": [["01:00", "02:00"]] * (schedule.MAX_WINDOWS + 1)}],
    [{"days": [1], "windows": [["01:00", "02:00"]]}] * (schedule.MAX_RULES + 1),
])
def test_normalize_rules_rejects_invalid_input(bad):
    with pytest.raises(ValueError):
        schedule.normalize_rules(bad)
    assert schedule.normalize_rules_safe(bad) == []


# ------------------------------------------------------------ okna
def test_windows_of_the_example_from_the_request():
    s = cfg(EXAMPLE)
    for day, hour, expected in ((TUE, 3, True), (TUE, 20, True), (TUE, 12, False), (TUE, 1, False), (THU, 2, True), (THU, 4, True),
                                (WED, 3, False), (WED, 20, False), (MON, 20, False), (SUN, 3, False)):
        assert schedule.state(s, ts(day, hour, 30))["open"] is expected, (day, hour)
    assert schedule.state(s, ts(TUE, 2, 0))["open"] and not schedule.state(s, ts(TUE, 5, 0))["open"]        # začátek platí, konec už ne
    assert schedule.state(s, ts(TUE, 4, 59))["open"] and schedule.state(s, ts(TUE, 18, 59))["open"] is False
    assert schedule.state(s, ts(TUE, 3))["closes"] == ts(TUE, 5)
    assert schedule.state(s, ts(TUE, 5))["next_open"] == ts(TUE, 19)
    assert schedule.state(s, ts(TUE, 21))["next_open"] == ts(THU, 2)
    assert schedule.state(s, ts(THU, 21))["next_open"] == ts(datetime(2026, 11, 24).date(), 2)              # příští úterý
    assert schedule.state(s, ts(SUN, 12))["next_open"] == ts(datetime(2026, 11, 24).date(), 2)


def test_window_over_midnight_counts_by_the_day_it_starts():
    s = cfg([{"days": [0], "windows": [["22:00", "06:00"]]}])                    # pondělí 22:00 až úterý 6:00
    assert schedule.state(s, ts(MON, 23))["open"] and schedule.state(s, ts(TUE, 5, 59))["open"]
    assert not schedule.state(s, ts(TUE, 6))["open"] and not schedule.state(s, ts(MON, 5))["open"] and not schedule.state(s, ts(TUE, 23))["open"]
    assert schedule.state(s, ts(MON, 23))["closes"] == ts(TUE, 6)
    assert schedule.state(s, ts(TUE, 12))["next_open"] == ts(datetime(2026, 11, 23).date(), 22)


def test_same_start_and_end_means_the_whole_day():
    s = cfg([{"days": [2], "windows": [["00:00", "00:00"]]}])
    assert schedule.state(s, ts(WED, 0, 0))["open"] and schedule.state(s, ts(WED, 23, 59))["open"]
    assert not schedule.state(s, ts(TUE, 23, 59))["open"] and not schedule.state(s, ts(THU, 0, 0))["open"]
    s2 = cfg([{"days": [2], "windows": [["10:00", "10:00"]]}])                   # i s jiným časem je to celý den (jako dřív)
    assert schedule.state(s2, ts(WED, 3))["open"]


def test_overlapping_and_adjacent_windows_merge():
    s = cfg([{"days": [0], "windows": [["08:00", "12:00"], ["11:00", "15:00"], ["15:00", "16:00"]]}, {"days": [0], "windows": [["16:00", "17:00"]]}])
    st = schedule.state(s, ts(MON, 9))
    assert st["open"] and st["closes"] == ts(MON, 17)
    assert schedule.state(s, ts(MON, 17))["open"] is False


def test_several_rules_add_up():
    s = cfg([{"days": [0, 1, 2, 3, 4], "windows": [["19:00", "23:00"]]}, {"days": [5, 6], "windows": [["08:00", "23:00"]]}])
    assert schedule.state(s, ts(MON, 20))["open"] and not schedule.state(s, ts(MON, 10))["open"]
    assert schedule.state(s, ts(SAT, 10))["open"] and schedule.state(s, ts(SUN, 22))["open"]


def test_no_rules_means_never_open():
    assert schedule.state(cfg([], schedule_start=None), ts(MON, 3)) == {"open": False, "closes": None, "next_open": None}
    assert schedule.allowed(cfg([], schedule_start=None), "queue", ts(MON, 3)) is False


def old_in_schedule(settings, now):
    """Dřívější implementace (jedno okno s dny) jako reference."""
    if not settings.get("schedule_enabled"):
        return True
    t = time.localtime(now)
    days = settings.get("schedule_days") or []
    sh, sm = map(int, settings["schedule_start"].split(":"))
    eh, em = map(int, settings["schedule_end"].split(":"))
    cur = t.tm_hour * 60 + t.tm_min
    start, end = sh * 60 + sm, eh * 60 + em
    if start == end:
        return t.tm_wday in days
    if start < end:
        return t.tm_wday in days and start <= cur < end
    if cur >= start:
        return t.tm_wday in days
    return ((t.tm_wday - 1) % 7) in days and cur < end


def test_legacy_single_window_behaves_exactly_as_before():
    rnd = random.Random(7)
    base = datetime(2026, 11, 14).timestamp()
    for _ in range(60):
        s = {"schedule_enabled": True, "schedule_rules": [], "schedule_scope": ["queue"],
             "schedule_start": f"{rnd.randint(0, 23):02d}:{rnd.choice([0, 15, 30, 45]):02d}", "schedule_end": f"{rnd.randint(0, 23):02d}:{rnd.choice([0, 15, 30, 45]):02d}",
             "schedule_days": sorted(rnd.sample(range(7), rnd.randint(0, 7)))}
        for _ in range(60):
            now = base + rnd.randint(0, 9 * 86400)
            assert schedule.allowed(s, "queue", now) == old_in_schedule(s, now) == util.in_schedule(s, now), (s, time.ctime(now))


def test_new_rules_take_precedence_over_the_old_window():
    s = cfg(EXAMPLE, schedule_start="00:00", schedule_end="23:59", schedule_days=[0, 1, 2, 3, 4, 5, 6])
    assert schedule.is_legacy(s) is False and schedule.state(s, ts(MON, 12))["open"] is False
    assert schedule.is_legacy(cfg([], schedule_start="08:00", schedule_end="09:00", schedule_days=[1])) is True


# ------------------------------------------------------------ rozsah a výjimka
def test_allowed_depends_on_enabled_scope_and_override(rt):
    closed = ts(MON, 12)
    s = cfg(EXAMPLE, scope=("queue", "catalog"))
    assert schedule.allowed(s, "queue", closed) is False and schedule.allowed(s, "catalog", closed) is False
    assert schedule.allowed(s, "subscriptions", closed) is True                              # mimo rozsah rozvrhu
    assert schedule.allowed(dict(s, schedule_enabled=False), "queue", closed) is True
    assert schedule.allowed({"schedule_enabled": True, "schedule_rules": EXAMPLE}, "queue", closed) is False   # výchozí rozsah: fronta
    assert schedule.allowed({"schedule_enabled": True, "schedule_rules": EXAMPLE}, "catalog", closed) is True
    assert schedule.allowed(s, "queue", ts(TUE, 3)) is True
    until = schedule.set_override(rt.db, 3, now=closed)
    assert until == closed + 3 * 3600
    assert schedule.allowed(s, "queue", closed + 60, db=rt.db) is True and schedule.allowed(s, "queue", closed + 60) is False
    assert schedule.allowed(s, "queue", closed + 3 * 3600 + 1, db=rt.db) is False           # výjimka vypršela
    assert schedule.override_until(rt.db, closed + 3 * 3600 + 1) is None
    schedule.clear_override(rt.db)
    assert schedule.allowed(s, "queue", closed + 60, db=rt.db) is False
    for bad in (0, 2, 12, True):
        with pytest.raises(ValueError):
            schedule.set_override(rt.db, bad)


def test_daylight_saving_changes_are_handled(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Prague")
    time.tzset()
    try:
        s = cfg([{"days": [6], "windows": [["02:00", "05:00"]]}])                    # neděle 2:00–5:00
        for d in (datetime(2026, 3, 29).date(), datetime(2026, 10, 25).date()):       # přechod na letní a na zimní čas
            assert schedule.state(s, ts(d, 4))["open"], d
            assert not schedule.state(s, ts(d, 5, 30))["open"], d
            assert not schedule.state(s, ts(d, 1))["open"], d
            nxt = schedule.state(s, ts(d, 12))["next_open"]
            assert datetime.fromtimestamp(nxt).weekday() == 6 and datetime.fromtimestamp(nxt).hour == 2
    finally:
        monkeypatch.undo()
        time.tzset()


def test_describe_for_the_gui(rt):
    s = cfg(EXAMPLE, scope=("queue", "subscriptions"), schedule_finish_running=True)
    d = schedule.describe(s, rt.db, ts(TUE, 3))
    assert d["enabled"] and d["open"] and d["closes"] == ts(TUE, 5) and d["scope"] == ["queue", "subscriptions"] and d["finish_running"]
    assert d["allowed"] == {"queue": True, "subscriptions": True, "catalog": True} and d["legacy"] is False and d["override_until"] is None
    d = schedule.describe(s, rt.db, ts(MON, 12))
    assert not d["open"] and d["next_open"] == ts(TUE, 2) and d["allowed"] == {"queue": False, "subscriptions": False, "catalog": True}


# ------------------------------------------------------------ nastavení
def test_settings_store_validate_and_read_rules(data):
    s = Settings()
    out = s.update({"schedule_rules": [{"days": [3, 1], "windows": [["19:00", "21:00"], ["2:00", "5:00"]]}], "schedule_scope": ["queue", "queue", "catalog"],
                    "schedule_finish_running": True})
    assert out["schedule_rules"] == [{"days": [1, 3], "windows": [["02:00", "05:00"], ["19:00", "21:00"]]}]      # zůstávají slovníky, ne řetězce
    assert out["schedule_scope"] == ["queue", "catalog"] and out["schedule_finish_running"] is True
    assert Settings().all()["schedule_rules"] == out["schedule_rules"]
    for bad in ({"schedule_rules": [{"days": [9], "windows": [["1:00", "2:00"]]}]}, {"schedule_scope": []}, {"schedule_scope": ["queue", "nic"]},
                {"schedule_rules": "text"}):
        with pytest.raises(ValueError):
            s.update(bad)
    assert s.get("schedule_scope") == ["queue", "catalog"]                                                     # po chybě se nic nezměnilo
    exported = s.export()
    s2 = Settings(data / "jiny.json")
    s2.update({k: exported[k] for k in ("schedule_rules", "schedule_scope")})
    assert s2.get("schedule_rules") == exported["schedule_rules"]


def test_corrupted_rules_in_the_file_are_ignored(data):
    (data / "settings.json").write_text(json.dumps({"schedule_rules": [{"days": "x"}], "schedule_enabled": True, "schedule_start": "08:00",
                                                   "schedule_end": "09:00", "schedule_days": [1]}), "utf-8")
    s = Settings().all()
    assert s["schedule_rules"] == [] and schedule.is_legacy(s)


# ------------------------------------------------------------ fronta stahování
def closed_rules():
    wd = datetime.now().weekday()
    return [{"days": [(wd + 3) % 7], "windows": [["00:00", "23:59"]]}]


def open_rules():
    return [{"days": [datetime.now().weekday()], "windows": [["00:00", "00:00"]]}]


def test_queue_waits_outside_the_window_and_starts_inside_it(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {}))
    rt.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules()})
    j, _ = rt.add("https://x/v")
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "done", timeout=2))
    assert rt.db.get(j)["status"] == "queued"
    rt.settings.update({"schedule_rules": open_rules()})
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "done"))
    assert rt.db.get(j)["status"] == "done"


def test_override_lets_the_queue_run_outside_the_window(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {}))
    rt.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules()})
    schedule.set_override(rt.db, 1)
    j, _ = rt.add("https://x/v")
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "done"))
    assert rt.db.get(j)["status"] == "done"


@pytest.mark.parametrize("finish,expected", [(False, "queued"), (True, "done")])
def test_end_of_window_interrupts_or_lets_a_running_download_finish(rt, monkeypatch, finish, expected):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {"sleep": 1.2}))
    rt.settings.update({"schedule_enabled": True, "schedule_rules": open_rules(), "schedule_finish_running": finish})
    j, _ = rt.add("https://x/v")
    flipped = {"t": None}

    def cond():
        st = rt.db.get(j)["status"]
        if st == "running" and flipped["t"] is None:
            rt.settings.update({"schedule_rules": closed_rules()})                  # okno skončilo, když stahování běží
            flipped["t"] = time.time()
        return flipped["t"] is not None and time.time() - flipped["t"] > 2.6
    asyncio.run(run_until(rt, cond, timeout=8))
    assert rt.db.get(j)["status"] == expected


def test_queue_previews_wait_for_the_window_too(rt, monkeypatch):
    called = []

    async def full_info(url, ctx, timeout=90):
        called.append(url)
        return {"title": "T"}
    monkeypatch.setattr(runner_mod.ytdlp, "full_info", full_info)
    rt.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules(), "queue_previews": True})
    rt.db.add("https://x/q", status="queued", kind="video")
    asyncio.run(run_until(rt, lambda: bool(called), timeout=1.5))
    assert called == []
    rt.settings.update({"schedule_rules": open_rules()})
    asyncio.run(run_until(rt, lambda: bool(called), timeout=4))
    assert called


# ------------------------------------------------------------ odběry
@pytest.mark.parametrize("scope,expect_call", [(["queue"], True), (["queue", "subscriptions"], False)])
def test_subscription_checks_obey_the_schedule_only_when_in_scope(rt, monkeypatch, scope, expect_call):
    calls = []
    monkeypatch.setattr(runner_mod.subscriptions, "due", lambda db, hours, now: calls.append(1))
    rt.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules(), "schedule_scope": scope})
    asyncio.run(run_until(rt, lambda: bool(calls), timeout=1.5))
    assert bool(calls) is expect_call
    rt.settings.update({"schedule_rules": open_rules()})
    asyncio.run(run_until(rt, lambda: bool(calls), timeout=3))
    assert calls


def test_manual_subscription_check_ignores_the_schedule(rt, monkeypatch):
    ran = []

    async def check(r, sid):
        ran.append(sid)
        return {}
    monkeypatch.setattr(runner_mod.subscriptions, "check", check)
    rt.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules(), "schedule_scope": ["queue", "subscriptions"]})
    sid = rt.db.sub_add("https://x/c", "/tmp/x")

    async def go():
        assert rt.check_subscription_now(sid) is True
        await asyncio.sleep(0.2)
    asyncio.run(go())
    assert ran == [sid]                                                                      # ruční kontrola běží i mimo okno


# ------------------------------------------------------------ katalog
class CatSt:
    def __init__(self, data):
        self.data = data
        self.settings = Settings()
        self.settings.update({"catalog_gap": 0})
        self.db = DB(data / "viddown.db")
        self.runner = SimpleNamespace(ctx=lambda: SimpleNamespace(settings=self.settings.all()))


def test_catalog_lists_only_manual_sources_outside_the_window(data, fake):
    st = CatSt(data)
    fake["https://x.example/ruc"] = playlist([e("a")], title="Ručně")
    fake["https://x.example/auto"] = playlist([e("b")], title="Automaticky")
    catalog.add_sources(st.db, ["https://x.example/ruc", "https://x.example/auto"])
    with st.db.conn() as c:
        c.execute("update catalog_sources set manual=0 where url='https://x.example/auto'")      # zařazeno automatickým obnovením
    st.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules(), "schedule_scope": ["queue", "catalog"]})

    async def go(seconds, cond):
        stop = asyncio.Event()
        t = asyncio.create_task(catalog.task(st, stop))
        end = time.monotonic() + seconds
        while time.monotonic() < end and not cond():
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(t, 5)
    status = lambda: {r["title"] or r["url"]: r["status"] for r in st.db.query("select url, title, status from catalog_sources")}  # noqa: E731
    asyncio.run(go(1.5, lambda: False))
    assert status() == {"Ručně": "done", "https://x.example/auto": "queued"}                   # ručně zařazený se zjistil hned, druhý čeká na okno
    st.settings.update({"schedule_rules": open_rules()})
    asyncio.run(go(8, lambda: status().get("Automaticky") == "done"))
    assert status() == {"Ručně": "done", "Automaticky": "done"}


def test_catalog_details_and_thumbnails_wait_for_the_window(data, monkeypatch):
    from viddown import catalogdetails as cd
    st = CatSt(data)
    w = cd.DetailWorker(st)
    assert w.allowed_now() is True
    st.settings.update({"schedule_enabled": True, "schedule_rules": closed_rules(), "schedule_scope": ["queue", "catalog"]})
    assert w.allowed_now() is False
    st.settings.update({"schedule_scope": ["queue"]})                                        # katalog mimo rozsah rozvrhu
    assert w.allowed_now() is True
    st.settings.update({"schedule_scope": ["catalog"]})
    schedule.set_override(st.db, 1)
    assert w.allowed_now() is True
    schedule.clear_override(st.db)
    st.db.kv_set("catalog_paused", True)
    st.settings.update({"schedule_rules": open_rules()})
    assert w.allowed_now() is False                                                         # ruční pozastavení platí i v okně


def test_manual_catalog_actions_are_flagged_manual(data):
    st = CatSt(data)
    catalog.add_sources(st.db, ["https://x.example/1"])
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    with st.db.conn() as c:
        c.execute("update catalog_sources set manual=0, status='done'")
    assert catalog.rescan_source(st.db, sid, "new") is True
    assert st.db.query("select manual from catalog_sources")[0]["manual"] == 1
    assert catalog.claim_source(st.db, manual_only=True)["id"] == sid


# ------------------------------------------------------------ API
@pytest.fixture
def client(rt, data, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    s = State(rt, data)
    s.bot, s.engines_cache = None, (lambda: [])
    return TestClient(create_app(s)), rt


def test_api_schedule_state_override_and_settings(client):
    c, rt = client
    r = c.put("/api/settings", json={"schedule_enabled": True, "schedule_rules": closed_rules(), "schedule_scope": ["queue", "catalog"]})
    assert r.status_code == 200
    sch = c.get("/api/schedule").json()
    assert sch["enabled"] and sch["open"] is False and sch["next_open"] and sch["scope"] == ["queue", "catalog"] and sch["legacy"] is False
    assert sch["allowed"]["queue"] is False and sch["override_until"] is None
    st = c.get("/api/state").json()
    assert st["in_window"] is False and st["schedule"]["enabled"] is True and "start" in st["schedule"] and st["schedule"]["next_open"]
    ov = c.post("/api/schedule/override", json={"hours": 3}).json()
    assert ov["override_until"] > time.time() + 3 * 3600 - 5 and ov["allowed"]["queue"] is True
    assert c.get("/api/state").json()["in_window"] is True
    assert c.delete("/api/schedule/override").json()["override_until"] is None
    assert c.get("/api/state").json()["in_window"] is False
    for bad in ({"hours": 2}, {"hours": True}, {"hours": "3"}, {}, [3]):
        assert c.post("/api/schedule/override", json=bad).status_code == 400
    assert c.put("/api/settings", json={"schedule_rules": [{"days": [8], "windows": [["1:00", "2:00"]]}]}).status_code == 400
    assert c.put("/api/settings", json={"schedule_scope": []}).status_code == 400
    assert c.get("/api/settings").json()["values"]["schedule_rules"] == closed_rules()


def test_api_legacy_settings_still_work_in_state(client):
    c, rt = client
    c.put("/api/settings", json={"schedule_enabled": True, "schedule_start": "00:00", "schedule_end": "23:59", "schedule_days": [0, 1, 2, 3, 4, 5, 6]})
    assert c.get("/api/schedule").json()["legacy"] is True
    st = c.get("/api/state").json()
    assert st["schedule"]["legacy"] is True and st["schedule"]["rules"][0]["windows"] == [["00:00", "23:59"]]
