"""GameCube GX texture decoding to RGBA8 and a tiny PNG writer.

Only the standard library is used. Decoders cover every GX_TF_* format the
hardware supports; palette formats need a TLUT (list of RGBA tuples).
"""
from __future__ import annotations

import struct
import zlib

GX_TF_I4 = 0
GX_TF_I8 = 1
GX_TF_IA4 = 2
GX_TF_IA8 = 3
GX_TF_RGB565 = 4
GX_TF_RGB5A3 = 5
GX_TF_RGBA8 = 6
GX_TF_C4 = 8
GX_TF_C8 = 9
GX_TF_C14X2 = 10
GX_TF_CMPR = 14

FORMAT_NAMES = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8",
                8: "C4", 9: "C8", 10: "C14X2", 14: "CMPR"}

# (block width, block height, bits per pixel)
BLOCK = {0: (8, 8, 4), 1: (8, 4, 8), 2: (8, 4, 8), 3: (4, 4, 16), 4: (4, 4, 16), 5: (4, 4, 16),
         6: (4, 4, 32), 8: (8, 8, 4), 9: (8, 4, 8), 10: (4, 4, 16), 14: (8, 8, 4)}

GX_TL_IA8 = 0
GX_TL_RGB565 = 1
GX_TL_RGB5A3 = 2


def encoded_size(fmt: int, w: int, h: int) -> int:
    bw, bh, bpp = BLOCK[fmt]
    return ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * bw * bh * bpp // 8


def _rgb565(v: int) -> tuple[int, int, int, int]:
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2), 255


def _rgb5a3(v: int) -> tuple[int, int, int, int]:
    if v & 0x8000:
        r = (v >> 10) & 0x1F
        g = (v >> 5) & 0x1F
        b = v & 0x1F
        return (r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2), 255
    a = (v >> 12) & 7
    r = (v >> 8) & 0xF
    g = (v >> 4) & 0xF
    b = v & 0xF
    return r * 17, g * 17, b * 17, (a << 5) | (a << 2) | (a >> 1)


def _ia8(v: int) -> tuple[int, int, int, int]:
    i = v & 0xFF
    return i, i, i, v >> 8


def decode_tlut(data: bytes, tlut_fmt: int, count: int) -> list[tuple[int, int, int, int]]:
    conv = {GX_TL_IA8: _ia8, GX_TL_RGB565: _rgb565, GX_TL_RGB5A3: _rgb5a3}[tlut_fmt]
    return [conv(v) for v in struct.unpack(f">{count}H", data[:count * 2])]


def decode(fmt: int, w: int, h: int, data: bytes, tlut=None) -> bytearray:
    """Return w*h*4 bytes of RGBA. Missing data is treated as zero."""
    bw, bh, _ = BLOCK[fmt]
    need = encoded_size(fmt, w, h)
    if len(data) < need:
        data = bytes(data) + bytes(need - len(data))
    out = bytearray(w * h * 4)
    bpr = (w + bw - 1) // bw  # blocks per row

    def put(x: int, y: int, px: tuple[int, int, int, int]) -> None:
        if x < w and y < h:
            i = (y * w + x) * 4
            out[i:i + 4] = px

    if fmt == GX_TF_CMPR:
        _decode_cmpr(w, h, data, out)
        return out

    pos = 0
    for by in range(0, h, bh):
        for bx in range(0, w, bw):
            if fmt == GX_TF_I4:
                for yy in range(bh):
                    for xx in range(0, bw, 2):
                        v = data[pos]
                        pos += 1
                        hi, lo = (v >> 4) * 17, (v & 0xF) * 17
                        put(bx + xx, by + yy, (hi, hi, hi, 255))
                        put(bx + xx + 1, by + yy, (lo, lo, lo, 255))
            elif fmt == GX_TF_I8:
                for yy in range(bh):
                    for xx in range(bw):
                        v = data[pos]
                        pos += 1
                        put(bx + xx, by + yy, (v, v, v, 255))
            elif fmt == GX_TF_IA4:
                for yy in range(bh):
                    for xx in range(bw):
                        v = data[pos]
                        pos += 1
                        i, a = (v & 0xF) * 17, (v >> 4) * 17
                        put(bx + xx, by + yy, (i, i, i, a))
            elif fmt == GX_TF_IA8:
                for yy in range(bh):
                    for xx in range(bw):
                        a, i = data[pos], data[pos + 1]
                        pos += 2
                        put(bx + xx, by + yy, (i, i, i, a))
            elif fmt == GX_TF_RGB565:
                for yy in range(bh):
                    for xx in range(bw):
                        v = (data[pos] << 8) | data[pos + 1]
                        pos += 2
                        put(bx + xx, by + yy, _rgb565(v))
            elif fmt == GX_TF_RGB5A3:
                for yy in range(bh):
                    for xx in range(bw):
                        v = (data[pos] << 8) | data[pos + 1]
                        pos += 2
                        put(bx + xx, by + yy, _rgb5a3(v))
            elif fmt == GX_TF_RGBA8:
                # two 32-byte halves per block: AR then GB
                ar = data[pos:pos + 32]
                gb = data[pos + 32:pos + 64]
                pos += 64
                for yy in range(4):
                    for xx in range(4):
                        k = (yy * 4 + xx) * 2
                        put(bx + xx, by + yy, (ar[k + 1], gb[k], gb[k + 1], ar[k]))
            elif fmt == GX_TF_C4:
                for yy in range(bh):
                    for xx in range(0, bw, 2):
                        v = data[pos]
                        pos += 1
                        put(bx + xx, by + yy, _pal(tlut, v >> 4))
                        put(bx + xx + 1, by + yy, _pal(tlut, v & 0xF))
            elif fmt == GX_TF_C8:
                for yy in range(bh):
                    for xx in range(bw):
                        put(bx + xx, by + yy, _pal(tlut, data[pos]))
                        pos += 1
            elif fmt == GX_TF_C14X2:
                for yy in range(bh):
                    for xx in range(bw):
                        v = ((data[pos] << 8) | data[pos + 1]) & 0x3FFF
                        pos += 2
                        put(bx + xx, by + yy, _pal(tlut, v))
            else:
                raise ValueError(f"unsupported texture format {fmt}")
    return out


def _pal(tlut, i: int) -> tuple[int, int, int, int]:
    if tlut is None or i >= len(tlut):
        v = (i * 37) & 0xFF  # no palette: show indices as grey
        return v, v, v, 255
    return tlut[i]


def _decode_cmpr(w: int, h: int, data: bytes, out: bytearray) -> None:
    pos = 0
    for by in range(0, h, 8):
        for bx in range(0, w, 8):
            for sy in (0, 4):
                for sx in (0, 4):
                    c0 = (data[pos] << 8) | data[pos + 1]
                    c1 = (data[pos + 2] << 8) | data[pos + 3]
                    bits = data[pos + 4:pos + 8]
                    pos += 8
                    p0, p1 = _rgb565(c0), _rgb565(c1)
                    if c0 > c1:
                        p2 = tuple((2 * a + b) // 3 for a, b in zip(p0[:3], p1[:3])) + (255,)
                        p3 = tuple((a + 2 * b) // 3 for a, b in zip(p0[:3], p1[:3])) + (255,)
                    else:
                        p2 = tuple((a + b) // 2 for a, b in zip(p0[:3], p1[:3])) + (255,)
                        p3 = (0, 0, 0, 0)
                    pal = (p0, p1, p2, p3)
                    for yy in range(4):
                        row = bits[yy]
                        for xx in range(4):
                            x, y = bx + sx + xx, by + sy + yy
                            if x < w and y < h:
                                i = (y * w + x) * 4
                                out[i:i + 4] = pal[(row >> (6 - 2 * xx)) & 3]


def to_png(w: int, h: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\0" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
