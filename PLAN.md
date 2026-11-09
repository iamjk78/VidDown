# VidDown – plán

Stav: **plánování**. Vývoj se zatím nezačal. Tento dokument shrnuje potvrzené požadavky, pravidla chování a návrh.

## 1. Cíl

Aplikace pro Windows, macOS a Docker. Uživatel zadá URL stránky, videa, playlistu nebo kanálu. Aplikace najde video a stáhne ho do nastavené složky. Ovládá se třemi způsoby: terminál (CLI), webové GUI a Telegram bot.

## 2. Stahování

### Funkce
- Vstup: URL videa, playlistu, kanálu nebo stránky s videem (i více URL najednou).
- Playlist nebo kanál: stáhne se **celý obsah**. Rozbalí se na samostatné položky fronty seskupené pod rodičovskou položkou.
- **Kanál**: ve výchozím stavu jen záložka **Videa**. Shorts a Živé přenosy jsou volitelné v nastavení.
- Výchozí kvalita: **maximální** (nejvyšší rozlišení a datový tok). Kontejner MKV, pokud se kodeky nevejdou do MP4.
- V nastavení lze přepnout na režim **Kompatibilita** (přednostně MP4/H.264 a AAC).
- Volitelně: výběr kvality před stažením, seznam playlistu k odškrtnutí, jen audio (MP3/M4A), titulky.
- Volitelně metadata: náhledový obrázek, kapitoly a popis vložené do souboru.
- YouTube jde přes yt-dlp (vyžaduje Deno, viz kap. 7).

### Metody a fallback
1. **yt-dlp** (výchozí první).
2. **HLS sniffer**: headless Chromium (Playwright) odposlouchává odpovědi stránky (`.m3u8`, MIME typy HLS, přímé video). ffmpeg pak stahuje a spojuje (`-c copy`). Pořadí metod jde změnit v nastavení.

**Kdy přejít na další metodu**
- **Přepnout:** "Unsupported URL", video na stránce nenalezeno.
- **Nepřepínat, rovnou chyba:** soukromé nebo smazané video, vyžadováno přihlášení, geoblokace, DRM.
- Před pokusem další metodou se smažou rozpracované soubory z předchozí.

### Pravidla
- **Práh velikosti playlistu/kanálu** (výchozí 50 videí) platí ve **všech** rozhraních. Nad ním se vyžaduje potvrzení (GUI dialog, tlačítka v Telegramu, `--yes` v CLI).
- **Živé přenosy:** probíhající přenos se přeskočí s hlášením. Nahrávání od začátku je volba v nastavení.
- **Duplicity:**
  - stejná URL se nepřidá do fronty dvakrát, pokud tam už čeká nebo běží,
  - archiv stažených ID (`--download-archive`) zabrání opakovanému stažení. Opakované vložení kanálu stáhne jen nová videa,
  - existující soubor se nepřepíše, přidá se přípona `(2)`, `(3)`…
- **Dočasná složka:** rozpracované soubory jsou mimo cílovou složku a přesunou se tam až po dokončení.
- **Bezpečné názvy souborů:** odstranění znaků zakázaných na Windows, dodržení limitu délky cesty (260 znaků), diakritika zůstává.
- **Pauzy u hromadného stahování:** mezi videi z kanálu či playlistu náhodná prodleva (výchozí 5–15 s) proti zablokování.
- **Místo na disku:** kontrola před stažením i průběžně. Pod nastaveným minimem (výchozí 2 GB) se fronta pozastaví a ohlásí se chyba.

## 3. Fronta

- Stavy: čeká, kontroluje se, stahuje se, pozastaveno, hotovo, chyba, zrušeno.
- Průběh v procentech, rychlost, zbývající čas.
- Akce: zrušit, opakovat, odstranit, změnit pořadí a prioritu, pozastavit položku i celou frontu.
- **Počet souběžných stahování** se nastavuje v GUI a platí za chodu.
- **Zrušení** smaže rozpracované soubory. **Pauza** je ponechá a umožní pokračovat.
- **Po pádu nebo restartu** se rozběhnuté úlohy vrátí do fronty a navážou.
- **Automatické opakování** neúspěšné úlohy: 2 pokusy s prodlevou 1 min a 5 min, potom stav chyba. Neplatí pro chyby, kde opakování nemá smysl (soukromé video, DRM, …).
- **Limit rychlosti** je celkový a dělí se mezi běžící stahování.
- **Plánování (časové okno):** po skončení okna se běžící stahování pozastaví a v dalším okně naváže. yt-dlp umí navázat, sniffer (ffmpeg) začne znovu.

## 4. Historie

- Dokončené a neúspěšné položky s datem, metodou, velikostí, cestou a chybou.
- Akce: otevřít soubor nebo složku, znovu stáhnout, hledat, smazat záznam.
- Smazání záznamu **nesmaže** soubor.
- Doba uchování historie je nastavitelná (výchozí neomezeně).

## 5. Nastavení (v GUI, sdílené s CLI)

- Cílová složka, dočasná složka, minimum volného místa.
- Počet souběžných stahování.
- Kvalita: Maximální / Kompatibilita. Výstupní formát pro jen audio.
- Omezení rychlosti (zapnout/vypnout, hodnota).
- Plánování: časové okno pro stahování.
- **Pojmenování souborů** (šablona), např. `{kanál}_{název}` u kanálů.
- **Samostatná složka** pro videa z kanálu nebo playlistu, pojmenovaná podle kanálu nebo playlistu (zapnout/vypnout zvlášť).
- Obsah kanálu: Videa / Shorts / Živé přenosy.
- Práh velikosti playlistu, pauzy mezi videi, počet opakování, pořadí metod.
- Titulky (jazyky, automatické titulky), metadata.
- Cookies (import z prohlížeče nebo `cookies.txt`), proxy.
- Heslo do GUI, přístup ze sítě (zapnout/vypnout).
- Telegram: token, povolené chat ID, chování po kontrole URL.
- Enginy: automatické aktualizace a interval, počet uchovaných verzí.
- Jazyk rozhraní: čeština / angličtina.
- Úroveň podrobnosti logů.
- Export a import nastavení (bez citlivých údajů, pokud je výslovně nezahrnete).

**Pořadí platnosti:** proměnná prostředí (Docker) má přednost před nastavením z GUI. Taková položka je v GUI zamčená s vysvětlením.

## 6. Telegram bot

- **Samostatný bot** pro VidDown (jiný token než bot pro ComfyUI, jinak by se oba rušily).
- Long polling, nepotřebuje veřejnou adresu.
- Smí ho používat **jen jedno povolené chat ID**. Ostatním neodpovídá.
- Token a chat ID se zadávají v GUI nebo proměnnou prostředí.
- Bot vytáhne ze zprávy všechny URL. Na zprávu bez URL odpoví krátkou nápovědou.
- Po odeslání URL proběhne **kontrola (probe) v samostatném vlákně**:
  - nezabírá sloty souběžných stahování, má vlastní limit (výchozí 2),
  - bot hned odpoví "Zjišťuji…" a zprávu pak upraví na výsledek,
  - výsledek: počet nalezených videí a rozlišení prvního, ve kterém se bude stahovat,
  - u snifferu je počet jen odhad, bot to uvede,
  - u DRM obsahu napíše, že ho nelze stáhnout,
  - výsledek se uloží a stahování ho znovu nezjišťuje.
- Chování po kontrole je v nastavení: **výchozí je stáhnout hned**, druhá volba je dotaz s tlačítky.
- Nad prahem velikosti playlistu (výchozí 50) se bot vždy zeptá tlačítky.
- **Oznámení: jen chyby.**
  - Kontrolní odpověď po URL se posílá vždy a za oznámení se nepočítá.
  - Chyby jednoho playlistu se sloučí do jedné souhrnné zprávy na konci.
  - Hlásí se i selhaná aktualizace enginu a automatický návrat na předchozí verzi.
- Příkazy: `/fronta`, `/historie`, `/zrusit <id>`, `/znovu <id>`, `/pauza`, `/pokracovat`, `/soubeh <n>`, `/engine`, `/aktualizovat`.
- Soubory se do Telegramu neposílají (limit Bot API 50 MB). Bot hlásí jen cestu k souboru.

## 7. Enginy a aktualizace

Verzované enginy s testem a návratem: **yt-dlp**, **Deno** (JS runtime pro YouTube), **ffmpeg**.

- Používají se **samostatné binárky** pro danou platformu (Windows, macOS, Linux), ne pip. Funguje to i v zabalené aplikaci.
- ffmpeg je **přibalený** k aplikaci a aktualizuje se stejně jako ostatní enginy.
- Každá verze je ve vlastní složce (`<data>/engines/<engine>/<verze>/`) a ukazatel `current` určuje aktivní.
- Postup aktualizace:
  1. stáhnout novou verzi vedle staré,
  2. otestovat novou i starou verzi,
  3. přepnout jen když nová projde,
  4. selžou-li obě, je to síť nebo web: nic se nepřepne,
  5. selže-li jen nová, smaže se a zůstane stará.
- Testy:
  - yt-dlp: `--version` a načtení metadat testovací URL bez stahování (testovací URL je nastavitelná),
  - Deno: `--version` a test v rámci testu yt-dlp na YouTube,
  - ffmpeg: `-version` a spojení přibaleného krátkého vzorku.
- Uchovává se posledních N verzí (výchozí 3). Ruční návrat: `viddown engine rollback <engine>` a tlačítko v GUI.
- Aktivní stahování doběhnou na staré verzi.
- Aktualizace ručně nebo automaticky v intervalu.
- **Chromium** se neaktualizuje zvlášť. Je svázané s verzí Playwright a aktualizuje se spolu s aplikací.

## 8. Architektura

Python, jedna aplikace. Žádná závislost na Node.js.

```
src/viddown/
  config.py      nastavení (settings.json) + citlivé údaje zvlášť
  db.py          SQLite: fronta, historie, archiv stažených ID
  engines.py     správce verzí yt-dlp, Deno, ffmpeg
  resolvers/     yt-dlp, sniffer, probe
  runner.py      fronta, souběžnost, fallback, plánování, limit rychlosti
  daemon.py      démon: runner + server + Telegram
  cli.py         příkazy
  server/        FastAPI, živý průběh (SSE), webové GUI
  telegram/      bot nad stejnou frontou a databází
  i18n/          čeština, angličtina
```

- **Jeden démon:** frontu zpracovává jen jeden proces (runner + server + Telegram). Zámek brání spuštění druhé instance.
- **CLI** se připojí k běžícímu démonovi přes API. Když démon neběží, CLI ho spustí, nebo frontu zpracuje samo pod stejným zámkem.
- **Autostart:** LaunchAgent na macOS, spuštění po přihlášení nebo služba na Windows, `restart: unless-stopped` v Dockeru. Bez toho by Telegram nefungoval.
- yt-dlp se spouští jako **samostatný proces** z verzované složky. Průběh se čte přes `--progress-template`, metadata přes `--dump-json`.
- Data (databáze, nastavení, enginy, logy) jsou v datové složce (`VIDDOWN_DATA`, výchozí `~/.viddown`, v Dockeru `/data`).

## 9. GUI (webové)

- Světlý a tmavý režim, jazyk čeština / angličtina s možností přepnutí.
- Záložky: **Fronta**, **Historie**, **Nastavení**, **Enginy**.
- Živý průběh bez ručního obnovování.
- Log každé úlohy je viditelný v detailu položky.
- V Dockeru a při vzdáleném přístupu se místo "Otevřít složku" nabízí stažení souboru přes prohlížeč.

```
┌──────────────────────────────────────────────────────────────┐
│ VidDown   [ Fronta ] Historie  Nastavení  Enginy     ⏸ Pauza │
├──────────────────────────────────────────────────────────────┤
│ [ Vložte URL videa, playlistu nebo kanálu...    ] [ Přidat ] │
├──────────────────────────────────────────────────────────────┤
│ Probíhá 2/2                                                  │
│ ▶ Me at the zoo            yt-dlp   ████████░░ 78%  2,1 MB/s │
│ ▶ Přednáška 3              sniffer  ███░░░░░░░ 31%  0,9 MB/s │
│ Čeká 5                                                       │
│ ⏳ Playlist: Kurz Python (12 videí)  ▸ rozbalit              │
│                                                              │
│ Volné místo: 84 GB          Cíl: ~/Downloads/VidDown         │
└──────────────────────────────────────────────────────────────┘
```

## 10. Bezpečnost

- GUI ve výchozím stavu poslouchá jen na `127.0.0.1`. Přístup ze sítě se zapíná vědomě a jen s heslem.
- Omezení počtu pokusů o přihlášení do GUI.
- Cookies, token bota a heslo jsou uložené zvlášť od běžného nastavení s omezenými právy souboru. V GUI se nezobrazují, jen přepisují.
- Telegram reaguje jen na povolené chat ID.

## 11. Logy a diagnostika

- Log každé úlohy (v GUI) a celkový log s rotací.
- Nastavitelná úroveň podrobnosti.
- `viddown doctor`: ověří ffmpeg, Deno, yt-dlp, Chromium, zapisovatelnost složek, volné místo a spojení s Telegramem.

## 12. Docker a platformy

- Docker: proměnné `TZ` (časové pásmo pro plánování), `PUID`/`PGID` (vlastník stažených souborů), svazky pro data a stažené soubory.
- Windows a macOS: aplikace zabalená (PyInstaller) včetně ffmpeg, Deno a Chromia. Samostatně se instaluje jen autostart.

## 13. Etapy a kritéria hotovosti

1. **Jádro a CLI**
   - nastavení, SQLite, správce enginů (yt-dlp, Deno, ffmpeg), fallback, sniffer, probe, fronta, pravidla z kap. 2 a 3, `viddown doctor`
   - Hotovo, když: z CLI se stáhne video, playlist i kanál z YouTube, HLS video z testovací stránky přes sniffer, funguje aktualizace a návrat enginu a fronta přežije restart.
2. **Démon, server a webové GUI**
   - fronta, historie, nastavení, enginy, heslo, CZ/EN, autostart
   - Hotovo, když: vše z etapy 1 jde ovládat z GUI, změna nastavení platí za chodu a GUI je chráněné heslem.
3. **Telegram bot**
   - probe, příkazy, oznámení chyb
   - Hotovo, když: URL poslaná přes Telegram vrátí počet videí a rozlišení, stáhne se a chyba přijde jako zpráva.
4. **Docker a balíčky pro Windows a macOS**
   - Hotovo, když: aplikace se nainstaluje a běží na čistém Windows, macOS i v Dockeru.

**Testy a CI:** jednotkové testy, lokální testovací HLS server pro sniffer, GitHub Actions na Windows, macOS a Linuxu.

## 14. Omezení

- DRM (Widevine, FairPlay) se neobchází.
- Sniffer nenajde vždy spolehlivě video, které se spustí až po kliknutí.
- Stránky s přihlášením nebo ochranou proti botům vyžadují cookies.
- Používejte jen pro obsah, ke kterému máte práva.

## 15. Otevřené body

- Přesná syntaxe šablony pojmenování a výchozí hodnoty.
- Způsob zadání časového okna (jedno okno, nebo víc oken podle dne).
- Zdroje binárek ffmpeg a Deno pro jednotlivé platformy a licence přibaleného ffmpeg (GPL/LGPL build).
- Soubory z předchozího rozpracování (`pyproject.toml`, `src/viddown/config.py`, `db.py`, `__init__.py`, `__main__.py`) zatím leží ve složce necommitnuté. Rozhodne se, zda je ponechat, nebo smazat.

## 16. Inspirace

Myšlenky z projektu [puemos/hls-downloader](https://github.com/puemos/hls-downloader) (MIT): detekce HLS playlistů, parsování m3u8, fragmenty, AES-128, spojování.
