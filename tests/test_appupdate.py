"""Aktualizace kódu aplikace zevnitř (etapa 1): archiv, instalace, samotest, přepnutí, zkušební doba, návrat, databáze."""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import zipfile

import pytest

from viddown import appupdate as au
from viddown import bootstrap


@pytest.fixture
def store(tmp_path, monkeypatch):
    for k in ("VIDDOWN_APP_ACTIVE", "VIDDOWN_BASE_VERSION", "VIDDOWN_IMAGE_API", "VIDDOWN_BASE_SCHEMA"):
        monkeypatch.delenv(k, raising=False)
    return au.AppStore(tmp_path / "data")


def make_zip(tmp_path, version="9.9.9", **kw):
    return au.pack(tmp_path / f"v{version}.zip", version=version, **kw)


def install(store, tmp_path, version="9.9.9", **kw):
    man = make_zip(tmp_path, version, **kw)
    return store.install_zip(tmp_path / f"v{version}.zip", man["sha256"])


def test_vkey_orders_versions():
    assert au.vkey("0.10.0") > au.vkey("0.9.9") > au.vkey("0.1.0")
    assert au.vkey(None) == (0,)


def test_pack_and_install(store, tmp_path):
    man = make_zip(tmp_path)
    assert man["version"] == "9.9.9" and len(man["sha256"]) == 64 and man["schema_version"] >= 7
    assert install(store, tmp_path) == "9.9.9"
    assert store.installed() == ["9.9.9"]
    assert '__version__ = "9.9.9"' in (store.path("9.9.9") / "viddown" / "__init__.py").read_text()
    assert (store.path("9.9.9") / "viddown" / "web" / "app.js").exists()      # i soubory GUI
    assert store.manifest("9.9.9")["schema_version"] == man["schema_version"]


def test_install_rejects_bad_checksum_and_unsafe_archives(store, tmp_path):
    man = make_zip(tmp_path)
    with pytest.raises(au.UpdateError, match="kontrolní součet"):
        store.install_zip(tmp_path / "v9.9.9.zip", "0" * 64)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"version": "9.9.9", "requires_image_api": 1}))
        z.writestr("../utek.txt", "x")
    with pytest.raises(au.UpdateError, match="nebezpečná cesta"):
        store.install_zip(evil)
    nomani = tmp_path / "nomani.zip"
    with zipfile.ZipFile(nomani, "w") as z:
        z.writestr("viddown/__init__.py", "")
    with pytest.raises(au.UpdateError, match="manifest"):
        store.install_zip(nomani)
    mism = tmp_path / "mism.zip"
    with zipfile.ZipFile(mism, "w") as z:
        z.writestr("manifest.json", json.dumps({"version": "9.9.8", "requires_image_api": 1}))
        z.writestr("viddown/__init__.py", '__version__ = "1.0.0"\n')
    with pytest.raises(au.UpdateError, match="neodpovídá"):
        store.install_zip(mism)
    assert store.installed() == [] and man


def test_install_rejects_release_needing_newer_image(store, tmp_path):
    make_zip(tmp_path, "9.9.9", requires_image_api=au.image_api() + 1)
    with pytest.raises(au.UpdateError, match="vyžaduje novější obraz"):
        store.install_zip(tmp_path / "v9.9.9.zip")


def test_selftest_passes_on_real_code(store, tmp_path):
    install(store, tmp_path)
    ok, rep = store.selftest("9.9.9", skip_engines=True)
    assert ok, rep
    names = {c["name"] for c in rep["checks"]}
    assert {"verze", "moduly", "databáze", "aplikace"} <= names


def test_selftest_uses_copy_of_real_db_and_leaves_it_untouched(store, tmp_path):
    from viddown.db import DB
    store.data.mkdir(parents=True)
    DB(store.data / "viddown.db").add("https://x/a")
    before = (store.data / "viddown.db").stat().st_mtime_ns
    install(store, tmp_path)
    ok, rep = store.selftest("9.9.9", skip_engines=True)
    assert ok, rep
    assert (store.data / "viddown.db").stat().st_mtime_ns == before


def test_selftest_fails_on_broken_module(store, tmp_path):
    install(store, tmp_path)
    (store.path("9.9.9") / "viddown" / "pagelist.py").write_text("def broken(:\n")
    ok, rep = store.selftest("9.9.9", skip_engines=True)
    assert not ok
    bad = [c for c in rep["checks"] if not c["ok"]]
    assert bad and "pagelist" in bad[0]["detail"]


def test_selftest_fails_on_wrong_version(store, tmp_path):
    install(store, tmp_path)
    ok, rep = store.selftest("9.9.9", skip_engines=True)
    assert ok
    # archiv se tváří jako 9.9.9, ale kód uvnitř hlásí jinou verzi
    init = store.path("9.9.9") / "viddown" / "__init__.py"
    init.write_text(init.read_text().replace("9.9.9", "9.9.8"))
    ok, rep = store.selftest("9.9.9", skip_engines=True)
    assert not ok and any(c["name"] == "verze" and not c["ok"] for c in rep["checks"])


def _db_with_schema(path, version, rows=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("create table if not exists t(x)")
    for i in range(rows):
        c.execute("insert into t values(?)", (i,))
    c.execute(f"pragma user_version={version}")
    c.commit()
    c.close()


def test_activate_sets_state_and_backs_up_db(store, tmp_path):
    _db_with_schema(store.db_path, 5, rows=3)
    install(store, tmp_path)
    store.activate("9.9.9")
    st = store.state()
    assert st["current"] == "9.9.9" and st["previous"] is None
    pr = st["probation"]
    assert pr["version"] == "9.9.9" and pr["attempts"] == 0 and pr["schema_before"] == 5
    assert os.path.exists(pr["db_backup"])
    with pytest.raises(au.UpdateError, match="už je aktivní"):
        store.activate("9.9.9")
    with pytest.raises(au.UpdateError, match="není nainstalována"):
        store.activate("9.9.10")


def test_activate_refuses_version_not_newer_than_image(store, tmp_path):
    install(store, tmp_path, "0.0.1")
    with pytest.raises(au.UpdateError, match="není novější"):
        store.activate("0.0.1")


def test_probation_rolls_back_after_two_failed_starts(store, tmp_path):
    install(store, tmp_path)
    store.activate("9.9.9")
    assert store.begin_start() == store.path("9.9.9")        # 1. start
    assert store.state()["probation"]["attempts"] == 1
    assert store.begin_start() == store.path("9.9.9")        # 2. start
    assert store.begin_start() is None                       # 3. start už nedojde: návrat na obraz
    st = store.state()
    assert st["current"] is None and st["probation"] is None
    assert "9.9.9" in st["skipped"] and "nenaběhla zdravě" in st["skipped"]["9.9.9"]["reason"]
    assert st["events"][-1]["kind"] == "rolled_back"


def test_healthy_ends_probation_and_prevents_rollback(store, tmp_path):
    install(store, tmp_path)
    store.activate("9.9.9")
    store.begin_start()
    assert store.mark_healthy("9.9.9")
    for _ in range(5):
        assert store.begin_start() == store.path("9.9.9")
    assert store.state()["current"] == "9.9.9" and not store.state()["skipped"]


def test_non_serve_commands_do_not_count_as_starts(store, tmp_path):
    install(store, tmp_path)
    store.activate("9.9.9")
    for _ in range(5):
        assert store.begin_start(count=False) == store.path("9.9.9")
    assert store.state()["probation"]["attempts"] == 0


def test_clean_stop_does_not_count(store, tmp_path):
    install(store, tmp_path)
    store.activate("9.9.9")
    store.begin_start()
    store.note_clean_stop("9.9.9")
    assert store.state()["probation"]["attempts"] == 0


def test_rollback_goes_to_previous_installed_version(store, tmp_path):
    install(store, tmp_path, "9.9.8")
    store.activate("9.9.8")
    store.mark_healthy("9.9.8")
    install(store, tmp_path, "9.9.9")
    store.activate("9.9.9")
    r = store.rollback("zkouška")
    assert r["to"] == "9.9.8" and store.state()["current"] == "9.9.8" and "9.9.9" in store.state()["skipped"]


def test_auto_rollback_restores_db_when_new_version_migrated(store, tmp_path):
    from viddown.db import MIGRATIONS
    latest = MIGRATIONS[-1][0]
    _db_with_schema(store.db_path, latest, rows=3)
    install(store, tmp_path)
    store.activate("9.9.9")
    # nová verze „zmigrovala“ databázi dál a zapsala další data
    _db_with_schema(store.db_path, latest + 1, rows=10)
    store.begin_start()
    store.begin_start()
    assert store.begin_start() is None
    c = sqlite3.connect(store.db_path)
    assert c.execute("pragma user_version").fetchone()[0] == latest
    assert c.execute("select count(*) from t").fetchone()[0] == 3
    c.close()
    failed = store.data / "viddown.db.failed-9.9.9"
    assert failed.exists()
    c = sqlite3.connect(failed)
    assert c.execute("select count(*) from t").fetchone()[0] == 13 or c.execute("select count(*) from t").fetchone()[0] >= 10
    c.close()
    assert "databáze obnovena" in store.state()["events"][-1]["msg"]


def test_manual_rollback_refuses_newer_schema_without_flag(store, tmp_path):
    from viddown.db import MIGRATIONS
    latest = MIGRATIONS[-1][0]
    _db_with_schema(store.db_path, latest, rows=1)
    install(store, tmp_path)
    store.activate("9.9.9")
    store.mark_healthy("9.9.9")                      # zkušební doba skončila, záloha zůstala
    _db_with_schema(store.db_path, latest + 1, rows=50)
    with pytest.raises(au.UpdateError, match="--restore-db"):
        store.rollback("ruční")
    assert store.state()["current"] == "9.9.9"        # nic se nezměnilo
    # po mark_healthy už není probation, a tím ani záloha → ani s příznakem nejde obnovit
    with pytest.raises(au.UpdateError, match="záloha"):
        store.rollback("ruční", restore_db=True)


def test_manual_rollback_without_schema_change_keeps_db(store, tmp_path):
    from viddown.db import MIGRATIONS
    _db_with_schema(store.db_path, MIGRATIONS[-1][0], rows=7)
    install(store, tmp_path)
    store.activate("9.9.9")
    store.mark_healthy("9.9.9")
    r = store.rollback("ruční")
    assert r["restored_db"] is False and r["to"] is None
    c = sqlite3.connect(store.db_path)
    assert c.execute("select count(*) from t").fetchone()[0] == 7
    c.close()


def test_image_catching_up_discards_installed_version(store, tmp_path, monkeypatch):
    install(store, tmp_path, "9.9.9")
    store.activate("9.9.9")
    store.mark_healthy("9.9.9")
    monkeypatch.setenv("VIDDOWN_BASE_VERSION", "9.9.9")       # po `pull` má obraz stejnou verzi
    assert store.begin_start() is None
    st = store.state()
    assert st["current"] is None and st["events"][-1]["kind"] == "superseded"


def test_missing_files_trigger_rollback(store, tmp_path):
    import shutil
    install(store, tmp_path)
    store.activate("9.9.9")
    shutil.rmtree(store.path("9.9.9"))
    assert store.begin_start() is None
    assert "9.9.9" in store.state()["skipped"]


def test_prune_keeps_current_previous_and_newest(store, tmp_path):
    for v in ("9.9.1", "9.9.2", "9.9.3", "9.9.4", "9.9.5"):
        install(store, tmp_path, v)
    store.activate("9.9.2")
    store.mark_healthy("9.9.2")
    store.activate("9.9.4")
    # activate() už samo uklidilo: zůstane aktivní, předchozí a nejnovější další
    assert set(store.installed()) == {"9.9.2", "9.9.4", "9.9.5"}
    assert store.prune(keep=3) == []


def test_skip_unskip_and_remove(store, tmp_path):
    install(store, tmp_path)
    store.skip("9.9.9", "zkouška")
    assert "9.9.9" in store.state()["skipped"]
    assert store.unskip("9.9.9") and not store.unskip("9.9.9")
    store.remove("9.9.9")
    assert store.installed() == []
    with pytest.raises(au.UpdateError):
        store.path("../x")


def test_health_task_marks_healthy_after_delay(store, tmp_path, monkeypatch):
    install(store, tmp_path)
    store.activate("9.9.9")
    monkeypatch.setenv("VIDDOWN_APP_ACTIVE", "9.9.9")

    async def go(stop_early):
        stop = asyncio.Event()
        t = asyncio.create_task(au.health_task(store.data, stop, after=0.2))
        if stop_early:
            await asyncio.sleep(0.05)
            stop.set()
        await t

    store.begin_start()
    asyncio.run(go(True))                       # řádné ukončení dřív: nezdravá, ale start se nepočítá
    assert store.state()["probation"]["attempts"] == 0
    asyncio.run(go(False))
    assert store.state()["probation"] is None


def test_bootstrap_end_to_end_runs_updated_code(store, tmp_path):
    """Spouštěč opravdu spustí aktualizovaný kód novým procesem (`viddown version` hlásí 9.9.9)."""
    install(store, tmp_path)
    store.activate("9.9.9")
    env = dict(os.environ, VIDDOWN_DATA=str(store.data))
    for k in ("VIDDOWN_APP_ACTIVE", "VIDDOWN_BASE_VERSION"):
        env.pop(k, None)
    code = "import sys; from viddown import bootstrap; sys.exit(bootstrap.main(['version']))"
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "VidDown 9.9.9" in r.stdout, (r.stdout, r.stderr)
    assert store.state()["probation"]["attempts"] == 0         # `version` se nepočítá jako start


def test_bootstrap_falls_back_to_image_when_state_is_corrupt(tmp_path):
    data = tmp_path / "d"
    (data / "app").mkdir(parents=True)
    (data / "app" / "state.json").write_text("{rozbité")
    env = dict(os.environ, VIDDOWN_DATA=str(data))
    for k in ("VIDDOWN_APP_ACTIVE", "VIDDOWN_BASE_VERSION"):
        env.pop(k, None)
    code = "import sys; from viddown import bootstrap; sys.exit(bootstrap.main(['version']))"
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    from viddown import __version__
    assert r.returncode == 0 and f"VidDown {__version__}" in r.stdout          # verze z obrazu (ne pevné číslo)


def test_migrations_are_additive():
    """Pravidlo pro vývoj: návrat na starší verzi funguje jen, když migrace nic nemažou ani nepřejmenovávají."""
    from viddown.db import MIGRATIONS
    forbidden = ("drop table", "drop column", "rename ", "delete from")
    for ver, step in MIGRATIONS:
        if isinstance(step, str) and ver > 7:
            low = step.lower()
            assert not any(w in low for w in forbidden), f"migrace {ver} není jen přidávací"


def test_cli_app_status_and_pack_install(tmp_path, monkeypatch, capsys):
    from viddown import cli
    monkeypatch.setenv("VIDDOWN_DATA", str(tmp_path / "d"))
    for k in ("VIDDOWN_APP_ACTIVE", "VIDDOWN_BASE_VERSION"):
        monkeypatch.delenv(k, raising=False)
    assert cli.main(["app", "pack", str(tmp_path / "x.zip"), "--version", "9.9.9"]) == 0
    assert cli.main(["app", "install", str(tmp_path / "x.zip")]) == 0
    assert cli.main(["app", "status"]) == 0
    out = capsys.readouterr().out
    assert "Nainstalována verze 9.9.9" in out and "Nainstalováno:     9.9.9" in out
    assert cli.main(["app", "rollback"]) == 1            # nic aktivního
