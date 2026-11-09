# PyInstaller spec – sestavení: pyinstaller packaging/viddown.spec
# macOS: dist/VidDown.app (dvojklik spustí aplikaci a otevře GUI; CLI: VidDown.app/Contents/MacOS/viddown add URL)
# Windows: dist/viddown/viddown.exe
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
datas = collect_data_files("viddown", includes=["web/*"])
datas += collect_data_files("playwright", includes=["driver/**/*"])
hidden = collect_submodules("uvicorn") + ["viddown.daemon", "viddown.server", "viddown.telegram", "multipart"]

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT / "src")], datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="viddown", console=sys.platform != "darwin",
          disable_windowed_traceback=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="viddown")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="VidDown.app", bundle_identifier="cz.viddown.app",
                 info_plist={"CFBundleShortVersionString": "0.1.0", "LSBackgroundOnly": False, "NSHighResolutionCapable": True})
