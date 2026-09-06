"""MusyX group parsing and sample decoding on a synthetic group file."""
import struct

from zzzzdat import dsp, formats, musyx


def _group(samples_pcm):
    """A minimal sfx group: one macro per sample, one sfx per macro."""
    coefs = (2048, -1024) + (0,) * 14  # simple 2-tap predictor set
    samp = bytearray()
    sdir = bytearray()
    adp = bytearray()
    n = len(samples_pcm)
    adp_base = n * 0x20 + 4
    for i, pcm in enumerate(samples_pcm):
        frames = _encode(pcm, coefs)
        off = len(samp)
        samp += frames
        while len(samp) % 32:
            samp += b"\0"
        sdir += struct.pack(">HHIIIIIII", 0x100 + i, 0, off, 0, (60 << 24) | 32000, len(pcm), 0, 0, adp_base + i * 0x28)
        adp += struct.pack(">HBBhh16h", 8, frames[0], 0, 0, 0, *coefs)
    sdir += b"\xff\xff\xff\xff" + adp
    # pool: macros
    macros = bytearray()
    for i in range(n):
        steps = struct.pack(">II", (0x100 + i) << 8 | musyx.OP_START_SAMPLE, 0) + struct.pack(">II", 0, 0)
        macros += struct.pack(">IHH", 8 + len(steps), 0x200 + i, 0) + steps
    macros += b"\xff\xff\xff\xff"
    pool = struct.pack(">IIII", 16, 16 + len(macros), 16 + len(macros), 16 + len(macros)) + macros + b"\xff\xff\xff\xff"
    # project: GROUP_DATA + id lists + fx table
    ids_m = b"".join(struct.pack(">H", 0x200 + i) for i in range(n)) + b"\xff\xff"
    ids_s = b"".join(struct.pack(">H", 0x100 + i) for i in range(n)) + b"\xff\xff"
    fx = struct.pack(">HH", n, 0) + b"".join(struct.pack(">HHBBBBBB", 0x300 + i, 0x200 + i, 0, 0, 127, 64, 60, 0) for i in range(n))
    head = 0x20
    mac_off = head
    smp_off = mac_off + len(ids_m)
    tab_off = smp_off + len(ids_s)
    proj = struct.pack(">IHHIIIIII", tab_off + len(fx), 7, 1, mac_off, smp_off, tab_off, tab_off, tab_off, tab_off) + ids_m + ids_s + fx
    proj_off = 0x20
    sdir_off = (proj_off + len(proj) + 31) & ~31
    pool_off = (sdir_off + len(sdir) + 31) & ~31
    samp_off = (pool_off + len(pool) + 31) & ~31
    out = bytearray(samp_off + len(samp))
    struct.pack_into(">8I", out, 0, proj_off, len(proj), sdir_off, len(sdir), pool_off, len(pool), samp_off, len(samp))
    out[proj_off:proj_off + len(proj)] = proj
    out[sdir_off:sdir_off + len(sdir)] = sdir
    out[pool_off:pool_off + len(pool)] = pool
    out[samp_off:] = samp
    return bytes(out)


def _encode(pcm, coefs):
    """Encode with predictor 0 and scale 1, so residuals are the samples
    themselves clipped to 4 bits; keeps the test independent of the decoder."""
    out = bytearray()
    for i in range(0, len(pcm), 14):
        chunk = list(pcm[i:i + 14]) + [0] * (14 - len(pcm[i:i + 14]))
        out.append(0x00)  # predictor 0, scale 0 -> nibble * 1 (+ prediction)
        for k in range(0, 14, 2):
            a, b = max(-8, min(7, chunk[k])), max(-8, min(7, chunk[k + 1]))
            out.append(((a & 0xF) << 4) | (b & 0xF))
    return bytes(out)


def test_group_parse_and_decode():
    data = _group([[1, 2, 3, 4, 5, 6, 7, -1, -2, -3, -4, -5, -6, -7], [3] * 20])
    assert musyx.is_group(data) and formats.classify_blob(data) == "musyx"
    g = musyx.parse_group(data)
    assert g and g.type == 1 and g.id == 7
    assert [s.id for s in g.samples] == [0x100, 0x101] and g.samples[1].count == 20
    assert g.macros == {0x200: [0x100], 0x201: [0x101]}
    assert [(f.id, f.macro, f.samples) for f in g.sfx] == [(0x300, 0x200, [0x100]), (0x301, 0x201, [0x101])]
    fi = formats.identify(data)
    assert fi.kind == "musyx" and len(fi.audio) == 2 and fi.audio[0]["rate"] == 32000
    assert fi.sfx[1]["streams"] == [1] and "effects" in fi.label
    pcm = musyx.decode(data, g, g.samples[1])
    assert len(pcm) == 40  # 20 samples * 2 bytes
    w = musyx.wav(data, g, g.samples[0])
    assert w[:4] == b"RIFF" and len(w) == 44 + 28
    # not a group: a plain container header must not match
    assert not musyx.is_group(struct.pack(">8I", 0x20, 0, 0x40, 0, 0x80, 0, 0xC0, 0) + bytes(0x100))
