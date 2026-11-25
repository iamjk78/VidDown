"""Ruční „Doplnit animace“ / „Doplnit data“ spustí doplnění hned, i mimo okno časového rozvrhu, a jen do vyřízení položek."""
import datetime as _dt

from viddown import catalogdetails as cd
from tests.test_catalog_anim import st, fake, scan_items  # noqa: F401  (fixtury a pomocná funkce)


def _closed_schedule(st):
    """Rozvrh, jehož okno dnes určitě neplatí (jen jeden den v týdnu, který není dnešní)."""
    tomorrow = (_dt.date.today().weekday() + 1) % 7
    st.settings.update({"schedule_enabled": True, "schedule_scope": ["catalog"],
                        "schedule_rules": [{"days": [tomorrow], "windows": [["00:00", "00:01"]]}]})


def _set_pending(st):
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending' where state in ('new','queued')")


def test_manual_refill_bypasses_closed_window_until_work_is_done(st, fake):
    scan_items(st, fake, ["a", "b"])
    _closed_schedule(st)
    w = cd.DetailWorker(st)
    _set_pending(st)
    assert w.allowed_now() is False                  # mimo okno se nic samo nespustí
    w.request_manual()                               # ruční „Doplnit …“
    assert w.allowed_now() is True
    with st.db.conn() as c:                          # práce vyřízena
        c.execute("update catalog_items set detail_state='done'")
    assert w.allowed_now() is False                  # ruční režim se po vyřízení sám vypne
    assert w.manual is False


def test_manual_refill_does_not_override_pause(st, fake):
    scan_items(st, fake, ["a"])
    _closed_schedule(st)
    w = cd.DetailWorker(st)
    _set_pending(st)
    w.request_manual()
    st.db.kv_set("catalog_paused", True)
    assert w.allowed_now() is False                  # ruční pozastavení platí dál
    st.db.kv_set("catalog_paused", False)
    assert w.allowed_now() is True


def test_without_manual_request_closed_window_still_blocks(st, fake):
    scan_items(st, fake, ["a"])
    _closed_schedule(st)
    w = cd.DetailWorker(st)
    _set_pending(st)
    assert w.allowed_now() is False
