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

#### Hotový obraz a Synology

Bez GitHub Actions se obraz sestavuje ručně na vývojovém počítači a posílá do soukromého registru
GitHub Container Registry (`ghcr.io/iamjk78/viddown`). Obsahuje `linux/amd64` (Synology s Intel/AMD) i `linux/arm64`.

```bash
docker login ghcr.io -u iamjk78      # jednorázově; heslo = osobní token se scope write:packages
scripts/release.sh                   # sestaví a nahraje :<verze> a :latest (--dry-run = jen sestavit)
```

Na NAS použijte [docker-compose.synology.yml](docker-compose.synology.yml) (Container Manager › Projekt, nebo SSH).
Upravte `PUID`/`PGID` a cesty svazků, jednou se přihlaste `docker login ghcr.io` (token se scope `read:packages`) a spusťte.
**Aktualizace:** `docker compose -f docker-compose.synology.yml pull && docker compose -f docker-compose.synology.yml up -d`.
Data (`/data`) leží mimo obraz, takže se zachovají; databáze se při startu sama upgraduje (viz níže).

**Přesun existující instalace (např. z Macu) na Synology:**

1. Na starém počítači zastavte VidDown (`docker compose down`) – Telegram bot smí běžet jen na jednom místě.
2. Zkopírujte složku `data` na NAS (např. `/volume1/docker/viddown/data`), **bez** podsložek `engines/`, `tmp/` a `ms-playwright/`
   (jsou pro jinou architekturu procesoru; na NAS se samy znovu stáhnou při prvním spuštění).
3. Spusťte projekt. V GUI (Nastavení › Cílová složka) zadejte novou cestu, např. `/downloads`.
4. Přepište cesty stažených souborů v historii, ať se videa nehlásí jako smazaná:

   ```bash
   docker exec viddown viddown db remap-paths /nas/Videos /downloads --dry-run
   docker exec viddown viddown db remap-paths /nas/Videos /downloads
   ```
5. Token Telegram bota, cookies, nastavení a seznam už stažených videí (`archive.txt`) se přenesou s složkou `data`.

**Migrace databáze:** verze schématu je v databázi (`pragma user_version`). Při startu se chybějící migrace provedou
automaticky a před tím se uloží záloha `viddown.db.v<stará verze>.bak` vedle databáze. Databázi z novější verze VidDown
starší verze odmítne otevřít (chrání před poškozením při downgradu). Stav ukáže `viddown db info` a `viddown doctor`.

**Aktualizace kódu bez nového obrazu** (zatím z terminálu):

- Vydání: zvyšte verzi v `src/viddown/__init__.py`, commitněte, pushněte a spusťte `scripts/release.sh`. Vedle obrazu vytvoří
  na GitHubu vydání `v<verze>` s archivem kódu a manifestem (`scripts/release.sh --app-only` jen sestaví archiv).
  Při změně závislostí nebo Dockerfile zvyšte `IMAGE_API` v `src/viddown/bootstrap.py`.
- Na straně aplikace: `docker exec viddown viddown app check` ukáže, zda je novější verze; `viddown app update` ji stáhne,
  ověří, otestuje a připraví; po restartu aplikace (nebo kontejneru) poběží. Nová verze má zkušební dobu a při potížích se sama
  vrátí na předchozí a vadná se přeskočí. Stav ukáže `viddown app status`.
- Soukromý repozitář vyžaduje GitHub token jen pro čtení (Contents: read): `docker exec -it viddown viddown app token`
  (nebo proměnná `VIDDOWN_APP_UPDATE_TOKEN`). Repozitář je v nastavení `app_update_repo`.

**Záloha a obnova (export a import):**

- V GUI: Nastavení › Záloha a obnova. „Stáhnout zálohu“ uloží šifrovaný soubor `VidDown_<datum>_<čas>.dtb`, „Vybrat zálohu…“ nahraje zálohu k obnovení (`.dtb` i ZIP).
  Obnova se provede při restartu aplikace; před ní se dosavadní stav uloží do `restore/before-<čas>/` v datové složce (poslední 3).
  Při přesunu na jiný stroj lze zadat „staré → nové“ cesty, které se přepíšou v historii, odběrech i nastavení.
- V terminálu: `viddown backup [soubor.dtb] [--thumbs] [--plain]` a `viddown restore soubor.dtb [--remap STARÁ NOVÁ]`.
  V Dockeru: `docker exec viddown viddown backup /data/zaloha.zip` (soubor je pak v datové složce na hostiteli).
  Když aplikace běží, `restore` obnovu jen připraví a provede se při jejím dalším startu.
- Záloha obsahuje databázi (konzistentní snapshot i za běhu), `settings.json`, `secrets.json` (heslo, token bota), `cookies.txt`
  a `archive.txt`; volitelně náhledy. **Neobsahuje** enginy, logy a dočasné soubory. Obsahuje tajné údaje – ukládejte ji bezpečně.
  Soubor `.dtb` je šifrovaný AES-256-GCM **klíčem zabudovaným v aplikaci**: otevře ho jen VidDown a na jakémkoli stroji, bez hesla.
  Je to ochrana před náhodným nahlédnutím, ne před někým, kdo má kopii aplikace (klíč je v jejím kódu), proto kód ani obraz nezveřejňujte.
  `--plain` (v GUI „bez šifrování“) uloží obyčejný ZIP.
- Záloha z novější verze, než kterou používáte, se odmítne (nejdřív aktualizujte aplikaci).
- **Automatické zálohy:** Nastavení › Záloha a obnova. Zapnete přepínač, zvolíte jak často (6 h, 12 h, 1 den, 3 dny, 1 týden),
  složku a kolik záloh uchovat. Po zapnutí se první záloha vytvoří hned, další podle intervalu. Nová záloha se po vytvoření ověří
  a teprve potom se smažou nejstarší nad zadaný počet (maže se jen to, co se jmenuje `VidDown_<datum>_<čas>.dtb`).
  Selže-li záloha (např. nepřipojený NAS), nic se nemaže, po hodině se to zkusí znovu a při selhání přijde zpráva do Telegramu
  (nejvýš jednou denně). Zálohy ve složce jsou v GUI vidět s tlačítkem „Obnovit“.
  Prázdná složka = `backups` v datové složce; proti ztrátě disku zvolte jiné místo. V Dockeru musí být složka připojená jako
  svazek (viz zakomentovaný příklad `/backups` v compose souborech).

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
