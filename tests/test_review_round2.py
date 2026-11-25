"""Nálezy z druhého kola review: přechodná chyba čtení nastavení, pořadí kroků „Doplnit animace“, obnova a záloha."""
import json
from pathlib import Path

import pytest

from viddown import catalogdetails as cd
from viddown.config import Settings
from tests.test_catalog_anim import st, fake, scan_items  # noqa: F401  (fixtury a pomocná funkce)


def test_transient_read_error_never_overwrites_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"download_dir": "/mnt/videa", "min_free_gb": 7}), encoding="utf-8")
    s = Settings(path)
    assert s.get("min_free_gb") == 7                   # načteno a uloženo do cache

    real_read = Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        if self == path:
            calls["n"] += 1
            raise OSError(5, "přechodná chyba (EIO)")
        return real_read(self, *a, **k)
    # změna mtime, aby se soubor znovu četl, a výpadek čtení
    path.write_text(json.dumps({"download_dir": "/mnt/videa", "min_free_gb": 7, "x": 1}), encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", flaky)
    with pytest.raises(ValueError):
        s.update({"min_free_gb": 9})                   # zápis se odmítne, ne přepíše soubor výchozími hodnotami
    monkeypatch.setattr(Path, "read_text", real_read)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["download_dir"] == "/mnt/videa"     # ostatní nastavení zůstala
    assert not (tmp_path / "settings.json.corrupt").exists()   # přechodná chyba není poškozený soubor


def test_refill_anims_does_not_reschedule_page_scan_rows_as_details(st, fake):
    scan_items(st, fake, ["a"])
    with st.db.conn() as c:                            # položka, na které chybí adresa animace: čeká se na sken stránky
        c.execute("update catalog_items set anim_url='', anim_file=null, detail_state='done'")
    res = cd.refill_anims(st.db)
    assert res["pages"] == 1 and res["details"] == 0   # jen sken stránky, žádné nové zjišťování podrobností
    row = st.db.query("select detail_state, anim_url from catalog_items")[0]
    assert row["detail_state"] == "done" and row["anim_url"] is None
