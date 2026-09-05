"""Thumbnails and texture PNG cache.

Decoding a texture means decompressing its whole entry, so thumbnails are
generated once and kept as small PNGs:

* `index/thumbs/<id>.png` - shipped with the program (built by `index`)
* `cache/<game key>/tex/<id>_<n>.png` - full-size textures decoded on demand
  for the game in use (safe to delete)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import gx
from .disc import PACKAGE_DATA, VIEWER_ROOT, Game

THUMB_SIZE = 96
SHIPPED_THUMBS = VIEWER_ROOT / "index" / "thumbs"
if not SHIPPED_THUMBS.exists() and (PACKAGE_DATA / "index" / "thumbs").exists():
    SHIPPED_THUMBS = PACKAGE_DATA / "index" / "thumbs"


def game_key(game: Game) -> str:
    return hashlib.sha1(str(game.setting).encode("utf-8", "replace")).hexdigest()[:12]


def cache_dir(game: Game) -> Path:
    d = VIEWER_ROOT / "cache" / game_key(game) / "tex"
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


def build_all(store, out_dir: Path = SHIPPED_THUMBS, log=print, force: bool = False) -> int:
    """Generate the shipped thumbnail for every entry with textures."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    ents = [e for e in store.zzzz_entries() if e.ntex]
    for i, e in enumerate(ents):
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
        store.forget(e)  # keep memory flat while sweeping the archive
        if i % 200 == 0:
            log(f"  thumbnails {i}/{len(ents)}")
    return n
