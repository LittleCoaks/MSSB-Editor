"""Updates: ask GitHub for the newest release, fetch its installer, run it.

The check is a single anonymous request to the GitHub Releases API, made
when the UI asks (on start-up if the setting allows, or on the button).
Nothing is downloaded until the person clicks Install. The asset is picked
by platform:

    Windows   "MSSB Editor Setup <version>.exe"   run; NSIS upgrades in place
    macOS     "MSSB Editor <version>.dmg"         opened; drag to Applications

Downloads land in the data folder under updates/ and are removed once the
installer has been launched. A development checkout (not frozen) reports
updates but does not install them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .paths import DATA_DIR, FROZEN
from .version import RELEASES_URL, VERSION, newer

API = "https://api.github.com/repos/{repo}/releases/latest"
UPDATE_DIR = DATA_DIR / "updates"
_lock = threading.Lock()
_last: dict | None = None
_last_at = 0.0
_last_repo = ""


def _asset_for_platform(assets: list[dict]) -> dict | None:
    names = [(a.get("name", ""), a) for a in assets]
    if sys.platform == "win32":
        want = lambda n: n.lower().endswith(".exe") and "setup" in n.lower()
    elif sys.platform == "darwin":
        want = lambda n: n.lower().endswith(".dmg")
    else:
        want = lambda n: n.lower().endswith(".zip") and "linux" in n.lower()
    return next((a for n, a in names if want(n)), None)


def check(repo: str, force: bool = False, timeout: float = 8.0) -> dict:
    """{current, latest, available, asset: {name, url, size} | None, notes, url, checked_at, error}.
    Cached for ten minutes unless `force`."""
    global _last, _last_at, _last_repo
    with _lock:
        if _last and not force and _last_repo == repo and time.time() - _last_at < 600:
            return _last
        out = {"current": VERSION, "latest": None, "available": False, "asset": None, "notes": "",
               "url": RELEASES_URL, "checked_at": time.time(), "error": None, "can_install": FROZEN}
        try:
            req = urllib.request.Request(API.format(repo=repo),
                                         headers={"Accept": "application/vnd.github+json", "User-Agent": f"MSSB-Editor/{VERSION}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                rel = json.load(r)
            tag = rel.get("tag_name") or rel.get("name") or ""
            out["latest"] = tag.lstrip("vV")
            out["available"] = newer(tag)
            out["notes"] = (rel.get("body") or "")[:4000]
            out["url"] = rel.get("html_url") or RELEASES_URL
            a = _asset_for_platform(rel.get("assets") or [])
            if a:
                out["asset"] = {"name": a["name"], "url": a["browser_download_url"], "size": a.get("size", 0)}
        except Exception as ex:  # offline, rate limited, no releases yet
            out["error"] = f"{type(ex).__name__}: {ex}"
        _last, _last_at, _last_repo = out, time.time(), repo
        return out


def download(asset: dict, progress=lambda done, total: None) -> Path:
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPDATE_DIR / asset["name"]
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(asset["url"], headers={"User-Agent": f"MSSB-Editor/{VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            progress(done, total)
    tmp.replace(dest)
    return dest


def launch(installer: Path) -> str:
    """Start the installer and return what the person should expect."""
    if not FROZEN:
        return f"downloaded to {installer}; a development checkout is not replaced by an installer"
    if sys.platform == "win32":
        # the NSIS installer asks for elevation itself and upgrades in place; the
        # running program must quit before it can replace the files
        subprocess.Popen([str(installer)], close_fds=True)
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return "installer started; the editor closes now and the installer takes over"
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(installer)])
        return "disk image opened; drag MSSB Editor to Applications, then relaunch it"
    return f"downloaded to {installer}"
