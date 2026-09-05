"""GX encoders, the PNG reader and in-place texture replacement (synthetic data)."""
import random
import struct

import pytest

from zzzzdat import formats, gx, png, texedit


def _noise(w, h, seed=1):
    rnd = random.Random(seed)
    return bytearray(rnd.randrange(256) for _ in range(w * h * 4))


def _gradient(w, h):
    out = bytearray()
    for y in range(h):
        for x in range(w):
            out += bytes((x * 255 // max(1, w - 1), y * 255 // max(1, h - 1), 128, 255))
    return out


@pytest.mark.parametrize("fmt", [0, 1, 2, 3, 4, 5, 6])
def test_direct_formats_are_fixed_points(fmt):
    w, h = 20, 12  # not block aligned on purpose
    img = _noise(w, h)
    enc = gx.encode(fmt, w, h, img)
    assert len(enc) == gx.encoded_size(fmt, w, h)
    dec = gx.decode(fmt, w, h, enc)
    assert gx.encode(fmt, w, h, dec) == enc
    assert gx.decode(fmt, w, h, gx.encode(fmt, w, h, dec)) == dec


def test_rgba8_is_lossless():
    img = _noise(8, 8)
    assert gx.decode(6, 8, 8, gx.encode(6, 8, 8, img)) == img


@pytest.mark.parametrize("fmt,tlut_fmt,count", [(8, 2, 16), (9, 1, 256), (9, 0, 256), (10, 2, 64)])
def test_palette_formats(fmt, tlut_fmt, count):
    w, h = 16, 16
    img = _noise(w, h)
    pal = gx.make_palette(img, fmt, tlut_fmt, count)
    assert 0 < len(pal) <= min(count, 16 if fmt == 8 else 256 if fmt == 9 else count)
    tlut = gx.encode_tlut(pal, tlut_fmt, count)
    assert len(tlut) == count * 2
    dec = gx.decode(fmt, w, h, gx.encode(fmt, w, h, img, pal), gx.decode_tlut(tlut, tlut_fmt, count))
    assert len(dec) == w * h * 4
    # an image that already uses <= n palette colours comes back exactly
    few = bytearray()
    cols = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (0, 0, 0, 0)]
    for i in range(w * h):
        few += bytes(cols[i % 4])
    pal = gx.make_palette(few, fmt, gx.GX_TL_RGB5A3, count)
    dec = gx.decode(fmt, w, h, gx.encode(fmt, w, h, few, pal), gx.decode_tlut(gx.encode_tlut(pal, 2, count), 2, count))
    assert dec == few


def test_cmpr_quality_and_alpha():
    w, h = 32, 32
    img = _gradient(w, h)
    enc = gx.encode(14, w, h, img)
    assert len(enc) == gx.encoded_size(14, w, h)
    dec = gx.decode(14, w, h, enc)
    err = sum(abs(a - b) for a, b in zip(img, dec)) / len(img)
    assert err < 6
    for i in range(0, len(img), 8):
        img[i + 3] = 0  # every other pixel transparent
    dec = gx.decode(14, w, h, gx.encode(14, w, h, img))
    assert all(dec[i + 3] == 0 for i in range(0, len(img), 8))
    assert all(dec[i + 3] == 255 for i in range(4, len(img), 8))
    flat = bytes((10, 20, 30, 255)) * (w * h)
    dec = gx.decode(14, w, h, gx.encode(14, w, h, flat))
    assert max(abs(a - b) for a, b in zip(flat, dec)) <= 8


def test_png_reader_roundtrip_and_resize():
    w, h = 13, 7
    img = _noise(w, h)
    assert png.read_png(gx.to_png(w, h, img)) == (w, h, img)
    with pytest.raises(png.PngError):
        png.read_png(b"not a png")
    small = png.resize(img, w, h, 5, 3)
    assert len(small) == 5 * 3 * 4
    big = png.resize(img, w, h, 20, 20)
    assert len(big) == 20 * 20 * 4
    flat = bytes((7, 8, 9, 10)) * (w * h)
    assert bytes(png.resize(flat, w, h, 3, 40)) == bytes((7, 8, 9, 10)) * 120
    m, mw, mh = png.halve(img, w, h)
    assert (mw, mh) == (6, 3) and len(m) == 6 * 3 * 4


def _texture_file(entries):
    """Build a standalone texture table with the given (w, h, fmt, mips, tlut_fmt, tlut_count)."""
    n = len(entries)
    table = bytearray(0x20 * n)
    body = bytearray()
    base = 0x20 * n
    for i, (w, h, fmt, mips, tf, tc) in enumerate(entries):
        toff = 0
        if tc:
            toff = base + len(body)
            body += bytes(tc * 2)
        doff = base + len(body)
        lw, lh = w, h
        for _ in range(mips + 1):
            body += bytes(gx.encoded_size(fmt, lw, lh))
            lw, lh = max(1, lw // 2), max(1, lh // 2)
        while len(body) % 32:
            body += b"\0"
        struct.pack_into(">HHIIHH4sfHBBHBB", table, i * 0x20, n if i == 0 else 0, 0, doff, toff, w, h, b"\1\1\1\1",
                         0.0, 0, mips, fmt, tc, tf, 0)
    return bytes(table + body)


def test_replace_texture_in_place():
    data = _texture_file([(16, 8, 14, 2, 0, 0), (8, 8, 9, 0, 2, 256), (4, 4, 6, 0, 0, 0)])
    fi = formats.identify(data)
    assert fi.kind == "textures" and len(fi.textures) == 3
    img = _gradient(16, 8)
    new, info = texedit.replace_texture(data, fi, 0, gx.to_png(16, 8, img))
    assert len(new) == len(data) and info.levels == 3 and not info.resized
    fi2 = formats.identify(new)
    assert [(t.width, t.height, t.fmt) for t in fi2.textures] == [(t.width, t.height, t.fmt) for t in fi.textures]
    dec = fi2.textures[0].decode_rgba(new)
    assert sum(abs(a - b) for a, b in zip(img, dec)) / len(img) < 6
    # bytes outside the texture's own span are untouched
    t = fi.textures[0]
    span = sum(gx.encoded_size(14, w, h) for w, h in texedit.level_dims(t))
    assert new[:t.abs_data_offset] == data[:t.abs_data_offset]
    assert new[t.abs_data_offset + span:] == data[t.abs_data_offset + span:]
    # palette texture: exact for a 4-colour image, TLUT written, sized image resampled
    cols = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (0, 0, 0, 0)]
    few = bytearray()
    for i in range(64):
        few += bytes(cols[i % 4])
    new2, info2 = texedit.replace_texture(data, fi, 1, gx.to_png(8, 8, few))
    assert info2.palette == 4
    assert formats.identify(new2).textures[1].decode_rgba(new2) == few
    new3, info3 = texedit.replace_texture(data, fi, 2, gx.to_png(9, 3, _noise(9, 3)))
    assert info3.resized and info3.source_size == (9, 3)
    assert len(new3) == len(data)
    with pytest.raises(texedit.TextureError):
        texedit.replace_texture(data, fi, 7, gx.to_png(1, 1, b"\0\0\0\0"))
    with pytest.raises(texedit.TextureError):
        texedit.replace_texture(data, fi, 0, b"junk")
