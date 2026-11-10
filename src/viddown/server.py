"""HTTP API a webové GUI (FastAPI)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, thumbs
from .config import DEFAULTS, CHOICES, cookies_path
from .util import check_dir_writable, extract_urls, in_docker, in_schedule

WEB = Path(__file__).parent / "web"

JOB_FIELDS = ("id", "url", "title", "status", "kind", "method", "parent_id", "pos", "paused", "source", "channel",
              "duration", "height", "size_est", "approx", "progress", "downloaded", "total", "speed", "eta", "filepath",
              "filesize", "error", "error_kind", "attempts", "not_before", "created_at", "finished_at", "thumb_url", "subdir")


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
        return {
            "queue": q,
            "stats": {
                "running": len(running), "concurrency": s["concurrency"],
                "waiting": len(waiting) + playlists_pending,
                "paused": sum(1 for j in q if j["paused"] and j["kind"] == "video"),
                "size_est": sum((j["size_est"] or 0) for j in waiting),
                "speed": sum((j["speed"] or 0) for j in running),
                "rate_limit": s["rate_limit_mbps"] if s["rate_limit_enabled"] else None,
                "today": S.db.stats_today(),
            },
            "queue_paused": bool(S.db.kv_get("queue_paused", False)),
            "pause_reason": S.db.kv_get("queue_pause_reason"),
            "target_error": S.db.kv_get("target_error"),
            "cookies_error": S.db.kv_get("cookies_error"),
            "schedule": {"enabled": s["schedule_enabled"], "start": s["schedule_start"], "end": s["schedule_end"]},
            "in_window": in_schedule(s),
            "disk": dict(S.runner.disk_status(s), dir=s["download_dir"], min_gb=s["min_free_gb"],
                         low_kind=S.db.kv_get("disk_low")),
            "telegram": S.bot.status() if S.bot else {"state": "off"},
            "engines": {e["name"]: (e["current"] or (f"{e['system']} (systém)" if e["system"] else None))
                        for e in S.engines_cache()},
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
        if action == "pause":
            S.db.kv_set("queue_paused", True)
            S.db.kv_set("queue_pause_reason", "user")
        elif action == "resume":
            S.db.kv_set("queue_paused", False)
            S.db.kv_set("queue_pause_reason", None)
            S.db.kv_set("cookies_error", None)
        else:
            raise HTTPException(404)
        return {"ok": True}

    # ------------------------------------------------------------ historie
    @app.get("/api/history")
    async def history(q: str = "", status: str = "", days: int = 0, offset: int = 0, limit: int = 50):
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        rows = S.db.history(q=q, status=status, days=days, offset=offset, limit=limit)
        matched = S.db.history_count(q=q, status=status, days=days)
        total = S.db.query("select count(*) n, coalesce(sum(filesize),0) b from jobs where status='done'")[0]

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
                jobs = S.db.history(q=str(f.get("q") or ""), status=str(f.get("status") or ""), days=int(f.get("days") or 0), limit=10 ** 9)
            elif body.get("ids"):
                jobs = [j for j in (S.db.get(int(i)) for i in body["ids"]) if j]
            else:
                jobs = S.db.history(limit=10 ** 9)
            forgot = S.runner.archive_forget_many([j for j in jobs if j["status"] in ("done", "skipped")])
        if isinstance(f, dict):  # hromadně podle aktuálního filtru (hledání, stav, období)
            n = S.db.delete_history_matching(str(f.get("q") or ""), str(f.get("status") or ""), int(f.get("days") or 0))
        else:
            n = S.db.delete_history(body.get("ids"))
        return {"deleted": n, "archive_removed": forgot}

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
        for key in ("download_dir", "temp_dir"):
            if key not in changes:
                continue
            val = str(changes[key] or "").strip()
            if key == "temp_dir" and not val:
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
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(WEB / "icon.svg", media_type="image/svg+xml")

    return app
