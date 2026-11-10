"""SQLite: fronta, historie a drobný klíč-hodnota sklad.

Fronta = úlohy se stavem new/probing/confirm/queued/running.
Historie = koncové stavy done/failed/cancelled/skipped.
Pořadí určuje sloupec pos (reálné číslo), takže jde vkládat i mezi existující úlohy.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
create table if not exists jobs (
    id integer primary key autoincrement,
    url text not null,
    title text,
    status text not null default 'new',
    kind text not null default 'video',     -- video | playlist | channel
    method text,
    parent_id integer,
    pos real not null,
    paused integer not null default 0,
    source text not null default 'gui',     -- gui | cli | telegram
    tg_chat text,
    tg_msg text,
    auto_confirm integer not null default 0,
    subdir text,
    info text,                              -- JSON z kontroly URL
    thumb_url text,
    channel text,
    duration real,
    height integer,
    size_est integer,
    approx integer not null default 0,
    progress real,
    downloaded integer,
    total integer,
    speed real,
    eta integer,
    filepath text,
    filesize integer,
    error text,
    error_kind text,
    attempts integer not null default 0,
    not_before real,
    created_at real not null,
    updated_at real not null,
    started_at real,
    finished_at real
);
create index if not exists jobs_status on jobs(status);
create index if not exists jobs_parent on jobs(parent_id);
create index if not exists jobs_pos on jobs(pos);
create table if not exists kv (key text primary key, value text);
"""

ACTIVE = ("new", "probing", "confirm", "queued", "running")
FINAL = ("done", "failed", "cancelled", "skipped")

# Migrace schématu. Verze se ukládá do `pragma user_version`. Každá položka je (verze, SQL nebo funkce(conn)).
# NIKDY neupravujte hotovou migraci – změnu schématu přidejte jako novou položku na konec seznamu.
MIGRATIONS: list[tuple[int, object]] = [
    (1, SCHEMA),   # základní schéma (VidDown 0.1.0)
]


def _split_sql(script: str) -> list[str]:
    """Rozdělí skript na příkazy (kvůli transakci; executescript by ji předčasně potvrdil)."""
    out, buf = [], ""
    for line in script.splitlines():
        code = line.split("--", 1)[0]
        buf += code + "\n"
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


class SchemaTooNew(RuntimeError):
    """Databáze pochází z novější verze VidDown, než je tato."""


class DB:
    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        with self.conn() as c:
            c.execute("pragma journal_mode=wal")
        self.migrate()

    @property
    def schema_version(self) -> int:
        with self.conn() as c:
            return c.execute("pragma user_version").fetchone()[0]

    def migrate(self) -> list[int]:
        """Provede chybějící migrace. U existující databáze před tím uloží zálohu `<db>.v<stará verze>.bak`.
        Vrací seznam provedených verzí. Novější databázi než zná tento kód odmítne (ochrana před downgradem)."""
        latest = MIGRATIONS[-1][0]
        with self.conn() as c:
            cur = c.execute("pragma user_version").fetchone()[0]
            if cur > latest:
                raise SchemaTooNew(f"Databáze {self.path} má schéma verze {cur}, tato verze VidDown umí nejvýše {latest}. "
                                   "Spusťte novější VidDown, nebo obnovte zálohu databáze.")
            existing = c.execute("select 1 from sqlite_master where type='table' and name='jobs'").fetchone() is not None
            if cur == 0 and existing:
                cur = 1   # databáze z doby před migracemi = základní schéma
            pending = [m for m in MIGRATIONS if m[0] > cur]
            if not pending:
                if c.execute("pragma user_version").fetchone()[0] != latest:
                    c.execute(f"pragma user_version={latest}")
                return []
            if existing and cur >= 1:
                bak = self.path.with_name(f"{self.path.name}.v{cur}.bak")
                dst = sqlite3.connect(bak)
                try:
                    c.backup(dst)
                finally:
                    dst.close()
            done = []
            for ver, step in pending:
                try:
                    c.execute("begin immediate")
                    if callable(step):
                        step(c)
                    else:
                        for stmt in _split_sql(str(step)):
                            c.execute(stmt)
                    c.execute(f"pragma user_version={int(ver)}")
                    c.execute("commit")
                except Exception:
                    if c.in_transaction:
                        c.execute("rollback")
                    raise
                done.append(ver)
            return done

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    # ------------------------------------------------------------ úlohy
    def _next_pos(self, c) -> float:
        r = c.execute("select max(pos) from jobs").fetchone()[0]
        return (r or 0) + 1

    def add(self, url: str, source="gui", parent_id=None, pos=None, **fields) -> int:
        now = time.time()
        with self.conn() as c:
            c.execute("begin immediate")
            if pos is None:
                pos = self._next_pos(c)
            cols = {"url": url, "source": source, "parent_id": parent_id, "pos": pos,
                    "created_at": now, "updated_at": now, **fields}
            if "info" in cols and not isinstance(cols["info"], (str, type(None))):
                cols["info"] = json.dumps(cols["info"], ensure_ascii=False)
            q = f"insert into jobs({','.join(cols)}) values({','.join('?' * len(cols))})"
            jid = c.execute(q, list(cols.values())).lastrowid
            c.execute("commit")
            return jid

    def add_children(self, parent_id: int, entries: list[dict], subdir: str | None, source: str) -> list[int]:
        """Vloží položky playlistu na místo rodiče (mezi rodiče a další položku fronty)."""
        now = time.time()
        ids = []
        with self.conn() as c:
            c.execute("begin immediate")
            p = c.execute("select pos from jobs where id=?", (parent_id,)).fetchone()["pos"]
            nxt = c.execute("select min(pos) from jobs where pos>?", (p,)).fetchone()[0]
            hi = nxt if nxt is not None else p + 1
            n = len(entries)
            for i, e in enumerate(entries):
                pos = p + (hi - p) * (i + 1) / (n + 1)
                info = e.get("info")
                jid = c.execute(
                    "insert into jobs(url,title,status,kind,parent_id,pos,source,subdir,thumb_url,channel,duration,info,created_at,updated_at)"
                    " values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (e["url"], e.get("title"), "queued", "video", parent_id, pos, source, subdir,
                     e.get("thumb_url"), e.get("channel"), e.get("duration"),
                     json.dumps(info, ensure_ascii=False) if info else None, now, now)).lastrowid
                ids.append(jid)
            c.execute("commit")
        return ids

    def get(self, jid: int) -> dict | None:
        with self.conn() as c:
            r = c.execute("select * from jobs where id=?", (jid,)).fetchone()
            return dict(r) if r else None

    def update(self, jid: int, **kw) -> None:
        if not kw:
            return
        kw["updated_at"] = time.time()
        if "info" in kw and not isinstance(kw["info"], (str, type(None))):
            kw["info"] = json.dumps(kw["info"], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in kw)
        with self.conn() as c:
            c.execute(f"update jobs set {cols} where id=?", (*kw.values(), jid))

    def update_where(self, where: str, args: tuple, **kw) -> int:
        kw["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in kw)
        with self.conn() as c:
            return c.execute(f"update jobs set {cols} where {where}", (*kw.values(), *args)).rowcount

    def query(self, sql: str, args=()) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def queue(self) -> list[dict]:
        """Aktivní úlohy v pořadí fronty (včetně rodičů playlistů, které ještě mají aktivní děti)."""
        return self.query(
            "select * from jobs where status in ('new','probing','confirm','queued','running') "
            "or (status='expanded' and exists(select 1 from jobs c where c.parent_id=jobs.id "
            "and c.status in ('new','probing','confirm','queued','running'))) order by pos")

    @staticmethod
    def _history_where(q: str, status: str, days: int) -> tuple[str, list]:
        sql = " where status in ('done','failed','cancelled','skipped')"
        args: list = []
        if status:
            sql += " and status=?"
            args.append(status)
        if q:
            sql += " and (title like ? or url like ? or channel like ?)"
            args += [f"%{q}%"] * 3
        if days:
            sql += " and coalesce(finished_at, updated_at) >= ?"
            args.append(time.time() - days * 86400)
        return sql, args

    def history(self, q: str = "", status: str = "", days: int = 0, limit: int = 300, offset: int = 0) -> list[dict]:
        where, args = self._history_where(q, status, days)
        return self.query(f"select * from jobs{where} order by coalesce(finished_at, updated_at) desc, id desc limit ? offset ?",
                          args + [limit, offset])

    def history_count(self, q: str = "", status: str = "", days: int = 0) -> int:
        where, args = self._history_where(q, status, days)
        return self.query(f"select count(*) n from jobs{where}", args)[0]["n"]

    def find_active_url(self, url: str) -> dict | None:
        r = self.query("select * from jobs where url=? and status in ('new','probing','confirm','queued','running') limit 1", (url,))
        return r[0] if r else None

    def children(self, parent_id: int) -> list[dict]:
        return self.query("select * from jobs where parent_id=? order by pos", (parent_id,))

    def move(self, jid: int, before_id: int | None) -> None:
        """Přesune úlohu před úlohu before_id (None = na konec fronty)."""
        with self.conn() as c:
            c.execute("begin immediate")
            if before_id is None:
                pos = (c.execute("select max(pos) from jobs").fetchone()[0] or 0) + 1
            else:
                b = c.execute("select pos from jobs where id=?", (before_id,)).fetchone()["pos"]
                prev = c.execute("select max(pos) from jobs where pos<? and id<>?", (b, jid)).fetchone()[0]
                prev = prev if prev is not None else b - 1
                pos = (prev + b) / 2
            c.execute("update jobs set pos=?, updated_at=? where id=?", (pos, time.time(), jid))
            # děti playlistu se stěhují s rodičem
            kids = c.execute("select id from jobs where parent_id=? order by pos", (jid,)).fetchall()
            for i, k in enumerate(kids):
                c.execute("update jobs set pos=? where id=?", (pos + (i + 1) * 1e-6, k["id"]))
            c.execute("commit")

    def recover(self) -> None:
        """Po pádu nebo restartu vrátí rozběhnuté úlohy zpět do fronty."""
        with self.conn() as c:
            c.execute("update jobs set status='queued', speed=null, eta=null where status='running'")
            c.execute("update jobs set status='new' where status='probing'")

    def delete_history(self, ids: list[int] | None = None) -> int:
        with self.conn() as c:
            if ids:
                q = f"delete from jobs where id in ({','.join('?' * len(ids))}) and status in ('done','failed','cancelled','skipped')"
                return c.execute(q, ids).rowcount
            n = c.execute("delete from jobs where status in ('done','failed','cancelled','skipped')").rowcount
            c.execute("delete from jobs where status='expanded' and not exists(select 1 from jobs c where c.parent_id=jobs.id)")
            return n

    def delete_history_matching(self, q: str = "", status: str = "", days: int = 0) -> int:
        """Smaže všechny záznamy historie odpovídající filtru (hledání, stav, období)."""
        where, args = self._history_where(q, status, days)
        with self.conn() as c:
            n = c.execute(f"delete from jobs{where}", args).rowcount
            c.execute("delete from jobs where status='expanded' and not exists(select 1 from jobs c where c.parent_id=jobs.id)")
            return n

    def remap_paths(self, old: str, new: str, dry_run: bool = False) -> int:
        """Přepíše začátek cest stažených souborů (po přesunu na jiný počítač nebo svazek). Vrací počet záznamů."""
        old, new = old.rstrip("/"), new.rstrip("/")
        where, args = "filepath is not null and (filepath=? or substr(filepath,1,?)=?)", (old, len(old) + 1, old + "/")
        with self.conn() as c:
            if dry_run:
                return c.execute(f"select count(*) from jobs where {where}", args).fetchone()[0]
            return c.execute(f"update jobs set filepath=? || substr(filepath, ?) where {where}",
                             (new, len(old) + 1, *args)).rowcount

    def purge_older(self, days: int) -> int:
        if not days:
            return 0
        with self.conn() as c:
            return c.execute("delete from jobs where status in ('done','failed','cancelled','skipped') and coalesce(finished_at,updated_at)<?",
                             (time.time() - days * 86400,)).rowcount

    def stats_today(self) -> dict:
        start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        r = self.query("select status, count(*) n, coalesce(sum(filesize),0) b from jobs where finished_at>=? group by status", (start,))
        d = {x["status"]: x for x in r}
        return {"done": d.get("done", {}).get("n", 0), "failed": d.get("failed", {}).get("n", 0),
                "bytes": d.get("done", {}).get("b", 0)}

    # ------------------------------------------------------------ kv
    def kv_get(self, key: str, default=None):
        with self.conn() as c:
            r = c.execute("select value from kv where key=?", (key,)).fetchone()
        if r is None:
            return default
        try:
            return json.loads(r["value"])
        except json.JSONDecodeError:
            return default

    def kv_set(self, key: str, value) -> None:
        with self.conn() as c:
            c.execute("insert into kv(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
                      (key, json.dumps(value, ensure_ascii=False)))
