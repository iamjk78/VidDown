"""Vstupní bod pro zabalenou aplikaci (PyInstaller). Bez argumentů spustí aplikaci a otevře GUI."""
import multiprocessing
import os
import sys

from viddown.config import data_dir

# Runtime hook PyInstalleru nastavuje PLAYWRIGHT_BROWSERS_PATH=0 (prohlížeč uvnitř balíčku).
# Chromium ale stahujeme až při prvním spuštění, proto ho ukládáme do datové složky aplikace.
if os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "0") == "0":
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(data_dir() / "ms-playwright")

from viddown.cli import main  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # macOS předává při spuštění z Finderu argument -psn_…
    sys.argv = [a for a in sys.argv if not a.startswith("-psn_")]
    raise SystemExit(main())
