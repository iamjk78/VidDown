"""Vytvoření a přejmenování složek v okně výběru (`/api/fs/mkdir`, `/api/fs/rename`)."""
import pytest
from fastapi.testclient import TestClient

from viddown.server import create_app
from tests.test_api import State


@pytest.fixture()
def env(data, tmp_path):
    st = State(data)
    root = tmp_path / "videa"
    root.mkdir()
    st.settings.update({"download_dir": str(root)})
    return TestClient(create_app(st)), st, root


def test_mkdir_creates_one_level_folder(env):
    c, st, root = env
    r = c.post("/api/fs/mkdir", json={"path": str(root), "name": "Seriály"})
    assert r.status_code == 200 and r.json()["path"] == str(root / "Seriály")
    assert (root / "Seriály").is_dir()


@pytest.mark.parametrize("name", ["", "  ", ".", "..", "a/b", "a\\b", "x:y", "x*", ".skryta", "x\x01y", "a" * 201])
def test_mkdir_rejects_bad_names(env, name):
    c, st, root = env
    assert c.post("/api/fs/mkdir", json={"path": str(root), "name": name}).status_code == 400
    assert [p.name for p in root.iterdir()] == []


def test_mkdir_refuses_existing_and_missing_parent(env):
    c, st, root = env
    (root / "Stará").mkdir()
    assert c.post("/api/fs/mkdir", json={"path": str(root), "name": "Stará"}).status_code == 409
    assert c.post("/api/fs/mkdir", json={"path": str(root / "neexistuje"), "name": "X"}).status_code == 400
    assert c.post("/api/fs/mkdir", json={"path": "relativni", "name": "X"}).status_code == 400


def test_rename_moves_folder_and_fixes_history_and_subscriptions(env):
    c, st, root = env
    old = root / "Stará"
    old.mkdir()
    (old / "video.mp4").write_bytes(b"x")
    jid = st.db.add("https://a.example/v1", status="done", filepath=str(old / "video.mp4"), target_dir=str(old))
    sid = st.db.sub_add("https://a.example/ch", str(old), kind="channel")
    other = root / "Jiná"
    other.mkdir()
    jid2 = st.db.add("https://a.example/v2", status="done", filepath=str(other / "x.mp4"))
    r = c.post("/api/fs/rename", json={"path": str(old), "name": "Nová"})
    assert r.status_code == 200, r.text
    new = root / "Nová"
    assert (new / "video.mp4").exists() and not old.exists()
    assert st.db.get(jid)["filepath"] == str(new / "video.mp4")
    assert st.db.get(jid)["target_dir"] == str(new)
    assert st.db.sub_get(sid)["folder"] == str(new)
    assert st.db.get(jid2)["filepath"] == str(other / "x.mp4")      # cizí složka se nedotkla
    assert r.json()["updated"]["jobs.filepath"] == 1


def test_rename_does_not_touch_similar_prefix(env):
    c, st, root = env
    (root / "Film").mkdir()
    jid = st.db.add("https://a.example/v3", status="done", filepath=str(root / "Film2" / "y.mp4"))
    c.post("/api/fs/rename", json={"path": str(root / "Film"), "name": "Kino"})
    assert st.db.get(jid)["filepath"] == str(root / "Film2" / "y.mp4")


def test_rename_refuses_configured_roots_and_their_parents(env):
    c, st, root = env
    assert c.post("/api/fs/rename", json={"path": str(root), "name": "Jinak"}).status_code == 400
    assert c.post("/api/fs/rename", json={"path": str(root.parent), "name": "Jinak"}).status_code == 400
    assert root.exists()


def test_rename_refuses_folder_with_running_download(env):
    c, st, root = env
    (root / "Práce").mkdir()
    st.db.add("https://a.example/v4", status="running", target_dir=str(root / "Práce"))
    r = c.post("/api/fs/rename", json={"path": str(root / "Práce"), "name": "Nová"})
    assert r.status_code == 409
    assert (root / "Práce").is_dir()


def test_rename_refuses_existing_target_and_bad_name(env):
    c, st, root = env
    (root / "A").mkdir()
    (root / "B").mkdir()
    assert c.post("/api/fs/rename", json={"path": str(root / "A"), "name": "B"}).status_code == 409
    assert c.post("/api/fs/rename", json={"path": str(root / "A"), "name": "../C"}).status_code == 400
    assert (root / "A").is_dir()


def test_gui_has_the_folder_buttons():
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/viddown/web/app.js").read_text()
    assert "/api/fs/mkdir" in js and "/api/fs/rename" in js and 'id="dnew"' in js and 'id="dren"' in js
