"""Thumbnails and texture PNG cache.

Decoding a texture means decompressing its whole entry, so thumbnails are
generated once per game and kept as small PNGs. Nothing from the game ships
with the program: the cache is built from the user's own files after a game is
selected (in the background, see `ThumbJob`) and reflects that copy, modified
entries included.

* `cache/<game key>/thumbs/<id>.png`   - thumbnails
* `cache/<game key>/tex/<id>_<n>.png`  - full-size textures decoded on demand
Both are safe to delete.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from . import gx
from .disc import Game
from .paths import CACHE_DIR

THUMB_SIZE = 96


def game_key(game: Game) -> str:
    return hashlib.sha1(str(game.setting).encode("utf-8", "replace")).hexdigest()[:12]


CACHE_VERSION = "v2"  # bump when texture decoding changes


def cache_dir(game: Game) -> Path:
    d = CACHE_DIR / game_key(game) / CACHE_VERSION / "tex"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_dir(game: Game) -> Path:
    d = CACHE_DIR / game_key(game) / CACHE_VERSION / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def downscale(rgba: bytes, w: int, h: int, size: int = THUMB_SIZE) -> tuple[bytes, int, int]:
    """Nearest-neighbour shrink so the longer side is at most `size`."""
    scale = max(w, h) / size
    if scale <= 1:
        return rgba, w, h
    nw, nh = max(1, int(w / scale)), max(1, int(h / scale))
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = int(y * scale)
        row = sy * w
        for x in range(nw):
            i = (row + int(x * scale)) * 4
            o = (y * nw + x) * 4
            out[o:o + 4] = rgba[i:i + 4]
    return bytes(out), nw, nh


def make_thumb_png(data: bytes, tex) -> bytes:
    rgba = tex.decode_rgba(data)
    small, w, h = downscale(rgba, tex.width, tex.height)
    return gx.to_png(w, h, small)


def build_all(store, log=print, force: bool = False, progress=None, stop=None) -> int:
    """Generate the thumbnail of every entry with textures for the current game."""
    out_dir = thumb_dir(store.game)
    n = 0
    ents = [e for e in store.zzzz_entries() if e.ntex]
    for i, e in enumerate(ents):
        if stop and stop.is_set():
            break
        p = out_dir / f"{e.id}.png"
        if p.exists() and not force:
            continue
        try:
            data = store.data(e)
            texs = store.info(e).all_textures()
            sec, t = texs[min(e.thumb, len(texs) - 1)]
            p.write_bytes(make_thumb_png(data, t))
            n += 1
        except Exception as ex:
            log(f"  thumb {e.id}: {ex}")
        store.forget_memory(e)  # keep memory flat while sweeping the archive
        if progress:
            progress(i + 1, len(ents))
        elif i % 200 == 0:
            log(f"  thumbnails {i}/{len(ents)}")
    return n


class ThumbJob:
    """Background thumbnail build for the selected game, with progress."""

    def __init__(self):
        self.done = 0
        self.total = 0
        self.running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, store) -> None:
        self.stop()
        self._stop = threading.Event()
        want = [e for e in store.zzzz_entries() if e.ntex]
        have = {p.stem for p in thumb_dir(store.game).glob("*.png")}
        missing = [e for e in want if str(e.id) not in have]
        self.total, self.done = len(want), len(want) - len(missing)
        if not missing:
            return
        self.running = True

        def work():
            try:
                build_all(store, log=lambda *a: None, progress=self._progress, stop=self._stop)
            finally:
                self.running = False
                self.done = self.total
        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def _progress(self, i: int, total: int) -> None:
        self.done, self.total = i, total

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=5)
        self.running = False

    def state(self) -> dict:
        return {"running": self.running, "done": self.done, "total": self.total}
