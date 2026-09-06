"""Build a standalone executable with PyInstaller:  python build.py

Produces dist/MSSB Editor/ (one-folder build, starts fastest). The
executable opens the desktop window; run it with arguments for the CLI, e.g.
`"MSSB Editor.exe" list --kind hvqm4`. Put the game files next to it
(see README "Setup") or set MSSB_DECOMP.

`python build.py --installer` also packs that folder into
dist/MSSB Editor Setup <version>.exe with NSIS (installer/installer.nsi):
Program Files, Start menu and optional desktop shortcut, an uninstaller that
leaves the user's settings, cache and exports alone. Needs makensis
(https://nsis.sourceforge.io) on PATH or in its default folder.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sep = ";" if sys.platform == "win32" else ":"
helper = "hvqm4dec.exe" if sys.platform == "win32" else "hvqm4dec"  # built by native/build_hvqm4.py, shipped next to the exe
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
    "--name", "MSSB Editor",
    "--windowed" if "--console" not in sys.argv else "--console",
    *(["--icon", str(ROOT / "zzzzdat" / "ui" / "icon.ico")] if sys.platform == "win32" else []),  # drawn by tools/make_icon.py
    "--add-data", f"{ROOT / 'zzzzdat' / 'ui'}{sep}zzzzdat/ui",
    "--add-data", f"{ROOT / 'index'}{sep}index",
    *(["--add-binary", f"{ROOT / 'native' / 'bin' / helper}{sep}."] if (ROOT / "native" / "bin" / helper).exists() else []),
    "--collect-all", "webview",
    "--collect-submodules", "zzzzdat",
    "--collect-all", "miniaudio",
    "--hidden-import", "numpy",
    str(ROOT / "run.py"),
]
print(" ".join(cmd))
rc = subprocess.call(cmd, cwd=ROOT)
if rc or "--installer" not in sys.argv:
    sys.exit(rc)

version = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
candidates = [r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe"]
makensis = shutil.which("makensis") or next((c for c in candidates if Path(c).exists()), None)
if not makensis:
    sys.exit("makensis not found: install NSIS (https://nsis.sourceforge.io) to build the installer")
cmd = [makensis, f"/DVERSION={version}", str(ROOT / "installer" / "installer.nsi")]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=ROOT))
