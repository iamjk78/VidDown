# VidDown

Aplikace pro stahování videí z webových stránek. Zadáte URL, aplikace najde video a uloží ho do nastavené složky.

> Stav: návrh / kostra projektu. Zatím bez implementace.

## Cíle

- Windows, macOS a běh v Dockeru
- Zadání URL stránky s videem nebo playlistu, stažení všech videí
- Dvoustupňové stahování s fallbackem:
  1. **yt-dlp** (YouTube a tisíce dalších webů)
  2. **vlastní HLS sniffer** (headless Chromium odposlouchává síť a hledá `.m3u8`)
- Terminálový režim (CLI) i grafické rozhraní (web UI)
- UI: fronta požadavků, historie, průběh aktuálních stahování, nastavení (cílová složka, počet souběžných stahování a další)
- Aktualizace yt-dlp (a Chromia) se zálohou: nová verze se otestuje a při selhání se vrátí předchozí funkční verze

## Návrh aktualizací enginů

```
data/engines/yt-dlp/
  <verze>/      každá verze ve vlastní složce
  current       ukazatel na aktivní verzi
```

1. Nová verze se stáhne vedle staré.
2. Self-test nové i staré verze (`--version`, načtení metadat bez stahování).
3. Selžou-li obě, je to síť nebo web: nic se nepřepne.
4. Selže-li jen nová, smaže se a zůstane stará.
5. Uchovává se posledních N verzí, ruční návrat přes `viddown engine rollback`.

## Inspirace

Návrh vychází z myšlenek projektu [puemos/hls-downloader](https://github.com/puemos/hls-downloader) (MIT): detekce HLS playlistů, parsování m3u8, stahování fragmentů, dešifrování AES-128 a spojování pomocí ffmpeg.

## Omezení

- DRM (Widevine, FairPlay) se neobchází.
- Určeno pro obsah, ke kterému máte práva.
