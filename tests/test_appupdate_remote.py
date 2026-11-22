"""Aktualizace zevnitř, etapa 2: kontrola a stažení vydání z (falešného) GitHubu, ověření, samotest, přeskočení."""
import hashlib
import json
import re
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests._update_test_key import TEST_PRIV_B64, TEST_PUB_B64
from viddown import appupdate as au

TOKEN = "tajny-token-123"
REPO = "vlastnik/projekt"


class Fake:
    """Falešné GitHub API (/repos/.../releases/latest a stažení souboru přesměrováním na jiný server)."""
    def __init__(self, bind="127.0.0.1", public="127.0.0.1"):
        self.bind, self.public = bind, public     # pro zkoušku v Dockeru: bind 0.0.0.0, public host.docker.internal
        self.assets = {}            # id -> (název, bajty)
        self.release = None         # {"tag_name", "body", "assets": [...]}
        self.api_auth, self.cdn_auth, self.calls = [], [], []
        fake = self

        class Api(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.api_auth.append(self.headers.get("Authorization"))
                fake.calls.append(self.path)
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(404, b'{"message":"Not Found"}')
                if self.path == f"/repos/{REPO}/releases/latest":
                    if fake.release is None:
                        return self._send(404, b'{"message":"Not Found"}')
                    return self._send(200, json.dumps(fake.release).encode())
                m = re.fullmatch(rf"/repos/{REPO}/releases/assets/(\d+)", self.path)
                if m and int(m.group(1)) in fake.assets:
                    self.send_response(302)
                    self.send_header("Location", f"http://{fake.public}:{fake.cdn.server_address[1]}/blob/{m.group(1)}")
                    self.end_headers()
                    return
                self._send(404, b"{}")

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Cdn(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.cdn_auth.append(self.headers.get("Authorization"))
                aid = int(self.path.rsplit("/", 1)[1])
                body = fake.assets[aid][1]
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.api = ThreadingHTTPServer((bind, 0), Api)
        self.cdn = ThreadingHTTPServer((bind, 0), Cdn)
        for srv in (self.api, self.cdn):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.url = f"http://{public}:{self.api.server_address[1]}"

    def close(self):
        for srv in (self.api, self.cdn):
            srv.shutdown()
            srv.server_close()

    def publish(self, tmp_path, version="9.9.9", tag=None, mutate=None, requires=None, sha=None, manifest_version=None,
                with_zip=True, zip_size=None):
        zp = tmp_path / f"viddown-{version}.zip"
        man = au.pack(zp, version=version, requires_image_api=requires)
        if mutate:
            mutate(zp)
            man["sha256"] = hashlib.sha256(zp.read_bytes()).hexdigest()
        manifest = {"version": manifest_version or version, "sha256": sha or man["sha256"],
                    "requires_image_api": man["requires_image_api"], "schema_version": man["schema_version"]}
        mbytes = json.dumps(manifest).encode()
        sig = au.sign_manifest(mbytes, TEST_PRIV_B64).encode()          # podpis přesných bajtů manifestu (testovací klíč)
        self.assets = {1: (au.MANIFEST_ASSET, mbytes), 2: (zp.name, zp.read_bytes()), 3: (au.MANIFEST_SIG_ASSET, sig)}
        assets = [{"id": 1, "name": au.MANIFEST_ASSET, "size": len(self.assets[1][1])},
                  {"id": 3, "name": au.MANIFEST_SIG_ASSET, "size": len(sig)}]
        if with_zip:
            assets.append({"id": 2, "name": zp.name, "size": zip_size if zip_size is not None else len(self.assets[2][1])})
        self.release = {"tag_name": tag or f"v{version}", "body": "- nová věc\n- oprava", "assets": assets}


@pytest.fixture
def gh(monkeypatch):
    f = Fake()
    monkeypatch.setattr(au, "UPDATE_PUBKEY_B64", TEST_PUB_B64)           # ověřování podpisu testovacím klíčem
    monkeypatch.setenv("VIDDOWN_GITHUB_API", f.url)
    for k in ("VIDDOWN_APP_ACTIVE", "VIDDOWN_BASE_VERSION", "VIDDOWN_IMAGE_API", "VIDDOWN_BASE_SCHEMA"):
        monkeypatch.delenv(k, raising=False)
    yield f
    f.close()


@pytest.fixture
def store(tmp_path):
    return au.AppStore(tmp_path / "data")


def break_module(zp):
    """Vydání s chybou v kódu (kontrolní součet pak souhlasí, vadný je až samotest)."""
    tmp = zp.with_suffix(".new")
    with zipfile.ZipFile(zp) as zi, zipfile.ZipFile(tmp, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, "def rozbite(:\n" if n == "viddown/pagelist.py" else zi.read(n))
    tmp.replace(zp)


def test_check_reports_available_and_up_to_date(gh, store, tmp_path):
    gh.publish(tmp_path, "9.9.9")
    c = au.check(store, REPO, TOKEN)
    assert c["status"] == "available" and c["version"] == "9.9.9" and c["current"] == au.baseline_version()
    assert "nová věc" in c["notes"] and c["size"] > 100_000
    assert store.state()["check"]["status"] == "available"
    gh.publish(tmp_path, "0.1.0")
    assert au.check(store, REPO, TOKEN)["status"] == "up_to_date"
    gh.publish(tmp_path, "0.0.5")
    assert au.check(store, REPO, TOKEN)["status"] == "up_to_date"


def test_private_repo_without_token_gives_helpful_error(gh, store, tmp_path):
    gh.publish(tmp_path)
    with pytest.raises(au.UpdateError, match="vyžaduje token"):
        au.check(store, REPO, None)
    st = store.state()["check"]
    assert st["status"] == "error" and "token" in st["error"]


def test_update_downloads_verifies_tests_and_activates(gh, store, tmp_path):
    gh.publish(tmp_path)
    r = au.update(store, REPO, TOKEN, skip_engines=True)
    assert r["status"] == "activated" and r["version"] == "9.9.9" and r["restart"]
    st = store.state()
    assert st["current"] == "9.9.9" and st["probation"]["version"] == "9.9.9"
    assert store.installed() == ["9.9.9"] and store.manifest("9.9.9")["version"] == "9.9.9"
    assert [e["kind"] for e in st["events"]][-2:] == ["installed", "switched"]
    # po aktualizaci je „aktuální“ nová verze
    assert au.check(store, REPO, TOKEN)["status"] == "up_to_date"
    assert au.update(store, REPO, TOKEN)["status"] == "up_to_date"


def test_token_is_sent_to_api_but_not_to_the_file_server(gh, store, tmp_path):
    gh.publish(tmp_path)
    au.update(store, REPO, TOKEN, skip_engines=True)
    assert gh.api_auth and all(a == f"Bearer {TOKEN}" for a in gh.api_auth)
    assert gh.cdn_auth and all(a is None for a in gh.cdn_auth)        # přesměrování na jiný server token nedostane


def test_wrong_checksum_installs_nothing(gh, store, tmp_path):
    gh.publish(tmp_path, sha="0" * 64)
    with pytest.raises(au.UpdateError, match="kontrolní součet"):
        au.update(store, REPO, TOKEN, skip_engines=True)
    assert store.installed() == [] and store.state()["current"] is None and not store.state()["skipped"]


def test_broken_release_is_removed_skipped_and_not_retried(gh, store, tmp_path):
    gh.publish(tmp_path, mutate=break_module)
    with pytest.raises(au.UpdateError, match="neprošla samotestem"):
        au.update(store, REPO, TOKEN, skip_engines=True)
    st = store.state()
    assert st["current"] is None and store.installed() == [] and "9.9.9" in st["skipped"]
    assert "samotest" in st["skipped"]["9.9.9"]["reason"]
    assert au.check(store, REPO, TOKEN)["status"] == "skipped"
    with pytest.raises(au.UpdateError, match="přeskočena"):
        au.update(store, REPO, TOKEN, skip_engines=True)               # bez --force se to nezkouší znovu
    n = len(gh.calls)
    gh.publish(tmp_path, "9.9.10")                                       # novější vydání se zkusí normálně
    assert au.update(store, REPO, TOKEN, skip_engines=True)["version"] == "9.9.10" and len(gh.calls) > n


def test_force_retries_a_skipped_version(gh, store, tmp_path):
    gh.publish(tmp_path, mutate=break_module)
    with pytest.raises(au.UpdateError):
        au.update(store, REPO, TOKEN, skip_engines=True)
    gh.publish(tmp_path)                                                 # opravené vydání se stejnou verzí
    assert au.update(store, REPO, TOKEN, force=True, skip_engines=True)["status"] == "activated"
    assert "9.9.9" not in store.state()["skipped"]


def test_release_needing_newer_image_is_refused(gh, store, tmp_path):
    gh.publish(tmp_path, requires=au.image_api() + 1)
    assert au.check(store, REPO, TOKEN)["status"] == "needs_image"
    with pytest.raises(au.UpdateError, match="vyžaduje novější obraz"):
        au.update(store, REPO, TOKEN)
    assert store.installed() == []


def test_inconsistent_or_incomplete_releases_are_rejected(gh, store, tmp_path):
    gh.publish(tmp_path, manifest_version="9.9.8")
    with pytest.raises(au.UpdateError, match="neodpovídá vydání"):
        au.check(store, REPO, TOKEN)
    gh.publish(tmp_path, with_zip=False)
    with pytest.raises(au.UpdateError, match="očekávané soubory"):
        au.check(store, REPO, TOKEN)
    gh.publish(tmp_path)
    gh.release["tag_name"] = "nejaky-tag"
    with pytest.raises(au.UpdateError, match="platnou verzi"):
        au.check(store, REPO, TOKEN)
    gh.publish(tmp_path, tag="V9.9.9")                                   # velké V se toleruje
    assert au.check(store, REPO, TOKEN)["version"] == "9.9.9"


def test_oversized_archive_is_refused(gh, store, tmp_path, monkeypatch):
    gh.publish(tmp_path, zip_size=au.MAX_ZIP_BYTES + 1)
    with pytest.raises(au.UpdateError, match="příliš velký"):
        au.update(store, REPO, TOKEN)
    gh.publish(tmp_path)
    monkeypatch.setattr(au, "MAX_ZIP_BYTES", 5000)                        # skutečný soubor větší než limit při stahování
    next(a for a in gh.release["assets"] if a["name"].endswith(".zip"))["size"] = 10                                  # GitHub hlásí menší velikost, než soubor má
    with pytest.raises(au.UpdateError, match="větší, než se čekalo"):
        au.update(store, REPO, TOKEN)
    assert store.installed() == []


def test_network_down_changes_nothing(gh, store, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDDOWN_GITHUB_API", "http://127.0.0.1:9")
    with pytest.raises(au.UpdateError, match="není dostupný"):
        au.update(store, REPO, TOKEN)
    st = store.state()
    assert st["current"] is None and st["check"]["status"] == "error" and not st["skipped"]


def test_invalid_repo_is_rejected(gh, store):
    for bad in ("", "bez-lomitka", "a/b/c", "../x", "a b/c"):
        with pytest.raises(au.UpdateError, match="neplatný repozitář"):
            au.check(store, bad, TOKEN)


def test_secret_token_and_env_override(tmp_path, monkeypatch):
    from viddown.config import Secrets
    monkeypatch.delenv("VIDDOWN_APP_UPDATE_TOKEN", raising=False)
    s = Secrets(tmp_path / "secrets.json")
    assert s.app_update_token == ""
    s.set_app_update_token("  abc  ")
    assert s.app_update_token == "abc" and (tmp_path / "secrets.json").stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("VIDDOWN_APP_UPDATE_TOKEN", "z-prostredi")
    assert s.app_update_token == "z-prostredi"
    monkeypatch.delenv("VIDDOWN_APP_UPDATE_TOKEN")
    s.set_app_update_token("")
    assert s.app_update_token == ""


def test_repo_setting_validation(data):
    from viddown.config import Settings
    s = Settings()
    assert s.get("app_update_repo")
    for bad in ("x", "a/b/c", "../x", "a/.."):
        with pytest.raises(ValueError):
            s.update({"app_update_repo": bad})
    assert s.update({"app_update_repo": "o/r"})["app_update_repo"] == "o/r"


def test_cli_check_and_update(gh, tmp_path, monkeypatch, capsys):
    from viddown import cli
    monkeypatch.setenv("VIDDOWN_DATA", str(tmp_path / "d"))
    monkeypatch.setenv("VIDDOWN_APP_UPDATE_TOKEN", TOKEN)
    from viddown.config import Settings
    Settings().update({"app_update_repo": REPO})
    monkeypatch.setattr(au.AppStore, "selftest", lambda self, ver, skip_engines=False, timeout=240: (True, {"ok": True, "checks": []}))
    gh.publish(tmp_path)
    assert cli.main(["app", "check"]) == 0
    out = capsys.readouterr().out
    assert "nejnovější vydání 9.9.9" in out and "k dispozici novější verze" in out and "nová věc" in out
    assert cli.main(["app", "update"]) == 0
    assert "Nainstalována a otestována verze 9.9.9" in capsys.readouterr().out
    assert cli.main(["app", "update"]) == 0
    assert "nejnovější verzi" in capsys.readouterr().out
    monkeypatch.delenv("VIDDOWN_APP_UPDATE_TOKEN")
    assert cli.main(["app", "check"]) == 1
    assert "token" in capsys.readouterr().err


def test_release_script_is_valid_bash():
    assert subprocess.run(["bash", "-n", "scripts/release.sh"], capture_output=True).returncode == 0
