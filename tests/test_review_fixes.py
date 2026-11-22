"""Opravy z hloubkového review: ztráta jediné kopie při nezdařeném přejmenování v cíli a návrat po nezdařené obnově zálohy."""
import asyncio
import errno
import json
from pathlib import Path

import pytest

from viddown import backup
from viddown import runner as runner_mod
from viddown.resolvers import ResolveError
from tests.test_runner import rt  # noqa: F401  (fixture runneru)


def test_failed_rename_keeps_the_only_copy_and_can_be_finished_later(rt, monkeypatch, tmp_path):
    j, _ = rt.add("https://x/v")
    job = rt.db.get(j)
    staging = rt.staging(j)
    staging.mkdir(parents=True, exist_ok=True)
    src = staging / "video.mp4"
    src.write_bytes(b"VIDEO-DATA")
    result = {"file": src, "thumb": None, "log": ""}

    real_replace = runner_mod.os.replace
    calls = {"n": 0}

    def flaky_replace(a, b):                       # první přejmenování v cíli selže (výpadek NAS)
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.EIO, "výpadek")
        return real_replace(a, b)

    monkeypatch.setattr(runner_mod.os, "replace", flaky_replace)
    with pytest.raises(ResolveError):
        rt._place(j, result, "ytdlp", staging)
    # data nesmí zmizet: po přesunu zůstává jedinou kopií v rozdělaném souboru, na který ukazuje pending
    pend = json.loads((staging / runner_mod.PENDING).read_text())
    kept = Path(pend["file"])
    assert kept.exists() and kept.read_bytes() == b"VIDEO-DATA"
    assert kept.name.endswith(runner_mod.PART_SUFFIX)

    # další pokus: dokončí jen přejmenování, nic se nekopíruje znovu
    monkeypatch.setattr(runner_mod.os, "replace", real_replace)
    dest = rt._place(j, {"file": kept, "thumb": None, "log": ""}, "ytdlp", staging)
    assert dest.name == "video.mp4" and dest.read_bytes() == b"VIDEO-DATA"
    assert not kept.exists()
    assert job["id"] == j


def test_rollback_restores_replaced_files_and_removes_new_ones(tmp_path):
    data = tmp_path / "data"
    keep = tmp_path / "keep"
    data.mkdir()
    (data / "a.txt").write_text("stará")
    done: list[str] = []

    backup._keep_old(data / "a.txt", keep / "a.txt")          # dosavadní obsah se zachová…
    done.append("a.txt")
    tmp = data / "a.txt.new"                                   # přepisuje se novým souborem (jako při obnově)
    tmp.write_text("nová")
    tmp.replace(data / "a.txt")
    (data / "b.txt").write_text("jen v záloze")               # soubor, který dřív neexistoval
    done.append("b.txt")

    backup._rollback(data, keep, done)
    assert (data / "a.txt").read_text() == "stará"
    assert not (data / "b.txt").exists()


# --- DNS rebinding: kontrola adresy při každém připojení (netsafe) ---------------------------------
import socket as _socket  # noqa: E402

import httpcore  # noqa: E402

from viddown import netsafe  # noqa: E402


def _fake_dns(monkeypatch, answers):
    """getaddrinfo vrací postupně odpovědi z `answers` (poslední se opakuje)."""
    seq = list(answers)

    def gai(host, *a, **k):
        ip = seq.pop(0) if len(seq) > 1 else seq[0]
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, 0))]
    monkeypatch.setattr(netsafe.socket, "getaddrinfo", gai)


def test_pin_refuses_private_address(monkeypatch):
    monkeypatch.delenv("VIDDOWN_ALLOW_PRIVATE_PREVIEW", raising=False)
    _fake_dns(monkeypatch, ["10.0.0.5"])
    with pytest.raises(httpcore.ConnectError):
        netsafe._pin_address("intranet.example")


def test_rebinding_between_check_and_connect_is_blocked(monkeypatch):
    monkeypatch.delenv("VIDDOWN_ALLOW_PRIVATE_PREVIEW", raising=False)
    # první dotaz (kontrola) vrátí veřejnou adresu, další (připojení) vnitřní
    _fake_dns(monkeypatch, ["93.184.216.34", "10.0.0.5"])
    assert netsafe.host_ok("https://rebind.example/x") is True
    with pytest.raises(httpcore.ConnectError):
        netsafe._pin_address("rebind.example")


def test_public_address_is_pinned_and_transport_is_used(monkeypatch):
    monkeypatch.delenv("VIDDOWN_ALLOW_PRIVATE_PREVIEW", raising=False)
    _fake_dns(monkeypatch, ["93.184.216.34"])
    assert netsafe._pin_address("public.example") == "93.184.216.34"
    kw = netsafe.client_kw(None)
    assert isinstance(kw["transport"], netsafe._PinnedTransport)
    assert "transport" not in netsafe.client_kw("http://proxy.example:3128")


# --- podpis vydání (appupdate) -------------------------------------------------------------------
from tests._update_test_key import TEST_PRIV_B64, TEST_PUB_B64  # noqa: E402
from viddown import appupdate as au  # noqa: E402


def test_manifest_signature_roundtrip_and_tamper_detection():
    data = b'{"version":"1.0.0","sha256":"' + b"a" * 64 + b'"}'
    sig = au.sign_manifest(data, TEST_PRIV_B64)
    assert au.verify_manifest(data, sig, TEST_PUB_B64)
    assert not au.verify_manifest(data + b" ", sig, TEST_PUB_B64)     # změněný manifest
    assert not au.verify_manifest(data, "AAAA", TEST_PUB_B64)          # nesmyslný podpis
    assert not au.verify_manifest(data, sig)                           # jiný (produkční) klíč podpis neuzná


def test_release_with_forged_manifest_is_refused(monkeypatch):
    monkeypatch.setattr(au, "UPDATE_PUBKEY_B64", TEST_PUB_B64)
    body = b'{"version":"1.0.0","sha256":"' + b"a" * 64 + b'"}'
    rel = {"version": "1.0.0", "tag": "v1.0.0", "assets": {
        au.MANIFEST_ASSET: {"id": 1, "size": len(body)},
        au.MANIFEST_SIG_ASSET: {"id": 2, "size": 4},
        "viddown-1.0.0.zip": {"id": 3, "size": 1}}}

    def fake_download(repo, token, aid, dest, max_bytes):
        dest.write_bytes(body if aid == 1 else b"AAAA")                  # podvržený manifest s neplatným podpisem
    monkeypatch.setattr(au, "_download_asset", fake_download)
    with pytest.raises(au.UpdateError, match="podpis"):
        au._release_manifest("o/r", None, rel)


# --- pomalý NAS nesmí zastavit frontu po jediné odpovědi --------------------------------------------
import time as _time  # noqa: E402


def test_one_slow_target_check_does_not_pause_the_queue(rt, monkeypatch):
    slow = {"on": True}

    def check(path):
        if slow["on"]:
            _time.sleep(0.3)                  # NAS neodpoví včas
        return True, ""
    monkeypatch.setattr(runner_mod, "target_available", check)
    monkeypatch.setattr(runner_mod, "TARGET_TIMEOUT", 0.05)
    s = rt.settings.all()

    async def go():
        await rt._check_target(s)             # jediná pomalá odpověď
        assert not rt.queue_paused()
        slow["on"] = False
        rt._target_checked = -1e9
        await rt._check_target(s)             # odpověď v pořádku
        assert not rt.queue_paused()
    asyncio.run(go())


def test_repeated_target_failures_pause_the_queue(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "target_available", lambda path: (False, "nedostupné"))
    s = rt.settings.all()

    async def go():
        for _ in range(runner_mod.TARGET_FAILS_BEFORE_PAUSE):
            rt._target_checked = -1e9
            await rt._check_target(s)
    asyncio.run(go())
    assert rt.queue_paused() and rt.db.kv_get("queue_pause_reason") == "target"
