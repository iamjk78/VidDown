"""HTTP API a webové GUI (FastAPI)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, appupdate, autobackup, backup, pagelist, subscriptions, thumbs, updater
from .config import DEFAULTS, CHOICES, cookies_path
from .probe import probe_url
from .util import check_dir_writable, extract_urls, in_docker, in_schedule, sanitize_filename

WEB = Path(__file__).parent / "web"

JOB_FIELDS = ("id", "url", "title", "status", "kind", "method", "parent_id", "pos", "paused", "source", "channel",
              "duration", "height", "size_est", "approx", "progress", "downloaded", "total", "speed", "eta", "filepath",
              "filesize", "error", "error_kind", "attempts", "not_before", "created_at", "finished_at", "thumb_url", "subdir",
              "sub_id")


def job_out(j: dict) -> dict:
    o = {k: j.get(k) for k in JOB_FIELDS}
    o["has_thumb"] = bool(j.get("thumb_url") or j.get("filepath"))
    if j.get("kind") in ("playlist", "channel") and j.get("info"):
        try:
            o["count"] = json.loads(j["info"]).get("count")
        except (json.JSONDecodeError, AttributeError):
            pass
    return o


def create_app(app_state) -> FastAPI:
    """app_state: objekt s atributy db, settings, secrets, engines, runner, bot, data."""
    S = app_state
    app = FastAPI(title="VidDown", version=__version__, docs_url=None, redoc_url=None)
    fails: dict[str, list[float]] = {}

    # ------------------------------------------------------------ přihlášení
    def token() -> str:
        return hmac.new(S.secrets.session_key().encode(), b"viddown-session", hashlib.sha256).hexdigest()

    def authed(req: Request) -> bool:
        if not S.secrets.has_password():
            return True
        return hmac.compare_digest(req.cookies.get("vd_session", ""), token())

    @app.middleware("http")
    async def guard(req: Request, call_next):
        p = req.url.path
        open_paths = ("/api/session", "/api/login")
        if p.startswith("/api/") and p not in open_paths and not authed(req):
            return JSONResponse({"error": "auth"}, status_code=401)
        resp = await call_next(req)
        if p.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif p.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"   # vždy ověřit (ETag), ať se po aktualizaci nenačte stará verze GUI
        return resp

    @app.get("/api/session")
    async def session(req: Request):
        return {"auth_required": S.secrets.has_password(), "authed": authed(req), "version": __version__,
                "language": S.settings.get("language"), "theme": S.settings.get("theme")}

    @app.post("/api/login")
    async def login(req: Request):
        ip = req.client.host if req.client else "?"
        now = time.time()
        recent = [t for t in fails.get(ip, []) if now - t < 300]
        if len(recent) >= 5:
            raise HTTPException(429, "too many attempts, wait 5 minutes")
        body = await req.json()
        if not S.secrets.check_password(str(body.get("password", ""))):
            recent.append(now)
            fails[ip] = recent
            await asyncio.sleep(1)
            raise HTTPException(401, "wrong password")
        fails.pop(ip, None)
        r = JSONResponse({"ok": True})
        r.set_cookie("vd_session", token(), httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)
        return r

    @app.post("/api/logout")
    async def logout():
        r = JSONResponse({"ok": True})
        r.delete_cookie("vd_session")
        return r

    # ------------------------------------------------------------ stav
    def state() -> dict:
        s = S.settings.all()
        q = [job_out(j) for j in S.db.queue()]
        running = [j for j in q if j["status"] == "running"]
        waiting = [j for j in q if j["status"] in ("queued", "new", "probing") and j["kind"] == "video"]
        playlists_pending = sum((j.get("count") or 0) for j in q if j["status"] == "confirm" and j["kind"] != "video")
        counts = S.db.sub_counts()
        return {
            "queue": q,
            "stats": {
                "running": len(running), "concurrency": S.runner.eff_concurrency(s),
                "waiting": len(waiting) + playlists_pending,
                "paused": sum(1 for j in q if j["paused"] and j["kind"] == "video"),
                "size_est": sum((j["size_est"] or 0) for j in waiting),
                "speed": sum((j["speed"] or 0) for j in running),
                # kolik místa ještě budou potřebovat videa ve frontě (odhad velikosti čekajících + zbytek rozpracovaných)
                "need": sum((j["size_est"] or 0) for j in waiting) + sum(max(0, (j["total"] or 0) - (j["downloaded"] or 0)) for j in running),
                "rate_limit": s["rate_limit_mbps"] if s["rate_limit_enabled"] else None,
                "today": S.db.stats_today(),
            },
            "cpu": S.runner.cpu.out(),
            "app": updater.banner_cached(S),
            "queue_paused": bool(S.db.kv_get("queue_paused", False)),
            "pause_reason": S.db.kv_get("queue_pause_reason"),
            "pause_hard": S.runner.pause_is_hard(),
            "target_error": S.db.kv_get("target_error"),
            "cookies_error": S.db.kv_get("cookies_error"),
            "schedule": {"enabled": s["schedule_enabled"], "start": s["schedule_start"], "end": s["schedule_end"]},
            "in_window": in_schedule(s),
            "disk": dict(S.runner.disk_status(s), dir=s["download_dir"], min_gb=s["min_free_gb"],
                         low_kind=S.db.kv_get("disk_low")),
            "telegram": S.bot.status() if S.bot else {"state": "off"},
            "engines": {e["name"]: (e["current"] or (f"{e['system']} (systém)" if e["system"] else None))
                        for e in S.engines_cache()},
            "subs": [sub_out(x, counts) for x in S.db.sub_list()],
            "onboarded": bool(S.db.kv_get("onboarded", False)),
            "docker": in_docker(),
            "version": __version__,
        }

    @app.get("/api/state")
    async def get_state():
        return await asyncio.to_thread(state)

    @app.get("/api/events")
    async def events(req: Request):
        async def gen():
            last = None
            while not getattr(S, "stopping", False) and not await req.is_disconnected():
                st = await asyncio.to_thread(state)
                payload = json.dumps(st, ensure_ascii=False, default=str)
                h = hashlib.md5(payload.encode()).hexdigest()
                if h != last:
                    last = h
                    yield f"data: {payload}\n\n"
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ úlohy
    @app.post("/api/jobs")
    async def add_jobs(req: Request):
        body = await req.json()
        raw = body.get("urls") or body.get("url") or ""
        urls = extract_urls(raw if isinstance(raw, str) else "\n".join(raw))
        if not urls:
            raise HTTPException(400, "no url")
        out = []
        for u in urls:
            jid, new = S.runner.add(u, source="gui", auto_confirm=bool(body.get("confirm")))
            out.append({"id": jid, "url": u, "new": new})
        return {"jobs": out}

    def _job(jid: int) -> dict:
        j = S.db.get(jid)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.post("/api/jobs/bulk-cancel")
    async def bulk_cancel(req: Request):
        """Hromadně odebere položky z fronty. U playlistu se odeberou i jeho položky; položky už zrušeného playlistu se přeskočí."""
        body = await req.json()
        ids = [int(i) for i in (body.get("ids") or [])][:5000]
        n = 0
        for jid in ids:
            j = S.db.get(jid)
            if j and j["status"] in ("new", "probing", "confirm", "queued", "running", "expanded"):
                S.runner.cancel(jid)
                n += 1
        return {"cancelled": n}

    @app.post("/api/jobs/{jid}/{action}")
    async def job_action(jid: int, action: str, req: Request):
        _job(jid)
        if action == "pause":
            S.runner.set_paused(jid, True)
        elif action == "resume":
            S.runner.set_paused(jid, False)
        elif action == "cancel":
            S.runner.cancel(jid)
        elif action == "retry":
            return {"id": S.runner.retry(jid)}
        elif action == "confirm":
            if not S.runner.confirm(jid):
                raise HTTPException(409, "not awaiting confirmation")
        elif action == "reject":
            S.runner.cancel(jid)
        elif action == "move":
            body = await req.json()
            S.db.move(jid, body.get("before_id"))
        elif action == "open":
            return _open(jid, req)
        else:
            raise HTTPException(404, "unknown action")
        return {"ok": True}

    def _open(jid: int, req: Request):
        j = _job(jid)
        host = req.client.host if req.client else ""
        if in_docker() or host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(403, "only on the local computer")
        p = Path(j["filepath"] or "")
        if not p.exists():
            raise HTTPException(404, "file not found")
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
        return {"ok": True}

    @app.get("/api/jobs/{jid}/log")
    async def job_log(jid: int):
        j = _job(jid)
        f = S.data / "logs" / f"job-{jid}.log"
        return {"log": f.read_text(encoding="utf-8", errors="replace") if f.exists() else "", "error": j.get("error"),
                "children": [job_out(c) for c in S.db.children(jid)] if j["kind"] != "video" else []}

    @app.get("/api/jobs/{jid}/children")
    async def job_children(jid: int):
        return {"children": [job_out(c) for c in S.db.children(jid)]}

    @app.get("/api/thumb/{jid}")
    async def thumb(jid: int):
        j = S.db.get(jid)
        if not j:
            raise HTTPException(404)
        p = await asyncio.to_thread(thumbs.ensure_cached, S.data, j)
        if not p:
            raise HTTPException(404)
        head = p.read_bytes()[:16]
        mt = "image/jpeg"
        if head[:4] == b"\x89PNG":
            mt = "image/png"
        elif head[8:12] == b"WEBP":
            mt = "image/webp"
        return FileResponse(p, media_type=mt, headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/file/{jid}")
    async def file(jid: int):
        j = _job(jid)
        p = Path(j["filepath"] or "")
        if not p.exists():
            raise HTTPException(404, "file not found")
        return FileResponse(p, filename=p.name)

    @app.get("/api/stream/{jid}")
    async def stream(jid: int):
        """Video pro přehrávač v GUI (podporuje HTTP Range, takže jde přetáčet)."""
        j = _job(jid)
        p = Path(j["filepath"] or "")
        if not p.exists():
            raise HTTPException(404, "file not found")
        mt = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mkv": "video/webm", ".webm": "video/webm", ".mov": "video/quicktime",
              ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".opus": "audio/ogg", ".ogg": "audio/ogg"}.get(p.suffix.lower(), "application/octet-stream")
        return FileResponse(p, media_type=mt, content_disposition_type="inline", filename=p.name)

    @app.post("/api/queue/{action}")
    async def queue_action(action: str):
        if action in ("pause", "pause_all"):
            # pause = nezačínat další, rozpracované doběhnou; pause_all = přerušit i rozpracované
            S.db.kv_set("queue_paused", True)
            S.db.kv_set("queue_pause_reason", "user")
            S.db.kv_set("queue_pause_hard", action == "pause_all")
        elif action == "resume":
            S.db.kv_set("queue_paused", False)
            S.db.kv_set("queue_pause_reason", None)
            S.db.kv_set("queue_pause_hard", False)
            S.db.kv_set("cookies_error", None)
        else:
            raise HTTPException(404)
        return {"ok": True}

    # ------------------------------------------------------------ historie
    # ------------------------------------------------------------ odběry
    def sub_out(s: dict, counts: dict) -> dict:
        d = {k: s[k] for k in ("id", "url", "kind", "title", "thumb_url", "folder", "since", "enabled", "last_check",
                               "last_error", "created_at", "check_hours")}
        d["tabs"] = json.loads(s["tabs"]) if s["tabs"] else None
        d["config"] = json.loads(s["config"]) if s.get("config") else None
        d["pending"] = len(json.loads(s["pending"])) if s["pending"] else 0
        d.update({"queued": 0, "running": 0, "done": 0, "failed": 0, "bytes": 0}, **counts.get(s["id"], {}))
        return d

    def parse_hours(v):
        """Vlastní interval kontroly v hodinách; prázdné/„default“ = globální nastavení."""
        if v in (None, "", "default", 0, "0"):
            return None
        try:
            h = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, "Neplatný interval kontroly.")
        if h not in subscriptions.CHECK_CHOICES:
            raise HTTPException(400, "Interval kontroly: 3 h, 6 h, 12 h, 1 den, 3 dny, 1 týden nebo 1 měsíc.")
        return h

    def parse_tabs(v):
        if v in (None, "", []):
            return None
        if not isinstance(v, list) or any(x not in ("videos", "shorts", "streams") for x in v):
            raise HTTPException(400, "záložky kanálu: videos, shorts, streams")
        return v

    async def check_folder(folder: str) -> str:
        folder = str(folder or "").strip()
        ok, msg = await asyncio.to_thread(check_dir_writable, folder)
        if not ok:
            raise HTTPException(400, msg)
        return str(Path(folder).expanduser())

    @app.get("/api/subscriptions")
    async def subs_list():
        counts = S.db.sub_counts()
        return {"items": [sub_out(s, counts) for s in S.db.sub_list()],
                "check_hours": S.settings.get("subscription_check_hours")}

    @app.post("/api/subscriptions/preview-page")
    async def subs_preview_page(req: Request):
        """Náhled odběru ze stránky: co by se našlo (díly s daty, vzor odkazů, stránkování)."""
        body = await req.json()
        urls = extract_urls(str(body.get("url") or ""))
        if not urls:
            raise HTTPException(400, "Zadejte platnou URL stránky se seznamem videí.")
        try:
            det = await pagelist.analyze(urls[0], S.settings.all())
        except pagelist.PageError as e:
            raise HTTPException(400, str(e))
        det["items"] = det["items"][:12]
        return det

    @app.post("/api/subscriptions")
    async def subs_add(req: Request):
        body = await req.json()
        urls = extract_urls(str(body.get("url") or ""))
        if not urls:
            raise HTTPException(400, "Zadejte platnou URL kanálu nebo playlistu.")
        url = urls[0]
        if S.db.query("select 1 from subscriptions where url=?", (url,)):
            raise HTTPException(409, "Tento odběr už existuje.")
        try:
            since = subscriptions.parse_since(body.get("since", "now"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        tabs = parse_tabs(body.get("tabs"))
        name = str(body.get("title") or "").strip() or None
        if body.get("kind") == "page":
            # odběr ze stránky s videi: bez kontroly přes yt-dlp, vzor odkazů najde a ověří pagelist
            try:
                det = await pagelist.analyze(url, S.settings.all())
            except pagelist.PageError as e:
                raise HTTPException(400, str(e))
            cfg = {k: det.get(k) for k in ("item_regex", "page_param", "page_start", "page_template")}
            for k in ("item_regex", "page_param", "page_template"):
                if body.get(k) is not None and str(body[k]).strip():
                    cfg[k] = str(body[k]).strip()
            try:
                re.compile(cfg["item_regex"])
            except re.error as e:
                raise HTTPException(400, f"Neplatný vzor odkazů: {e}")
            title = name or det.get("title") or urlparse(url).netloc
            folder = str(body.get("folder") or "").strip() or str(Path(S.settings.get("download_dir")) / sanitize_filename(title))
            folder = await check_folder(folder)
            sid = S.db.sub_add(url, folder, kind="page", title=title, since=since, config=cfg, check_hours=parse_hours(body.get("check_hours")))
            return sub_out(S.db.sub_get(sid), S.db.sub_counts())
        res = await probe_url(url, S.runner.ctx())
        if name:
            res["title"] = name
        if res["type"] == "none":
            # není to kanál ani video? Možná je to stránka se seznamem videí (odběr typu „Stránka“)
            try:
                det = await pagelist.analyze(url, S.settings.all())
            except pagelist.PageError:
                det = None
            if det and len(det["items"]) >= 2:
                raise HTTPException(400, f"Tato adresa není kanál ani playlist, ale vypadá jako stránka se seznamem videí "
                                         f"(nalezeno {len(det['items'])}). Přepněte zdroj na „Stránka s videi“.")
            raise HTTPException(400, f"URL se nepodařilo zkontrolovat: {res['error']}")
        if res["type"] not in ("channel", "playlist"):
            raise HTTPException(400, "Tato URL je jedno video, ne kanál ani playlist. Odběr jde zřídit jen na seznam videí.")
        folder = str(body.get("folder") or "").strip() or str(Path(S.settings.get("download_dir")) / sanitize_filename(res["title"] or "odběr"))
        folder = await check_folder(folder)
        sid = S.db.sub_add(url, folder, kind=res["type"], title=res.get("title"), thumb_url=res.get("thumb_url"),
                           since=since, tabs=tabs, check_hours=parse_hours(body.get("check_hours")))
        return sub_out(S.db.sub_get(sid), S.db.sub_counts())

    def need_sub(sid: int) -> dict:
        s = S.db.sub_get(sid)
        if not s:
            raise HTTPException(404, "Odběr neexistuje.")
        return s

    @app.get("/api/subscriptions/{sid}")
    async def subs_get(sid: int):
        return sub_out(need_sub(sid), S.db.sub_counts())

    @app.put("/api/subscriptions/{sid}")
    async def subs_put(sid: int, req: Request):
        need_sub(sid)
        body = await req.json()
        ch: dict = {}
        if "folder" in body:
            ch["folder"] = await check_folder(body["folder"])
        if "since" in body:
            try:
                ch["since"] = subscriptions.parse_since(body["since"])
            except ValueError as e:
                raise HTTPException(400, str(e))
            ch["seen_old"] = None   # závěry „starší než datum“ platily pro původní datum
        if "enabled" in body:
            ch["enabled"] = 1 if body["enabled"] else 0
        if "check_hours" in body:
            ch["check_hours"] = parse_hours(body["check_hours"])
        if "tabs" in body:
            ch["tabs"] = parse_tabs(body["tabs"])
        if "title" in body and str(body["title"]).strip():
            ch["title"] = str(body["title"]).strip()
        S.db.sub_update(sid, **ch)
        if "folder" in ch:   # už zařazená videa odběru se uloží do nové složky
            S.db.update_where("sub_id=? and status in ('new','probing','confirm','queued')", (sid,), target_dir=ch["folder"])
        return sub_out(S.db.sub_get(sid), S.db.sub_counts())

    @app.delete("/api/subscriptions/{sid}")
    async def subs_delete(sid: int, keep_history: bool = True):
        need_sub(sid)
        for j in S.db.query("select id from jobs where sub_id=? and status='running'", (sid,)):
            S.runner.cancel(j["id"])
        S.db.sub_delete(sid, keep_history=keep_history)
        return {"ok": True}

    @app.post("/api/subscriptions/{sid}/check")
    async def subs_check(sid: int):
        need_sub(sid)
        if not S.runner.check_subscription_now(sid):
            raise HTTPException(409, "Právě se kontroluje jiný odběr, zkuste to za chvíli.")
        return {"ok": True}

    @app.post("/api/subscriptions/{sid}/confirm")
    async def subs_confirm(sid: int):
        need_sub(sid)
        return {"queued": subscriptions.confirm_pending(S.db, sid)}

    @app.post("/api/subscriptions/{sid}/reject")
    async def subs_reject(sid: int):
        need_sub(sid)
        return {"rejected": subscriptions.reject_pending(S.db, sid)}

    @app.get("/api/history")
    async def history(q: str = "", status: str = "", days: int = 0, offset: int = 0, limit: int = 50, sub: int = 0):
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        rows = S.db.history(q=q, status=status, days=days, offset=offset, limit=limit, sub=sub)
        matched = S.db.history_count(q=q, status=status, days=days, sub=sub)
        total = S.db.query("select count(*) n, coalesce(sum(filesize),0) b from jobs where status='done'" + (" and sub_id=? and hide_sub=0" if sub else " and hide_global=0"),
                           (sub,) if sub else ())[0]

        def out():
            items = []
            for r in rows:
                o = job_out(r)
                if r["status"] == "done":
                    o["file_exists"] = bool(r.get("filepath")) and Path(r["filepath"]).exists()
                items.append(o)
            return items
        return {"items": await asyncio.to_thread(out), "total_done": total["n"], "total_bytes": total["b"],
                "matched": matched, "offset": offset, "limit": limit}

    @app.delete("/api/history")
    async def clear_history(req: Request):
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            body = {}
        f = body.get("filter")
        forgot = 0
        if body.get("forget_archive"):
            # vyřadit z archivu stažených jen hotová a přeskočená videa (jen u nich archiv záznam má);
            # musí proběhnout dřív, než záznamy zmizí z databáze
            if isinstance(f, dict):
                jobs = S.db.history(q=str(f.get("q") or ""), status=str(f.get("status") or ""), days=int(f.get("days") or 0), limit=10 ** 9, sub=int(f.get("sub") or 0))
            elif body.get("ids"):
                jobs = [j for j in (S.db.get(int(i)) for i in body["ids"]) if j]
            else:
                jobs = S.db.history(limit=10 ** 9)
            forgot = S.runner.archive_forget_many([j for j in jobs if j["status"] in ("done", "skipped")])
        scope = "both" if body.get("scope") == "both" else "here"
        if isinstance(f, dict):  # hromadně podle aktuálního filtru (hledání, stav, období)
            n = S.db.delete_history_matching(str(f.get("q") or ""), str(f.get("status") or ""), int(f.get("days") or 0), int(f.get("sub") or 0), scope)
        else:
            n = S.db.delete_history(body.get("ids"), int(body.get("view") or 0), scope)
        return {"deleted": n, "archive_removed": forgot}

    def _schedule_restart():
        stop = getattr(S, "stop", None)
        if stop is None:
            raise HTTPException(501, "Restart není v tomto režimu k dispozici")
        S.restart = True
        asyncio.get_running_loop().call_later(0.5, stop.set)

    @app.post("/api/restart")
    async def restart_app():
        """Řádně ukončí aplikaci a spustí ji znovu (rozpracovaná stahování se vrátí do fronty)."""
        _schedule_restart()
        return {"ok": True, "docker": in_docker()}

    # --- záloha a obnova (export a import) ------------------------------------------------------
    @app.get("/api/backup")
    async def backup_download(thumbs: int = 0, plain: int = 0):
        try:
            p = await asyncio.to_thread(backup.create, S.data, None, bool(thumbs), not plain)
        except backup.BackupError as e:
            raise HTTPException(400, str(e))
        return FileResponse(p, media_type="application/zip" if plain else "application/octet-stream",
                            filename=backup.default_name(not plain), background=BackgroundTask(p.unlink, missing_ok=True))

    def _restore_status():
        pend = backup.pending(S.data)
        return {"pending": pend, "last": backup.last_result(S.data)}

    @app.get("/api/restore")
    async def restore_status():
        return _restore_status()

    @app.post("/api/restore")
    async def restore_stage(file: UploadFile = File(...)):
        """Nahraje zálohu a ověří ji. Samotná obnova se provede až po potvrzení a restartu."""
        import shutil
        import tempfile
        tmp = Path(tempfile.mkstemp(suffix=".zip", prefix="vd-restore-")[1])
        try:
            with open(tmp, "wb") as out:
                shutil.copyfileobj(file.file, out, 1 << 20)
            man = await asyncio.to_thread(backup.stage, S.data, tmp)
        except backup.BackupError as e:
            raise HTTPException(400, str(e))
        finally:
            tmp.unlink(missing_ok=True)
        return {"manifest": man}

    @app.post("/api/restore/apply")
    async def restore_apply(req: Request):
        """Potvrdí obnovu: uloží případný přepis cest a restartuje aplikaci (obnova proběhne při startu)."""
        body = await req.json() if (await req.body()) else {}
        if backup.pending(S.data) is None:
            raise HTTPException(409, "Není připravená žádná záloha k obnově.")
        try:
            backup.set_remap(S.data, str(body.get("remap_old") or ""), str(body.get("remap_new") or ""))
        except backup.BackupError as e:
            raise HTTPException(400, str(e))
        _schedule_restart()
        return {"ok": True, "docker": in_docker()}

    # --- aktualizace aplikace zevnitř -----------------------------------------------------------
    async def _app_call(fn, *a, **kw):
        try:
            return await asyncio.to_thread(fn, *a, **kw)
        except appupdate.UpdateError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/app")
    async def app_status():
        return await asyncio.to_thread(updater.status, S)

    @app.post("/api/app/check")
    async def app_check():
        return await _app_call(updater.do_check, S)

    @app.post("/api/app/update")
    async def app_update(req: Request):
        body = await req.json() if (await req.body()) else {}
        return await _app_call(updater.do_update, S, bool(body.get("force")))

    @app.post("/api/app/apply")
    async def app_apply():
        """Restart po doběhnutí běžících stahování (fronta se měkce pozastaví a po restartu obnoví)."""
        st = await asyncio.to_thread(updater.status, S)
        if not st["prepared"]:
            raise HTTPException(409, "Žádná nová verze není připravená k restartu.")
        if st["applying"]:
            return st
        asyncio.get_running_loop().create_task(updater.apply_when_idle(S))
        await asyncio.sleep(0.05)
        return await asyncio.to_thread(updater.status, S)

    @app.post("/api/app/rollback")
    async def app_rollback(req: Request):
        body = await req.json() if (await req.body()) else {}
        return await _app_call(updater.do_rollback, S, bool(body.get("restore_db")))

    @app.post("/api/app/unskip")
    async def app_unskip(req: Request):
        ver = str((await req.json()).get("version") or "")
        await asyncio.to_thread(updater.store(S).unskip, ver)
        return await asyncio.to_thread(updater.status, S)

    @app.post("/api/app/dismiss")
    async def app_dismiss(req: Request):
        t = float((await req.json()).get("t") or 0)
        await asyncio.to_thread(updater.store(S).update_state, dismissed=t)
        updater._BANNER_CACHE["t"] = 0.0
        return await asyncio.to_thread(updater.status, S)

    @app.post("/api/app/token")
    async def app_token(req: Request):
        """Uloží (nebo smaže, když je prázdný) token pro čtení vydání z GitHubu. Zpět se nikdy nevrací."""
        S.secrets.set_app_update_token(str((await req.json()).get("token") or ""))
        return await asyncio.to_thread(updater.status, S)

    # --- automatické zálohy ---------------------------------------------------------------------
    async def _ab_status():
        fold = autobackup.folder(S.data, S.settings)
        items = await asyncio.to_thread(autobackup.list_backups, fold)
        return {"enabled": bool(S.settings.get("auto_backup")), "dir": str(fold), "hours": S.settings.get("auto_backup_hours"),
                "keep": S.settings.get("auto_backup_keep"), "state": autobackup.state(S.db),
                "next": autobackup.next_due(S.settings, S.db), "backups": items[:20]}

    @app.get("/api/autobackup")
    async def autobackup_status():
        return await _ab_status()

    @app.post("/api/autobackup/run")
    async def autobackup_run():
        try:
            await asyncio.to_thread(autobackup.run, S)
        except backup.BackupError as e:
            raise HTTPException(400, str(e))
        return await _ab_status()

    @app.post("/api/autobackup/restore")
    async def autobackup_restore(req: Request):
        """Připraví obnovu ze zálohy ve složce automatických záloh (bez stahování do prohlížeče)."""
        name = str((await req.json()).get("name") or "")
        p = autobackup.folder(S.data, S.settings) / name
        if not autobackup.NAME_RE.match(name) or not p.is_file():
            raise HTTPException(404, "Taková záloha ve složce není.")
        try:
            man = await asyncio.to_thread(backup.stage, S.data, p)
        except backup.BackupError as e:
            raise HTTPException(400, str(e))
        return {"manifest": man}

    @app.delete("/api/restore")
    async def restore_cancel():
        backup.clear_pending(S.data)
        return _restore_status()

    @app.get("/api/cpu")
    async def cpu_info():
        return dict(S.runner.cpu.out(), history=list(S.runner.cpu.history), mem_history=list(S.runner.cpu.mem_history),
                    rate_history={k: list(v) for k, v in S.runner.cpu.rate_history.items()}, step=2)

    # ------------------------------------------------------------ statistiky
    @app.get("/api/stats")
    async def stats(t0: float = 0, t1: float = 0, tz: int = 0, sub: int = 0):
        now = time.time()
        t1 = t1 or now + 1
        if not t0:   # celé období: od prvního záznamu
            r = S.db.query("select min(ts) m from downloads")[0]["m"]
            t0 = min(r or now, t1 - 86400)
        r = S.db.stats(t0, t1, tz, sub)
        # doplnit prázdné intervaly, ať graf nemá mezery
        step = {"%Y-%m-%d %H:00": 3600, "%Y-%m-%d": 86400}.get(r["fmt"])
        have = {x["b"]: x for x in r["series"]}
        out, off = [], tz * 60
        if step:
            cur = (int(t0 + off) // step) * step
            while cur < t1 + off:
                b = time.strftime(r["fmt"], time.gmtime(cur))
                out.append(have.get(b) or {"b": b, "n": 0, "bytes": 0, "failed": 0})
                cur += step
        else:
            y, m = time.gmtime(t0 + off)[:2]
            ey, em = time.gmtime(t1 + off)[:2]
            while (y, m) <= (ey, em):
                b = f"{y:04d}-{m:02d}"
                out.append(have.get(b) or {"b": b, "n": 0, "bytes": 0, "failed": 0})
                y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        r["series"] = out
        r["t0"], r["t1"] = t0, t1
        return r

    @app.delete("/api/stats")
    async def stats_reset():
        return {"deleted": S.db.stats_reset()}

    # ------------------------------------------------------------ nastavení
    def settings_out():
        cp = cookies_path()
        return {"values": S.settings.all(), "defaults": DEFAULTS, "choices": CHOICES,
                "locked": S.settings.locked_keys(), "has_password": S.secrets.has_password(),
                "telegram_token_set": bool(S.secrets.telegram_token),
                "cookies_file": {"exists": cp.exists(), "mtime": cp.stat().st_mtime if cp.exists() else None},
                "docker": in_docker()}

    @app.get("/api/settings")
    async def get_settings():
        return settings_out()

    async def validate_dirs(changes: dict) -> None:
        """Cílová a dočasná složka: musí jít zapisovat, jinak se uložení odmítne."""
        for key in ("download_dir", "temp_dir", "auto_backup_dir"):
            if key not in changes:
                continue
            val = str(changes[key] or "").strip()
            if key in ("temp_dir", "auto_backup_dir") and not val:
                changes[key] = ""
                continue
            ok, msg = await asyncio.to_thread(check_dir_writable, val)
            if not ok:
                raise HTTPException(400, msg)
            changes[key] = str(Path(val).expanduser())

    @app.put("/api/settings")
    async def put_settings(req: Request):
        body = await req.json()
        locked = S.settings.locked_keys()
        changes = {k: v for k, v in body.items() if k not in locked}
        if changes.get("cookies_mode") == "browser" and in_docker():
            raise HTTPException(400, "V Dockeru nelze číst cookies z prohlížeče – aplikace neběží na stejném počítači "
                                     "jako prohlížeč. Exportujte cookies do souboru cookies.txt a nahrajte ho.")
        await validate_dirs(changes)
        if changes.get("network_access") and not S.secrets.has_password():
            raise HTTPException(400, "Nastavte nejdřív heslo do GUI.")
        try:
            S.settings.update(changes)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if "telegram_chat_id" in changes and S.bot:
            S.bot.reload()
        return settings_out()

    @app.post("/api/settings/password")
    async def set_password(req: Request):
        body = await req.json()
        pw = str(body.get("password") or "")
        if pw and len(pw) < 6:
            raise HTTPException(400, "Heslo musí mít alespoň 6 znaků.")
        if not pw and S.settings.get("network_access"):
            raise HTTPException(400, "Při přístupu ze sítě je heslo povinné.")
        S.secrets.set_password(pw)
        r = JSONResponse(settings_out())
        if pw:
            r.set_cookie("vd_session", token(), httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)
        return r

    @app.post("/api/settings/telegram_token")
    async def set_tg(req: Request):
        body = await req.json()
        S.secrets.set_telegram_token(str(body.get("token") or ""))
        if S.bot:
            S.bot.reload()
        return settings_out()

    @app.post("/api/settings/cookies")
    async def upload_cookies(file: UploadFile = File(...)):
        data = await file.read()
        text = data.decode("utf-8", "replace")
        if "\t" not in text:
            raise HTTPException(400, "Soubor nevypadá jako cookies.txt (formát Netscape).")
        cp = cookies_path()
        cp.write_text(text, encoding="utf-8")
        try:
            os.chmod(cp, 0o600)
        except OSError:
            pass
        S.settings.update({"cookies_mode": "file"})
        return settings_out()

    @app.delete("/api/settings/cookies")
    async def delete_cookies():
        cookies_path().unlink(missing_ok=True)
        if S.settings.get("cookies_mode") == "file":
            S.settings.update({"cookies_mode": "none"})
        return settings_out()

    @app.get("/api/settings/export")
    async def export_settings():
        return Response(json.dumps(S.settings.export(), indent=2, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="viddown-settings.json"'})

    @app.post("/api/settings/import")
    async def import_settings(file: UploadFile = File(...)):
        try:
            d = json.loads((await file.read()).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(400, "Neplatný soubor nastavení.")
        locked = S.settings.locked_keys()
        changes = {k: v for k, v in d.items() if k in DEFAULTS and k not in locked and k != "network_access"}
        await validate_dirs(changes)
        try:
            S.settings.update(changes)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return settings_out()

    @app.post("/api/onboarded")
    async def onboarded():
        S.db.kv_set("onboarded", True)
        return {"ok": True}

    @app.get("/api/fs")
    async def fs(path: str = ""):
        """Jednoduchý prohlížeč složek pro výběr cílové složky."""
        p = Path(path).expanduser() if path else Path.home()
        if not p.exists() or not p.is_dir():
            p = Path.home()
        try:
            dirs = sorted([d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")], key=str.lower)[:300]
        except PermissionError:
            dirs = []
        return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs}

    # ------------------------------------------------------------ enginy
    @app.get("/api/engines")
    async def engines():
        st = await asyncio.to_thread(S.engines.status)
        S._engines_snapshot = st
        return {"engines": st, "log": (S.db.kv_get("engine_log", []) or [])[-80:], "busy": S.engines.busy,
                "chromium": S.engines.chromium_status(), "chromium_busy": getattr(S, "chromium_busy", False),
                "auto": S.settings.get("engine_auto_update"), "hours": S.settings.get("engine_update_hours"),
                "last_auto": S.db.kv_get("engine_last_auto")}

    async def _bg(fn, *a):
        async def run():
            try:
                await asyncio.to_thread(fn, *a)
            except Exception as e:  # noqa: BLE001
                S.engines.log(a[0] if a else "engine", f"chyba: {e}")
        asyncio.create_task(run())

    @app.post("/api/engines/check")
    async def engines_check():
        if S.engines.busy:
            raise HTTPException(409, "busy")
        await _bg(lambda: S.engines.update_all())
        return {"started": True}

    @app.post("/api/engines/{name}/{action}")
    async def engine_action(name: str, action: str, req: Request):
        if name == "chromium":
            if action != "install":
                raise HTTPException(404)
            S.chromium_busy = True

            async def inst():
                try:
                    ok, msg = await asyncio.to_thread(S.engines.chromium_install)
                    S.engines.log("chromium", "instalace OK" if ok else f"instalace selhala: {msg}")
                finally:
                    S.chromium_busy = False
            asyncio.create_task(inst())
            return {"started": True}
        if name not in S.engines.engines:
            raise HTTPException(404)
        if action == "update":
            if S.engines.busy:
                raise HTTPException(409, "busy")
            await _bg(S.engines.update, name)
            return {"started": True}
        if action == "test":
            await _bg(S.engines.test, name)
            return {"started": True}
        if action == "rollback":
            body = await req.json()
            try:
                v = S.engines.rollback(name, body.get("version"))
            except ValueError as e:
                raise HTTPException(400, str(e))
            return {"version": v}
        if action == "remove":
            body = await req.json()
            try:
                S.engines.get(name).remove(body["version"])
            except ValueError as e:
                raise HTTPException(400, str(e))
            return {"ok": True}
        raise HTTPException(404)

    @app.post("/api/telegram/test")
    async def tg_test():
        if not S.bot:
            raise HTTPException(400, "bot off")
        ok, msg = await S.bot.send_test()
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True}

    # ------------------------------------------------------------ statické soubory
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    async def index():
        # odkazy na JS a CSS dostanou číslo verze podle obsahu, takže prohlížeč nikdy nepoužije starou kopii
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for name in ("app.js", "app.css"):
            v = hashlib.md5((WEB / name).read_bytes()).hexdigest()[:10]
            html = html.replace(f"/static/{name}", f"/static/{name}?v={v}")
        return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(WEB / "icon.svg", media_type="image/svg+xml")

    return app
