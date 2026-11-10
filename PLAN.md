# VidDown – plán

Stav: **etapy 1–4 implementovány** (listopad 2026), odběry a statistiky (kap. 17) rozpracovány – hotová etapa 1. Tento dokument shrnuje potvrzené požadavky, pravidla chování a návrh. Odchylky a doplňky z vývoje jsou v kapitole 17.

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
2. GUI Odběry (přehled, přidání, podmenu s frontou, historií a nastavením).
3. Dvojí historie (příznaky skrytí, volba „z jedné / z obou“).
4. Tabulka `downloads` + API + GUI Statistiky.

### 17.5 K potvrzení (navržené výchozí hodnoty)

- Interval kontroly globálně 6 h (bez nastavení u jednotlivého odběru).
- Odběr funguje pro kanály i playlisty z libovolného webu, který yt-dlp umí vypsat; první verze testována na YouTube.
- Shorts a živé záložky se u odběru výchozí vypnuté (jen „videa“).
- Kvalita a šablona názvu zůstávají globální.

## 18. Inspirace

Myšlenky z projektu [puemos/hls-downloader](https://github.com/puemos/hls-downloader) (MIT): detekce HLS playlistů, parsování m3u8, fragmenty, AES-128, spojování.
