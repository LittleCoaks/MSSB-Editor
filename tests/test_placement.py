"""Stadium prop placement tables (game.rel), on synthetic data."""
import struct

from zzzzdat import placement


def test_tree_table_is_found_and_read():
    rec = lambda x, z, s, rot, tag: struct.pack(">3f3ff4B", x, 0.0, z, s, s, s, rot, *tag)
    table = rec(24.4, 117.2, 1.0, -16.0, (2, 1, 0, 0)) + rec(-22.0, 109.8, 0.9, 32.0, (2, 1, 0, 0)) + rec(0, 0, 0, 0, (4, 0, 0, 0))
    data = b"\0" * 0x40 + table + b"\0" * 0x40
    got = placement.instances(data, 0)
    assert [len(got[s]) for s in (7, 13)] == [2, 2]          # the day palm and its night twin
    first, second = got[7]
    # actor space (-Y up, +Z outfield) to the viewer's: x, -y, -z, and the turn reversed
    assert first["pos"] == [struct.unpack(">f", struct.pack(">f", 24.4))[0], -0.0, -struct.unpack(">f", struct.pack(">f", 117.2))[0]]
    assert first["rot"] == 16.0 and abs(second["scale"][0] - 0.9) < 1e-6


def test_copy_number_picks_the_model():
    # Wario Palace's Chain Chomps: 0x34-byte records, the tag's third byte is the copy
    rec = lambda x, copy: struct.pack(">3f4B", x, 0.0, 40.0, 0, 1, copy, 0) + struct.pack(">9f", 0, 180, 0, 0, 180, 0, 160, 120, 0)
    data = rec(55.0, 1) + rec(-55.0, 2) + struct.pack(">3f4B", 0, 0, 0, 0xD, 0, 0, 0) + b"\0" * 0x40
    got = placement.instances(data, 2)
    assert got[2][0]["pos"][0] == 55.0 and got[4][0]["pos"][0] == -55.0 and got[2][0]["rot"] == -180.0


def test_missing_table_is_no_instances():
    assert placement.instances(b"\0" * 256, 1) == {} and placement.instances(b"", 5) == {}
