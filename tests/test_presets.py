"""The character stat table and line-up records."""
import struct

from zzzzdat import chars, formats, presets


def _file():
    out = bytearray(presets.SIZE)
    for cid in range(chars.SLOTS):
        o = cid * presets.ROW
        out[o] = 100 + cid            # curve ball speed
        struct.pack_into(">Ih", out, o + 0x20, 0x0A, cid)   # wall jump + sliding catch, char id
        out[o + 0x31] = cid % 4
        out[o + 0x3B:o + 0x3B + chars.SLOTS] = bytes(range(chars.SLOTS))
    o = presets.STATS_SIZE + 481 * presets.LINEUP
    out[o:o + presets.LINEUP] = bytes([0, 1, 0x12, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]) + b"\x0a" * 9
    return bytes(out)


def test_identify_and_parse():
    data = _file()
    assert presets.is_roster(data)
    fi = formats.identify(data)
    assert fi.kind == "roster" and fi.roster == {"rows": 54, "lineups": 1}
    d = presets.parse(data)
    m = d["stats"][0]
    assert m["name"] == "Mario" and m["curve_ball_speed"] == 100 and m["fielding_abilities"] == ["wall jump", "sliding catch"]
    assert d["stats"][2]["class_name"] == "speed" and d["stats"][3]["class_name"] == "technique" and d["stats"][53]["chemistry"][53] == 53
    assert d["lineups"] == [{"n": 481, "members": [0, 1, 0x12], "tail": "0a" * 9}]


def test_wrong_size_or_ids():
    assert not presets.is_roster(_file()[:-1])
    bad = bytearray(_file())
    struct.pack_into(">h", bad, 0x24, 7)
    assert not presets.is_roster(bytes(bad))
