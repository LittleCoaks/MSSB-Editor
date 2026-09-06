"""MusyX sequenced songs (the menu, jingle and results music) and MIDI export.

The game's sequenced music lives in two files referenced from game.rel: a
container whose sections are 19 song arrangements, and a one-song container.
`sndSeqPlayEx` plays them on the instrument bank (MusyX group 31). The
arrangement layout is the one `seqStartPlay` in the decomp's seq.c parses,
an older MusyX version without the loop-point table:

    ARR     0x00 u32 tTab      track table: 64 x u32 offset of a TENTRY list (0 = unused)
            0x04 u32 pTab      pattern table: u32 offsets, one per pattern
            0x08 u32 tmTab     MIDI channel per track (u8 x 64, 0xFF = none)
            0x0C u32 mTrack    tempo track: {u32 time, u32 bpm} until time 0xFFFFFFFF (0 = constant)
            0x10 u32 info      bits 0..27 bpm (<<10 when bit 30 set), bit 31 = track sections used
            0x14 u32 tsTab
    TENTRY  (0xC) u32 time, u8 prgChange (0xFF none), u8 velocity (0xFF none), u8 res[2],
            u16 pattern (0xFFFF ends the track, 0xFFFE loops), s8 transpose, s8 velocityAdd
    pattern u32 pitchBendStream, u32 modulationStream, then events:
            u16 dt, u8 key, u8 velocity            (4 bytes) when key & 0x80:
                velocity 0    -> program change key & 0x7F
                velocity 1    -> controller 0x82 (MusyX)
                velocity&0x80 -> controller (velocity & 0x7F) = key & 0x7F
            u16 dt, u8 0, u8 0                     (4 bytes) rest
            u16 dt, u8 key, u8 velocity, u16 len   (6 bytes) note
            key 0xFF, velocity 0xFF ends the pattern
    Times are ticks (384 per quarter note, judging by the note lengths);
    each event's time is a delta from the previous event in the pattern.

All offsets are relative to the arrangement start.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

PPQ = 384


@dataclass
class Event:
    time: int        # absolute ticks
    kind: str        # "note", "program", "control"
    channel: int
    a: int           # key / program / controller
    b: int = 0       # velocity / value
    length: int = 0  # note length in ticks


@dataclass
class Song:
    offset: int
    bpm: int
    tempo: list[tuple[int, int]]   # (time, bpm)
    channels: list[int]            # per track, 0xFF = none
    events: list[Event] = field(default_factory=list)
    track_count: int = 0

    @property
    def notes(self) -> int:
        return sum(1 for e in self.events if e.kind == "note")

    @property
    def ticks(self) -> int:
        return max((e.time + e.length for e in self.events), default=0)

    @property
    def seconds(self) -> float:
        """Duration honouring tempo changes."""
        tempo = sorted(self.tempo) or [(0, self.bpm)]
        end = self.ticks
        total, t, bpm = 0.0, 0, tempo[0][1] or self.bpm or 120
        for tt, b in tempo[1:] + [(end, bpm)]:
            tt = min(tt, end)
            total += (tt - t) / PPQ * 60.0 / max(bpm, 1)
            t, bpm = tt, b
        return total


def is_arrangement(data: bytes, base: int) -> bool:
    if base + 0x18 + 256 > len(data):
        return False
    t, p, tm, mt, info, _ts = struct.unpack_from(">6I", data, base)
    if t != 0x18 or p % 4 or base + p >= len(data) or base + tm >= len(data):
        return False
    bpm = info & 0x0FFFFFFF
    if info & 0x40000000:
        bpm >>= 10
    if not 20 <= bpm <= 400:
        return False
    tabs = struct.unpack_from(">64I", data, base + t)
    used = [x for x in tabs if x]
    return bool(used) and all(x % 4 == 0 and base + x < len(data) for x in used)


def song_offsets(data: bytes) -> list[int]:
    """Section offsets of a song container, [] if the file is not one."""
    if len(data) < 0x20:
        return []
    hdr = struct.unpack_from(">I", data, 0)[0]
    if not (8 <= hdr <= 0x400 and hdr % 4 == 0):
        return []
    offs = [o for o in struct.unpack_from(f">{hdr // 4}I", data, 0) if o]
    if not offs or offs[0] != hdr or any(not is_arrangement(data, o) for o in offs):
        return []
    return offs


def parse_song(data: bytes, base: int) -> Song:
    t, p, tm, mt, info, _ts = struct.unpack_from(">6I", data, base)
    bpm = info & 0x0FFFFFFF
    if info & 0x40000000:
        bpm >>= 10
    tempo = []
    if mt:
        pos = base + mt
        while pos + 8 <= len(data):
            tt, b = struct.unpack_from(">II", data, pos)
            if tt == 0xFFFFFFFF:
                break
            tempo.append((tt, b))
            pos += 8
    if not tempo:
        tempo = [(0, bpm)]
    channels = list(data[base + tm:base + tm + 64])
    song = Song(base, bpm, tempo, channels)
    tabs = struct.unpack_from(">64I", data, base + t)
    ptab_base = base + p
    for tr, toff in enumerate(tabs):
        if not toff:
            continue
        song.track_count += 1
        chan = channels[tr] if tr < len(channels) else 0xFF
        chan = 0 if chan == 0xFF else chan & 0x0F
        pos = base + toff
        for _ in range(4096):
            if pos + 12 > len(data):
                break
            time, prg, vel, _r0, _r1, pat, transpose, veladd = struct.unpack_from(">IBBBBHbb", data, pos)
            pos += 12
            if pat == 0xFFFF or pat == 0xFFFE:
                break
            if prg != 0xFF:
                song.events.append(Event(time, "program", chan, prg))
            if vel != 0xFF:
                song.events.append(Event(time, "control", chan, 7, vel))
            poff = struct.unpack_from(">I", data, ptab_base + pat * 4)[0] if ptab_base + pat * 4 + 4 <= len(data) else 0
            if not poff or base + poff + 8 > len(data):
                continue
            _decode_pattern(data, base + poff + 8, time, chan, transpose, veladd, song.events)
    song.events.sort(key=lambda e: (e.time, e.kind != "program", e.kind != "control"))
    return song


def _decode_pattern(data: bytes, pos: int, base_time: int, chan: int, transpose: int, veladd: int,
                    out: list[Event]) -> None:
    t = base_time
    for _ in range(1 << 16):
        if pos + 4 > len(data):
            return
        dt, key, vel = struct.unpack_from(">HBB", data, pos)
        if key == 0xFF and vel == 0xFF:
            return
        t += dt
        if key & 0x80:
            pos += 4
            if vel == 0:
                out.append(Event(t, "program", chan, key & 0x7F))
            elif vel & 0x80 and (vel & 0x7F) < 0x80:
                ctl = vel & 0x7F
                if ctl < 120:  # channel-mode messages (0x78+) and MusyX specials are skipped
                    out.append(Event(t, "control", chan, ctl, key & 0x7F))
            continue
        if key == 0 and vel == 0:
            pos += 4
            continue
        if pos + 6 > len(data):
            return
        length = struct.unpack_from(">H", data, pos + 4)[0]
        pos += 6
        k = max(0, min(127, key + transpose))
        v = max(1, min(127, vel + veladd))
        out.append(Event(t, "note", chan, k, v, length))


def parse_songs(data: bytes) -> list[Song]:
    return [parse_song(data, o) for o in song_offsets(data)]


# ----------------------------------------------------------------- MIDI --
def _vlq(n: int) -> bytes:
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, 0x80 | (n & 0x7F))
        n >>= 7
    return bytes(out)


def to_midi(song: Song, name: str = "") -> bytes:
    """Standard MIDI file (format 1): a tempo track plus one track per channel."""
    msgs: list[tuple[int, int, bytes]] = []  # (time, order, bytes)
    for tt, b in song.tempo:
        usec = int(60_000_000 / max(b, 1))
        msgs.append((tt, 0, b"\xff\x51\x03" + usec.to_bytes(3, "big")))
    tempo_track = _track(msgs, name)
    by_chan: dict[int, list] = {}
    for e in song.events:
        lst = by_chan.setdefault(e.channel, [])
        if e.kind == "note":
            lst.append((e.time, 2, bytes([0x90 | e.channel, e.a, e.b])))
            lst.append((e.time + max(e.length, 1), 1, bytes([0x80 | e.channel, e.a, 0])))
        elif e.kind == "program":
            lst.append((e.time, 0, bytes([0xC0 | e.channel, e.a & 0x7F])))
        else:
            lst.append((e.time, 0, bytes([0xB0 | e.channel, e.a & 0x7F, e.b & 0x7F])))
    tracks = [tempo_track] + [_track(lst, f"channel {c + 1}") for c, lst in sorted(by_chan.items())]
    head = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ)
    return head + b"".join(tracks)


def _track(msgs: list, name: str) -> bytes:
    body = bytearray()
    if name:
        nm = name.encode("ascii", "replace")
        body += b"\x00\xff\x03" + _vlq(len(nm)) + nm
    last = 0
    for tt, _order, b in sorted(msgs, key=lambda m: (m[0], m[1])):
        body += _vlq(max(0, tt - last)) + b
        last = tt
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)
