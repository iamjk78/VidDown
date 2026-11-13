"""Spouštěč: vybere, který kód aplikace se má spustit (verze z obrazu, nebo aktualizovaná z `<data>/app/`).

Používá se jako vstupní bod `viddown`. Záměrně bez závislostí a s ochranou proti chybě: cokoli se pokazí,
spustí se verze zabudovaná v obraze. Aktualizovaná verze se spustí novým procesem (`execve`, stejné PID),
s `PYTHONPATH` na její složku, takže se importuje místo balíčku z obrazu.
"""
from __future__ import annotations

import os
import sys

# Co umí obraz. Zvyšuje se při změně závislostí (pyproject.toml) nebo Dockerfile; vydání může vyžadovat vyšší hodnotu.
IMAGE_API = 2   # 2: závislost cryptography (šifrované zálohy .dtb)


def _choose(argv: list[str]):
    from .appupdate import AppStore
    from .config import data_dir
    store = AppStore(data_dir())
    if not store.file.exists():
        return None
    count = not argv or argv[0] == "serve"      # jen start aplikace se počítá do zkušební doby
    return store.begin_start(count=count)


def _exec(target, argv: list[str]):
    from . import __version__
    from .db import MIGRATIONS
    env = dict(os.environ)
    env.update(VIDDOWN_APP_ACTIVE=target.name, VIDDOWN_BASE_VERSION=__version__, VIDDOWN_IMAGE_API=str(IMAGE_API),
               VIDDOWN_BASE_SCHEMA=str(MIGRATIONS[-1][0]))
    env["PYTHONPATH"] = str(target) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    os.execve(sys.executable, [sys.executable, "-m", "viddown.cli", *argv], env)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not os.environ.get("VIDDOWN_APP_ACTIVE") and not getattr(sys, "frozen", False):
        try:
            target = _choose(argv)
        except Exception as e:  # noqa: BLE001 – spouštěč nesmí aplikaci shodit
            print(f"VidDown: aktualizovanou verzi nelze vybrat ({e}), spouštím verzi z obrazu", file=sys.stderr)
            target = None
        if target:
            _exec(target, argv)
    from .cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
