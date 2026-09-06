"""Dolphin texture-dump names, so exported PNGs can go straight into a
Dolphin custom-texture pack (User/Load/Textures/GYQE01/).

Dolphin names a dumped texture

    tex1_<w>x<h>[_m]_<hash>[_<tlut hash>]_<format>.png

where the hashes are XXH64 (seed 0) of the base level's raw GX-encoded
bytes, block-aligned exactly as they sit in the file, and of the palette
bytes for C4/C8/C14X2 textures; `_m` marks a texture whose mip chain is
loaded, and <format> is the GX format number (C4 = 8, C8 = 9, CMPR = 14...).
The hash never covers mip levels, so it is the same bytes we store.
"""
from __future__ import annotations

import struct

from . import gx
from .formats import Texture

P1, P2, P3, P4, P5 = 0x9E3779B185EBCA87, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9, 0x85EBCA77C2B2AE63, 0x27D4EB2F165667C5
M = (1 << 64) - 1


def _rotl(x: int, r: int) -> int:
    return ((x << r) | (x >> (64 - r))) & M


def _round(acc: int, lane: int) -> int:
    acc = (acc + lane * P2) & M
    return (_rotl(acc, 31) * P1) & M


def _merge(acc: int, v: int) -> int:
    acc ^= _round(0, v)
    return (acc * P1 + P4) & M


def xxh64(data: bytes, seed: int = 0) -> int:
    n = len(data)
    p = 0
    if n >= 32:
        v1 = (seed + P1 + P2) & M
        v2 = (seed + P2) & M
        v3 = seed & M
        v4 = (seed - P1) & M
        limit = n - 32
        unpack = struct.Struct("<4Q").unpack_from
        while p <= limit:
            a, b, c, d = unpack(data, p)
            v1 = _round(v1, a)
            v2 = _round(v2, b)
            v3 = _round(v3, c)
            v4 = _round(v4, d)
            p += 32
        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & M
        h = _merge(h, v1)
        h = _merge(h, v2)
        h = _merge(h, v3)
        h = _merge(h, v4)
    else:
        h = (seed + P5) & M
    h = (h + n) & M
    while p + 8 <= n:
        k = struct.unpack_from("<Q", data, p)[0]
        h ^= _round(0, k)
        h = (_rotl(h, 27) * P1 + P4) & M
        p += 8
    if p + 4 <= n:
        k = struct.unpack_from("<I", data, p)[0]
        h ^= (k * P1) & M
        h = (_rotl(h, 23) * P2 + P3) & M
        p += 4
    while p < n:
        h ^= (data[p] * P5) & M
        h = (_rotl(h, 11) * P1) & M
        p += 1
    h ^= h >> 33
    h = (h * P2) & M
    h ^= h >> 29
    h = (h * P3) & M
    h ^= h >> 32
    return h


def texture_name(data: bytes, t: Texture, mips: bool | None = None) -> str:
    """The Dolphin dump name (without .png) of texture record `t` in `data`."""
    size = gx.encoded_size(t.fmt, t.width, t.height)
    start = t.abs_data_offset
    h = xxh64(data[start:start + size])
    name = f"tex1_{t.width}x{t.height}"
    if mips if mips is not None else t.mips > 0:
        name += "_m"
    name += f"_{h:016x}"
    if t.fmt in (gx.GX_TF_C4, gx.GX_TF_C8, gx.GX_TF_C14X2) and t.tlut_count:
        ts = t.base + t.tlut_offset
        name += f"_{xxh64(data[ts:ts + t.tlut_count * 2]):016x}"
    return name + f"_{t.fmt}"
