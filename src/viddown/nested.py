"""Zdroje, jejichž položky nejsou videa, ale další seznamy (např. záložka „Playlisty“ kanálu YouTube).

yt-dlp pro ně vrací položky typu `url` s extraktorem `YoutubeTab` a adresou `…/playlist?list=…`. Katalog i fronta je dřív brala jako
videa; teď je rozpoznají a rozbalí (Katalog: každý playlist jako samostatný zdroj, fronta: videa všech playlistů do podsložek).
"""
from __future__ import annotations

import re

LIST_IES = ("youtubetab", "youtubeplaylist")
LIST_URL = re.compile(r"^https?://(?:[\w-]+\.)?youtube\.com/playlist\?(?:[^#]*&)?list=[\w-]+", re.I)
MAX_LISTS = 100                    # nejvýš tolik playlistů najednou (Katalog i fronta)


def is_list_entry(e: dict) -> bool:
    """Položka je odkaz na další seznam (playlist), ne video. Položka s vloženými `entries` se zplošťuje jinde."""
    if not isinstance(e, dict) or e.get("entries"):
        return False
    if e.get("_type") not in (None, "url", "url_transparent"):
        return False
    ie = (e.get("ie_key") or e.get("extractor_key") or "").lower()
    u = e.get("url") or e.get("webpage_url") or ""
    return ie in LIST_IES or bool(LIST_URL.match(u))


def list_infos(entries) -> list[dict]:
    """Odkazy na seznamy ze surových položek: [{url, title, id}] bez duplicit, v původním pořadí."""
    out, seen = [], set()
    for e in entries or []:
        if not e or not is_list_entry(e):
            continue
        u = e.get("url") or e.get("webpage_url")
        if not u or not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "title": e.get("title") or None, "id": e.get("id")})
    return out
