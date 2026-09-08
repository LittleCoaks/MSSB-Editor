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
        struct.pack_into(">HHIIHH4sfHBBHBB", table, i * 0x20, n if i == 0 else 0, 0, doff, toff, h, w, b"\1\1\1\1",
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


def _container(sections):
    """A section container: a 0x20-byte header of u32 section offsets (slot 0 doubles as the header size) then 32-aligned sections."""
    hdr = 0x20
    out = bytearray(hdr)
    offs = []
    for blob in sections:
        while len(out) % 32:
            out += b"\0"
        offs.append(len(out))
        out += blob
    # slot 0 is the header size and, with it, the first section's offset
    for i, o in enumerate(offs):
        struct.pack_into(">I", out, i * 4, o)
    return bytes(out)


def test_resize_texture_rebuilds_table_and_container():
    from zzzzdat import rebase
    table = _texture_file([(16, 8, 14, 2, 0, 0), (8, 8, 9, 0, 2, 256), (4, 4, 6, 0, 0, 0)])
    fi = formats.identify(table)
    img = _gradient(32, 32)
    new, info = texedit.replace_texture(table, fi, 0, gx.to_png(32, 32, img), resize=True)
    assert (info.width, info.height) == (32, 32) and not info.resized and len(new) > len(table)
    fi2 = formats.identify(new)
    assert fi2.kind == "textures" and [(t.width, t.height) for t in fi2.textures] == [(32, 32), (8, 8), (4, 4)]
    dec = fi2.textures[0].decode_rgba(new)
    assert sum(abs(a - b) for a, b in zip(img, dec)) / len(img) < 6
    # the untouched textures keep their pixels and palette
    assert fi2.textures[1].decode_rgba(new) == fi.textures[1].decode_rgba(table)
    assert fi2.textures[1].tlut_count == 256 and fi2.textures[1].tlut_offset

    # inside a container with a section after the textures: the trailing section slides and stays intact
    trailer = bytes(range(256)) * 3
    cont = _container([table, trailer])
    fic = formats.identify(cont)
    assert fic.kind == "container" and len(fic.sections) == 2 and fic.sections[0].textures
    new2, info2 = texedit.replace_texture(cont, fic, 0, gx.to_png(64, 16, _gradient(64, 16)), resize=True)
    fic2 = formats.identify(new2)
    assert len(fic2.sections) == 2 and fic2.sections[0].textures[0].width == 64
    s1 = fic2.sections[1]
    assert new2[s1.offset:s1.offset + len(trailer)] == trailer and s1.offset % 32 == 0
    # header slot order is kept
    assert struct.unpack_from(">I", new2, 0)[0] == 0x20
    # smaller than before also works and the same-size case stays in place
    new3, _ = texedit.replace_texture(cont, fic, 0, gx.to_png(8, 4, _gradient(8, 4)), resize=True)
    assert formats.identify(new3).sections[0].textures[0].width == 8
    same, _ = texedit.replace_texture(cont, fic, 0, gx.to_png(16, 8, _gradient(16, 8)), resize=True)
    assert len(same) == len(cont)


def _solid(w, h, rgba):
    return bytearray(bytes(rgba) * (w * h))


def test_composite_kind_reads_the_pixels():
    """The display states carry no blend mode, so how a texture wants
    compositing is decided from what it holds."""
    n = 32 * 32
    assert gx.composite_kind(_solid(32, 32, (200, 180, 60, 255))) == "opaque"
    # a cutout: alpha is only ever off or on
    cut = _solid(32, 32, (200, 180, 60, 255))
    cut[3::4] = bytes(0 if i % 2 else 255 for i in range(n))
    assert gx.composite_kind(cut) == "mask"
    # a gradient over a real picture: alpha in between, on more than a scattering
    grad = bytearray()
    for y in range(32):
        for x in range(32):
            grad += bytes((x * 8, y * 8, 128, 255))
    grad[3] = 128
    assert gx.composite_kind(grad) == "opaque"          # one stray pixel is dithering
    for i in range(0, 20 * 4, 4):
        grad[i + 3] = 128
    assert gx.composite_kind(grad) == "blend"
    # an overlay: a picture with nothing solid anywhere in it, so there is no
    # threshold to test against and it has to be blended wherever it is drawn
    over = bytearray(grad)
    over[3::4] = bytes(min(200, 40 + (i % 32) * 5) for i in range(n))
    assert gx.composite_kind(over) == "alpha"
    # and a flat colour whose picture is entirely in the alpha
    flat = _solid(32, 32, (10, 10, 10, 255))
    flat[3::4] = bytes((i * 255) // n for i in range(n))
    assert gx.composite_kind(flat) == "alpha"
    # paint on a black ground, which the console added to what was underneath
    paint = _solid(32, 32, (0, 0, 0, 255))
    for i in range(0, n, 4):
        paint[i * 4:i * 4 + 3] = b"\xd0\xd0\xd0"
    assert gx.composite_kind(paint) == "add"
    # an evenly dark *surface* has no pure black in it, and must stay opaque
    assert gx.composite_kind(_solid(32, 32, (26, 24, 22, 255))) == "opaque"
