# VidDown – plán

Stav: **etapy 1–4 implementovány** (listopad 2026), odběry a statistiky (kap. 17) rozpracovány – hotové etapy 1 a 2. Tento dokument shrnuje potvrzené požadavky, pravidla chování a návrh. Odchylky a doplňky z vývoje jsou v kapitole 17.

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
- Miniatura se vždy ukládá vedle videa jako JPG se stejným názvem (viz kap. 9).
- Volitelně metadata: náhledový obrázek, kapitoly a popis vložené přímo do souboru videa.
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
- **Pauzy u hromadného stahování:** mezi videi z kanálu či playlistu náhodná prodleva (výchozí 5–15 s) proti zablokování. Platí pro každý souběžný slot zvlášť (najednou se rozjede až tolik videí, kolik je souběžných stahování), takže nesnižuje nastavenou souběžnost.
- **Místo na disku:** kontrola před stažením i průběžně. Pod nastaveným minimem (výchozí 2 GB) se fronta pozastaví a ohlásí se chyba.

## 3. Fronta

### Pořadí
- Aplikace má **jednu frontu**. Úlohy se spouštějí postupně **v pořadí přidání** (FIFO), bez ohledu na to, odkud přišly (GUI, CLI, Telegram).
- Žádné priority. Pořadí mění jen uživatel ručně v GUI.
- **Počet souběžných stahování** (nastavení v GUI, platí za chodu) určuje, kolik úloh z čela fronty běží najednou. Při hodnotě 1 se stahuje přísně jedna po druhé.
- Videa z playlistu nebo kanálu zaberou ve frontě místo své rodičovské položky a zachovají pořadí z playlistu.

### Zásahy do fronty (pouze v GUI)
- Jen v GUI lze:
  - **změnit pořadí** úloh (přetažením),
  - **odstranit** úlohu z fronty,
  - **pozastavit** úlohu.
- CLI a Telegram umí do fronty jen **přidávat** a **zobrazovat** ji.
- **Pozastavená úloha** zůstává na svém místě a při výběru další úlohy se **přeskakuje**, dokud ji uživatel v GUI znovu nepovolí.
- Pozastavení běžící úlohy přeruší stahování. Rozpracované soubory zůstanou a po povolení stahování naváže.
- Pozastavení rodičovské položky playlistu platí pro všechna její dosud nestažená videa.
- Odstranění úlohy smaže rozpracované soubory. Do historie se zapíše jako zrušená.

### Stavy a průběh
- Stavy: čeká, kontroluje se, stahuje se, pozastaveno, hotovo, chyba, zrušeno.
- Průběh v procentech, rychlost, zbývající čas.

### Chyby a obnova
- **Po pádu nebo restartu** se rozběhnuté úlohy vrátí do fronty na své místo a navážou.
- **Automatické opakování** neúspěšné úlohy: 2 pokusy s prodlevou 1 min a 5 min, potom stav chyba. Úloha při tom zůstává na svém místě ve frontě. Neplatí pro chyby, kde opakování nemá smysl (soukromé video, DRM, …).
- **Limit rychlosti** je celkový a dělí se mezi běžící stahování.
- **Plánování (časové okno):** po skončení okna se běžící stahování pozastaví a v dalším okně naváže. yt-dlp umí navázat, sniffer (ffmpeg) začne znovu.

## 4. Historie

- Dokončené a neúspěšné položky s datem, metodou, velikostí, cestou a chybou.
- Akce: otevřít soubor nebo složku, znovu stáhnout, hledat, smazat záznam.
- Smazání záznamu **nesmaže** soubor.
- **Stránkování** historie s volbou počtu záznamů na stránku (25 / 50 / 100 / 200, pamatuje se v prohlížeči).
- **Přehrávání** staženého videa přímo v GUI (okno s přehrávačem, přetáčení přes HTTP Range); když prohlížeč formát neumí (např. MKV s AV1/VP9 v Safari), nabídne stažení souboru.
- Ručně smazaný soubor historie pozná (štítek **Soubor smazán**). **Stáhnout znovu** video vyřadí z archivu yt-dlp a zařadí do fronty. Opakované vložení kanálu dál přeskočí všechna kdy stažená videa, i smazaná.
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
- Příkazy: `/fronta`, `/historie`, `/engine`, `/aktualizovat`.
- Bot frontu nemění: nemůže měnit pořadí, odstraňovat ani pozastavovat úlohy ani měnit počet souběžných stahování. To jde jen v GUI.
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

**Zvolená varianta: B – postranní panel a přehled.** Vzor: `design/VidDown_navrhy_GUI.pdf`, strany 5–7 (zdroj `design/build_mockups.py`).

- **Postranní panel vlevo:** logo, navigace **Fronta** (s počtem položek), **Historie**, **Nastavení**, **Enginy**. Dole stav disku (volné místo, cílová složka), stav Telegram bota, přepínač tmavého režimu, verze aplikace a jazyk.
- **Fronta:**
  - nahoře nadpis, pole pro URL a tlačítko Přidat,
  - čtyři ukazatele: Probíhá (x / souběžnost), Ve frontě (počet, odhad velikosti, počet pozastavených), Rychlost (celkem a limit), Dnes staženo (počet, chyby, objem),
  - sekce **Právě se stahuje**: velké řádky s miniaturou, názvem, metodou, kanálem, zdrojem (GUI / Telegram / CLI), průběhem, rychlostí, zbývajícím časem a tlačítky Pozastavit / Odstranit,
  - sekce **Čeká ve frontě**: kompaktní řádky s úchytem pro přetažení, pořadím, miniaturou, metodou, odhadem velikosti a rozlišení. Playlist je jedna rozbalitelná položka. Pozastavená položka je zvýrazněná s tlačítkem Povolit.
- **Nastavení:** karty ve dvou sloupcích (Stahování, Pojmenování a složky, Rychlost a plánování, Přístup a síť, Telegram, Vzhled a jazyk). Změny se ukládají automaticky. Export a import nastavení.
- **Historie** a **Enginy** se v rámci varianty B zpracují ve stejném stylu (obsah podle stran 4 a 10 návrhů).
- Světlý a tmavý režim, jazyk čeština / angličtina s možností přepnutí.
- Živý průběh bez ručního obnovování.
- Log každé úlohy je viditelný v detailu položky.
- **Miniatury** u položek ve frontě i u právě stahovaných souborů:
  - yt-dlp: miniatura z metadat videa,
  - sniffer: `og:image` nebo `poster` přehrávače, jinak snímek z prvních sekund videa přes ffmpeg,
  - získávají se při kontrole URL (probe), která proto běží u **každé** nově přidané položky, nejen u Telegramu,
  - do jejich získání se zobrazí zástupný obrázek,
  - během čekání a stahování jsou v mezipaměti v datové složce a GUI je načítá lokálně, ne z cizích webů,
  - **po dokončení** se miniatura uloží jako **JPG se stejným názvem jako video do stejné složky** (`Název videa.mp4` a `Název videa.jpg`),
  - miniatura v plném rozlišení. Formáty jako WebP nebo PNG se převedou na JPG,
  - přípona proti přepsání `(2)`, `(3)`… platí pro video i miniaturu stejně,
  - u zrušené nebo neúspěšné úlohy se do cílové složky nic neuloží a miniatura z mezipaměti se smaže.
- V Dockeru a při vzdáleném přístupu se místo "Otevřít složku" nabízí stažení souboru přes prohlížeč.


### Nápověda a průvodce
- Sekce **Nápověda** v postranním panelu: co aplikace umí, přidávání videí, fronta, playlisty a kanály, pojmenování, plánování, cookies, Telegram, enginy, CLI, řešení problémů. Česky i anglicky.
- **Průvodce prvním spuštěním** (5 kroků): přehled funkcí, cílová složka a kvalita, souběžnost / limit / časové okno, Telegram (volitelně), shrnutí. Zobrazí se automaticky při prvním otevření GUI a jde ho spustit znovu z Nápovědy nebo z Nastavení.

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

**Testy:** jednotkové testy a lokální testovací HLS server pro sniffer, spouštěné lokálně (`pytest`). GitHub slouží jen jako úložiště repozitáře, **bez GitHub Actions**.

## 14. Omezení

- DRM (Widevine, FairPlay) se neobchází.
- Sniffer nenajde vždy spolehlivě video, které se spustí až po kliknutí.
- Stránky s přihlášením nebo ochranou proti botům vyžadují cookies.
- Používejte jen pro obsah, ke kterému máte práva.

## 15. Otevřené body (k 9. 11. 2026)

- Šablona: tokeny `{název} {kanál} {playlist} {datum} {rozlišení} {id} {pořadí}` (i anglicky). Výchozí `{název}`, u kanálu `{kanál}_{název}`.
- Časové okno: jedno okno (od–do, může přes půlnoc) + vybrané dny.
- Zdroje binárek ffmpeg a Deno pro jednotlivé platformy a licence přibaleného ffmpeg (GPL/LGPL build).
- Telegram bot ověřen jen testy s podvrženým API – ověřit se skutečným botem.
- Balíček pro Windows je potřeba sestavit a vyzkoušet na počítači s Windows (macOS balíček a Docker obraz ověřeny lokálně).

## 16. Odchylky a doplňky z vývoje

- **ffmpeg:** když je v systému novější ffmpeg než přibalený, používá se systémový. Přibalená verze se nainstaluje jen tam, kde žádný ffmpeg není (zabalená aplikace, Docker se starším ffmpeg), nebo když je novější.
- **Chromium** se v zabalené aplikaci stáhne automaticky při prvním spuštění. V Enginech je tlačítko „Nainstalovat / opravit prohlížeč“.
- **Chyba při fallbacku:** když selže yt-dlp i sniffer, zobrazí se chyby obou metod. O opakování rozhoduje chyba hlavní metody.
- **Telegram:** bot frontu nemění (pořadí, pauzy, odstranění, souběžnost jen v GUI). Příkazy: `/fronta`, `/historie`, `/engine`, `/aktualizovat`, `/pomoc`. Kdo napíše z cizího chatu, dostane jen své chat ID (pro nastavení).
- **Zrušení vs. vypnutí:** zrušení má vždy přednost; úlohy ve stavu „ruší se“ se po restartu dokončí a osiřelé dočasné složky se uklidí.
- **Pauza během načítání metadat** se projeví před spuštěním stahování (stahování se vůbec nespustí).
- **Cílová složka** jde měnit v GUI i v Dockeru (kvůli nasazení na Synology). Při uložení se ověří zápis (zkušební vytvoření a smazání složky), v Dockeru navíc, že cesta leží na připojeném svazku; jinak se uložení odmítne s vysvětlením. Za provozu se dostupnost kontroluje každých 20 s: při nedostupnosti se fronta pozastaví a po obnovení sama pokračuje; hotové video čeká v dočasné složce na přesun.
- **Volné místo:** hlídá se dočasná složka (rozpracovaná stahování) i cílová složka. Docker Desktop na macOS u složek z `/Volumes` (síťové disky) hlásí místo interního disku Macu – takový údaj se nezobrazuje („nelze zjistit“) a do kontroly minima se nepočítá. Na Synology s nativním Dockerem je údaj správný.
- **Cookies z prohlížeče** čte yt-dlp z profilu prohlížeče na počítači, kde VidDown běží – v Dockeru proto tato volba není (uložení se odmítne) a používá se nahraný `cookies.txt`. Chyba načtení cookies pozastaví frontu (úlohy zůstanou ve frontě) místo toho, aby postupně selhaly všechny.
- **Sniffer a limit rychlosti:** limit rychlosti platí jen pro yt-dlp (ffmpeg ho neumí).
- **Licence přibaleného ffmpeg** (GPL build z eugeneware/ffmpeg-static) – při veřejné distribuci balíčků je potřeba přiložit licenci a odkaz na zdrojový kód.

## 17. Odběry a Statistiky (návrh, zatím neimplementováno)

### 17.1 Odběry

**Co to je.** Nové menu **Odběry**. Odběr = URL kanálu (nebo playlistu) + složka + datum „od kdy“. Aplikace sama pravidelně hledá nová videa a řadí je do běžné fronty. Odběry se zakládají a upravují **jen v GUI** (CLI a Telegram je neumí).

**Nastavení odběru** (dialog „Přidat odběr“, po zadání URL se zobrazí název, miniatura a počet nalezených videí):
- **URL kanálu / playlistu** (cokoli, co yt-dlp vypíše jako seznam; YouTube kanál se bere po záložkách videa/shorts/živě podle globálního nastavení, u odběru jde přepsat).
- **Složka pro tento odběr** – absolutní cesta, při uložení se ověří zápis stejně jako u cílové složky; výchozí `<cílová složka>/<kanál>`.
- **Stahovat od data** – předvolby „jen nové od teď“, „od minulého měsíce“, „od data…“ (kalendář), „vše“. Starší videa se nikdy nestáhnou; nová od data až po budoucí ano.
- Zapnuto/pozastaveno. Kontrola hned tlačítkem „Zkontrolovat teď“.
- Kvalita, šablona názvu a ostatní volby se berou z globálního nastavení (v první verzi bez přepsání).

**Kontrola nových videí.**
- Interval globálně v Nastavení (výchozí 6 h), běží jen když fronta není pozastavená; odběry se kontrolují postupně (žádná dávka dotazů najednou), při HTTP 429 se kontrola odloží.
- Postup: seznam od nejnovějších (`--flat-playlist`), u neznámých ID se zjistí datum nahrání; čtení se zastaví u prvního videa starší než „od data“. Přeskakují se videa v `archive.txt`, videa už vedená v databázi, živá vysílání a premiéry (stáhnou se při dalším kontrolním běhu, až skončí).
- Nová videa se zařadí na konec fronty jako běžné úlohy se zdrojem „odběr“ (bez potvrzování); při **první** kontrole se nad prahem (výchozí 50 videí) zeptá, jako u playlistů.
- Chyba kontroly (kanál smazán, vyžaduje přihlášení…) se zobrazí u odběru a odběr se nezastaví; kontrola se zopakuje při dalším běhu.

**Podmenu a historie.** V bočním panelu je pod položkou Odběry seznam odběrů; každý má vlastní stránku se záložkami **Fronta**, **Historie**, **Nastavení**. Stránka Odběry (přehled) ukazuje karty: miniatura, název, počet nových videí, poslední kontrola, stav.
- **Fronta** odběru = běžná fronta vyfiltrovaná na odběr (pořadí, pauza, odstranění fungují stejně).
- **Historie** odběru = stejný seznam jako globální historie (stránkování, hledání, přehrávání, hromadný výběr), jen s filtrem na odběr.
- **Jedna úloha, dva pohledy:** záznam je v databázi jednou (`jobs.sub_id`). Odstranění z historie se zeptá, odkud: **jen z historie odběru**, **jen z celkové historie**, nebo **z obou** (hromadný výběr včetně volby „odstranit i z archivu stažených“). Technicky dva příznaky skrytí (`hide_sub`, `hide_global`); záznam se fyzicky smaže, až když je skrytý z obou míst, nebo při volbě „z obou“.
- Smazání odběru: dotaz, jestli zachovat stažené záznamy v celkové historii (výchozí) nebo je odstranit; stažené soubory se nikdy nemažou.

### 17.2 Statistiky

Nové menu **Statistiky** s přepínačem období: 24 h, 7 dní, 30 dní, 12 měsíců, vše, vlastní rozsah (od–do).
- **Přehled:** počet stažených videí, objem dat, průměr za den, úspěšnost (hotovo / chyba), celkový čas stahování.
- **Grafy:** sloupce po dnech (týdnech u delších období) s přepínačem počet / objem; **podle kanálu** (nejvíc stahované), **podle zdroje** (GUI, CLI, Telegram, odběr), **podle metody** (yt-dlp / sniffer), **podle webu**.
- Tabulka kanálů s počtem a objemem; klik na kanál otevře jeho odběr nebo vyhledá v historii.
- **Statistiky nezávisí na historii:** při dokončení každého stažení se zapíše řádek do samostatné tabulky `downloads` (datum, kanál, web, zdroj, metoda, velikost, doba, odběr). Smazání historie ani odstranění záznamů statistiky nemění. Při zavedení se tabulka jednorázově naplní z dosavadních hotových úloh. Tlačítko „Vynulovat statistiky“ s potvrzením.

### 17.3 Technické změny

- **Verzované migrace databáze** (`pragma user_version`) – nutné před první změnou schématu; stávající databáze se upgraduje beze ztráty dat.
- Nové tabulky `subscriptions` (id, url, název, miniatura, složka, od data, záložky, zapnuto, poslední kontrola, poslední chyba, vytvořeno) a `downloads` (viz výše); nové sloupce `jobs.sub_id`, `jobs.hide_sub`, `jobs.hide_global`.
- Rozhraní: `/api/subscriptions` (seznam, vytvoření s kontrolou URL a složky, úprava, smazání, „zkontrolovat teď“), `/api/history?sub=ID`, `/api/stats?from=&to=&group=`.
- Kontrola odběrů je součást smyčky runneru (jako automatická aktualizace enginů), ne samostatný proces.
- Testy: kontrola nových videí s podvrženým yt-dlp (datum, archiv, deduplikace, živé přenosy), semantika skrytí/smazání z historií, agregace statistik, migrace.

### 17.4 Etapy

1. ✅ **Hotovo (11. 2026):** migrace databáze + `subscriptions` + kontrola nových videí + API (bez GUI) + testy. Ověřeno na skutečném YouTube kanálu (název a miniatura při zakládání, výběr videí podle data, vlastní cílová složka). Podrobnosti:
   - Migrace: schéma verze 2 (`subscriptions`, `jobs.sub_id`, `jobs.target_dir`); před migrací se uloží záloha `viddown.db.v<verze>.bak`. Příznaky skrytí historie (`hide_sub`, `hide_global`) přijdou s etapou 3, tabulka `downloads` s etapou 4.
   - Kontrola: první kontrola vyhodnotí nejvýše 500 nejnovějších videí, další jen 60 nejnovějších. U kanálu se čtení zastaví u prvního videa staršího než „od data“ (jeho ID se zapamatuje v `seen_old`), u playlistu se projdou všechna. Videa bez data v seznamu se dohledají plným načtením (nejvýše 40 na kontrolu). Odběr bez omezení „od data“ (`since` = null) bere všechno.
   - Fronta pozastavená uživatelem nebo kvůli cookies kontroly odběrů zastaví; ruční „Zkontrolovat teď“ (`POST /api/subscriptions/{id}/check`) ji ignoruje.
   - První kontrola nad prahem potvrzení (50) nic nezařadí; videa čekají v `subscriptions.pending` a řeší se `POST …/confirm` nebo `…/reject`.
   - Úloha z odběru má `target_dir` (absolutní složka odběru; mění se i u čekajících úloh po úpravě odběru) a pro kanál se použije šablona názvu kanálu.
   - API: `GET/POST /api/subscriptions`, `GET/PUT/DELETE /api/subscriptions/{id}` (`?keep_history=false` smaže i záznamy), `POST …/check|confirm|reject`. Nastavení `subscription_check_hours` (výchozí 6, 0 = vypnuto) zatím jen v `settings.json` / `viddown config set`.
2. ✅ **Hotovo (11. 2026):** GUI Odběry – menu **Odběry** s kartami (stav, složka, od data, počty, poslední kontrola), stránka **Přidat odběr** (URL, složka s výběrem, „od data“, záložky kanálu), podmenu v bočním panelu a stránka odběru se záložkami **Fronta** / **Historie** / **Nastavení** (úprava, smazání s volbou zachovat / odstranit záznamy). Potvrzení první dávky nad prahem je přímo na kartě a v záhlaví odběru. Fronta a historie odběru jsou pohledy na stejné záznamy filtrované podle `sub_id` (`/api/history?sub=ID`, `sub` je i ve stavu `/api/state`). Odstranění z historie odběru zatím maže záznam úplně i z celkové historie – volba „z jedné / z obou“ je etapa 3. Interval kontroly je i v Nastavení › Stahování. Změna data „od“ zneplatní zapamatovaná starší videa (`seen_old`).
3. ✅ **Hotovo (11. 2026):** Dvojí historie – migrace 3 přidává `jobs.hide_sub` / `jobs.hide_global`. Odstranění „jen tady“ záznam skryje v zobrazené historii (celková / odběr); jakmile není vidět nikde (nebo nemá odběr), smaže se fyzicky. Volba „i z celkové historie“ / „i z historie odběrů“ (`scope: both`) maže hned. API: `DELETE /api/history` s `view` (id odběru, 0 = celková) a `scope` (`here`|`both`). Smazání odběru se zachováním historie odstraní záznamy skryté v celkové historii. Statistiky (etapa 4) se budou číst z vlastní tabulky, takže mazání historie je neovlivní.
4. ✅ **Hotovo (11. 2026):** Statistiky – migrace 4 vytváří tabulku `downloads` a jednorázově ji naplní z dosavadních hotových i chybných úloh; dál se řádek zapisuje při každém konečném dokončení nebo selhání (`Runner._finalize` / `_failed`). `GET /api/stats?t0&t1&tz&sub` (souhrn, řada po hodinách/dnech/měsících s doplněnými mezerami, žebříčky podle kanálu, zdroje, metody a webu), `DELETE /api/stats` vynuluje. GUI menu **Statistiky**: období 24 h / 7 d / 30 d / 12 m / vše / vlastní, čtyři KPI, graf s přepínačem počet/objem, žebříčky, tabulka kanálů (klik otevře odběr nebo hledání v historii), „Vynulovat statistiky“. Mazání historie statistiky nemění.

### 17.5 K potvrzení (navržené výchozí hodnoty)

- Interval kontroly globálně 6 h (bez nastavení u jednotlivého odběru).
- Odběr funguje pro kanály i playlisty z libovolného webu, který yt-dlp umí vypsat; první verze testována na YouTube.
- Shorts a živé záložky se u odběru výchozí vypnuté (jen „videa“).
- Kvalita a šablona názvu zůstávají globální.

## 18. Aktualizace aplikace zevnitř (schváleno 13. 11. 2026, varianta A)

Kód aplikace se aktualizuje bez nového Docker obrazu: `<data>/app/<verze>/` (balíček `viddown`, čistý Python), spouštěč `bootstrap.py` vybere aktivní verzi a spustí ji novým procesem (`execve`, `PYTHONPATH` na verzi). Verze zabudovaná v obraze je záloha („baseline“). Windows ani macOS aplikace (PyInstaller) se dělat nebudou; cílem je Docker (Synology), na Macu jen vývoj.

Pravidla:
- **Vrstvy:** obraz (Python, ffmpeg, Chromium, závislosti), kód aplikace (aktualizuje se zevnitř), enginy (už mají vlastní aktualizace).
- **`IMAGE_API`** (`bootstrap.py`) se zvýší při změně závislostí (`pyproject.toml`) nebo Dockerfile. Vydání nese `requires_image_api`; vyžaduje-li víc, než obraz umí, nainstaluje se až po `pull` nového obrazu.
- **Samotest** před přepnutím běží v odděleném procesu nad **kopií** databáze: verze, import všech modulů, migrace a kontrola integrity, `/api/session` a `/api/state`, `ffmpeg` a `yt-dlp`. Selže-li, verze se označí jako přeskočená.
- **Zkušební doba:** po přepnutí musí nová verze běžet 120 s (`HEALTHY_AFTER`), jinak se při dvou nezdravých startech za sebou (`MAX_FAILED_STARTS`) automaticky vrátí předchozí verze a vadná se přeskočí. Řádné ukončení (ruční restart) se do počtu nezapočítává; příkazy mimo `serve` také ne.
- **Databáze:** před přepnutím se uloží záloha (`<data>/app/db-before-<verze>.sqlite`). Starší kód odmítne novější schéma (`SchemaTooNew`), proto automatický návrat po migraci **obnoví zálohu** (poškozená databáze zůstane jako `viddown.db.failed-<verze>`). Ruční návrat to udělá jen s `--restore-db`.
- **Migrace jsou jen přidávací** (nové sloupce a tabulky, nic se nemaže ani nepřejmenovává); hlídá to test.
- Je-li obraz stejně nový nebo novější než nainstalovaná verze (po `pull`), nainstalovaná verze se zahodí.
- Ověřuje se `sha256` archivu, rozbalení je bezpečné (žádné cesty ven, odkazy, limity velikosti). Zdroj aktualizací je jen nastavené soukromé repozitář, token jen pro čtení v `secrets.json`.

Etapy: **1** spouštěč, správa verzí, samotest, návrat a databáze (hotovo: `appupdate.py`, `bootstrap.py`, `selftest.py`, `viddown app …`); **2** kontrola a stažení z GitHub Release a rozšíření `scripts/release.sh` (hotovo, viz níže); **3** GUI (Nastavení, banner), Telegram, automatický režim (hotovo, viz níže; výchozí je oznámit s tlačítkem); **4** dokumentace a ostrá zkouška v Dockeru před Synology (hotovo, viz níže). Návrh s obrázky: `design/VidDown_plan_aktualizace.pdf`.

Etapa 2 (hotovo): `release.sh` vedle obrazu sestaví `viddown-<verze>.zip` a `manifest.json` (verze, `sha256`, `requires_image_api`, schéma databáze, commit) a vytvoří GitHub Release `v<verze>` přes `gh` (před dlouhým sestavováním ověří přihlášení `gh`, že commit je na GitHubu a že vydání ještě neexistuje; upozorní, když se změnily závislosti a nezvýšilo se `IMAGE_API`). Aplikace (`viddown app check|update|token`) se ptá `GET /repos/<repo>/releases/latest` (repozitář v `app_update_repo`, token jen pro čtení v `secrets.json` nebo `VIDDOWN_APP_UPDATE_TOKEN`), stáhne manifest a archiv, ověří `sha256` a velikost, rozbalí, spustí samotest a až potom přepne (po restartu). Token se posílá jen na GitHub API; při přesměrování na úložiště souborů se zahodí. Chyba sítě nic nemění; vadná verze se odstraní a přeskočí (`--force` ji zkusí znovu); vydání vyžadující vyšší `IMAGE_API` se nenainstaluje. Zatím nezkoušeno proti skutečnému GitHubu (až při prvním vydání).

Etapa 3 (hotovo, `updater.py`): nastavení `app_update_mode` (`off` / `notify` výchozí / `auto`), `app_update_hours` (6/12/24/72/168 h), `app_update_repo`, token v `secrets.json`. Smyčka na pozadí (jednou za minutu) kontroluje podle intervalu (po chybě za hodinu). **Oznámit:** GUI ukáže globální banner „Je k dispozici verze X“ s tlačítkem Aktualizovat a Telegram pošle zprávu jednou za verzi. **Automaticky:** stáhne, otestuje a připraví verzi, pak **měkce pozastaví frontu** (rozpracovaná stahování doběhnou, `kv update_resume`), počká (nejdéle 6 h; když uživatel frontu obnoví, restart se zruší) a restartuje; po startu se fronta, kterou jsme pozastavili my, obnoví. Připravená verze má banner „Restartovat po doběhnutí stahování / hned“. Banner „verze X nenaběhla zdravě a aplikace se vrátila“ jde zavřít; Telegram oznámí zdravý start nové verze i návrat (staré události se při prvním spuštění neoznamují). Karta Nastavení › Aktualizace aplikace: verze, stav, Zkontrolovat, Aktualizovat, Vrátit zpět, přeskočené verze s „Zkusit znovu“, token. Telegram: příkaz `/aplikace` (stav a tlačítka Aktualizovat / Restartovat po doběhnutí / hned). API: `/api/app` (+ `check`, `update`, `apply`, `rollback`, `unskip`, `dismiss`, `token`); banner je i v `/api/state` (`app`).

Etapa 4 (hotovo): návod v README (Aktualizace aplikace bez nového obrazu: nastavení tokenu, vydání, průběh, příkazy, řešení potíží) a ostrá zkouška `scripts/e2e_update.py`. Ta v jednorázovém kontejneru (kopie enginů, prázdná data, bez Telegramu a fronty, port 8766) proti falešnému GitHubu ověřila na skutečném obrazu a s politikou `restart: unless-stopped` (13. 11. 2026, vše prošlo): **A)** úspěšná aktualizace (kontrola, stažení, samotest, restart, nová verze běží a po 120 s je zdravá), **B)** vadná verze, která projde samotestem a při startu spadne (po dvou pádech se sama vrátila předchozí verze, vadná se přeskakuje), **C)** vadná verze s migrací databáze a pádem (databáze obnovena ze zálohy na schéma 7, data zůstala, poškozená databáze uložena vedle). Nezkoušeno proti skutečnému GitHubu (až při prvním vydání) ani na Synology.

## 19. Záloha a obnova (export a import)

Modul `backup.py`, GUI v Nastavení (karta „Záloha a obnova“), příkazy `viddown backup` a `viddown restore`.
- Záloha je soubor `VidDown_<datum>_<čas>.dtb`: ZIP zašifrovaný AES-256-GCM (po blocích 1 MiB, `dtb.py`) klíčem **zabudovaným v aplikaci** (rozhodnutí uživatele: žádné heslo, import na jakémkoli stroji s VidDown). Ochrana před náhodným nahlédnutím, ne před držitelem kopie aplikace; kód a obraz proto nikdy nezveřejňovat. Volitelně obyčejný ZIP (`--plain`). Import přijímá oba formáty. Závislost `cryptography` zvýšila `IMAGE_API` na 2. Vnitřní ZIP: `backup.json` (popis: verze, schéma, počty, cílová složka), konzistentní snapshot `viddown.db` (SQLite backup API, funguje i za provozu), `settings.json`, `secrets.json`, `cookies.txt`, `archive.txt`, volitelně `thumbs/`. Enginy, logy a `tmp/` ne.
- Import za běhu se jen **připraví** (`restore/pending.zip`); provede se při startu, **před otevřením databáze**. Dosavadní stav se uloží do `restore/before-<čas>/` (poslední 3). Chybná záloha nezabrání startu, zůstanou stará data a výsledek je v `restore/last.json`.
- Ověření zálohy: bezpečné názvy souborů (jen povolené), limity velikosti, kontrola integrity databáze, záloha z novější verze schématu se odmítne.
- Přepis cest při přesunu na jiný stroj (`--remap` / pole v GUI) mění `jobs.filepath`, `jobs.target_dir`, `subscriptions.folder` a `download_dir`/`temp_dir` v nastavení; respektuje hranice složek (`/nas/Videa` se nedotkne `/nas/Videa2`).
- Soubory chybějící v záloze (např. cookies) se při obnově neodstraňují.
- **Automatické zálohy** (`autobackup.py`, nastavení `auto_backup`, `auto_backup_hours` 6/12/24/72/168, `auto_backup_dir`, `auto_backup_keep` 1–100): smyčka na pozadí jednou za minutu zkontroluje rozvrh (interval od poslední úspěšné zálohy; změna složky nebo první zapnutí = hned). Záloha se vytvoří (nešifrovaný ZIP vzniká jen v lokální dočasné složce, na cíl jde jen `.dtb`), **ověří** a teprve potom se smažou nejstarší nad `keep`; maže se jen soubor s názvem `VidDown_<datum>_<čas>[-<s>].dtb`, nově vytvořená záloha se nikdy nesmaže. Při chybě se nic nemaže, další pokus za hodinu, Telegram jen při selhání a nejvýš jednou denně. Stav je v `kv` (`auto_backup_state`). GUI ukazuje poslední a příští zálohu, chybu, seznam záloh ve složce a tlačítka „Zálohovat teď“ a „Obnovit“ (obnova ze složky bez stahování do prohlížeče).

## 20. Katalog (třídění videí před stahováním; schváleno 14. 11. 2026)

Nové menu **Katalog**: zdroje (kanály, playlisty, stránky, jednotlivá videa) se přidají po jednom, dávkou nebo ze souboru `.txt`, aplikace je **jen zjistí** a videa se nabízejí k výběru. Návrh s náčrtem obrazovky: `design/VidDown_plan_katalog.pdf`. Ovládá se jen v GUI.

Rozhodnutí: čte se celý zdroj bez limitu; zjišťování má **vlastní frontu** (nezabírá stahovací sloty); nejdřív seznamy všech zdrojů, pak rychlé podrobnosti všech videí, **pomalé podrobnosti (prohlížečem u webů bez podpory yt-dlp) až nakonec**, ve výchozím stavu zapnuté, jeden prohlížeč; pauza mezi dotazy na stejný zdroj je nastavitelná (výchozí 3 s). Miniatura = největší dostupná, uložená do nastavené složky; velikost zobrazení S/M/L. Stahování: tlačítko u karty i hromadně, do složky s názvem kanálu/playlistu (jednotlivé video bez složky), nezávisle na nastavení „samostatná složka“. Stavy: `new`, `queued` (viditelné); `removed`, `done`, `gone` (pamatované, skryté). **Obnovení zdroje (ruční i automatické) přidá jen dosud nenabídnutá videa**; „Načíst znovu vše“ a opětovné přidání zdroje nabídnou znovu i odmítnutá (odznak „Dříve odmítnuté“) a stažená („Staženo dříve“). Odebrání zdroje smaže i paměť o jeho videích. Videa, která ze zdroje zmizela (úplný seznam je už nevrací) nebo jsou soukromá či smazaná, se skryjí (`gone`) a vrátí se, až se zdroj znovu nabídne dostupná. Zjišťování reaguje na vypnutí aplikace (rozpracovaný zdroj se vrátí do fronty a yt-dlp se ukončí). Hromadné akce: Vybrat zobrazené i Vybrat všech vyhovujících; filtry (text s ignorováním diakritiky, rozlišení, zdroj, stav), řazení (zdroj, rozlišení, velikost, délka, pořadí), stránkování 25 až 500.

Etapy: **1** jádro (hotovo: migrace v8 `catalog_sources`/`catalog_items`/`jobs.catalog_item_id`, `catalog.py`, přidání zdrojů, fronta zjišťování, seznam pro yt-dlp zdroje, „staženo dříve“ z archivu a historie, dotazy s filtry/řazením/stránkováním, `/api/catalog…`); **2** podrobnosti a miniatury (hotovo, viz níže); **3** obrazovka (hotovo, viz níže); **4** stahování a vazba na frontu; **5** další typy zdrojů, automatické hledání (hotovo, viz níže).

Etapa 2 (hotovo, `catalogdetails.py`): pracovník podrobností zjišťuje u viditelných videí rozlišení, velikost, délku, název a kanál přes `yt-dlp` (vždy video v nejlepší kvalitě, i když je v nastavení „jen zvuk“). **Pořadí:** nejdřív se dokončí seznamy všech zdrojů, pak se zjišťují podrobnosti. **Zátěž:** po jednom videu na web, pauza `catalog_gap` (0–60 s, výchozí 3 s, ±30 %, ×2 Vyvážený a ×4 Šetrný režim výkonu), souběžně nejvýš 3 weby (sloupec `host`, dílčí indexy). **Chyby:** omezení dotazů a výpadek (`network`) odloží web na 2 min a pak zdvojnásobuje až na 2 h, ověření „nejsem robot“ a cookies na 1 h, video zůstává čekat; smazané nebo soukromé video se skryje (`gone`), ostatní chyby (geo, DRM, věk, přímý přenos, neznámé) označí jen to video (`failed`, tlačítko „Zkusit znovu“ = `POST /api/catalog/retry`). `POST /api/catalog/pause` zjišťování pozastaví (metoda `allowed_now()` je místo pro napojení na časový rozvrh). **Miniatury** se stahují zvlášť, po dávkách po 4, do složky `catalog_thumbs_dir` (výchozí `<data>/catalog/thumbs`, soubor `<id>.<přípona>`); kandidáti jdou od největšího (poslední v seznamu yt-dlp), zkouší se jich až 10, protože největší varianty starším videím chybějí; ukládají se jako záložní adresy u položky; obrázek se ověřuje podle hlavičky souboru; selhání se označí (`thumb_file=''`) a nezkouší se dokola. Miniatury se mažou s odebraným zdrojem; `GET /api/catalog/thumb/<id>` je podává s mezipamětí prohlížeče (middleware už nepřepisuje hlavičku `Cache-Control` koncovým bodům, které si ji nastavují). Stav (`details`) je v `GET /api/catalog`. Migrace 8 (dosud nevydaná) dostala sloupce `host` a `thumb_alts` a dílčí indexy. Pomalá úroveň (prohlížeč u webů bez podpory) čeká na etapu 5.

Etapa 3 (hotovo): menu **Katalog** (`renderCatalog` v `app.js`): panel zdrojů (stav, počet videí, průběh podrobností, Obnovit / Načíst znovu vše / Odebrat, klik na zdroj = filtr), informační řádek (podrobnosti, odložené weby, „Zkusit znovu neúspěšné“), tlačítko Pozastavit zjišťování, banner časového rozvrhu, nástroje (hledání s ×/Esc, zdroj, řazení a směr, počet na stránku, velikost miniatur S/M/L, filtry rozlišení a stavu), mřížka karet (miniatura se zálohou, odznak rozlišení, délka, název s odkazem, zdroj a kanál, velikost nebo „zjišťuji…“, odznaky Ve frontě / Staženo dříve / Dříve odmítnuté / Nedostupné), stránkování, přidání zdrojů (po jednom, dávkou, soubor `.txt`, hlášení přeskočených a neplatných). Obrazovka se obnovuje každé 3 s (mřížka se překreslí jen při změně, bez blikání). Výběr: po kartách, zobrazené, **všech vyhovujících** (posílá se jako popis filtru s výjimkami, `catalog.select_ids`), hromadné **Odstranit** (`POST /api/catalog/items/action`, stav `removed`, smaže miniaturu, položky ve frontě přeskočí). Základ pro hromadné stahování je připravený; tlačítka Stáhnout byla do etapy 4 vypnutá.

Etapa 4 (hotovo): stahování z katalogu. `catalog.queue_items(db, runner, ids, force)` vybere jen položky ve stavu `new` a každou zařadí přes `Runner.add(url, source="catalog", auto_confirm=True, catalog_item_id=…, subdir=<složka zdroje>)`; položka dostane stav `queued` a `job_id`. Položky „staženo dříve“ se bez `force` přeskočí; s `force` se jejich klíč nejdřív odebere z archivu yt-dlp (`archive_forget_many`), jinak by je yt-dlp odmítl. URL, která už je ve frontě, se jen propojí (`linked`). Výsledek: `queued`, `linked`, `skipped_downloaded`, `skipped_state`. `catalog.reconcile` (volá se v každém kole smyčky katalogu) porovná `queued` položky s úlohami: aktivní nechá, `done` → stav `done` (zmizí z katalogu, smaže se miniatura), `failed`/`cancelled`/`skipped`/smazaná úloha → zpět `new` s poznámkou „stahování …“ (pole `download_error`, odznak na kartě). Jednotlivé video bez zdroje‑seznamu jde do hlavní složky. API: akce `download` (s `force: true`) v `POST /api/catalog/items/action`. GUI: Stáhnout na kartě (potvrzení u „Staženo dříve“) a hromadně (okno s volbou „stáhnout znovu“), souhrn v toastu. Žádná změna schématu.

Etapa 5 (hotovo): **zdroj „Stránka“** (`kind='page'`, složka podle `<title>`). `catalog.list_source` zkusí yt-dlp; jen při chybě `unsupported` volá `catalog.list_page`: `pagelist.fetch` + `pagelist.detect` (rychlá vrstva z HTML) a další stránky podle parametru stránkování (nejvýš 200, pauza 1 s; HTTP 404/410 za poslední stránkou je konec, jiná chyba označí seznam za neúplný, takže se nic nepovažuje za zmizelé). Když se v HTML seznam nenajde a je zapnuté `catalog_slow_browser` (výchozí zapnuto), stránku (i další) vykreslí `sniffer.render_html` (Chromium, postupné odrolování, odmítnutí cookies). Klíč položky je adresa dílu. **Pomalé podrobnosti:** detail yt-dlp s chybou `unsupported` nastaví `detail_state='slow'` (bez změny schématu); `DetailWorker` je zpracuje až když nezbývá žádná rychlá práce (mimo odložené weby), **jedno video najednou** přes `sniffer.sniff` (rozlišení nejlepšího streamu, miniatura `og:image`/poster, délka); bez streamu nebo s DRM `failed` s důvodem, síťová chyba web odloží a video zůstane čekat. Bez zapnutého prohlížeče zůstává `unsupported` chybou videa. **Automatické hledání:** nastavení `catalog_auto` (výchozí vypnuto) a `catalog_auto_hours` (6/12/24/72/168); smyčka katalogu v rozvrhem povoleném čase volá `catalog.auto_refresh`, které zařadí zdroje (stav `done`/`error`) se `last_scan` starším než interval v režimu „jen nová“ jako automatické (`manual=0`). GUI: přepínač a interval v záhlaví Katalogu, řádek „Pomalé (prohlížečem): čeká N“, přepínač prohlížeče v Nastavení › Katalog. Ověřeno naživo proti lokálnímu falešnému webu (stránkování, seznam vykreslený JavaScriptem, pomalá vrstva v Chromiu); nezkoušeno na skutečném cizím webu.

## 21. Časový rozvrh (schváleno 15. 11. 2026)

Návrh s náčrtem editoru: `design/VidDown_plan_rozvrh.pdf`. Modul `schedule.py` rozhoduje, kdy smí aplikace automaticky pracovat. **Pravidla** (`schedule_rules`): každé má dny (0 = pondělí) a 1 až 8 oken `HH:MM`–`HH:MM`; pravidla a okna se sčítají a překrývající se se spojí; okno přes půlnoc platí podle dne začátku; stejný začátek a konec = celý den; čas je místní čas serveru (přechod letního času se řeší sám). **Rozsah** (`schedule_scope`, výchozí jen `queue`, jako dřív): `queue` (stahování fronty a náhledy čekajících položek), `subscriptions` (automatické kontroly odběrů), `catalog` (seznamy, podrobnosti a miniatury katalogu). Mimo okno nezačne nová automatická práce; probíhající kontrola nebo dotaz doběhne. **Ruční akce** se rozvrhem neřídí: „Zkontrolovat teď“ u odběru a ručně přidaný nebo obnovený zdroj katalogu (`catalog_sources.manual`) se zjistí hned; stahování zařazená ručně začnou až v okně. Aktualizace enginů a aplikace a automatické zálohy se rozvrhem neřídí. **Konec okna u stahování:** rozpracovaná stahování se přeruší a vrátí do fronty (jako dřív), nebo doběhnou (`schedule_finish_running`). **Dočasná výjimka** na 1, 3 nebo 6 hodin (`POST /api/schedule/override`, `DELETE`) rozvrh obejde pro všechny řízené činnosti (klíč `schedule_override_until` v databázi, přežije restart). **Převod:** dokud nejsou nová pravidla, platí dřívější jedno okno (`schedule_start`, `schedule_end`, `schedule_days`) s přesně stejným chováním (ověřeno porovnáním se starou implementací na tisících časů). Stav je v `GET /api/schedule` a v bloku `schedule` proudu stavu (`open`, `closes`, `next_open`, `override_until`, `allowed` podle činností, `rules`, `legacy`); `in_window` je výsledek pro frontu. Zjišťování katalogu se dotazuje přes `allowed_now()`.

Etapy: **1** jádro (hotovo: `schedule.py`, nastavení a ověření pravidel, řízení fronty, odběrů a katalogu, výjimka, API, 311 testů); **2** obrazovka (hotovo: karta Časový rozvrh v Nastavení s editorem pravidel a oken, rozsahem, volbou konce okna a stavem; banner „čeká na časové okno“ s tlačítky výjimky ve frontě a v odběrech; dřívější okno se zobrazí jako první pravidlo; průvodce prvním spuštěním zůstává u jednoho okna); **3** dokumentace a ostrá zkouška v Dockeru (hotovo): `scripts/e2e_schedule.py` v jednorázovém kontejneru s `TZ=Europe/Prague` (oddělená data, port 8767, falešný web s `x.mp4`) ověřila (13. 11. 2026, vše prošlo): zavřené okno (stav, další otevření v 10:00 místního času kontejneru, odběry mimo rozsah smějí), ručně přidané stahování zůstane ve frontě a ručně přidaný zdroj katalogu se i mimo okno zjistí, dočasná výjimka stahování uvolní a po zrušení rozvrh znovu zavře, okno kolem „teď“ (i přes půlnoc) je otevřené a ukazuje čas zavření. Zjištění (kontrola URL) ručně přidaného videa se rozvrhem neřídí, jen samotné stahování. Nezkoušeno: konec okna během běžícího stahování v kontejneru (pokryto testy) a Synology.

Nastavení (GUI, 14. 11. 2026): karty jsou ve skupinách **Stahování** (Stahování, Rychlost, Časový rozvrh, Pojmenování a složky), **Katalog**, **Telegram a síť**, **Aplikace** (Vzhled a jazyk, Aktualizace aplikace, Enginy), **Data** (Záloha a obnova) a **Pokročilé**. Skupiny jsou podmenu v bočním panelu pod položkou Nastavení (adresa `#settings/<skupina>`, poslední skupina se pamatuje v prohlížeči), na úzké obrazovce pruh tlačítek nad kartami. Karty skupiny se do dvou sloupců rozdělí podle skutečné výšky (prvních k vlevo, zbytek vpravo). Pole „Hledat v nastavení“ prohledá názvy karet, popisky a nápovědy napříč skupinami. Beze změny nastavení, API a databáze.

## 22. Inspirace

Myšlenky z projektu [puemos/hls-downloader](https://github.com/puemos/hls-downloader) (MIT): detekce HLS playlistů, parsování m3u8, fragmenty, AES-128, spojování.

## 23. Animované náhledy v katalogu (návrh, čeká na schválení)

Cíl: u karet katalogu ukázat krátkou animaci (co je ve videu) místo statické miniatury, kde ji web nabízí. Rozhodnutí uživatele (14. 11. 2026): podporovat **všechny tři zdroje animací** (A, B, C níže); zobrazení **při najetí myší** (na dotykovém displeji po klepnutí), jinak statická miniatura; ve výchozím stavu **vypnuto**, zapíná se v Nastavení › Katalog; u webů bez podpory yt-dlp **obecná heuristika** z HTML stránky videa. Zjištění: současné zdroje vracejí přes yt-dlp jen statické JPEG, takže přínos dá až etapa 3 (nebo jiné zdroje).

Technické zásady: animace je volitelná příloha položky (statická miniatura zůstává vždy); stahuje se až po podrobnostech a miniaturách, stejnou smyčkou, pauzou mezi dotazy na web a rozvrhem (rozsah „katalog“); limit velikosti jedné animace (výchozí 3 MB, nastavitelné 1–20); soubor se ukládá vedle miniatur (`<id>.webp|gif|mp4`), maže se s miniaturou při odstranění nebo stažení; služba `/api/catalog/anim/<id>` (podpora Range pro MP4); v mřížce se `<video muted loop playsinline>` nebo `<img>` načte až při najetí (`preload=none`), nikdy ne všechny najednou. **Schéma:** migrace 9 (`catalog_items.anim_url`, `anim_file` – prázdný řetězec = nepodařilo se, jako u miniatury, a dílčí index na čekající), schéma 8 se nemění.

Etapy:
1. **Jádro a zdroj A** (animace, které už yt-dlp vrací): migrace 9, nastavení `catalog_anim` (výchozí vypnuto) a `catalog_anim_max_mb`; rozpoznání animovaných miniatur v seznamu (přípona gif/mp4/webm, u WebP až podle obsahu – blok ANIM), uložení `anim_url`, stahování s limitem a kontrolou obsahu, služba souboru, mazání s položkou; testy.
2. **Obrazovka:** přehrání při najetí / klepnutí na kartě (video nebo obrázek), přepínač v Nastavení › Katalog (vypnuto / při najetí), tlačítko „Doplnit animace“ (znovu zjistí podrobnosti u položek bez animace, protože u starších položek se `anim_url` neukládal), odznak „animace“ na kartě, dokumentace.
3. **Zdroj B – storyboardy:** z `formats` yt-dlp (mhtml `storyboard`) stáhnout sprite sheety a ffmpegem složit krátký smyčkový MP4 (nejvýš ~6 s, šířka ≤ 320 px, bez zvuku); jen když A animaci nenašel; respektovat limit; test s falešným storyboardem a živá zkouška ffmpegu.
4. **Zdroj C – náhled ze stránky videa:** nový modul (`catalogpreview.py`): jeden GET stránky videa (limit velikosti jako `pagelist.fetch`, pauza podle webu) a obecná heuristika: `og:video`, `<video poster/src>`, `data-preview`/`data-webm`/`data-mp4` a podobné značky, jen odkazy na stejného hostitele nebo CDN a jen soubory do limitu; neúspěch = zůstane statická miniatura, web se nezkouší znovu. Pozor: dotaz navíc na každé video (proto až po A a B a jen při zapnutém nastavení).
5. **Dolaďování a ostrá zkouška:** zahrnutí do zálohy jen s volbou „s náhledy“, místo na disku v Nastavení (součet velikostí), živá zkouška proti lokálnímu falešnému webu (A, B, C) a v Dockeru, deep review.

Otevřené detaily (výchozí předpoklady, upřesnit lze kdykoli): formát složené animace MP4 (H.264, bez zvuku); limit 3 MB; heuristika C jen pro položky, kterým A a B animaci nenašly; animace se nepřehrávají na pozadí ani v „vždy“ režimu; po vypnutí nastavení soubory zůstanou (jdou smazat tlačítkem „Smazat animace“, součást etapy 5).

