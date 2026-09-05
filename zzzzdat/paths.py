"""Where things live.

Two kinds of location:

* **Shipped, read-only data** (`PACKAGE_DATA`): the index and the built UI.
  In a PyInstaller bundle this is the unpacked bundle; in development it is
  the repository root.
* **Per-user, writable data** (`DATA_DIR`): config.json, cache/, extracted/.
  In development this is the repository root too (so it behaves like before);
  when frozen it is the platform's per-user application-data folder, so the
  program works from Program Files or a read-only location:

      Windows   %APPDATA%\\MSSB Editor
      macOS     ~/Library/Application Support/MSSB Editor
      Linux     $XDG_DATA_HOME/mssb-editor  (default ~/.local/share/mssb-editor)

`MSSB_EDITOR_HOME` overrides the per-user folder in both modes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MSSB Editor"
FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    PACKAGE_DATA = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    EXE_DIR = Path(sys.executable).resolve().parent
else:
    PACKAGE_DATA = Path(__file__).resolve().parents[1]
    EXE_DIR = PACKAGE_DATA


def _user_data_dir() -> Path:
    env = os.environ.get("MSSB_EDITOR_HOME")
    if env:
        return Path(env).expanduser()
    if not FROZEN:
        return PACKAGE_DATA
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "mssb-editor"


DATA_DIR = _user_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
CACHE_DIR = DATA_DIR / "cache"
EXTRACT_DIR = DATA_DIR / "extracted"
INDEX_DIR = PACKAGE_DATA / "index"
UI_DIR = Path(__file__).resolve().parent / "ui"


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
