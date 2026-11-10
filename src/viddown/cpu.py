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


def preexec():
    """Funkce pro `preexec_fn` – nově spuštěný podproces dostane aktuální nižší prioritu. None = nic nedělat."""
    n = _nice
    if not n or sys.platform == "win32":
        return None

    def f() -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, 0, n)
        except OSError:
            pass
    return f


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


class Monitor:
    def __init__(self) -> None:
        self.percent: float | None = None
        self.cores = float(os.cpu_count() or 1)
        self.history: deque[float] = deque(maxlen=HISTORY)
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
                delta = self._psutil_total() if self._last_cpu is not None else None
                self._last_cpu = 0.0
            else:
                delta = None
            if delta is not None and self._last_t and dt > 0:
                self.percent = max(0.0, min(100.0, delta / (dt * max(0.1, self.cores)) * 100))
                self.history.append(round(self.percent, 1))
        except Exception as e:  # noqa: BLE001
            log.debug("měření CPU selhalo: %s", e)
        self._renice()

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
                "cores": round(self.cores, 2), "source": self.source}
