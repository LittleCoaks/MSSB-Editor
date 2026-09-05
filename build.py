"""Build a standalone executable with PyInstaller:  python build.py

Produces dist/MSSB Editor/ (one-folder build, starts fastest). The
executable opens the desktop window; run it with arguments for the CLI, e.g.
`"MSSB Editor.exe" list --kind hvqm4`. Put the game files next to it
(see README "Setup") or set MSSB_DECOMP.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sep = ";" if sys.platform == "win32" else ":"
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
    "--name", "MSSB Editor",
    "--windowed" if "--console" not in sys.argv else "--console",
    "--add-data", f"{ROOT / 'zzzzdat' / 'ui'}{sep}zzzzdat/ui",
    "--add-data", f"{ROOT / 'index'}{sep}index",  # includes index/thumbs
    "--collect-all", "webview",
    "--collect-all", "miniaudio",
    "--hidden-import", "numpy",
    str(ROOT / "run.py"),
]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=ROOT))
