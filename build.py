"""Build a standalone executable with PyInstaller:  python build.py

Produces dist/MSSB Editor/ (one-folder build, starts fastest). The
executable opens the desktop window; run it with arguments for the CLI, e.g.
`"MSSB Editor.exe" list --kind hvqm4`. Put the game files next to it
(see README "Setup") or set MSSB_DECOMP.

`python build.py --installer` also packs that folder into an installer:
on Windows dist/MSSB Editor Setup <version>.exe with NSIS
(installer/installer.nsi; needs makensis on PATH or in its default folder),
on macOS dist/MSSB Editor <version>.dmg holding the .app bundle and an
Applications shortcut (hdiutil). The version comes from zzzzdat/version.py.
"""
import os
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
    *(["--icon", str(ROOT / "zzzzdat" / "ui" / "icon.icns"), "--osx-bundle-identifier", "com.littlecoaks.mssbeditor"]
      if sys.platform == "darwin" and (ROOT / "zzzzdat" / "ui" / "icon.icns").exists() else []),
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

sys.path.insert(0, str(ROOT))
from zzzzdat.version import VERSION as version  # noqa: E402

if sys.platform == "darwin":
    # a disk image with the .app and an Applications shortcut, the usual drag-to-install
    app = ROOT / "dist" / "MSSB Editor.app"
    if not app.exists():
        sys.exit("PyInstaller did not produce dist/MSSB Editor.app")
    stage = ROOT / "dist" / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copytree(app, stage / app.name, symlinks=True)
    os.symlink("/Applications", stage / "Applications")
    dmg = ROOT / "dist" / f"MSSB Editor {version}.dmg"
    dmg.unlink(missing_ok=True)
    cmd = ["hdiutil", "create", "-volname", "MSSB Editor", "-srcfolder", str(stage), "-ov", "-format", "UDZO", str(dmg)]
    print(" ".join(cmd))
    sys.exit(subprocess.call(cmd))

candidates = [r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe"]
makensis = shutil.which("makensis") or next((c for c in candidates if Path(c).exists()), None)
if not makensis:
    sys.exit("makensis not found: install NSIS (https://nsis.sourceforge.io) to build the installer")
cmd = [makensis, "/V3", f"/DVERSION={version}", f"/DROOT={ROOT}", str(ROOT / "installer" / "installer.nsi")]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=ROOT))
