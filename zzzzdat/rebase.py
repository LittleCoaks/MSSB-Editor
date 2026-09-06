"""Rebuild a section container or a texture table with sections of new sizes.

The in-place writers keep every offset in a file fixed, so a texture can only
be swapped for one of the same size. This module lifts that: a section
container is a header of u32 section offsets (the first is the header size)
followed by the sections, and every section addresses its own contents
relative to its own start (GeoPalettes, actors, animation banks, skins and
hand poses all do), so a section can be replaced by a blob of any size and
the ones after it slide along, 32-byte aligned as the originals are. A
texture table is a run of 0x20-byte records followed by pixel data and
palettes at offsets relative to the table, and models refer to textures by
index, so the table can be rebuilt with any texture at any size.

Not covered: files whose descriptors sit in the master table's ARAM chunk,
which the game loads whole and packed, so those must keep their size (the
editor refuses to grow them).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from . import gx
from .formats import Section, Texture

ALIGN = 32


def _pad(b: bytearray) -> None:
    b += bytes(-len(b) % ALIGN)


def rebuild_container(data: bytes, sections: list[Section], replaced: dict[int, bytes]) -> bytes:
    """`data` with the sections whose index is in `replaced` swapped for the
    given bytes; the header keeps its size and slot order, and every section
    starts on a 32-byte boundary."""
    hdr = struct.unpack_from(">I", data, 0)[0]
    slots = list(struct.unpack_from(f">{hdr // 4}I", data, 0))
    out = bytearray(bytes(hdr))
    _pad(out)
    new_offsets: dict[int, int] = {}
    for s in sections:
        blob = replaced.get(s.index, data[s.offset:s.offset + s.size])
        new_offsets[s.offset] = len(out)
        out += blob
        _pad(out)
    for k, o in enumerate(slots):
        if k == 0:
            struct.pack_into(">I", out, 0, hdr)
        elif o:
            struct.pack_into(">I", out, k * 4, new_offsets[o])
    return bytes(out)


@dataclass
class TextureChange:
    width: int
    height: int
    pixels: bytes          # every mip level, encoded
    tlut: bytes | None
    mips: int              # levels beyond the base


def rebuild_texture_table(data: bytes, base: int, texs: list[Texture], changes: dict[int, TextureChange],
                          end: int | None = None) -> bytes:
    """The bytes of a texture table (records + data) with `changes` applied,
    keyed by record index. Unchanged textures keep their pixels; records that
    shared pixel data or a palette keep sharing it."""
    count = struct.unpack_from(">H", data, base)[0]
    out = bytearray(data[base:base + count * 0x20])
    _pad(out)
    placed: dict[int, int] = {}      # original relative offset -> new relative offset (shared data)

    def put(blob: bytes, orig_rel: int | None) -> int:
        if orig_rel is not None and orig_rel in placed:
            return placed[orig_rel]
        off = len(out)
        out.extend(blob)
        _pad(out)
        if orig_rel is not None:
            placed[orig_rel] = off
        return off

    limit = end if end is not None else len(data)
    for t in texs:
        rec = base + t.index * 0x20
        fields = list(struct.unpack_from(">HHIIHH4sfHBBHBB", data, rec))
        ch = changes.get(t.index)
        if ch:
            doff = put(ch.pixels, None)
            toff = put(ch.tlut, None) if ch.tlut else 0
            fields[2], fields[3], fields[4], fields[5], fields[9] = doff, toff, ch.height, ch.width, ch.mips
        else:
            size = sum(gx.encoded_size(t.fmt, w, h) for w, h in _level_dims(t))
            src = base + t.data_offset
            doff = put(data[src:min(src + size, limit)], t.data_offset)
            toff = 0
            if t.tlut_count and t.tlut_offset:
                tsrc = base + t.tlut_offset
                tsize = t.tlut_count * 2
                toff = put(data[tsrc:min(tsrc + tsize, limit)], t.tlut_offset)
            fields[2], fields[3] = doff, toff
        struct.pack_into(">HHIIHH4sfHBBHBB", out, t.index * 0x20, *fields)
    return bytes(out)


def _level_dims(t: Texture) -> list[tuple[int, int]]:
    dims, w, h = [], t.width, t.height
    for _ in range(t.mips + 1):
        dims.append((w, h))
        w, h = max(1, w // 2), max(1, h // 2)
    return dims
