"""Replace one texture inside an entry's decompressed bytes.

The new image is written *in place*: same width, height, GX format, mip
count and palette size as the original, so every offset in the texture table
and in the sections around it stays valid. Anything else in the file is
untouched, which keeps this safe for the shared-data and odd-padding layouts
seen in the archive (some records point at the same pixels, some tables
leave gaps). The image is resampled to the original size when it differs;
mip levels are regenerated with a box filter.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import gx, png
from .formats import FileInfo, Texture


class TextureError(ValueError):
    pass


@dataclass
class Replaced:
    n: int
    width: int
    height: int
    fmt: str
    levels: int
    source_size: tuple[int, int]
    resized: bool
    palette: int  # colours used, 0 for direct formats
    truncated: int = 0  # bytes of the encoding the table has no room for (see `reserved_span`)

    def as_dict(self) -> dict:
        return {"n": self.n, "width": self.width, "height": self.height, "fmt": self.fmt, "levels": self.levels,
                "source_width": self.source_size[0], "source_height": self.source_size[1], "resized": self.resized,
                "palette": self.palette, "truncated": self.truncated}


def level_dims(t: Texture) -> list[tuple[int, int]]:
    """(w, h) of the base level and each mip level stored after it."""
    dims, w, h = [], t.width, t.height
    for _ in range(t.mips + 1):
        dims.append((w, h))
        w, h = max(1, w // 2), max(1, h // 2)
    return dims


def reserved_span(fi: FileInfo, sec, t: Texture, at: int) -> int:
    """How many bytes the file reserves from relative offset `at` in this
    texture's table before the next record's data or palette starts. Some
    tables allocate less than the block-rounded size (the last block row of
    an odd-sized C8 image overlaps the next texture), so writes are capped."""
    siblings = sec.textures if sec is not None else fi.textures
    nxt = [o for s in siblings for o in (s.data_offset, s.tlut_offset) if o > at and (o != s.tlut_offset or s.tlut_count)]
    end = (sec.offset + sec.size if sec is not None else None)
    limit = min(nxt) if nxt else None
    if limit is None:
        return (end - t.base - at) if end is not None else 1 << 31
    return limit - at


def encode_texture(t: Texture, rgba: bytes, w: int, h: int) -> tuple[bytes, bytes | None, Replaced, int]:
    """Encode an RGBA image for texture record `t`: (pixel data for every
    level, TLUT bytes or None, summary)."""
    resized = (w, h) != (t.width, t.height)
    src = (w, h)
    if resized:
        rgba = png.resize(rgba, w, h, t.width, t.height)
        w, h = t.width, t.height
    tlut = None
    pal = None
    if t.fmt in (gx.GX_TF_C4, gx.GX_TF_C8, gx.GX_TF_C14X2):
        if not t.tlut_count:
            raise TextureError("this palette texture has no palette to write")
        pal = gx.make_palette(rgba, t.fmt, t.tlut_fmt, t.tlut_count)
        tlut = gx.encode_tlut(pal, t.tlut_fmt, t.tlut_count)
    out = bytearray()
    lw, lh, level = w, h, rgba
    for i, (dw, dh) in enumerate(level_dims(t)):
        if i:
            level, lw, lh = png.halve(level, lw, lh)
            if (lw, lh) != (dw, dh):
                level = png.resize(level, lw, lh, dw, dh)
                lw, lh = dw, dh
        out += gx.encode(t.fmt, dw, dh, level, pal)
    return bytes(out), tlut, Replaced(t.index, t.width, t.height, t.fmt_name, t.mips + 1, src, resized,
                                      len(pal) if pal else 0), len(out)


def replace_texture(data: bytes, fi: FileInfo, n: int, image: bytes) -> tuple[bytes, Replaced]:
    """Return the entry's bytes with texture `n` (index into
    `fi.all_textures()`) replaced by `image` (a PNG file)."""
    texs = fi.all_textures()
    if n < 0 or n >= len(texs):
        raise TextureError(f"no texture {n} (the file has {len(texs)})")
    sec, t = texs[n]
    try:
        w, h, rgba = png.read_png(image)
    except png.PngError as ex:
        raise TextureError(str(ex)) from None
    pixels, tlut, info, size = encode_texture(t, rgba, w, h)
    info.n = n
    start = t.abs_data_offset
    room = min(size, reserved_span(fi, sec, t, t.data_offset), len(data) - start)
    if room <= 0:
        raise TextureError("texture data runs past the end of the file")
    info.truncated = size - room
    out = bytearray(data)
    out[start:start + room] = pixels[:room]
    if tlut is not None:
        ts = t.base + t.tlut_offset
        troom = min(len(tlut), reserved_span(fi, sec, t, t.tlut_offset), len(data) - ts)
        if troom <= 0:
            raise TextureError("palette runs past the end of the file")
        out[ts:ts + troom] = tlut[:troom]
    return bytes(out), info
