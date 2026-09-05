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


# ----------------------------------------------------------------- encoding --
# Encoders for every format above. Lossless formats round-trip exactly once the
# input has been quantised to the format's precision (decode(encode(x)) is a
# fixed point); CMPR is a small DXT1 compressor; palette formats build their
# TLUT with a median-cut quantiser.

def _to565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _to5a3(r: int, g: int, b: int, a: int) -> int:
    if a >> 5 == 7:
        return 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
    return ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)


def _lum(r: int, g: int, b: int) -> int:
    return r if r == g == b else (r * 77 + g * 151 + b * 28) >> 8


def _to_ia8(r: int, g: int, b: int, a: int) -> int:
    return (a << 8) | _lum(r, g, b)


def encode_tlut(colors: list[tuple[int, int, int, int]], tlut_fmt: int, count: int) -> bytes:
    """Pack `count` palette entries (missing ones are zero)."""
    conv = {GX_TL_IA8: lambda c: _to_ia8(*c), GX_TL_RGB565: lambda c: _to565(*c[:3]),
            GX_TL_RGB5A3: lambda c: _to5a3(*c)}[tlut_fmt]
    vals = [conv(c) for c in colors[:count]] + [0] * max(0, count - len(colors))
    return struct.pack(f">{count}H", *vals)


def _tlut_quantise(c: tuple[int, int, int, int], tlut_fmt: int) -> tuple[int, int, int, int]:
    """What a palette colour becomes after a round trip through the TLUT format."""
    if tlut_fmt == GX_TL_IA8:
        return _ia8(_to_ia8(*c))
    if tlut_fmt == GX_TL_RGB565:
        return _rgb565(_to565(*c[:3]))
    return _rgb5a3(_to5a3(*c))


def quantise(rgba: bytes, n: int) -> list[tuple[int, int, int, int]]:
    """Median-cut palette of at most `n` colours (exact when the image has <= n)."""
    hist: dict[tuple[int, int, int, int], int] = {}
    for i in range(0, len(rgba), 4):
        px = (rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3])
        hist[px] = hist.get(px, 0) + 1
    if len(hist) <= n:
        return sorted(hist, key=lambda c: -hist[c])
    boxes = [list(hist.items())]
    while len(boxes) < n:
        best, best_i, best_c = -1, -1, 0
        for i, box in enumerate(boxes):
            if len(box) < 2:
                continue
            for c in range(4):
                lo = min(px[c] for px, _ in box)
                hi = max(px[c] for px, _ in box)
                span = (hi - lo) * (2 if c == 3 else 1)
                if span > best:
                    best, best_i, best_c = span, i, c
        if best_i < 0:
            break
        box = boxes.pop(best_i)
        box.sort(key=lambda kv: kv[0][best_c])
        total = sum(cnt for _, cnt in box)
        acc, cut = 0, 0
        for cut, (_, cnt) in enumerate(box):
            acc += cnt
            if acc * 2 >= total:
                break
        cut = min(max(cut + 1, 1), len(box) - 1)
        boxes += [box[:cut], box[cut:]]
    out = []
    for box in boxes:
        tot = sum(cnt for _, cnt in box)
        out.append(tuple(sum(px[c] * cnt for px, cnt in box) // tot for c in range(4)))
    return out


def _nearest_index(pal: list[tuple[int, int, int, int]]):
    cache: dict[tuple[int, int, int, int], int] = {}

    def f(px: tuple[int, int, int, int]) -> int:
        i = cache.get(px)
        if i is None:
            r, g, b, a = px
            i = min(range(len(pal)), key=lambda k: (pal[k][0] - r) ** 2 + (pal[k][1] - g) ** 2
                    + (pal[k][2] - b) ** 2 + 2 * (pal[k][3] - a) ** 2)
            cache[px] = i
        return i
    return f


def make_palette(rgba: bytes, fmt: int, tlut_fmt: int, count: int) -> list[tuple[int, int, int, int]]:
    """Palette for a C4/C8/C14X2 image, already rounded to the TLUT format."""
    n = min(count, {GX_TF_C4: 16, GX_TF_C8: 256, GX_TF_C14X2: 16384}[fmt])
    pal = [_tlut_quantise(c, tlut_fmt) for c in quantise(rgba, n)]
    seen: dict = {}
    for c in pal:
        seen.setdefault(c, None)
    return list(seen)


def encode(fmt: int, w: int, h: int, rgba: bytes, tlut: list[tuple[int, int, int, int]] | None = None) -> bytes:
    """Encode w*h RGBA8 pixels; the result has `encoded_size(fmt, w, h)` bytes.
    Palette formats index into `tlut` (see `make_palette`)."""
    bw, bh, _ = BLOCK[fmt]
    if len(rgba) < w * h * 4:
        rgba = bytes(rgba) + bytes(w * h * 4 - len(rgba))
    if fmt == GX_TF_CMPR:
        return _encode_cmpr(w, h, rgba)
    out = bytearray()
    nearest = _nearest_index(tlut) if tlut is not None else None

    def px(x: int, y: int) -> tuple[int, int, int, int]:
        if x >= w or y >= h:
            return (0, 0, 0, 0)
        i = (y * w + x) * 4
        return (rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3])

    for by in range(0, h, bh):
        for bx in range(0, w, bw):
            if fmt == GX_TF_I4:
                for yy in range(bh):
                    for xx in range(0, bw, 2):
                        a = _lum(*px(bx + xx, by + yy)[:3]) >> 4
                        b = _lum(*px(bx + xx + 1, by + yy)[:3]) >> 4
                        out.append((a << 4) | b)
            elif fmt == GX_TF_I8:
                for yy in range(bh):
                    for xx in range(bw):
                        out.append(_lum(*px(bx + xx, by + yy)[:3]))
            elif fmt == GX_TF_IA4:
                for yy in range(bh):
                    for xx in range(bw):
                        r, g, b, a = px(bx + xx, by + yy)
                        out.append(((a >> 4) << 4) | (_lum(r, g, b) >> 4))
            elif fmt == GX_TF_IA8:
                for yy in range(bh):
                    for xx in range(bw):
                        r, g, b, a = px(bx + xx, by + yy)
                        out += bytes((a, _lum(r, g, b)))
            elif fmt == GX_TF_RGB565:
                for yy in range(bh):
                    for xx in range(bw):
                        out += _to565(*px(bx + xx, by + yy)[:3]).to_bytes(2, "big")
            elif fmt == GX_TF_RGB5A3:
                for yy in range(bh):
                    for xx in range(bw):
                        out += _to5a3(*px(bx + xx, by + yy)).to_bytes(2, "big")
            elif fmt == GX_TF_RGBA8:
                ar = bytearray(32)
                gb = bytearray(32)
                for yy in range(4):
                    for xx in range(4):
                        r, g, b, a = px(bx + xx, by + yy)
                        k = (yy * 4 + xx) * 2
                        ar[k], ar[k + 1], gb[k], gb[k + 1] = a, r, g, b
                out += ar + gb
            elif fmt == GX_TF_C4:
                for yy in range(bh):
                    for xx in range(0, bw, 2):
                        out.append((nearest(px(bx + xx, by + yy)) << 4) | nearest(px(bx + xx + 1, by + yy)))
            elif fmt == GX_TF_C8:
                for yy in range(bh):
                    for xx in range(bw):
                        out.append(nearest(px(bx + xx, by + yy)))
            elif fmt == GX_TF_C14X2:
                for yy in range(bh):
                    for xx in range(bw):
                        out += nearest(px(bx + xx, by + yy)).to_bytes(2, "big")
            else:
                raise ValueError(f"unsupported texture format {fmt}")
    return bytes(out)


def _encode_cmpr(w: int, h: int, rgba: bytes) -> bytes:
    out = bytearray()
    for by in range(0, h, 8):
        for bx in range(0, w, 8):
            for sy in (0, 4):
                for sx in (0, 4):
                    pix = []
                    for yy in range(4):
                        for xx in range(4):
                            x, y = bx + sx + xx, by + sy + yy
                            if x < w and y < h:
                                i = (y * w + x) * 4
                                pix.append((rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]))
                            else:
                                pix.append((0, 0, 0, 0))
                    out += _dxt1_block(pix)
    return bytes(out)


def _mix(p0, p1, a: int, b: int):
    return tuple((a * x + b * y) // (a + b) for x, y in zip(p0, p1))


def _dxt1_block(pix: list[tuple[int, int, int, int]]) -> bytes:
    """One 4x4 DXT1 block. Any pixel with alpha < 128 makes it a 3-colour block
    with index 3 = transparent (the decoder's c0 <= c1 mode)."""
    alpha = any(p[3] < 128 for p in pix)
    opaque = [p[:3] for p in pix if p[3] >= 128]
    if not opaque:
        return bytes((0, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF))
    c0, c1 = _endpoints(opaque)
    if alpha:
        if c0 > c1:
            c0, c1 = c1, c0
    elif c0 == c1:
        # 4-colour mode needs c0 > c1: nudge one endpoint by a unit of blue
        if c0 & 0x1F:
            c1 -= 1
        else:
            c0 += 1
    elif c0 < c1:
        c0, c1 = c1, c0
    p0, p1 = _rgb565(c0)[:3], _rgb565(c1)[:3]
    if c0 > c1:
        pal = [p0, p1, _mix(p0, p1, 2, 1), _mix(p0, p1, 1, 2)]
        n = 4
    else:
        pal = [p0, p1, _mix(p0, p1, 1, 1)]
        n = 3
    bits = bytearray(4)
    for i, p in enumerate(pix):
        if alpha and p[3] < 128:
            idx = 3
        else:
            r, g, b = p[:3]
            idx = min(range(n), key=lambda k: (pal[k][0] - r) ** 2 + (pal[k][1] - g) ** 2 + (pal[k][2] - b) ** 2)
        bits[i // 4] |= idx << (6 - 2 * (i % 4))
    return c0.to_bytes(2, "big") + c1.to_bytes(2, "big") + bytes(bits)


def _endpoints(cols: list[tuple[int, int, int]]) -> tuple[int, int]:
    """Two RGB565 endpoints: the extremes along the block's principal colour
    axis, refined by least squares against the indices they produce."""
    n = len(cols)
    mean = [sum(c[k] for c in cols) / n for k in range(3)]
    cov = [[sum((c[i] - mean[i]) * (c[j] - mean[j]) for c in cols) for j in range(3)] for i in range(3)]
    v = [1.0, 1.0, 1.0]
    for _ in range(6):  # power iteration for the dominant eigenvector
        nv = [sum(cov[i][j] * v[j] for j in range(3)) for i in range(3)]
        mag = max(abs(x) for x in nv)
        if mag < 1e-9:
            v = [1.0, 1.0, 1.0]
            break
        v = [x / mag for x in nv]
    dots = [sum((c[k] - mean[k]) * v[k] for k in range(3)) for c in cols]
    lo, hi = cols[dots.index(min(dots))], cols[dots.index(max(dots))]
    c0, c1 = _to565(*hi), _to565(*lo)
    if c0 == c1:
        return c0, c1
    weights = ((1.0, 0.0), (0.0, 1.0), (2 / 3, 1 / 3), (1 / 3, 2 / 3))
    for _ in range(2):
        p0, p1 = _rgb565(c0)[:3], _rgb565(c1)[:3]
        pal = [p0, p1, _mix(p0, p1, 2, 1), _mix(p0, p1, 1, 2)]
        a00 = a01 = a11 = 0.0
        b0 = [0.0, 0.0, 0.0]
        b1 = [0.0, 0.0, 0.0]
        for c in cols:
            k = min(range(4), key=lambda i: (pal[i][0] - c[0]) ** 2 + (pal[i][1] - c[1]) ** 2 + (pal[i][2] - c[2]) ** 2)
            w0, w1 = weights[k]
            a00 += w0 * w0
            a01 += w0 * w1
            a11 += w1 * w1
            for ch in range(3):
                b0[ch] += w0 * c[ch]
                b1[ch] += w1 * c[ch]
        det = a00 * a11 - a01 * a01
        if abs(det) < 1e-6:
            break
        e0 = [min(255, max(0, int((a11 * b0[ch] - a01 * b1[ch]) / det + 0.5))) for ch in range(3)]
        e1 = [min(255, max(0, int((a00 * b1[ch] - a01 * b0[ch]) / det + 0.5))) for ch in range(3)]
        n0, n1 = _to565(*e0), _to565(*e1)
        if (n0, n1) == (c0, c1):
            break
        c0, c1 = n0, n1
    return c0, c1
