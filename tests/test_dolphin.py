"""Dolphin texture-dump names: the XXH64 hash and the name rule."""
import struct

from zzzzdat import dolphin, formats, gx


def test_xxh64_vectors():
    assert dolphin.xxh64(b"") == 0xEF46DB3751D8E999
    assert dolphin.xxh64(b"a") == 0xD24EC4F1A98C6E5B
    assert dolphin.xxh64(b"abc") == 0x44BC2CF5AD770999
    assert dolphin.xxh64(b"abc", seed=1) != dolphin.xxh64(b"abc")
    long = bytes(range(256)) * 9 + b"tail"
    assert dolphin.xxh64(long) == dolphin.xxh64(bytes(long))


def test_texture_name_rule():
    # a bare table with one CMPR texture and one C8 texture with a palette
    from tests.test_texedit import _texture_file
    data = _texture_file([(16, 8, 14, 1, 0, 0), (8, 8, 9, 0, 2, 256)])
    fi = formats.identify(data)
    t0, t1 = fi.textures
    n0 = dolphin.texture_name(data, t0)
    n1 = dolphin.texture_name(data, t1)
    h0 = dolphin.xxh64(data[t0.abs_data_offset:t0.abs_data_offset + gx.encoded_size(14, 16, 8)])
    assert n0 == f"tex1_16x8_m_{h0:016x}_14"      # mipmapped, no palette
    assert n1.startswith("tex1_8x8_") and n1.endswith("_9") and n1.count("_") == 4  # palette hash present
    assert dolphin.texture_name(data, t0, mips=False) == f"tex1_16x8_{h0:016x}_14"
