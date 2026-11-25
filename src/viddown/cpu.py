"""Měření vytížení procesoru touto aplikací a režimy výkonu (priorita podprocesů, vlákna ffmpeg, souběžnost).

Měření: v Dockeru se čte součet celého kontejneru z cgroup (přesně to, co zatěžuje NAS), jinde se sečtou časy
procesu a jeho potomků přes psutil. Výsledek je v procentech celého procesoru (100 % = všechna jádra).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from pathlib import Path

try:
    import psutil
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore[assignment]

log = logging.getLogger("viddown.cpu")

# režim -> (nice podprocesů, vlákna ffmpeg v yt-dlp (0 = bez omezení), nejvýše souběžných stahování (0 = bez omezení))
MODES: dict[str, tuple[int, int, int]] = {"full": (0, 0, 0), "balanced": (10, 2, 0), "eco": (19, 1, 1)}
SAMPLE_EVERY = 2.0
HISTORY = 900           # 30 minut po 2 s

_nice = 0               # priorita pro nově spouštěné podprocesy (nastavuje Monitor)


def current_nice() -> int:
    return _nice


def apply_nice(pid: int) -> None:
    """Nastaví právě spuštěnému podprocesu aktuální nižší prioritu (rodičem, ne `preexec_fn`: ten je v aplikaci s vlákny nebezpečný)."""
    n = _nice
    if not n or sys.platform == "win32":
        return
    try:
        os.setpriority(os.PRIO_PROCESS, pid, n)
    except OSError:
        pass


def win_flags() -> int:
    if _nice >= 19:
        return 0x00000040   # IDLE_PRIORITY_CLASS
    if _nice > 0:
        return 0x00004000   # BELOW_NORMAL_PRIORITY_CLASS
    return 0


def _read(p: str) -> str | None:
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None


def _cgroup_usage() -> tuple[float, float] | None:
    """(spotřebovaný CPU čas v sekundách, počet jader dostupných kontejneru) nebo None."""
    ncpu = float(os.cpu_count() or 1)
    t = _read("/sys/fs/cgroup/cpu.stat")
    if t:  # cgroup v2
        for line in t.splitlines():
            if line.startswith("usage_usec"):
                cm = (_read("/sys/fs/cgroup/cpu.max") or "max 100000").split()
                if cm[0] != "max":
                    ncpu = min(ncpu, int(cm[0]) / max(1, int(cm[1])))
                return int(line.split()[1]) / 1e6, ncpu
    u = _read("/sys/fs/cgroup/cpuacct/cpuacct.usage") or _read("/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage")   # cgroup v1
    if u:
        q = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        per = _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if q and per and int(q) > 0:
            ncpu = min(ncpu, int(q) / max(1, int(per)))
        return int(u) / 1e9, ncpu
    return None


def _meminfo_total() -> float:
    t = _read("/proc/meminfo") or ""
    for line in t.splitlines():
        if line.startswith("MemTotal:"):
            return float(line.split()[1]) * 1024
    return psutil.virtual_memory().total if psutil else 0.0


def _cgroup_mem() -> tuple[float, float] | None:
    """(používaná paměť v B bez diskové cache, limit v B) celého kontejneru nebo None."""
    total = _meminfo_total()
    cur = _read("/sys/fs/cgroup/memory.current")
    if cur:   # cgroup v2
        inactive = 0
        for line in (_read("/sys/fs/cgroup/memory.stat") or "").splitlines():
            if line.startswith("inactive_file "):
                inactive = int(line.split()[1])
        lim = _read("/sys/fs/cgroup/memory.max")
        limit = total if not lim or lim == "max" else min(total or float(lim), float(lim))
        return max(0.0, int(cur) - inactive), limit
    cur = _read("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if cur:   # cgroup v1
        inactive = 0
        for line in (_read("/sys/fs/cgroup/memory/memory.stat") or "").splitlines():
            if line.startswith("total_inactive_file "):
                inactive = int(line.split()[1])
        lim = float(_read("/sys/fs/cgroup/memory/memory.limit_in_bytes") or 0)
        return max(0.0, int(cur) - inactive), min(total, lim) if total and lim else (lim or total)
    return None


def _psutil_mem() -> tuple[float, float] | None:
    if not psutil:
        return None
    me = psutil.Process()
    used = 0.0
    for p in [me, *me.children(recursive=True)]:
        try:
            used += p.memory_info().rss
        except psutil.Error:
            pass
    return used, float(psutil.virtual_memory().total)


def _net_totals() -> tuple[float, float] | None:
    """(přijato, odesláno) v bajtech přes všechna rozhraní kromě lo – v Dockeru jen provoz kontejneru."""
    if not psutil:
        return None
    try:
        c = psutil.net_io_counters(pernic=True)
    except Exception:  # noqa: BLE001
        return None
    rx = sum(v.bytes_recv for k, v in c.items() if k != "lo" and not k.startswith("lo"))
    tx = sum(v.bytes_sent for k, v in c.items() if k != "lo" and not k.startswith("lo"))
    return float(rx), float(tx)


class Monitor:
    def __init__(self) -> None:
        self.percent: float | None = None
        self.cores = float(os.cpu_count() or 1)
        self.history: deque[float] = deque(maxlen=HISTORY)
        self.mem_history: deque[float] = deque(maxlen=HISTORY)   # využití paměti v %
        self.mem: tuple[float, float] | None = None
        # rychlosti v B/s: síť přijato/odesláno (celý kontejner), zápis a čtení souborů procesy aplikace
        self.rates: dict[str, float | None] = {"net_in": None, "net_out": None, "io_w": None, "io_r": None}
        self.rate_history: dict[str, deque[float]] = {k: deque(maxlen=HISTORY) for k in self.rates}
        self._net_prev: tuple[float, float] | None = None
        self._io_prev: dict[int, tuple[float, float]] = {}
        self.mode = "full"
        self.source = "cgroup" if _cgroup_usage() else ("psutil" if psutil else None)
        self._last_t = 0.0
        self._last_cpu: float | None = None
        self._pids: dict[int, float] = {}
        self._applied: dict[int, int] = {}

    # -------------------------------------------------------------- měření
    def _psutil_total(self) -> float:
        me = psutil.Process()
        total, cur = 0.0, {}
        for p in [me, *me.children(recursive=True)]:
            try:
                t = p.cpu_times()
            except psutil.Error:
                continue
            cur[p.pid] = t.user + t.system
        total = sum(v - self._pids.get(pid, 0.0) for pid, v in cur.items())
        self._pids = cur
        return max(0.0, total)

    def sample(self, mode: str = "full") -> None:
        """Volá se z hlavní smyčky; sama si hlídá odstup. Také prosazuje prioritu podprocesů."""
        global _nice
        now = time.monotonic()
        if now - self._last_t < SAMPLE_EVERY:
            return
        dt, self._last_t = now - self._last_t, now
        self.mode = mode if mode in MODES else "full"
        _nice = MODES[self.mode][0]
        try:
            cg = _cgroup_usage() if self.source == "cgroup" else None
            if cg:
                used, self.cores = cg
                delta = None if self._last_cpu is None else used - self._last_cpu
                self._last_cpu = used
            elif psutil:
                first = self._last_cpu is None
                total_now = self._psutil_total()             # při prvním měření jen uloží výchozí stav (jinak by byl celý dosavadní čas špička)
                delta = None if first else total_now
                self._last_cpu = 0.0
            else:
                delta = None
            if delta is not None and self._last_t and dt > 0:
                self.percent = max(0.0, min(100.0, delta / (dt * max(0.1, self.cores)) * 100))
                self.history.append(round(self.percent, 1))
        except Exception as e:  # noqa: BLE001
            log.debug("měření CPU selhalo: %s", e)
        try:
            self.mem = (_cgroup_mem() if self.source == "cgroup" else None) or _psutil_mem()
            if self.mem and self.mem[1]:
                self.mem_history.append(round(self.mem[0] / self.mem[1] * 100, 1))
        except Exception as e:  # noqa: BLE001
            log.debug("měření paměti selhalo: %s", e)
        try:
            self._rates(dt)
        except Exception as e:  # noqa: BLE001
            log.debug("měření I/O selhalo: %s", e)
        self._renice()

    def _rates(self, dt: float) -> None:
        out: dict[str, float | None] = {k: None for k in self.rates}
        nt = _net_totals()
        if nt:
            if self._net_prev:
                out["net_in"] = max(0.0, (nt[0] - self._net_prev[0]) / dt)
                out["net_out"] = max(0.0, (nt[1] - self._net_prev[1]) / dt)
            self._net_prev = nt
        if psutil and sys.platform.startswith("linux"):
            me = psutil.Process()
            cur: dict[int, tuple[float, float]] = {}
            for p in [me, *me.children(recursive=True)]:
                try:
                    io = p.io_counters()
                except (psutil.Error, OSError):
                    continue
                cur[p.pid] = (float(io.write_chars), float(io.read_bytes))   # write_chars zahrnuje i zápis na síťový disk
            if self._io_prev:
                out["io_w"] = max(0.0, sum(v[0] - self._io_prev.get(pid, (0.0, 0.0))[0] for pid, v in cur.items()) / dt)
                out["io_r"] = max(0.0, sum(v[1] - self._io_prev.get(pid, (0.0, 0.0))[1] for pid, v in cur.items()) / dt)
            self._io_prev = cur
        self.rates = out
        for k, v in out.items():
            if v is not None:
                self.rate_history[k].append(round(v))

    def _renice(self) -> None:
        """Podprocesy, které vznikly mimo náš kód (Chromium, node), převedeme na cílovou prioritu."""
        if not psutil:
            return
        target = _nice
        try:
            kids = psutil.Process().children(recursive=True)
        except psutil.Error:
            return
        alive = set()
        for p in kids:
            alive.add(p.pid)
            if self._applied.get(p.pid) == target:
                continue
            try:
                if sys.platform == "win32":
                    p.nice(psutil.IDLE_PRIORITY_CLASS if target >= 19 else psutil.BELOW_NORMAL_PRIORITY_CLASS if target > 0 else psutil.NORMAL_PRIORITY_CLASS)
                else:
                    p.nice(target)
                self._applied[p.pid] = target
            except (psutil.Error, OSError, PermissionError):
                self._applied[p.pid] = target   # (zvýšit prioritu zpět bez oprávnění nejde – doběhne s nižší)
        for pid in list(self._applied):
            if pid not in alive:
                del self._applied[pid]

    def out(self) -> dict:
        return {"percent": None if self.percent is None else round(self.percent, 1), "mode": self.mode,
                "cores": round(self.cores, 2), "source": self.source,
                "mem": {"used": int(self.mem[0]), "total": int(self.mem[1])} if self.mem else None,
                "rates": {k: (None if v is None else int(v)) for k, v in self.rates.items()}}
