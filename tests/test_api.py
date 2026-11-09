"""HTTP API přes TestClient (bez spuštěného démona)."""
import pytest
from fastapi.testclient import TestClient

from viddown.config import Secrets, Settings
from viddown.db import DB
from viddown.runner import Runner
from viddown.server import create_app


class FakeEngines:
    busy = None
    engines = {}

    def status(self):
        return []

    @staticmethod
    def chromium_status():
        return {"installed": True, "playwright": "x"}


class State:
    def __init__(self, data):
        self.data = data
        self.settings = Settings()
        self.secrets = Secrets()
        self.db = DB(data / "t.db")
        self.engines = FakeEngines()
        self.runner = Runner(self.db, self.settings, self.engines, data)
        self.bot = None

    def engines_cache(self):
        return []


@pytest.fixture()
def client(data, tmp_path):
    st = State(data)
    st.settings.update({"download_dir": str(tmp_path)})
    return TestClient(create_app(st)), st


def test_add_jobs_extracts_urls_and_dedups(client):
    c, st = client
    r = c.post("/api/jobs", json={"urls": "viz https://a.cz/v1 a https://a.cz/v2\nhttps://a.cz/v1"})
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert [j["url"] for j in jobs] == ["https://a.cz/v1", "https://a.cz/v2"]
    r = c.post("/api/jobs", json={"urls": "https://a.cz/v1"})
    assert r.json()["jobs"][0]["new"] is False
    state = c.get("/api/state").json()
    assert len(state["queue"]) == 2 and state["stats"]["concurrency"] == 2


def test_pause_resume_move_cancel(client):
    c, st = client
    a = st.db.add("https://a", status="queued")
    b = st.db.add("https://b", status="queued")
    assert c.post(f"/api/jobs/{a}/pause").status_code == 200 and st.db.get(a)["paused"] == 1
    c.post(f"/api/jobs/{a}/resume")
    assert st.db.get(a)["paused"] == 0
    c.post(f"/api/jobs/{b}/move", json={"before_id": a})
    assert [j["id"] for j in st.db.queue()] == [b, a]
    c.post(f"/api/jobs/{a}/cancel")
    assert st.db.get(a)["status"] == "cancelled"
    assert c.post("/api/jobs/9999/pause").status_code == 404


def test_settings_validation_and_network_requires_password(client):
    c, st = client
    r = c.put("/api/settings", json={"concurrency": 3})
    assert r.status_code == 200 and r.json()["values"]["concurrency"] == 3
    assert c.put("/api/settings", json={"quality": "x"}).status_code == 400
    assert c.put("/api/settings", json={"network_access": True}).status_code == 400
    assert c.post("/api/settings/password", json={"password": "123"}).status_code == 400


def test_password_protects_api(client):
    c, st = client
    r = c.post("/api/settings/password", json={"password": "tajneheslo"})
    assert r.status_code == 200
    fresh = TestClient(c.app)
    assert fresh.get("/api/state").status_code == 401
    assert fresh.get("/api/session").json()["auth_required"] is True
    assert fresh.post("/api/login", json={"password": "spatne"}).status_code == 401
    assert fresh.post("/api/login", json={"password": "tajneheslo"}).status_code == 200
    assert fresh.get("/api/state").status_code == 200


def test_cookies_upload_validation(client):
    c, st = client
    r = c.post("/api/settings/cookies", files={"file": ("c.txt", b"nesmysl", "text/plain")})
    assert r.status_code == 400
    good = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    r = c.post("/api/settings/cookies", files={"file": ("c.txt", good, "text/plain")})
    assert r.status_code == 200 and r.json()["values"]["cookies_mode"] == "file"


def test_static_gui_served(client):
    c, _ = client
    assert "VidDown" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200


def test_download_dir_validated_on_save(client, tmp_path):
    c, st = client
    good = tmp_path / "nas" / "VidDown"
    r = c.put("/api/settings", json={"download_dir": str(good)})
    assert r.status_code == 200 and r.json()["values"]["download_dir"] == str(good) and good.is_dir()
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        r = c.put("/api/settings", json={"download_dir": str(ro / "x")})
        assert r.status_code == 400 and "platnou cestu" in r.json()["detail"]
    finally:
        ro.chmod(0o700)
    assert st.settings.get("download_dir") == str(good)  # neplatná cesta se neuložila
    assert c.put("/api/settings", json={"download_dir": "relativni"}).status_code == 400


def test_browser_cookies_rejected_in_docker(client, monkeypatch):
    import viddown.server as srv
    c, st = client
    monkeypatch.setattr(srv, "in_docker", lambda: True)
    r = c.put("/api/settings", json={"cookies_mode": "browser"})
    assert r.status_code == 400 and "cookies.txt" in r.json()["detail"]
    assert st.settings.get("cookies_mode") == "none"
    monkeypatch.setattr(srv, "in_docker", lambda: False)
    assert c.put("/api/settings", json={"cookies_mode": "browser"}).status_code == 200


def test_history_marks_deleted_files(client, tmp_path):
    c, st = client
    f = tmp_path / "v.mkv"
    f.write_bytes(b"x")
    a = st.db.add("https://a", status="done", filepath=str(f), finished_at=1.0)
    b = st.db.add("https://b", status="done", filepath=str(tmp_path / "smazane.mkv"), finished_at=2.0)
    items = {i["id"]: i for i in c.get("/api/history").json()["items"]}
    assert items[a]["file_exists"] is True and items[b]["file_exists"] is False


def test_history_pagination_and_stream(client, tmp_path):
    c, st = client
    for i in range(7):
        st.db.add(f"https://v/{i}", status="done", title=f"V{i}", finished_at=100.0 + i)
    r = c.get("/api/history?limit=3&offset=0").json()
    assert r["matched"] == 7 and [i["title"] for i in r["items"]] == ["V6", "V5", "V4"]
    r = c.get("/api/history?limit=3&offset=6").json()
    assert [i["title"] for i in r["items"]] == ["V0"] and r["offset"] == 6 and r["limit"] == 3
    assert c.get("/api/history?q=V3").json()["matched"] == 1
    f = tmp_path / "video.mp4"
    f.write_bytes(b"0123456789" * 1000)
    j = st.db.add("https://v/x", status="done", filepath=str(f))
    r = c.get(f"/api/stream/{j}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == b"0123456789"
    assert r.headers["content-type"].startswith("video/mp4") and r.headers["content-disposition"].startswith("inline")
