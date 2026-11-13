"""Texty pro CLI a Telegram (GUI má vlastní překlady v app.js)."""
from __future__ import annotations

T = {
    "cs": {
        "probing": "Zjišťuji…",
        "found_video": "Nalezeno 1 video{approx}. Rozlišení {res}, stáhne se v {res}.",
        "found_many": "Nalezeno {n} videí{approx}. První v rozlišení {res}, stáhne se v nejvyšší kvalitě.",
        "approx": " (odhad)",
        "queued": "Přidáno do fronty.",
        "ask": "Stáhnout?",
        "ask_big": "Playlist má {n} videí (více než {limit}). Stáhnout?",
        "btn_download": "Stáhnout",
        "btn_cancel": "Zrušit",
        "cancelled": "Zrušeno.",
        "drm": "Video je chráněné DRM a nelze ho stáhnout.",
        "not_found": "Na stránce jsem nenašel žádné video.",
        "failed_probe": "Kontrola selhala: {err}",
        "already": "Tahle URL už je ve frontě.",
        "live_skip": "Probíhá živý přenos, přeskakuji (nahrávání od začátku lze zapnout v Nastavení).",
        "err_job": "❌ Chyba: {title}\n{err}",
        "err_summary": "❌ Playlist „{title}“: {failed} z {total} videí selhalo.\n{lines}",
        "done_job": "✅ Staženo: {title}\n{path}",
        "engine_fail": "⚠️ Aktualizace {engine} na {new} neprošla testem. Zůstává verze {old}.",
        "engine_both_fail": "⚠️ Test {engine} selhal u nové i staré verze (síť nebo web). Nic se nezměnilo.",
        "backup_fail": "⚠️ Automatická záloha selhala: {error}",
        "help": ("Pošlete mi odkaz na video, playlist nebo kanál a stáhnu ho.\n\n"
                 "/fronta – co se stahuje a čeká\n/historie – posledních 10 položek\n"
                 "/engine – verze enginů\n/aktualizovat – zkontrolovat aktualizace enginů"),
        "not_allowed": "Tento bot je soukromý. Vaše chat ID je {id}. Pokud jste vlastník, zadejte ho v Nastavení › Telegram.",
        "no_url": "Ve zprávě není žádný odkaz. Pošlete URL videa, playlistu nebo kanálu.",
        "queue_empty": "Fronta je prázdná.",
        "queue_head": "Fronta ({n}):",
        "history_empty": "Historie je prázdná.",
        "updating": "Kontroluji aktualizace enginů…",
        "status": {"new": "čeká na kontrolu", "probing": "kontroluje se", "confirm": "čeká na potvrzení",
                   "queued": "čeká", "running": "stahuje se", "done": "hotovo", "failed": "chyba",
                   "cancelled": "zrušeno", "skipped": "přeskočeno", "expanded": "playlist"},
    },
    "en": {
        "probing": "Checking…",
        "found_video": "Found 1 video{approx}. Resolution {res}, will download in {res}.",
        "found_many": "Found {n} videos{approx}. First one in {res}, will download in the best quality.",
        "approx": " (estimate)",
        "queued": "Added to the queue.",
        "ask": "Download?",
        "ask_big": "The playlist has {n} videos (more than {limit}). Download?",
        "btn_download": "Download",
        "btn_cancel": "Cancel",
        "cancelled": "Cancelled.",
        "drm": "The video is DRM protected and can't be downloaded.",
        "not_found": "No video found on the page.",
        "failed_probe": "Check failed: {err}",
        "already": "This URL is already in the queue.",
        "live_skip": "Live stream in progress, skipping (recording from start can be enabled in Settings).",
        "err_job": "❌ Failed: {title}\n{err}",
        "err_summary": "❌ Playlist “{title}”: {failed} of {total} videos failed.\n{lines}",
        "done_job": "✅ Downloaded: {title}\n{path}",
        "engine_fail": "⚠️ Update of {engine} to {new} failed its test. Keeping {old}.",
        "engine_both_fail": "⚠️ {engine} test failed for both new and old version (network or website). Nothing changed.",
        "backup_fail": "⚠️ Automatic backup failed: {error}",
        "help": ("Send me a link to a video, playlist or channel and I'll download it.\n\n"
                 "/fronta – queue\n/historie – last 10 items\n/engine – engine versions\n/aktualizovat – check engine updates"),
        "not_allowed": "This bot is private. Your chat ID is {id}. If you're the owner, enter it in Settings › Telegram.",
        "no_url": "There's no link in the message. Send a video, playlist or channel URL.",
        "queue_empty": "The queue is empty.",
        "queue_head": "Queue ({n}):",
        "history_empty": "History is empty.",
        "updating": "Checking engine updates…",
        "status": {"new": "waiting for check", "probing": "checking", "confirm": "awaiting confirmation",
                   "queued": "waiting", "running": "downloading", "done": "done", "failed": "failed",
                   "cancelled": "cancelled", "skipped": "skipped", "expanded": "playlist"},
    },
}


def t(lang: str, key: str, **kw):
    d = T.get(lang) or T["cs"]
    v = d.get(key, T["cs"].get(key, key))
    return v.format(**kw) if kw and isinstance(v, str) else v
