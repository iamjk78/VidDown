"""Zbylé body z hloubkového review: přesměrování snifferu, přesun souborů při změně složky, osiřelé .part, priorita podprocesů."""
import asyncio
import os
import time
from pathlib import Path

import pytest

from viddown import catalog
from viddown import catalogdetails as cd
from viddown import cpu
from viddown.resolvers import sniffer
from tests.test_catalog_anim import st, fake, scan_items  # noqa: F401  (fixtury)


class _Resp:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}


class _Ctx:
    """Falešný context.request: předem daná odpověď pro každou adresu, zapisuje, co se volalo."""
    def __init__(self, table):
        self.table = table
        self.calls = []

        class R:
            pass
        self.request = R()
        self.request.get = self._get

    async def _get(self, url, headers=None, timeout=None, max_redirects=None):
        self.calls.append((url, max_redirects))
        return self.table[url]


def _allow_all(monkeypatch):
    monkeypatch.setattr(sniffer.netsafe, "host_ok", lambda url: True)


def test_redirect_to_private_address_is_refused(monkeypatch):
    seen = []

    def host_ok(url):
        seen.append(url)
        return "10.0.0.5" not in url                  # vnitřní cíl přesměrování
    monkeypatch.setattr(sniffer.netsafe, "host_ok", host_ok)
    ctx = _Ctx({"https://cdn.example/a.m3u8": _Resp(302, {"location": "http://10.0.0.5/secret"})})
    with pytest.raises(ValueError):
        asyncio.run(sniffer._get(ctx, "https://cdn.example/a.m3u8", "https://page.example/"))
    assert all(m == 0 for _, m in ctx.calls)         # přesměrování řeší VidDown sám, ne klient
    assert "http://10.0.0.5/secret" in seen          # a cíl se ověřil, než se na něj šlo


def test_redirect_chain_to_public_address_is_followed(monkeypatch):
    _allow_all(monkeypatch)
    ctx = _Ctx({"https://cdn.example/a": _Resp(301, {"location": "/b"}),
                "https://cdn.example/b": _Resp(200)})
    r = asyncio.run(sniffer._get(ctx, "https://cdn.example/a", "https://page.example/"))
    assert r.status == 200 and [u for u, _ in ctx.calls] == ["https://cdn.example/a", "https://cdn.example/b"]


def test_redirect_loop_is_stopped(monkeypatch):
    _allow_all(monkeypatch)
    ctx = _Ctx({"https://cdn.example/a": _Resp(302, {"location": "https://cdn.example/a"})})
    with pytest.raises(ValueError):
        asyncio.run(sniffer._get(ctx, "https://cdn.example/a", "https://page.example/"))
    assert len(ctx.calls) == sniffer.MAX_REDIRECTS + 1


def test_moved_download_follows_a_changed_folder(st, fake, tmp_path):
    scan_items(st, fake, ["a"])
    w = cd.DetailWorker(st)
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "1.jpg").write_bytes(b"x")
    seq = iter([old, new])                             # při spuštění byla složka „old“, po dokončení je v nastavení „new“
    w.folder = lambda: next(seq)
    name = asyncio.run(w._stored(lambda folder, *a: "1.jpg", 1))
    assert name == "1.jpg"
    assert (new / "1.jpg").exists()


def test_prune_removes_stale_part_leftovers_only(st, tmp_path):
    folder = tmp_path / "thumbs"
    folder.mkdir()
    old_part = folder / "5.jpg.abcd1234.part"
    new_part = folder / "6.jpg.beef0000.part"
    for p in (old_part, new_part):
        p.write_bytes(b"x")
    long_ago = time.time() - 7200
    os.utime(old_part, (long_ago, long_ago))
    catalog.prune_thumbs(st.db, folder, min_age=3600)
    assert not old_part.exists()                      # osiřelý, starší než hodina
    assert new_part.exists()                          # může se ještě stahovat
