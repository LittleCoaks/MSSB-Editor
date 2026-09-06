"""MusyX song arrangements and MIDI export on a synthetic song container."""
import struct

from zzzzdat import formats, song


def _arrangement(bpm=120):
    """One track on channel 0 with one pattern: program 5, then C4 and E4 quarter notes."""
    hdr = 0x18
    ttab = hdr                      # 64 x u32
    tentry = ttab + 256             # one TENTRY + end marker
    ptab = tentry + 24              # one pattern offset
    tmtab = ptab + 4                # channel map (64 bytes)
    mtrack = tmtab + 64             # tempo track
    pattern = mtrack + 16
    events = (struct.pack(">HBB", 0, 0x80 | 5, 0)          # program change 5
              + struct.pack(">HBB", 0, 0x80 | 0x40, 0x80 | 7)  # controller 7 = 64
              + struct.pack(">HBBH", 0, 60, 100, 384)        # C4, quarter
              + struct.pack(">HBBH", 384, 64, 90, 192)       # E4 a quarter later, eighth long
              + struct.pack(">HBB", 0, 0xFF, 0xFF))
    out = bytearray(struct.pack(">6I", ttab, ptab, tmtab, mtrack, bpm, 0))
    out += struct.pack(">64I", *([tentry] + [0] * 63))
    out += struct.pack(">IBBBBHbb", 0, 0xFF, 0xFF, 0, 0, 0, 12, -10)   # pattern 0, transpose +12, velocity -10
    out += struct.pack(">IBBBBHbb", 0, 0xFF, 0xFF, 0, 0, 0xFFFF, 0, 0)
    out += struct.pack(">I", pattern)
    out += bytes([0] + [0xFF] * 63)
    out += struct.pack(">IIII", 0, bpm, 0xFFFFFFFF, 0xFFFFFFFF)
    out += struct.pack(">II", 0, 0) + events
    return bytes(out)


def _container(*arrs):
    hdr = 8 if len(arrs) <= 2 else 16
    offs, body = [], bytearray()
    for a in arrs:
        offs.append(hdr + len(body))
        body += a
        while len(body) % 32:
            body += b"\0"
    return struct.pack(f">{hdr // 4}I", *(offs + [0] * (hdr // 4 - len(offs)))) + bytes(body)


def test_song_parse_and_midi():
    data = _container(_arrangement(120), _arrangement(90))
    assert song.song_offsets(data) == [8, 8 + ((len(_arrangement()) + 31) // 32) * 32]
    assert formats.classify_blob(data) == "songs"
    fi = formats.identify(data)
    assert fi.kind == "songs" and len(fi.songs) == 2 and fi.songs[1]["bpm"] == 90 and "songs (2)" in fi.label
    s = song.parse_songs(data)[0]
    notes = [e for e in s.events if e.kind == "note"]
    assert [(e.time, e.a, e.b, e.length) for e in notes] == [(0, 72, 90, 384), (384, 76, 80, 192)]
    assert [e.kind for e in s.events[:2]] == ["program", "control"] and s.events[0].a == 5
    assert s.ticks == 576 and abs(s.seconds - 0.75) < 1e-6
    mid = song.to_midi(s, "test")
    assert mid[:4] == b"MThd" and struct.unpack(">HHH", mid[8:14]) == (1, 2, song.PPQ)
    assert mid.count(b"MTrk") == 2 and b"\xff\x51\x03" in mid


def test_text_table_detection():
    recs = [b"\x00\x2f\x00\x4f\x40\x00", b"\x00\x3e\x40\x00"]
    n = len(recs)
    offs, body = [], b""
    for r in recs:
        offs.append(4 + n * 4 + len(body))
        body += r
    data = struct.pack(">HH", n, 0x131) + struct.pack(f">{n}I", *offs) + body
    assert formats.is_text_table(data) and formats.classify_blob(data) == "text"
    assert formats.identify(data).label == "Text strings (2)"
    assert not formats.is_text_table(b"\x00\x02\x01\x31\x00\x00\x00\x00")
