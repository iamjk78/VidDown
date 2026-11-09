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
