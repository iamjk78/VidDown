# VidDown

Stahování videí z webových stránek, playlistů a celých kanálů do složky ve vašem počítači.
Běží na **macOS, Windows i v Dockeru**. Ovládá se **webovým GUI**, **Telegram botem** i **příkazy v terminálu**.

- **YouTube a tisíce dalších webů** přes [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- **Ostatní stránky** přes vestavěný **HLS sniffer**: neviditelný prohlížeč (Chromium) načte stránku, odposlechne stream (`.m3u8`, DASH, MP4) a ffmpeg ho stáhne a spojí. Když yt-dlp video nenajde, automaticky se zkusí sniffer.
- **Jedna fronta**, stahuje se v pořadí přidání. V GUI jde měnit pořadí přetažením, pozastavit a odstranit položky.
- **Nejvyšší kvalita** je výchozí. Vedle každého videa se uloží miniatura `Název videa.jpg`.
- **Playlisty a kanály** se stáhnou celé (u kanálu jen záložka Videa, Shorts a živé přenosy volitelně), do vlastní složky.
- **Telegram:** pošlete botovi odkaz, odpoví počtem nalezených videí a rozlišením prvního. Pak hlásí jen chyby.
- **Enginy** (yt-dlp, Deno, ffmpeg) se aktualizují s testem. Když nová verze nefunguje, zůstane předchozí.
- Nastavení: souběžná stahování, limit rychlosti, časové okno, šablona názvů, cookies, proxy, heslo do GUI, čeština i angličtina, světlý i tmavý režim.
- V GUI je **nápověda** a **průvodce prvním spuštěním**.

> Používejte jen pro obsah, ke kterému máte práva. DRM (Netflix, Disney+ apod.) se neobchází.

## Instalace

### macOS a Windows (zabalená aplikace)

Balíček se sestavuje lokálně na cílovém systému (PyInstaller neumí křížové sestavení):

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pyinstaller packaging/viddown.spec
```

Na Macu vznikne `dist/VidDown.app`, na Windows `dist/viddown/viddown.exe` (příkaz spusťte na počítači s Windows: `.venv\Scripts\pyinstaller packaging\viddown.spec`).

- **macOS:** rozbalte, přesuňte `VidDown.app` do Aplikací a spusťte. Při prvním spuštění: pravé tlačítko › Otevřít (aplikace není podepsaná).
- **Windows:** rozbalte a spusťte `viddown.exe`.

Při prvním spuštění se otevře GUI v prohlížeči (`http://127.0.0.1:8765`) a aplikace si stáhne yt-dlp, Deno, ffmpeg a Chromium (jednorázově, cca 250 MB).

### Docker

```bash
docker compose up -d --build
```

GUI je na `http://127.0.0.1:8765`. Videa se ve výchozím stavu ukládají do `./downloads`, data aplikace do `./data`.
V `docker-compose.yml` nastavte `TZ` (plánování), `PUID`/`PGID` (vlastník souborů) a případně Telegram.
Pro přístup ze sítě odstraňte `127.0.0.1:` z mapování portu a nastavte `VIDDOWN_PASSWORD`.

**Cílová složka (např. síťová složka na NAS).** Kontejner vidí jen připojené složky. Připojte nadřazenou složku
a konkrétní cíl pak zvolte v GUI (Nastavení › Stahování › Cílová složka). Místní připojení dejte do
`docker-compose.override.yml` (necommituje se), Docker Compose ho načte automaticky:

```yaml
services:
  viddown:
    environment:
      PUID: "501"   # id -u
      PGID: "20"    # id -g
    volumes:
      - /Volumes/DATA:/nas      # macOS: připojené SMB sdílení
      # - /volume1:/nas         # Synology: celý svazek
```

V GUI pak zadejte cestu uvnitř kontejneru, např. `/nas/Videos`. Při uložení se ověří,
že složka leží na připojeném svazku a že do ní jde zapisovat. Jinak se uložení odmítne s vysvětlením.
Když cílová složka za provozu přestane být dostupná (odpojený NAS), fronta se pozastaví a po obnovení
přístupu sama pokračuje. Už stažené video počká v dočasné složce a znovu se nestahuje.

### Ze zdrojového kódu

Vyžaduje Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m playwright install chromium-headless-shell
.venv/bin/viddown
```

## Použití

| Příkaz | Co dělá |
|---|---|
| `viddown` | spustí aplikaci a otevře GUI |
| `viddown serve [--open]` | spustí aplikaci (fronta, GUI, Telegram) |
| `viddown add URL [URL…] [--yes]` | přidá do fronty, `--yes` potvrdí velké playlisty; když aplikace neběží, spustí ji na pozadí |
| `viddown queue` / `viddown history` | vypíše frontu / historii |
| `viddown engine status\|update\|test\|rollback [engine] [verze]` | správa enginů |
| `viddown config get [klíč]` / `viddown config set klíč hodnota` | nastavení |
| `viddown password` | heslo do GUI |
| `viddown telegram --token … --chat …` | Telegram bot |
| `viddown autostart on\|off\|status` | spouštění po přihlášení (LaunchAgent / registr / systemd) |
| `viddown doctor` | kontrola závislostí |

Frontu zpracovává vždy jen jeden proces (zámek). CLI zapisuje do stejné databáze, takže běžící aplikace převezme úlohy okamžitě.

### Telegram bot

1. V Telegramu otevřete **@BotFather**, pošlete `/newbot` a zkopírujte token.
2. Token vložte v **Nastavení › Telegram** (nebo `viddown telegram --token …`).
3. Napište botovi. Odpoví vaším chat ID – vložte ho do pole **Povolené chat ID**.

Použijte samostatného bota: jeden token nemůže číst zprávy ve dvou aplikacích zároveň.

## Kde jsou data

| Systém | Datová složka |
|---|---|
| macOS | `~/Library/Application Support/VidDown` |
| Windows | `%APPDATA%\VidDown` |
| Linux | `~/.local/share/viddown` |
| Docker | `/data` |

Obsahuje `settings.json`, `secrets.json` (token a hash hesla, práva 600), `viddown.db`, `engines/`, `thumbs/`, `logs/` a `archive.txt` (už stažená videa). Jinou složku nastavíte proměnnou `VIDDOWN_DATA`.

Proměnné prostředí (mají přednost před nastavením v GUI a zamknou ho): `VIDDOWN_DOWNLOAD_DIR`, `VIDDOWN_TEMP_DIR`, `VIDDOWN_CONCURRENCY`, `VIDDOWN_PORT`, `VIDDOWN_HOST`, `VIDDOWN_LANGUAGE`, `VIDDOWN_PASSWORD`, `VIDDOWN_TELEGRAM_TOKEN`, `VIDDOWN_TELEGRAM_CHAT_ID`, `VIDDOWN_ALLOW_NO_PASSWORD`. `VIDDOWN_DEFAULT_DOWNLOAD_DIR` cílovou složku jen předvyplní a v GUI zůstane měnitelná (používá ji Docker obraz).

## Vývoj

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # testy (integrační test snifferu potřebuje ffmpeg a Chromium)
VIDDOWN_DATA=$PWD/.devdata .venv/bin/viddown serve
.venv/bin/pyinstaller packaging/viddown.spec   # balíček pro aktuální systém
```

Struktura:

```
src/viddown/
  config.py      nastavení a citlivé údaje
  db.py          SQLite: fronta, historie
  engines.py     verzované enginy s testem a návratem
  probe.py       kontrola URL (počet videí, rozlišení, miniatura)
  resolvers/     yt-dlp a HLS sniffer
  runner.py      fronta: pořadí, souběžnost, pauzy, plánování, opakování
  server.py      HTTP API
  web/           GUI (HTML, CSS, JS bez build kroku)
  telegram.py    Telegram bot
  daemon.py      jeden proces: fronta + GUI + bot
  cli.py         příkazy
```

Plán a pravidla chování jsou v [PLAN.md](PLAN.md). Návrhy GUI v [design/](design/).

## Inspirace

Detekce HLS a práce s m3u8 vychází z myšlenek projektu [puemos/hls-downloader](https://github.com/puemos/hls-downloader) (MIT).
