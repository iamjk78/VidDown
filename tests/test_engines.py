"""Logika aktualizace s testem a návratem – na falešném enginu bez sítě."""
import sys

import pytest

from viddown.config import Settings
from viddown.db import DB
from viddown.engines import EXE, Engine, EngineManager, Release


class FakeEngine(Engine):
    name = "fake"
    binaries = ("fake",)
    latest = "2.0"
    broken: set = set()
    calls: list = []

    def latest_release(self):
        return Release(self.latest, {})

    def install_release(self, rel, target):
        (target / ("fake" + EXE)).write_text(rel.version)

    def test(self, version):
        v = version or self.current()
        FakeEngine.calls.append(v)
        return (v not in self.broken), ("rozbité" if v in self.broken else "OK")

    def system_version(self):
        return None


@pytest.fixture()
def mgr(data):
    m = EngineManager(data, Settings(), DB(data / "t.db"), notify=lambda key, **kw: notes.append(key))
    m.engines["fake"] = FakeEngine(m.root, m)
    FakeEngine.broken, FakeEngine.calls = set(), []
    notes.clear()
    return m


notes: list = []


def install(m, v):
    e = m.get("fake")
    e.latest = v
    return m.update("fake")


def test_update_switches_when_new_passes(mgr):
    assert install(mgr, "1.0")["status"] == "updated"
    r = install(mgr, "2.0")
    assert r["status"] == "updated" and r["previous"] == "1.0"
    assert mgr.get("fake").current() == "2.0"
    assert install(mgr, "2.0")["status"] == "up-to-date"


def test_new_fails_old_passes_rolls_back(mgr):
    install(mgr, "1.0")
    FakeEngine.broken = {"2.0"}
    r = install(mgr, "2.0")
    assert r["status"] == "rolled-back" and r["version"] == "1.0"
    assert mgr.get("fake").current() == "1.0"
    assert "2.0" not in [v["version"] for v in mgr.get("fake").versions()]  # neúspěšná verze smazána
    assert notes == ["engine_fail"]


def test_both_fail_is_inconclusive(mgr):
    install(mgr, "1.0")
    FakeEngine.broken = {"1.0", "2.0"}
    r = install(mgr, "2.0")
    assert r["status"] == "inconclusive"
    assert mgr.get("fake").current() == "1.0"
    assert notes == ["engine_both_fail"]


def test_prune_and_manual_rollback(mgr):
    mgr.settings.update({"keep_engine_versions": 2})
    for v in ("1.0", "2.0", "3.0"):
        install(mgr, v)
    vs = [v["version"] for v in mgr.get("fake").versions()]
    assert vs == ["3.0", "2.0"]
    assert mgr.rollback("fake") == "2.0"
    assert mgr.get("fake").current() == "2.0"
    with pytest.raises(ValueError):
        mgr.rollback("fake", "9.9")
