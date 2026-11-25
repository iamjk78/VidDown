"""Playlist HLS: každá adresa, na kterou ffmpeg půjde, se ověří předem (ne jen adresa playlistu)."""
import asyncio

from viddown.resolvers import sniffer


def _playlist(monkeypatch, body: str, public=lambda host: True):
    def fetch(url, headers, max_bytes, proxy=None, total_timeout=60.0):
        return 200, {}, body.encode()
    monkeypatch.setattr(sniffer.netsafe, "fetch_limited", fetch)
    monkeypatch.setattr(sniffer.netsafe, "host_ok", lambda url: public(url.split("/")[2].split(":")[0]))


def test_segment_on_private_address_is_refused(monkeypatch):
    _playlist(monkeypatch, "#EXTM3U\n#EXTINF:4,\nhttp://10.0.0.5/secret.ts\n",
              public=lambda h: not h.startswith("10."))
    assert asyncio.run(sniffer.hls_hosts_ok("https://cdn.example/v.m3u8", "https://page.example/")) is False


def test_playlist_on_public_hosts_is_accepted(monkeypatch):
    _playlist(monkeypatch, "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"https://keys.example/k\"\n#EXTINF:4,\nseg1.ts\n")
    assert asyncio.run(sniffer.hls_hosts_ok("https://cdn.example/v.m3u8", "https://page.example/")) is True


def test_non_http_scheme_in_playlist_is_refused(monkeypatch):
    _playlist(monkeypatch, "#EXTM3U\n#EXTINF:4,\nfile:///etc/passwd\n")
    assert asyncio.run(sniffer.hls_hosts_ok("https://cdn.example/v.m3u8", "https://page.example/")) is False
