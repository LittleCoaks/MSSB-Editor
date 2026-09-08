"""SoundFont export: the RIFF layout, the record counts and the generators a
zone gets, on the synthetic MusyX group the group tests build."""
import struct

import pytest

from zzzzdat import musyx, render, sf2
from test_musyx import _group

RECORD = {b"phdr": 38, b"pbag": 4, b"pmod": 10, b"pgen": 4, b"inst": 22,
          b"ibag": 4, b"imod": 10, b"igen": 4, b"shdr": 46}


def chunks(buf: bytes, off: int, end: int) -> dict:
    """{tag: (body offset, size)} for one RIFF level; LIST forms recurse."""
    out = {}
    while off + 8 <= end:
        tag, size = buf[off:off + 4], struct.unpack_from("<I", buf, off + 4)[0]
        body = off + 8
        if tag in (b"RIFF", b"LIST"):
            out[buf[body:body + 4]] = chunks(buf, body + 4, body + size)
        else:
            out[tag] = (body, size)
        off = body + size + (size % 2)
    assert off == end, "a chunk overran its parent"
    return out


def records(buf, pdta, tag):
    o, s = pdta[tag]
    assert s % RECORD[tag] == 0
    return [buf[o + i * RECORD[tag]:o + (i + 1) * RECORD[tag]] for i in range(s // RECORD[tag])]


def gens(rec):
    return [struct.unpack_from("<HH", rec, i * 4) for i in range(len(rec) // 4)]


@pytest.fixture(scope="module")
def built():
    data = _group([[1, 2, 3, 4, 5, 6, 7, -1, -2, -3, -4, -5, -6, -7], [3] * 20])
    buf = sf2.build(data, "test group")
    return data, buf, chunks(buf, 0, len(buf))[b"sfbk"]


def test_riff_layout(built):
    _data, buf, top = built
    assert buf[:4] == b"RIFF" and set(top) == {b"INFO", b"sdta", b"pdta"}
    assert struct.unpack_from("<HH", buf, top[b"INFO"][b"ifil"][0]) == (2, 1)
    o, s = top[b"INFO"][b"INAM"]
    assert buf[o:o + s].rstrip(b"\0") == b"test group"
    assert set(top[b"pdta"]) == set(RECORD)


def test_samples_and_terminal_records(built):
    data, buf, top = built
    g = musyx.parse_group(data)
    shdr = records(buf, top[b"pdta"], b"shdr")
    assert len(shdr) == len(g.samples) + 1                      # plus the EOS terminal
    assert shdr[-1][:20].rstrip(b"\0") == b"EOS"
    o, s = top[b"sdta"][b"smpl"]
    for rec, want in zip(shdr, g.samples):
        name, start, end, ls, le, rate, pitch, _corr, _lnk, typ = struct.unpack("<20sIIIIIBbHH", rec)
        assert name.rstrip(b"\0") == f"sample {want.id:04x}".encode()
        assert end - start == want.count and rate == want.rate and pitch == want.base_note
        assert typ == 1 and start <= ls <= le <= end            # mono, loop points inside the sample
        assert end * 2 <= s                                     # and inside the smpl chunk
    # the samples are the decoded PCM, each followed by the terminal zeros
    first = struct.unpack_from("<20sII", shdr[0], 0)
    pcm = musyx.decode(data, g, g.samples[0])
    assert buf[o + first[1] * 2:o + first[2] * 2] == pcm
    assert buf[o + first[2] * 2:o + first[2] * 2 + sf2.TERMINAL_SAMPLES * 2] == b"\0" * (sf2.TERMINAL_SAMPLES * 2)


def test_one_preset_per_sound_effect(built):
    data, buf, top = built
    pdta = top[b"pdta"]
    phdr, pgen = records(buf, pdta, b"phdr"), records(buf, pdta, b"pgen")
    names = [r[:20].rstrip(b"\0").decode() for r in phdr]
    assert names == ["sfx 0300", "sfx 0301", "EOP"]             # the group's FX table, then the terminal
    assert [struct.unpack_from("<HH", r, 20) for r in phdr[:-1]] == [(0, 0), (1, 0)]   # preset, bank
    # every preset zone selects its instrument, and every instrument zone a sample
    assert [g for g in (gens(r) for r in pgen[:-1])] == [[(sf2.INSTRUMENT, 0)], [(sf2.INSTRUMENT, 1)]]
    igen = [gens(r)[0] for r in records(buf, pdta, b"igen")]
    zones = [g for g in igen if g[0] == sf2.KEY_RANGE]
    assert len(zones) == 2 and all(g == (sf2.KEY_RANGE, 0 | (127 << 8)) for g in zones)
    ids = [g for g in igen if g[0] == sf2.SAMPLE_ID]
    assert [g[1] for g in ids] == [0, 1]
    assert len(records(buf, pdta, b"inst")) == 3                # two instruments plus EOI


def test_zone_pitch_and_envelope():
    """A macro that adds to the key becomes coarseTune; one that pins the key
    with SET_KEY becomes coarseTune with scaleTuning 0, and an ADSR curve
    becomes the volume envelope generators."""
    data = _group([[1] * 14])
    bank = render.Bank(data)
    index = {0x100: (0, False)}
    s = bank.group.samples[0]

    bank.macros = {1: bank.macros[0x200]}
    plain = sf2._zone(bank, 1, index, 0, 127, 3, 1.0, 64)
    assert plain.coarse == 3 and plain.scale == 100 and plain.root == s.base_note and plain.pan == 0

    # rewrite the macro's steps: SET_KEY 72, SET_ADSR, then START_SAMPLE
    steps = (struct.pack(">II", (72 << 8) | 0x19, 0) + struct.pack(">II", (5 << 8) | 0x0C, 0)
             + struct.pack(">II", (0x100 << 8) | musyx.OP_START_SAMPLE, 0))
    bank.data = steps
    bank.macros = {2: (0, len(steps))}
    bank.curves = {5: (0.1, 0.2, 0.5, 0.4)}
    fixed = sf2._zone(bank, 2, index, 20, 40, 7, 0.5, 127)
    assert fixed.scale == 0                                     # the played key no longer moves the pitch
    assert fixed.coarse == 72 - s.base_note                     # and the transpose does not either
    assert fixed.pan == 500 and fixed.atten == sf2._cb(0.5)
    g = dict(fixed.generators())
    assert g[sf2.KEY_RANGE] == 20 | (40 << 8)
    assert g[sf2.ATTACK] == sf2._tc(0.1) & 0xFFFF and g[sf2.DECAY] == sf2._tc(0.2) & 0xFFFF
    assert g[sf2.SUSTAIN] == sf2._cb(0.5) and g[sf2.RELEASE] == sf2._tc(0.4) & 0xFFFF
    assert list(dict.fromkeys(k for k, _v in fixed.generators()))[-1] == sf2.SAMPLE_ID


def test_timecents_and_centibels():
    assert sf2._tc(1.0) == 0 and sf2._tc(2.0) == 1200 and sf2._tc(0.5) == -1200
    assert sf2._tc(0.0) == -12000                                # the floor, not an error
    assert sf2._cb(1.0) == 0 and sf2._cb(0.0) == 1440
    assert sf2._cb(0.5) == 60                                    # half the amplitude is 6 dB down


def test_song_group_uses_the_page_tables(monkeypatch):
    """A song group has no FX table; its presets come from the page tables,
    drums landing in bank 128 the way General MIDI players expect."""
    data = _group([[1] * 14])
    bank = render.Bank(data)
    bank.type = 0
    bank.pages, bank.drum_pages = {0: 0x200, 5: 0x200}, {3: 0x200}
    presets = sf2._presets(bank, {0x100: (0, False)})
    assert [(b, n, name) for b, n, name, _z in presets] == [
        (0, 0, "Program 0"), (0, 5, "Program 5"), (128, 3, "Drum 3")]


def test_group_without_presets_still_maps_its_samples():
    data = _group([[1] * 14, [2] * 14])
    bank = render.Bank(data)
    bank.group.sfx.clear()
    presets = sf2._presets(bank, {0x100: (0, False), 0x101: (1, True)})
    assert len(presets) == 1 and presets[0][2] == "Samples 1-2"
    assert [(z.lo, z.hi, z.sample) for z in presets[0][3]] == [(0, 0, 0), (1, 1, 1)]
