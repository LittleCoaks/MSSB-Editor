"""Stride and column guesses for unrecognised tables."""
import struct

from zzzzdat import structview


def test_stride_and_columns():
    rows = [struct.pack(">ffhhI", 1.5 * i, -2.0, i, 3, 7) for i in range(200)]
    data = b"".join(rows)
    d = structview.describe(data)
    assert d["stride"] == 16
    assert d["strides"][0]["stride"] == 16
    assert d["columns"] == ["f32", "f32", "s16", "s16"]  # a u32 of 7 reads as two small shorts too


def test_tiny_file():
    assert structview.describe(b"\x01\x02") == {"size": 2, "strides": [], "stride": 16, "columns": []}
