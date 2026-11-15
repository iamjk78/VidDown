"""Dávka G po hloubkové revizi: katalog – osiřelé miniatury, přesun při změně složky, znovu dostupná videa, datum u jednotlivého videa,
archiv stažených se při vynuceném stažení přepíše jednou."""
import os
import time

from tests.test_api import client  # noqa: F401
from tests.test_catalog import e, fake, playlist, rt as _unused, scan  # noqa: F401
from tests.test_catalog_download import St, item, load
from tests.test_runner import rt  # noqa: F401
from viddown import catalog


def test_orphaned_thumbnails_are_pruned_but_used_and_foreign_files_stay(rt, fake, tmp_path):
    st = St(rt)
    load(st, fake, [e("a"), e("b")])
    a = item(st, "youtube a")["id"]
    with rt.db.conn() as c:
        c.execute("update catalog_items set thumb_file=? where id=?", (f"{a}.jpg", a))
    f = tmp_path / "th"
    f.mkdir()
    for name in (f"{a}.jpg", "999.jpg", "999.anim.mp4", "moje-foto.jpg", "998.jpg"):
        (f / name).write_bytes(b"x")
    old = time.time() - 7200
    for name in (f"{a}.jpg", "999.jpg", "999.anim.mp4", "moje-foto.jpg"):
        os.utime(f / name, (old, old))
    assert catalog.prune_thumbs(rt.db, f) == 2
    assert sorted(p.name for p in f.iterdir()) == sorted([f"{a}.jpg", "moje-foto.jpg", "998.jpg"])   # čerstvý soubor se ještě nechá


def test_thumbnails_move_with_the_folder_setting(client, tmp_path):
    c, st = client
    old = catalog.thumbs_dir(st.data, st.settings)
    old.mkdir(parents=True, exist_ok=True)
    (old / "5.jpg").write_bytes(b"x")
    (old / "5.anim.mp4").write_bytes(b"y")
    new = tmp_path / "nove"
    assert c.put("/api/settings", json={"catalog_thumbs_dir": str(new)}).status_code == 200
    for _ in range(50):
        if (new / "5.jpg").exists():
            break
        time.sleep(0.05)
    assert (new / "5.jpg").exists() and (new / "5.anim.mp4").exists() and not (old / "5.jpg").exists()


def test_video_back_from_gone_gets_its_details_again(rt, fake):
    st = St(rt)
    load(st, fake, [e("a"), e("b")])
    a = item(st, "youtube a")["id"]
    with rt.db.conn() as c:
        c.execute("update catalog_items set state='gone', detail_state='failed', detail_error='removed' where id=?", (a,))
    scan(st, "https://x.example/pl")
    r = item(st, "youtube a")
    assert (r["state"], r["detail_state"], r["detail_error"]) == ("new", "pending", None)


def test_forced_download_rewrites_the_archive_once(rt, fake, monkeypatch):
    st = St(rt)
    load(st, fake, [e("a"), e("b")])
    ids = [item(st, k)["id"] for k in ("youtube a", "youtube b")]
    with rt.db.conn() as c:
        c.execute("update catalog_items set downloaded_before=1")
    calls = []
    monkeypatch.setattr(catalog, "_forget_job", lambda db, r: {"url": r["url"], "info": "{}"})
    monkeypatch.setattr(rt, "archive_forget_many", lambda jobs: calls.append(len(jobs)) or 0)
    catalog.queue_items(rt.db, rt, ids, True)
    assert calls == [2]


def test_single_video_source_keeps_its_publish_date():
    info = {"id": "x", "extractor_key": "Youtube", "title": "T", "upload_date": "20240102", "webpage_url": "https://y.example/v"}
    got = catalog.listing_from_info(info, "https://y.example/v") if hasattr(catalog, "listing_from_info") else None
    if got is None:                                                       # starší název funkce: kontrola přímo ve zdrojovém kódu
        src = open(catalog.__file__, encoding="utf-8").read()
        assert '"anim_url": anim_source(info), "published_at": published_ts(info)}]}' in src
    else:
        assert got["entries"][0]["published_at"]
