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


def _documents_dir() -> Path | None:
    """The user's Documents folder on Windows (asked of the shell, so a redirected
    folder is honoured), else None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        buf = ctypes.c_wchar_p()
        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = (ctypes.c_ubyte * 16)(0xD0, 0x9A, 0xD3, 0xFD, 0x8F, 0x23, 0xAF, 0x46, 0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7)
        if ctypes.windll.shell32.SHGetKnownFolderPath(fid, 0, None, ctypes.byref(buf)) == 0 and buf.value:
            path = Path(buf.value)
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except Exception:
        pass
    home = Path.home() / "Documents"
    return home if home.is_dir() else None


DATA_DIR = _user_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
CACHE_DIR = DATA_DIR / "cache"
# exports go where a person will find them: Documents/MSSB Editor when installed; the data
# folder in development, on macOS/Linux, or when MSSB_EDITOR_HOME is set
_docs = _documents_dir() if FROZEN and not os.environ.get("MSSB_EDITOR_HOME") else None
EXTRACT_DIR = (_docs / APP_NAME / "extracted") if _docs else DATA_DIR / "extracted"
INDEX_DIR = PACKAGE_DATA / "index"
UI_DIR = Path(__file__).resolve().parent / "ui"


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
