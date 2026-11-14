import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture()
def data(tmp_path, monkeypatch):
    """Izolovaná datová složka pro každý test."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("VIDDOWN_DATA", str(d))
    for k in list(os.environ):
        if k.startswith("VIDDOWN_") and k != "VIDDOWN_DATA":
            monkeypatch.delenv(k, raising=False)
    return d


@pytest.fixture(autouse=True)
def _no_min_gap(monkeypatch):
    """Zkoušky Katalogu nastavují pauzu 0, aby běžely rychle; skutečné minimum (1 s) ověřuje samostatná zkouška."""
    import viddown.catalogdetails as cd
    monkeypatch.setattr(cd, "MIN_GAP", 0.0)
    monkeypatch.setattr(cd, "THUMB_GAP", 0.0)


@pytest.fixture(autouse=True)
def _clean_viddown_env(monkeypatch):
    """Proměnné VIDDOWN_* exportované v shellu (např. VIDDOWN_ALLOW_PRIVATE_PREVIEW) se nesmí dostat do žádného testu."""
    for k in list(os.environ):
        if k.startswith("VIDDOWN_"):
            monkeypatch.delenv(k, raising=False)
