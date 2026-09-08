"""SoundFont 2 (.sf2) export of MusyX groups.

A group already holds everything a SoundFont wants, under other names: its
DSP-ADPCM samples become the `smpl` chunk (decoded to PCM16), and the
macro / layer / keymap graph the renderer walks becomes preset and instrument
zones. Which presets a group gets depends on its type:

* a song group (the instrument bank) has *page* tables (program number to
  macro), so each normal page becomes a melodic preset in bank 0 and each
  drum page a preset in bank 128, the way General MIDI players expect;
* an sfx group has no pages, so each entry of its FX table becomes a preset,
  128 to a bank, named after the sound-effect id.

A zone's pitch is set the way `render.Bank` plays it: the sample's base note
is the root key, a macro's ADD_KEY (and a layer's or keymap's transpose)
become `coarseTune`, and a macro whose SET_KEY pins the pitch gets
`scaleTuning` 0 so the played key no longer moves it. Volume envelopes come
from the macro's curve table, and loops from the sample directory.

Reference: SoundFont 2.04 specification, sections 6 (RIFF layout), 7 (record
formats) and 8 (generators).
"""
from __future__ import annotations

import math
import struct

from . import musyx

# generator operators (SF2 8.1.3)
KEY_RANGE, PAN, ATTACK, DECAY, SUSTAIN, RELEASE = 43, 17, 34, 36, 37, 38
INSTRUMENT, ATTENUATION, COARSE_TUNE, SAMPLE_ID, SAMPLE_MODES, SCALE_TUNING, ROOT_KEY = 41, 48, 51, 53, 54, 56, 58

TERMINAL_SAMPLES = 46   # zero samples the spec requires after each sample
MAX_ZONES = 512         # a runaway keymap must not produce an unusable file


def _pad(b: bytes) -> bytes:
    return b + (b"\0" if len(b) % 2 else b"")


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack("<I", len(body)) + _pad(body)


def _list(tag: bytes, body: bytes) -> bytes:
    return b"LIST" + struct.pack("<I", len(body) + 4) + tag + _pad(body)


def _name(s: str) -> bytes:
    return s.encode("ascii", "replace")[:19].ljust(20, b"\0")


def _tc(seconds: float) -> int:
    """Seconds as SF2 timecents (1200 * log2 s), floored at the 1 ms minimum."""
    if seconds <= 0.0005:
        return -12000
    return max(-12000, min(8000, int(round(1200 * math.log2(seconds)))))


def _cb(gain: float) -> int:
    """A linear gain as centibels of attenuation."""
    if gain >= 1.0:
        return 0
    if gain <= 0.0:
        return 1440
    return max(0, min(1440, int(round(-200 * math.log10(gain)))))


class Zone:
    """One instrument zone: a key range playing one sample."""

    __slots__ = ("lo", "hi", "sample", "root", "coarse", "scale", "pan", "atten", "adsr", "loop")

    def __init__(self, lo, hi, sample, root, coarse, scale, pan, atten, adsr, loop):
        self.lo, self.hi, self.sample, self.root = lo, hi, sample, root
        self.coarse, self.scale, self.pan, self.atten = coarse, scale, pan, atten
        self.adsr, self.loop = adsr, loop

    def key(self) -> tuple:
        return (self.sample, self.root, self.coarse, self.scale, self.pan, self.atten, self.adsr, self.loop)

    def generators(self) -> list:
        g = [(KEY_RANGE, self.lo | (self.hi << 8))]
        if self.pan:
            g.append((PAN, self.pan & 0xFFFF))
        if self.atten:
            g.append((ATTENUATION, self.atten))
        at, dt, sl, rt = self.adsr
        if at > 0.0005:
            g.append((ATTACK, _tc(at) & 0xFFFF))
        if dt > 0.0005:
            g.append((DECAY, _tc(dt) & 0xFFFF))
            g.append((SUSTAIN, _cb(sl)))
        g.append((RELEASE, _tc(rt) & 0xFFFF))
        if self.coarse:
            g.append((COARSE_TUNE, self.coarse & 0xFFFF))
        if self.scale != 100:
            g.append((SCALE_TUNING, self.scale))
        g.append((SAMPLE_MODES, 1 if self.loop else 0))
        g.append((ROOT_KEY, self.root))
        g.append((SAMPLE_ID, self.sample))   # must come last (SF2 7.9)
        return g


def _zone(bank, mid: int, index: dict, lo: int, hi: int, transpose: int, gain: float, pan: int) -> Zone | None:
    r = bank._macro_voice(mid, 0)
    if not r:
        return None
    s, delta, adsr, fixed = r
    ent = index.get(s.id)
    if ent is None:
        return None
    n, looped = ent
    root = s.base_note if 0 <= s.base_note <= 127 else 60
    # the renderer pitches by (key + transpose + delta) - base_note; SF2 pitches
    # by (key - root) + coarseTune, and by coarseTune alone when scaleTuning is 0
    coarse = (delta - s.base_note) if fixed else (transpose + delta + root - s.base_note)
    return Zone(lo, hi, n, root, max(-120, min(120, coarse)), 0 if fixed else 100,
                max(-500, min(500, round((pan - 64) / 63 * 500))), _cb(gain), adsr, looped)


def _zones(bank, mid: int, index: dict) -> list:
    """The zones one page (or FX table) macro id resolves to: a layer gives a
    zone per key span, a keymap a zone per run of keys, a plain macro one."""
    out: list = []
    if mid & 0x8000 and mid in bank.layers:
        a, b = bank.layers[mid]
        num = struct.unpack_from(">I", bank.data, a)[0]
        for i in range(min(num, (b - a - 4) // 12, MAX_ZONES)):
            m, lo, hi, tr, vol, _prio, pan = struct.unpack_from(">HBBbBhB", bank.data, a + 4 + i * 12)
            if lo > hi:
                continue
            z = _zone(bank, m, index, lo, hi, tr, vol / 127.0, pan)
            if z:
                out.append(z)
    elif mid & 0x4000 and mid in bank.keymaps:
        a, b = bank.keymaps[mid]
        prev = None
        for key in range(128):
            if a + key * 8 + 8 > b:
                break
            m, tr, pan, _prio, _r = struct.unpack_from(">HbBhH", bank.data, a + key * 8)
            z = _zone(bank, m, index, key, key, tr, 1.0, pan) if m != 0xFFFF else None
            if z and prev is not None and prev.key() == z.key():
                prev.hi = key          # a run of keys playing the same thing is one zone
            elif z:
                out.append(z)
                prev = z
            else:
                prev = None
    else:
        z = _zone(bank, mid, index, 0, 127, 0, 1.0, 64)
        if z:
            out.append(z)
    return out[:MAX_ZONES]


def _presets(bank, index: dict) -> list:
    """[(bank number, preset number, name, zones)] for a group."""
    out = []
    if bank.type == 0:
        for label, base, table in (("Program", 0, bank.pages), ("Drum", 128, bank.drum_pages)):
            for prog in sorted(table):
                z = _zones(bank, table[prog], index)
                if z:
                    out.append((base + prog // 128, prog % 128, f"{label} {prog}", z))
    else:
        for n, f in enumerate(bank.group.sfx):
            z = _zones(bank, f.macro, index)
            if z:
                out.append((n // 128, n % 128, f"sfx {f.id:04x}", z))
    if out:
        return out
    # nothing resolved (or a group with no FX table): still give every sample a
    # home, one per key, so the file opens somewhere useful
    from .render import DEFAULT_ADSR
    ordered = [(s, index[s.id]) for s in bank.group.samples if s.id in index]
    for c in range(0, len(ordered), 128):
        zones = [Zone(k, k, n, s.base_note if 0 <= s.base_note <= 127 else 60, 0, 100, 0, 0,
                      DEFAULT_ADSR, looped)
                 for k, (s, (n, looped)) in enumerate(ordered[c:c + 128])]
        if zones:
            out.append((c // 128, 0, f"Samples {c + 1}-{c + len(zones)}", zones))
    return out


def build(data: bytes, name: str = "MusyX group") -> bytes:
    """One MusyX group file as a SoundFont 2 bank."""
    from .render import Bank
    bank = Bank(data)
    g = bank.group
    if g is None:
        raise ValueError("not a MusyX group")

    smpl = bytearray()
    shdr = b""
    index: dict = {}          # MusyX sample id -> (shdr index, loops)
    for s in g.samples:
        if s.id in index or s.count < 2:
            continue
        pcm = musyx.decode(data, g, s)
        n = len(pcm) // 2
        if n < 2:
            continue
        start = len(smpl) // 2
        smpl += pcm[:n * 2] + b"\0" * (TERMINAL_SAMPLES * 2)
        loop = s.loop_length > 0 and s.loop_start + s.loop_length <= n
        ls = start + s.loop_start if loop else start
        le = start + s.loop_start + s.loop_length if loop else start + n
        shdr += struct.pack("<20sIIIIIBbHH", _name(f"sample {s.id:04x}"), start, start + n, ls, le,
                            max(s.rate, 400), s.base_note if 0 <= s.base_note <= 127 else 60, 0, 0, 1)
        index[s.id] = (len(index), loop)

    phdr = pbag = pgen = inst = ibag = igen = b""
    for bnk, num, pname, zones in _presets(bank, index):
        phdr += struct.pack("<20sHHHIII", _name(pname), num, bnk, len(pbag) // 4, 0, 0, 0)
        pbag += struct.pack("<HH", len(pgen) // 4, 0)
        pgen += struct.pack("<HH", INSTRUMENT, len(inst) // 22)
        inst += struct.pack("<20sH", _name(pname), len(ibag) // 4)
        for z in zones:
            ibag += struct.pack("<HH", len(igen) // 4, 0)
            for op, amount in z.generators():
                igen += struct.pack("<HH", op, amount)
    phdr += struct.pack("<20sHHHIII", _name("EOP"), 0, 0, len(pbag) // 4, 0, 0, 0)
    pbag += struct.pack("<HH", len(pgen) // 4, 0)
    inst += struct.pack("<20sH", _name("EOI"), len(ibag) // 4)
    ibag += struct.pack("<HH", len(igen) // 4, 0)
    pgen += struct.pack("<HH", 0, 0)
    igen += struct.pack("<HH", 0, 0)
    shdr += struct.pack("<20sIIIIIBbHH", _name("EOS"), 0, 0, 0, 0, 0, 0, 0, 0, 0)
    mod = struct.pack("<HHhHH", 0, 0, 0, 0, 0)   # the terminal modulator; this writer uses none

    info = (_chunk(b"ifil", struct.pack("<HH", 2, 1)) + _chunk(b"isng", b"EMU8000\0")
            + _chunk(b"INAM", _pad(name.encode("ascii", "replace")[:255] + b"\0"))
            + _chunk(b"ISFT", b"zzzzdat\0"))
    sdta = _chunk(b"smpl", bytes(smpl))
    pdta = (_chunk(b"phdr", phdr) + _chunk(b"pbag", pbag) + _chunk(b"pmod", mod) + _chunk(b"pgen", pgen)
            + _chunk(b"inst", inst) + _chunk(b"ibag", ibag) + _chunk(b"imod", mod) + _chunk(b"igen", igen)
            + _chunk(b"shdr", shdr))
    body = b"sfbk" + _list(b"INFO", info) + _list(b"sdta", sdta) + _list(b"pdta", pdta)
    return b"RIFF" + struct.pack("<I", len(body)) + body
