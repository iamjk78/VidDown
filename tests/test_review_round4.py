"""Opravy z kontroly posledních oprav: hlavní smyčka pro vlákna, maskování hesla proxy, chyba sítě v kontrole HLS."""
import asyncio

from viddown import util
from viddown.resolvers import sniffer


def test_mask_proxy_hides_password_with_or_without_scheme_and_with_at_sign():
    assert util.mask_proxy("http://u:p@ss@h:8080/x") == "http://u:***@h:8080/x"
    assert util.mask_proxy("user:secret@proxy.local:3128") == "user:***@proxy.local:3128"
    assert util.mask_proxy("socks5://u:p@h:1080") == "socks5://u:***@h:1080"
    assert util.mask_proxy("http://h:8080") == "http://h:8080"


def test_notification_from_a_thread_reaches_the_loop_set_at_startup():
    ran = {"v": False}

    async def note():
        ran["v"] = True

    async def main():
        util.set_main_loop(asyncio.get_running_loop())        # jako při startu aplikace, bez předchozího spawn
        ok = await asyncio.to_thread(lambda: util.spawn(note()) is not None)
        for _ in range(50):
            if ran["v"]:
                break
            await asyncio.sleep(0.02)
        return ok
    assert asyncio.run(main()) is True
    assert ran["v"] is True


def test_network_error_while_checking_playlist_only_drops_that_candidate(monkeypatch):
    def boom(*a, **k):
        raise OSError("spojení selhalo")
    monkeypatch.setattr(sniffer.netsafe, "fetch_limited", boom)
    assert asyncio.run(sniffer.hls_hosts_ok("https://cdn.example/v.m3u8", "https://page.example/")) is False
