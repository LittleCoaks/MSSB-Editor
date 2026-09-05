import os
import random

import pytest

from zzzzdat.lzss import BitReader, BitWriter, compress, decompress, decompress_ex


def test_bitwriter_reader_symmetry():
    rng = random.Random(1)
    fields = [(rng.randrange(1, 17), rng.randrange(0, 1 << 16)) for _ in range(500)]
    bw = BitWriter()
    for bits, val in fields:
        bw.write(val & ((1 << bits) - 1), bits)
    data = bw.finish(align=4)
    rd = BitReader(data)
    for bits, val in fields:
        assert rd.read(bits) == val & ((1 << bits) - 1)


@pytest.mark.parametrize("params", [(0xB, 4), (0xE, 5)])
@pytest.mark.parametrize("kind", ["zeros", "random", "text", "mixed"])
def test_roundtrip(params, kind):
    rng = random.Random(7)
    if kind == "zeros":
        raw = bytes(5000)
    elif kind == "random":
        raw = bytes(rng.randrange(256) for _ in range(3000))
    elif kind == "text":
        raw = (b"stadium0.gpc Group01 Group02 the quick brown fox " * 80)[:3777]
    else:
        raw = b"".join(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40))) * rng.randrange(1, 6) for _ in range(60))
    lb, rb = params
    comp = compress(raw, lb, rb)
    assert bytes(decompress(comp, lb, rb, len(raw))) == raw
    out, used = decompress_ex(comp, lb, rb, None)
    assert bytes(out[:len(raw)]) == raw


def test_compresses_repetition():
    raw = b"abcdefgh" * 500
    assert len(compress(raw)) < len(raw) // 4


def test_empty_and_tiny():
    assert decompress(compress(b""), 0xB, 4, 0) == b""
    for n in range(1, 5):
        raw = bytes(range(n))
        assert bytes(decompress(compress(raw), 0xB, 4, n)) == raw


def test_stored_passthrough():
    raw = os.urandom(100)
    assert bytes(decompress(raw, 0, 0, 50)) == raw[:50]
