"""Read PNG files (standard library only) into RGBA8 and resize them.

Supports every colour type at bit depths 1-16, non-interlaced only (Adam7
images are rejected with a clear message; nearly no tool writes them).
"""
from __future__ import annotations

import struct
import zlib


class PngError(ValueError):
    pass


def read_png(data: bytes) -> tuple[int, int, bytearray]:
    """Return (width, height, rgba bytes)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError("not a PNG file")
    pos = 8
    w = h = 0
    depth = ctype = interlace = 0
    palette: list[tuple[int, int, int, int]] = []
    trns = b""
    idat = []
    while pos + 8 <= len(data):
        ln, tag = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            palette = [(body[i], body[i + 1], body[i + 2], 255) for i in range(0, len(body) - 2, 3)]
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    if not w or not h:
        raise PngError("PNG has no IHDR")
    if interlace:
        raise PngError("interlaced (Adam7) PNGs are not supported; re-save without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise PngError(f"unknown PNG colour type {ctype}")
    if ctype == 3:
        for i, a in enumerate(trns[:len(palette)]):
            palette[i] = palette[i][:3] + (a,)
    bpp = max(1, channels * depth // 8)           # bytes per complete pixel (filter unit)
    stride = (w * channels * depth + 7) // 8
    raw = zlib.decompress(b"".join(idat))
    if len(raw) < (stride + 1) * h:
        raise PngError("PNG image data is truncated")
    rows = _unfilter(raw, stride, h, bpp)
    out = bytearray(w * h * 4)
    color_key = None
    if trns and ctype in (0, 2):
        vals = struct.unpack(f">{len(trns) // 2}H", trns[:len(trns) // 2 * 2])
        color_key = vals

    for y in range(h):
        row = rows[y]
        samples = _samples(row, w * channels, depth)
        o = y * w * 4
        if ctype == 6:
            if depth == 8:
                out[o:o + w * 4] = row[:w * 4]
            else:
                for x in range(w):
                    out[o + x * 4:o + x * 4 + 4] = samples[x * 4:x * 4 + 4]
        elif ctype == 2:
            for x in range(w):
                r, g, b = samples[x * 3:x * 3 + 3]
                a = 0 if color_key and _key_match(row, x, depth, 3, color_key) else 255
                out[o + x * 4:o + x * 4 + 4] = (r, g, b, a)
        elif ctype == 0:
            for x in range(w):
                v = samples[x]
                a = 0 if color_key and _key_match(row, x, depth, 1, color_key) else 255
                out[o + x * 4:o + x * 4 + 4] = (v, v, v, a)
        elif ctype == 4:
            for x in range(w):
                v, a = samples[x * 2], samples[x * 2 + 1]
                out[o + x * 4:o + x * 4 + 4] = (v, v, v, a)
        else:  # palette
            idx = _indices(row, w, depth)
            for x in range(w):
                i = idx[x]
                out[o + x * 4:o + x * 4 + 4] = palette[i] if i < len(palette) else (0, 0, 0, 255)
    return w, h, out


def _key_match(row: bytes, x: int, depth: int, channels: int, key) -> bool:
    if depth == 16:
        vals = struct.unpack_from(f">{channels}H", row, x * channels * 2)
    elif depth == 8:
        vals = tuple(row[x * channels:x * channels + channels])
    else:
        vals = tuple(_indices(row, (x + 1) * channels, depth)[x * channels:(x + 1) * channels])
    return tuple(vals) == tuple(key[:channels])


def _samples(row: bytes, n: int, depth: int) -> bytes:
    """Row samples scaled to 8 bits."""
    if depth == 8:
        return row[:n]
    if depth == 16:
        return bytes(row[i * 2] for i in range(n))
    idx = _indices(row, n, depth)
    scale = 255 // ((1 << depth) - 1)
    return bytes(v * scale for v in idx)


def _indices(row: bytes, n: int, depth: int) -> list[int]:
    if depth == 8:
        return list(row[:n])
    if depth == 16:
        return [row[i * 2] << 8 | row[i * 2 + 1] for i in range(n)]
    per = 8 // depth
    mask = (1 << depth) - 1
    out = []
    for i in range(n):
        b = row[i // per]
        shift = 8 - depth * (i % per + 1)
        out.append((b >> shift) & mask)
    return out


def _unfilter(raw: bytes, stride: int, h: int, bpp: int) -> list[bytearray]:
    rows: list[bytearray] = []
    prev = bytearray(stride)
    p = 0
    for _ in range(h):
        ft = raw[p]
        cur = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                cur[i] = (cur[i] + pred) & 0xFF
        elif ft != 0:
            raise PngError(f"bad PNG filter type {ft}")
        rows.append(cur)
        prev = cur
    return rows


def resize(rgba: bytes, w: int, h: int, nw: int, nh: int) -> bytearray:
    """Resample to nw x nh: area-averaging when shrinking, bilinear when growing."""
    if (w, h) == (nw, nh):
        return bytearray(rgba)
    out = bytearray(nw * nh * 4)
    if nw <= w and nh <= h:
        for y in range(nh):
            y0, y1 = y * h // nh, max(y * h // nh + 1, (y + 1) * h // nh)
            for x in range(nw):
                x0, x1 = x * w // nw, max(x * w // nw + 1, (x + 1) * w // nw)
                r = g = b = a = 0
                n = (y1 - y0) * (x1 - x0)
                for yy in range(y0, y1):
                    base = (yy * w + x0) * 4
                    for xx in range(x1 - x0):
                        i = base + xx * 4
                        r += rgba[i]; g += rgba[i + 1]; b += rgba[i + 2]; a += rgba[i + 3]
                o = (y * nw + x) * 4
                out[o:o + 4] = (r // n, g // n, b // n, a // n)
        return out
    for y in range(nh):
        fy = (y + 0.5) * h / nh - 0.5
        y0 = min(max(int(fy), 0), h - 1)
        y1 = min(y0 + 1, h - 1)
        ty = min(max(fy - y0, 0.0), 1.0)
        for x in range(nw):
            fx = (x + 0.5) * w / nw - 0.5
            x0 = min(max(int(fx), 0), w - 1)
            x1 = min(x0 + 1, w - 1)
            tx = min(max(fx - x0, 0.0), 1.0)
            o = (y * nw + x) * 4
            for c in range(4):
                p00 = rgba[(y0 * w + x0) * 4 + c]
                p10 = rgba[(y0 * w + x1) * 4 + c]
                p01 = rgba[(y1 * w + x0) * 4 + c]
                p11 = rgba[(y1 * w + x1) * 4 + c]
                top = p00 + (p10 - p00) * tx
                bot = p01 + (p11 - p01) * tx
                out[o + c] = int(top + (bot - top) * ty + 0.5)
    return out


def halve(rgba: bytes, w: int, h: int) -> tuple[bytearray, int, int]:
    """Next mip level: 2x2 box filter (dimensions halve, never below 1)."""
    nw, nh = max(1, w // 2), max(1, h // 2)
    return resize(rgba, w, h, nw, nh), nw, nh
