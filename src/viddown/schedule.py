"""Časový rozvrh (PLAN.md kap. 21): kdy smí aplikace automaticky pracovat.

Rozvrh tvoří pravidla; každé pravidlo má dny v týdnu (0 = pondělí) a jedno až osm časových oken „HH:MM“–„HH:MM“.
Pravidla a okna se sčítají. Okno přes půlnoc (např. 22:00–06:00) platí podle dne začátku; stejný začátek a konec
znamená celý den. Čas je místní čas serveru, přechod letního času se řeší sám.

Rozvrh řídí zvolené činnosti (`schedule_scope`): stahování fronty (`queue`), kontroly odběrů (`subscriptions`) a
zjišťování katalogu (`catalog`). Mimo okno nezačne nová automatická práce. Dočasná výjimka (`set_override`) rozvrh na
1, 3 nebo 6 hodin obejde. Nastavení z doby jednoho okna (`schedule_start`, `schedule_end`, `schedule_days`) se čte dál,
dokud nevzniknou pravidla (`effective_rules`).
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, time as dtime, timedelta

SCOPES = ("queue", "subscriptions", "catalog")
MAX_RULES = 20
MAX_WINDOWS = 8
OVERRIDE_CHOICES = (1, 3, 6)
OVERRIDE_KV = "schedule_override_until"
HORIZON_DAYS = 9                      # jak daleko se hledá další okno
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _minutes(value) -> int:
    m = _HHMM.match(value) if isinstance(value, str) else None
    if not m:
        raise ValueError(f"invalid time: {value!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalize_rules(raw) -> list[dict]:
    """Ověří a zapíše pravidla do jednotného tvaru. Neplatný vstup vyhodí ValueError."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        raise ValueError(f"schedule_rules must be a list of at most {MAX_RULES} rules")
    out = []
    for r in raw:
        if not isinstance(r, dict):
            raise ValueError("a rule must be an object")
        days = r.get("days")
        if not isinstance(days, list) or not days or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise ValueError("a rule needs days (0 = Monday … 6 = Sunday)")
        wins = r.get("windows")
        if not isinstance(wins, list) or not 1 <= len(wins) <= MAX_WINDOWS:
            raise ValueError(f"a rule needs 1 to {MAX_WINDOWS} time windows")
        norm = []
        for w in wins:
            if not isinstance(w, (list, tuple)) or len(w) != 2:
                raise ValueError("a window is [start, end]")
            norm.append([_fmt(_minutes(w[0])), _fmt(_minutes(w[1]))])
        out.append({"days": sorted(set(days)), "windows": sorted(norm)})
    return out


def normalize_rules_safe(raw) -> list[dict]:
    try:
        return normalize_rules(raw)
    except ValueError:
        return []


def effective_rules(settings) -> list[dict]:
    """Pravidla, podle kterých se rozhoduje: nová, a když žádná nejsou, jedno pravidlo z dřívějšího nastavení."""
    rules = settings.get("schedule_rules") or []
    if rules:
        return rules
    start, end = settings.get("schedule_start"), settings.get("schedule_end")
    if start and end:
        return [{"days": list(settings.get("schedule_days") or []), "windows": [[start, end]]}]
    return []


def is_legacy(settings) -> bool:
    return not (settings.get("schedule_rules") or [])


def _intervals(rules: list[dict], first: date, days: int) -> list[tuple[float, float]]:
    """Úseky (od, do) jako časy, kdy je rozvrh otevřený, pro dny `first` až `first + days`, sloučené a seřazené."""
    spans = []
    for i in range(days + 1):
        d = first + timedelta(days=i)
        for r in rules:
            if d.weekday() not in r["days"]:
                continue
            for s, e in r["windows"]:
                sm, em = _minutes(s), _minutes(e)
                start = datetime.combine(d, dtime(sm // 60, sm % 60))
                if sm == em:                                        # stejný začátek a konec = celý den
                    start, end = datetime.combine(d, dtime(0, 0)), datetime.combine(d + timedelta(days=1), dtime(0, 0))
                elif sm < em:
                    end = datetime.combine(d, dtime(em // 60, em % 60))
                else:                                               # přes půlnoc
                    end = datetime.combine(d + timedelta(days=1), dtime(em // 60, em % 60))
                spans.append((start.timestamp(), end.timestamp()))
    spans.sort()
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def state(settings, now: float | None = None) -> dict:
    """Podle samotných pravidel (bez přepínače a výjimky): zda je otevřeno, kdy se zavře a kdy se otevře další okno."""
    now = time.time() if now is None else now
    rules = effective_rules(settings)
    if not rules:
        return {"open": False, "closes": None, "next_open": None}
    first = datetime.fromtimestamp(now).date() - timedelta(days=1)
    spans = _intervals(rules, first, HORIZON_DAYS + 1)
    for a, b in spans:
        if a <= now < b:
            return {"open": True, "closes": b, "next_open": None}
    nxt = min((a for a, _ in spans if a > now), default=None)
    return {"open": False, "closes": None, "next_open": nxt}


def override_until(db, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    until = db.kv_get(OVERRIDE_KV)
    return float(until) if isinstance(until, (int, float)) and until > now else None


def set_override(db, hours: int, now: float | None = None) -> float:
    if isinstance(hours, bool) or hours not in OVERRIDE_CHOICES:        # True by se jinak bralo jako 1
        raise ValueError(f"hours must be one of {OVERRIDE_CHOICES}")
    until = (time.time() if now is None else now) + hours * 3600
    db.kv_set(OVERRIDE_KV, until)
    return until


def clear_override(db) -> None:
    db.kv_set(OVERRIDE_KV, None)


def allowed(settings, scope: str, now: float | None = None, db=None) -> bool:
    """Smí teď automatická práce typu `scope` začít? Rozvrh vypnutý, činnost mimo rozsah rozvrhu nebo platná dočasná
    výjimka znamenají ano; jinak rozhodují okna."""
    if not settings.get("schedule_enabled"):
        return True
    if scope not in (settings.get("schedule_scope") or ["queue"]):
        return True
    if db is not None and override_until(db, now) is not None:
        return True
    return state(settings, now)["open"]


def describe(settings, db=None, now: float | None = None) -> dict:
    """Stav rozvrhu pro GUI."""
    now = time.time() if now is None else now
    st = state(settings, now)
    scope = list(settings.get("schedule_scope") or ["queue"])
    over = override_until(db, now) if db is not None else None
    return {"enabled": bool(settings.get("schedule_enabled")), "scope": scope, "finish_running": bool(settings.get("schedule_finish_running")),
            "rules": effective_rules(settings), "legacy": is_legacy(settings), "open": st["open"], "closes": st["closes"],
            "next_open": st["next_open"], "override_until": over,
            "allowed": {s: allowed(settings, s, now, db) for s in SCOPES}}
