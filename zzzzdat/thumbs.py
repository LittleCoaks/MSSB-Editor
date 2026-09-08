"""Thumbnails and texture PNG cache.

Decoding a texture means decompressing its whole entry, so thumbnails are made
once and kept as small PNGs. Nothing from the game ships with the program: the
cache is built from the user's own files, the first time a page asks for one,
and reflects that copy, modified entries included. Only the Characters and
Stadiums pages show them, so this is a few dozen images; `zzzzdat thumbs`
still fills the whole cache up front if you want it warm.

* `cache/<game key>/thumbs/<id>.png`   - thumbnails
* `cache/<game key>/tex/<id>_<n>.png`  - full-size textures decoded on demand
Both are safe to delete.
"""
from __future__ import annotations

import hashlib
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
