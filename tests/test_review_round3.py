"""Nálezy z třetího kola review: opakovaný neúspěch přejmenování nesmí smazat jedinou kopii; upozornění z pracovního vlákna."""
import asyncio
import errno
import json
from pathlib import Path

import pytest

from viddown import runner as runner_mod
from viddown import util
from viddown.resolvers import ResolveError
from tests.test_runner import rt  # noqa: F401  (fixture runneru)


def test_second_failed_rename_keeps_the_only_copy(rt, monkeypatch):
    j, _ = rt.add("https://x/v")
    staging = rt.staging(j)
    staging.mkdir(parents=True, exist_ok=True)
    src = staging / "video.mp4"
    src.write_bytes(b"VIDEO-DATA")
    real_replace = runner_mod.os.replace
    calls = {"n": 0}

    def always_failing(a, b):                          # cíl je nedostupný při každém pokusu
        calls["n"] += 1
        raise OSError(errno.EIO, "výpadek")

    monkeypatch.setattr(runner_mod.os, "replace", always_failing)
    with pytest.raises(ResolveError):
        rt._place(j, {"file": src, "thumb": None, "log": ""}, "ytdlp", staging)   # první pokus: přesun do rozdělaného souboru
    kept = Path(json.loads((staging / runner_mod.PENDING).read_text())["file"])
    with pytest.raises(ResolveError):
        rt._place(j, {"file": kept, "thumb": None, "log": ""}, "ytdlp", staging)  # navázání, které znovu selže
    assert kept.exists() and kept.read_bytes() == b"VIDEO-DATA"                 # jediná kopie zůstala
    monkeypatch.setattr(runner_mod.os, "replace", real_replace)
    dest = rt._place(j, {"file": kept, "thumb": None, "log": ""}, "ytdlp", staging)
    assert dest.read_bytes() == b"VIDEO-DATA"


def test_spawn_from_a_worker_thread_runs_on_the_main_loop():
    ran = {"v": False}

    async def note():
        ran["v"] = True

    async def main():
        util.spawn(note())                             # v aplikaci už hlavní smyčka běží a spawn z ní ji zapamatuje
        ran["v"] = False
        loop_thread_ok = await asyncio.to_thread(lambda: util.spawn(note()) is not None)
        for _ in range(50):                            # čekání na doběh (krátké)
            if ran["v"]:
                break
            await asyncio.sleep(0.02)
        return loop_thread_ok

    assert asyncio.run(main()) is True
    assert ran["v"] is True
