"""Příkazová řádka: viddown [serve|add|queue|history|engine|config|password|telegram|autostart|doctor|version]."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import DEFAULTS, Secrets, Settings, data_dir
from .db import DB
from .i18n import t
from .util import extract_urls, fmt_bytes, free_space


def _db() -> DB:
    return DB(data_dir() / "viddown.db")


def _spawn_daemon() -> None:
    cmd = [sys.executable, "serve"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "viddown", "serve"]
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def cmd_add(a) -> int:
    from .daemon import running_info
    db = _db()
    urls = extract_urls(" ".join(a.urls))
    if not urls:
        print("Žádná platná URL.")
        return 1
    for u in urls:
        ex = db.find_active_url(u)
        if ex:
            print(f"#{ex['id']} už je ve frontě: {u}")
            continue
        jid = db.add(u, source="cli", status="new", auto_confirm=1 if a.yes else 0)
        print(f"#{jid} přidáno: {u}")
    if running_info() is None:
        if a.no_start:
            print("VidDown neběží – úlohy se zpracují po spuštění `viddown serve`.")
        else:
            _spawn_daemon()
            print("VidDown neběžel – spouštím ho na pozadí.")
    return 0


def _status_txt(j) -> str:
    st = t(Settings().get("language", "cs"), "status")
    s = st.get(j["status"], j["status"])
    if j["status"] == "running" and j["progress"] is not None:
        s += f" {int(j['progress'] * 100)} %"
    if j["paused"]:
        s += " (pozastaveno)"
    return s


def cmd_queue(a) -> int:
    rows = _db().queue()
    if not rows:
        print("Fronta je prázdná.")
        return 0
    for j in rows:
        indent = "   " if j["parent_id"] else ""
        print(f"{indent}#{j['id']:<5} {_status_txt(j):<22} {(j['title'] or j['url'])[:70]}")
    return 0


def cmd_history(a) -> int:
    rows = _db().history(limit=a.n)
    for j in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(j["finished_at"] or j["updated_at"]))
        extra = fmt_bytes(j["filesize"]) if j["status"] == "done" else (j["error"] or "")[:60]
        print(f"#{j['id']:<5} {when} {_status_txt(j):<10} {(j['title'] or j['url'])[:60]}  {extra}")
    if not rows:
        print("Historie je prázdná.")
    return 0


def cmd_engine(a) -> int:
    from .engines import EngineManager
    st = EngineManager(data_dir(), Settings(), _db())
    if a.action == "status":
        for e in st.status():
            cur = e["current"] or (f"{e['system']} (systém)" if e["system"] else "—")
            vs = ", ".join(v["version"] for v in e["versions"])
            print(f"{e['name']:<7} aktivní: {cur:<22} uchované: {vs or '—'}")
        return 0
    names = [a.name] if a.name else list(st.ORDER)
    if a.action == "update":
        for n in names:
            r = st.update(n)
            print(f"{n}: {r.get('status')} {r.get('version') or ''} {r.get('message') or ''}")
    elif a.action == "test":
        for n in names:
            ok, msg = st.test(n)
            print(f"{n}: {'OK' if ok else 'CHYBA'} {'' if ok else msg}")
    elif a.action == "rollback":
        if not a.name:
            print("Zadejte engine: viddown engine rollback yt-dlp [verze]")
            return 1
        print(f"{a.name}: aktivní verze {st.rollback(a.name, a.version)}")
    elif a.action == "install":
        st.ensure()
    return 0


def cmd_config(a) -> int:
    s = Settings()
    if a.action == "get":
        vals = s.all()
        if a.key:
            print(json.dumps(vals.get(a.key), ensure_ascii=False))
        else:
            for k, v in vals.items():
                print(f"{k} = {json.dumps(v, ensure_ascii=False)}")
        return 0
    if a.key not in DEFAULTS:
        print(f"Neznámé nastavení: {a.key}")
        return 1
    if a.key in ("download_dir", "temp_dir") and (a.key == "download_dir" or a.value.strip()):
        from .util import check_dir_writable
        ok, msg = check_dir_writable(a.value)
        if not ok:
            print(f"Chyba: {msg}")
            return 1
    try:
        s.update({a.key: a.value})
    except ValueError as e:
        print(f"Chyba: {e}")
        return 1
    print(f"{a.key} = {json.dumps(s.get(a.key), ensure_ascii=False)}")
    return 0


def cmd_password(a) -> int:
    p1 = getpass.getpass("Nové heslo do GUI (prázdné = odstranit): ")
    if p1:
        if len(p1) < 6:
            print("Heslo musí mít alespoň 6 znaků.")
            return 1
        if getpass.getpass("Heslo znovu: ") != p1:
            print("Hesla se neshodují.")
            return 1
    Secrets().set_password(p1)
    print("Heslo uloženo." if p1 else "Heslo odstraněno.")
    return 0


def cmd_telegram(a) -> int:
    if a.token is not None:
        Secrets().set_telegram_token(a.token)
        print("Token uložen.")
    if a.chat is not None:
        Settings().update({"telegram_chat_id": a.chat})
        print("Chat ID uloženo.")
    return 0


def cmd_db(a) -> int:
    db = _db()
    if a.action == "info":
        n = db.query("select status, count(*) n from jobs group by status order by n desc")
        print(f"Databáze: {db.path}")
        print(f"Schéma:   verze {db.schema_version}")
        print("Úlohy:    " + (", ".join(f"{r['status']} {r['n']}" for r in n) or "žádné"))
        return 0
    if not a.old or not a.new:
        print("Použití: viddown db remap-paths STARÁ_CESTA NOVÁ_CESTA [--dry-run]")
        return 1
    n = db.remap_paths(a.old, a.new, dry_run=a.dry_run)
    print(f"{'Změnilo by se' if a.dry_run else 'Změněno'} {n} cest v historii ({a.old} → {a.new}).")
    return 0


def cmd_autostart(a) -> int:
    from . import autostart
    if a.action == "on":
        print(f"Autostart zapnut: {autostart.enable()}")
    elif a.action == "off":
        autostart.disable()
        print("Autostart vypnut.")
    else:
        print("zapnuto" if autostart.is_enabled() else "vypnuto")
    return 0


def cmd_app(a) -> int:
    """Aktualizace kódu aplikace (PLAN.md kap. 18): správa verzí v <data>/app."""
    from . import appupdate as au
    from .config import data_dir
    store = au.AppStore(data_dir())
    try:
        if a.action == "status":
            s = store.status()
            print(f"Verze v obraze:    {s['baseline']}  (IMAGE_API {s['image_api']})")
            print(f"Běží:              {s['running']}")
            print(f"Aktivní:           {s['current'] or '- (verze z obrazu)'}   předchozí: {s['previous'] or '-'}")
            print(f"Nainstalováno:     {', '.join(s['installed']) or '-'}")
            if s["skipped"]:
                print("Přeskočené:        " + "; ".join(f"{v} ({d['reason']})" for v, d in s["skipped"].items()))
            if s["probation"]:
                pr = s["probation"]
                print(f"Zkušební doba:     verze {pr['version']}, starty {pr['attempts']}/{au.MAX_FAILED_STARTS}")
            for e in s["events"]:
                print(f"  {time.strftime('%d.%m. %H:%M', time.localtime(e['t']))}  {e['kind']:<12} {e['version'] or '':<8} {e['msg']}")
        elif a.action in ("check", "update"):
            repo, token = Settings().get("app_update_repo"), Secrets().app_update_token
            if a.action == "check":
                c = au.check(store, repo, token)
                label = {"available": "k dispozici novější verze", "up_to_date": "máte nejnovější verzi",
                         "skipped": f"verze byla přeskočena ({c['skipped_reason']})", "needs_image": "vyžaduje novější obraz"}[c["status"]]
                print(f"Máte {c['current']}, nejnovější vydání {c['version']}: {label}.")
                if c["status"] == "available":
                    print(f"Velikost {fmt_bytes(c['size'])}. Aktualizace: viddown app update")
                    if c["notes"]:
                        print("\n" + c["notes"])
            else:
                r = au.update(store, repo, token, force=a.force)
                if r["status"] == "up_to_date":
                    print(f"Máte nejnovější verzi ({r['version']}).")
                else:
                    print(f"Nainstalována a otestována verze {r['version']}. Změna se projeví po restartu aplikace "
                          "(spustí se na zkušební dobu a při potížích se sama vrátí).")
        elif a.action == "token":
            tok = getpass.getpass("GitHub token pro čtení vydání (prázdné = smazat): ")
            Secrets().set_app_update_token(tok)
            print("Token uložen." if tok.strip() else "Token smazán.")
        elif a.action == "pack":
            if not a.arg:
                print("Použití: viddown app pack VÝSTUP.zip [--version X.Y.Z]", file=sys.stderr)
                return 2
            man = au.pack(Path(a.arg), version=a.version, commit=a.commit)
            print(f"{man['file']}\nverze {man['version']}, schéma {man['schema_version']}, sha256 {man['sha256']}")
            if a.json:
                body = json.dumps({k: v for k, v in man.items() if k != "file"}, ensure_ascii=False, indent=1).encode("utf-8")
                Path(a.json).write_bytes(body)
                key = _signing_key(a)
                if key:                                                     # podpis přesných bajtů manifestu (ověřuje aplikace)
                    sig_path = Path(a.json).with_name(au.MANIFEST_SIG_ASSET)
                    sig_path.write_text(au.sign_manifest(body, key) + "\n", "ascii")
                    print(f"manifest podepsán: {sig_path}")
                elif a.require_signature:
                    print("Vydání bez podpisu: chybí --sign-key-file nebo VIDDOWN_UPDATE_SIGNING_KEY.", file=sys.stderr)
                    return 1
                else:
                    print("Pozor: manifest není podepsán (chybí --sign-key-file nebo VIDDOWN_UPDATE_SIGNING_KEY).", file=sys.stderr)
        elif a.action == "install":
            if not a.arg:
                print("Použití: viddown app install ARCHIV.zip [--sha256 SOUČET]", file=sys.stderr)
                return 2
            print(f"Nainstalována verze {store.install_zip(Path(a.arg), a.sha256)}")
        elif a.action in ("selftest", "activate"):
            if not a.arg:
                print(f"Použití: viddown app {a.action} VERZE", file=sys.stderr)
                return 2
            if a.action == "selftest" or not a.no_test:
                ok, rep = store.selftest(a.arg, skip_engines=a.skip_engines)
                for c in rep["checks"]:
                    print(f"  {'OK ' if c['ok'] else 'CHYBA'} {c['name']}: {c['detail']}")
                if not ok:
                    if a.action == "activate":
                        store.skip(a.arg, "samotest selhal")
                        print(f"Verze {a.arg} je přeskočená.", file=sys.stderr)
                    return 1
            if a.action == "activate":
                store.activate(a.arg)
                print(f"Aktivní je verze {a.arg}. Změna se projeví po restartu aplikace.")
        elif a.action == "rollback":
            if a.restore_db and _daemon_running():                      # databáze se nesmí přepsat pod běžícím procesem
                print("Aplikace běží. Nejdřív ji zastavte, pak obnovte databázi.", file=sys.stderr)
                return 1
            r = store.rollback("ruční návrat", restore_db=a.restore_db)
            print(f"Zpět na {r['to'] or 'verzi z obrazu'}" + (" (databáze obnovena ze zálohy)" if r["restored_db"] else "")
                  + ". Změna se projeví po restartu aplikace.")
        elif a.action == "unskip":
            print("Přeskočení zrušeno." if a.arg and store.unskip(a.arg) else "Taková přeskočená verze není.")
        elif a.action == "remove":
            store.remove(a.arg or "")
            print("Odstraněno.")
    except au.UpdateError as e:
        print(f"Chyba: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_backup(a) -> int:
    """Záloha dat (databáze, nastavení, token bota, cookies, archiv) do jednoho ZIP souboru."""
    from . import backup
    out = Path(a.out) if a.out else Path.cwd() / backup.default_name(not a.plain)
    try:
        p = backup.create(data_dir(), out, include_thumbs=a.thumbs, encrypt=not a.plain)
    except backup.BackupError as e:
        print(f"Chyba: {e}", file=sys.stderr)
        return 1
    print(f"Záloha: {p} ({fmt_bytes(p.stat().st_size)})")
    print("Pozor: obsahuje token Telegram bota, heslo a cookies. Ukládejte ji bezpečně a nesdílejte."
          + ("" if a.plain else " Soubor je šifrovaný klíčem aplikace, otevře ho jen VidDown."))
    return 0


def cmd_backup_key(a) -> int:
    """Klíč záloh této instalace."""
    from . import dtb
    print(dtb.format_key(dtb.install_key(data_dir())))
    print("Uložte si ho bezpečně (správce hesel). Bez něj zálohu z tohoto počítače jinde neobnovíte.", file=sys.stderr)
    return 0


def cmd_restore(a) -> int:
    """Obnova ze zálohy. Když aplikace běží, obnova se jen připraví a provede se při jejím dalším startu."""
    from . import backup
    from .daemon import running_info
    zp = Path(a.file)
    remap = tuple(a.remap) if a.remap else None
    try:
        man = backup.validate(zp, getattr(a, "key", None), data_dir())
        created = time.strftime("%d.%m.%Y %H:%M", time.localtime(man.get("created", 0)))
        print(f"Záloha z {created}, verze {man.get('app_version')}: {man.get('jobs')} úloh, {man.get('done')} stažených, "
              f"{man.get('subscriptions')} odběrů.")
        if man.get("path_hint"):
            print(f"Cesty stažených souborů v záloze začínají např.: {man['path_hint']}")
        if running_info() is not None:
            backup.stage(data_dir(), zp, getattr(a, "key", None))
            if remap:
                backup.set_remap(data_dir(), *remap)
            print("Aplikace běží: obnova je připravená a provede se při jejím dalším startu. Restartujte ji (Nastavení › Restartovat, "
                  "nebo `docker compose restart`).")
            return 0
        if not a.yes and input("Nahradit aktuální data daty ze zálohy? Dosavadní stav se uloží do složky restore/. [a/N] ").lower() not in ("a", "y"):
            print("Zrušeno.")
            return 1
        if _daemon_running():                                           # obnova se přepisuje pod běžícím procesem: odmítnout
            print("Aplikace běží. Nejdřív ji zastavte, pak obnovte zálohu.", file=sys.stderr)
            return 1
        res = backup.apply(data_dir(), zp, remap, getattr(a, "key", None))
    except backup.BackupError as e:
        print(f"Chyba: {e}", file=sys.stderr)
        return 1
    print(f"Obnoveno. Předchozí stav: {res['before']}")
    if res.get("remap"):
        print("Přepsané cesty: " + ", ".join(f"{k} {v}" for k, v in res["remap"].items()))
    return 0


def cmd_doctor(a) -> int:
    from .daemon import running_info
    from .engines import EngineManager
    s = Settings()
    ok_all = True

    def line(ok, name, info=""):
        nonlocal ok_all
        ok_all &= bool(ok)
        print(f"{'✔' if ok else '✘'} {name:<24} {info}")

    d = data_dir()
    line(os.access(d, os.W_OK), "Datová složka", str(d))
    dl = s.get("download_dir")
    try:
        os.makedirs(dl, exist_ok=True)
        line(os.access(dl, os.W_OK), "Cílová složka", dl)
    except OSError as e:
        line(False, "Cílová složka", f"{dl}: {e}")
    free, reliable = free_space(dl)
    limit = s.get("min_free_gb") * 1024 ** 3
    if reliable:
        line(free > limit, "Volné místo (cíl)", fmt_bytes(free))
    else:
        line(True, "Volné místo (cíl)", "nelze zjistit (Docker Desktop: složka z /Volumes hlásí místo disku Macu)")
    tmp = s.get("temp_dir") or str(d / "tmp")
    tfree, _ = free_space(tmp)
    line(tfree is None or tfree > limit, "Volné místo (dočasná)", f"{fmt_bytes(tfree)} – {tmp}")
    m = EngineManager(d, s, _db())
    for e in m.status():
        cur = e["current"] or (f"{e['system']} (systém)" if e["system"] else None)
        line(bool(e["path"]), e["name"], cur or "chybí – spusťte `viddown engine install`")
    ch = m.chromium_status()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        line(True, "Chromium (sniffer)", f"Playwright {ch.get('playwright')}")
    except Exception as e:  # noqa: BLE001
        line(False, "Chromium (sniffer)", f"{str(e).splitlines()[0][:80]} – v GUI Enginy › Nainstalovat prohlížeč")
    sec = Secrets()
    line(True, "Telegram", ("token nastaven" if sec.telegram_token else "bez tokenu (volitelné)") +
         (f", chat ID {s.get('telegram_chat_id')}" if s.get("telegram_chat_id") else ""))
    info = running_info()
    line(True, "Databáze", f"schéma verze {_db().schema_version}")
    line(True, "Démon", f"běží (PID {info.get('pid')}, port {info.get('port')})" if info is not None else "neběží")
    return 0 if ok_all else 1


def _signing_key(a) -> str | None:
    """Soukromý klíč pro podpis vydání: soubor z `--sign-key-file`, jinak proměnná prostředí (v CI z tajemství)."""
    if getattr(a, "sign_key_file", None):
        return Path(a.sign_key_file).read_text("utf-8").strip() or None
    return os.environ.get("VIDDOWN_UPDATE_SIGNING_KEY", "").strip() or None


def _daemon_running() -> bool:
    """Běží instance aplikace? (zámek daemon.lock drží běžící proces)"""
    from .daemon import Lock
    lk = Lock(data_dir() / "daemon.lock")
    if lk.acquire():
        lk.release()
        return False
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="viddown", description="VidDown – stahování videí (yt-dlp + HLS sniffer)")
    p.add_argument("--version", action="version", version=f"VidDown {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("serve", help="spustí aplikaci (fronta, GUI, Telegram)")
    sp.add_argument("--open", action="store_true", help="otevře GUI v prohlížeči")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)

    sp = sub.add_parser("add", help="přidá URL do fronty")
    sp.add_argument("urls", nargs="+")
    sp.add_argument("--yes", "-y", action="store_true", help="potvrdí i velké playlisty")
    sp.add_argument("--no-start", action="store_true", help="nespouštět aplikaci, jen zapsat do fronty")

    sub.add_parser("queue", help="vypíše frontu")
    sp = sub.add_parser("history", help="vypíše historii")
    sp.add_argument("-n", type=int, default=20)

    sp = sub.add_parser("engine", help="správa enginů")
    sp.add_argument("action", choices=["status", "update", "test", "rollback", "install"])
    sp.add_argument("name", nargs="?", choices=["yt-dlp", "deno", "ffmpeg"])
    sp.add_argument("version", nargs="?")

    sp = sub.add_parser("config", help="nastavení")
    sp.add_argument("action", choices=["get", "set"])
    sp.add_argument("key", nargs="?")
    sp.add_argument("value", nargs="?")

    sub.add_parser("password", help="nastaví heslo do GUI")
    sp = sub.add_parser("telegram", help="token a chat ID Telegram bota")
    sp.add_argument("--token")
    sp.add_argument("--chat")
    sp = sub.add_parser("db", help="databáze: info, přepsání cest po přesunu na jiný počítač")
    sp.add_argument("action", choices=["info", "remap-paths"])
    sp.add_argument("old", nargs="?")
    sp.add_argument("new", nargs="?")
    sp.add_argument("--dry-run", action="store_true", help="jen vypíše, kolik záznamů by se změnilo")
    sp = sub.add_parser("autostart", help="spouštění po přihlášení")
    sp.add_argument("action", choices=["on", "off", "status"])
    sp = sub.add_parser("backup", help="záloha dat do šifrovaného souboru .dtb (databáze, nastavení, token, cookies, archiv)")
    sp.add_argument("out", nargs="?", help="cílový soubor (výchozí VidDown_<datum>_<čas>.dtb)")
    sp.add_argument("--thumbs", action="store_true", help="přibalit i náhledy")
    sp.add_argument("--plain", action="store_true", help="bez šifrování (obyčejný ZIP)")
    sp = sub.add_parser("restore", help="obnova dat ze zálohy")
    sp.add_argument("file")
    sp.add_argument("--remap", nargs=2, metavar=("STARÁ", "NOVÁ"), help="přepíše začátek cest po přesunu na jiný stroj")
    sp.add_argument("--yes", "-y", action="store_true", help="bez potvrzení")
    sp.add_argument("--key", help="klíč instalace (jen u zálohy vytvořené verzí 0.2.0 na jiném počítači)")
    sub.add_parser("backup-key", help="klíč instalace pro zálohy vytvořené verzí 0.2.0")
    sp = sub.add_parser("app", help="aktualizace kódu aplikace: verze, samotest, návrat")
    sp.add_argument("action", choices=["status", "check", "update", "token", "pack", "install", "selftest", "activate", "rollback", "unskip", "remove"])
    sp.add_argument("arg", nargs="?", help="verze nebo cesta k archivu")
    sp.add_argument("--version", help="pack: přepíše verzi v archivu (pro zkoušky)")
    sp.add_argument("--commit", help="pack: zkrácený commit zapsaný do manifestu")
    sp.add_argument("--json", help="pack: zapíše manifest vydání (včetně sha256) do tohoto souboru")
    sp.add_argument("--sign-key-file", help="pack: soubor se soukromým klíčem (base64) pro podpis manifestu; jinak VIDDOWN_UPDATE_SIGNING_KEY")
    sp.add_argument("--require-signature", action="store_true", help="pack: bez podpisu skončí chybou (pro vydání)")
    sp.add_argument("--force", action="store_true", help="update: zkusí znovu i dřív přeskočenou verzi")
    sp.add_argument("--sha256", help="install: očekávaný kontrolní součet")
    sp.add_argument("--no-test", action="store_true", help="activate: přeskočí samotest")
    sp.add_argument("--skip-engines", action="store_true", help="selftest: bez kontroly enginů")
    sp.add_argument("--restore-db", action="store_true", help="rollback: obnoví zálohu databáze (ztráta dat od přepnutí)")
    sub.add_parser("doctor", help="kontrola závislostí")
    sub.add_parser("version", help="verze")

    a = p.parse_args(argv)
    from .db import SchemaTooNew
    try:
        return _dispatch(p, a)
    except SchemaTooNew as e:
        print(f"Chyba: {e}", file=sys.stderr)
        return 2


def _dispatch(p, a) -> int:
    if a.cmd is None:
        from .daemon import serve
        return serve(open_browser=True)
    if a.cmd == "serve":
        from .daemon import serve
        return serve(open_browser=a.open, host=a.host, port=a.port)
    if a.cmd == "version":
        print(f"VidDown {__version__}")
        return 0
    if a.cmd == "config" and a.action == "set" and (a.key is None or a.value is None):
        p.error("config set KLÍČ HODNOTA")
    return {"add": cmd_add, "queue": cmd_queue, "history": cmd_history, "engine": cmd_engine, "config": cmd_config,
            "password": cmd_password, "telegram": cmd_telegram, "autostart": cmd_autostart, "doctor": cmd_doctor,
            "db": cmd_db, "app": cmd_app, "backup": cmd_backup, "restore": cmd_restore,
            "backup-key": cmd_backup_key}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
