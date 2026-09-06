"""Render a MusyX song with the instrument bank's own samples (needs numpy).

A song's program numbers select entries of the bank's *page* table (PAGE:
u16 macro, u8 prio, u8 maxVoices, u8 program): normal pages for melodic
channels, drum pages for MIDI channel 10. A page's macro id is one of:

* a plain macro: its steps set the pitch (0x18 ADD_KEY adds a signed byte to
  the key, 0x19 SET_KEY fixes it) and 0x10 START_SAMPLE names the sample;
* a layer (id | 0x8000): LAYER entries {u16 macro, u8 keyLow, u8 keyHigh,
  s8 transpose, u8 volume, s16 prioOffset, u8 pan} choose a macro by key;
* a keymap (id | 0x4000): 128 KEYMAP entries {u16 macro, s8 transpose,
  u8 pan, s16 prioOffset, pad} choose a macro per key (drums).

The renderer keeps what the ear needs most: sample choice, key transposition
against the sample's base note, sample loops while a note is held, velocity
and channel volume, pan, the macro's ADSR envelope (0x0C SET_ADSR names a
curve table: little-endian u16 attack ms, decay ms, sustain level / 4096,
release ms) and, when the song has one, the MIDISETUP channel setup
(initial program, volume, pan per channel, selected by the song id the game
starts the song with). A program change naming a program the
bank has no page for is ignored, as the sequencer does. Envelopes, vibrato
and the other macro commands are ignored, so it is a preview, not the game's
mixer.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from . import dsp, musyx
from .song import PPQ, Song

OUT_RATE = 32000
RELEASE = 0.35   # seconds of fade after a note ends when the macro has no ADSR
DEFAULT_ADSR = (0.0, 0.0, 1.0, RELEASE)


@dataclass
class Voice:
    sample: musyx.Sample
    key: int
    volume: float   # 0..1
    pan: int        # 0..127
    adsr: tuple = DEFAULT_ADSR   # attack s, decay s, sustain 0..1, release s


class Bank:
    def __init__(self, data: bytes):
        self.data = data
        self.group = musyx.parse_group(data)
        (po, ps), (so, ss), (lo, ls), (mo, ms) = musyx.sections(data)
        _n, _gid, typ, _mac, _smp, _cv, _km, _ly, normpage, drumpage, _ms = struct.unpack_from(">IHHIIIIIIII", data, po)
        self.pages = self._pages(po, ps, normpage)
        self.drum_pages = self._pages(po, ps, drumpage) if typ == 0 else {}
        macro_off, _curve_off, keymap_off, layer_off = struct.unpack_from(">4I", data, lo)
        self.macros = self._mem_list(lo, ls, macro_off)
        self.curves = {}
        for cid, (a, b) in self._mem_list(lo, ls, _curve_off).items():
            if b - a >= 8:
                at, dt, sl, rt = struct.unpack_from("<4H", data, a)
                self.curves[cid] = (at / 1000.0, dt / 1000.0, min(sl, 4096) / 4096.0, max(rt, 5) / 1000.0)
        self.midisetup = {}
        p = po + _ms
        while _ms and p + 0x54 <= po + ps:
            sid = struct.unpack_from(">H", data, p)[0]
            if sid == 0xFFFF:
                break
            self.midisetup[sid] = [struct.unpack_from(">BBBBB", data, p + 4 + c * 5) for c in range(16)]
            p += 0x54
        self.keymaps = self._mem_list(lo, ls, keymap_off)
        self.layers = self._mem_list(lo, ls, layer_off)
        self.samples = {s.id: s for s in self.group.samples}
        self._pcm: dict[int, object] = {}

    def _pages(self, po: int, ps: int, off: int) -> dict[int, int]:
        out = {}
        p = po + off
        while off and p + 6 <= po + ps:
            macro, _prio, _maxv, idx, _res = struct.unpack_from(">HBBBB", self.data, p)
            if macro == 0xFFFF:
                break
            out[idx] = macro
            p += 6
        return out

    def _mem_list(self, lo: int, ls: int, off: int) -> dict[int, tuple[int, int]]:
        out = {}
        pos = lo + off
        while off and pos + 8 <= lo + ls:
            n, mid = struct.unpack_from(">IH", self.data, pos)
            if n == 0xFFFFFFFF or n < 8:
                break
            out[mid] = (pos + 8, min(pos + n, lo + ls))
            pos += n
        return out

    # ------------------------------------------------------------ lookup --
    def _macro_voice(self, mid: int, key: int, depth: int = 0) -> tuple[musyx.Sample, int, tuple] | None:
        span = self.macros.get(mid)
        if not span or depth > 4:
            return None
        a, b = span
        adsr = DEFAULT_ADSR
        for q in range(a, b, 8):
            w0, w1 = struct.unpack_from(">II", self.data, q)
            op = w0 & 0x7F
            if op == 0:
                return None
            if op == 0x18:                       # ADD_KEY
                key += struct.unpack(">b", bytes([(w0 >> 8) & 0xFF]))[0]
            elif op == 0x19:                     # SET_KEY
                key = (w0 >> 8) & 0xFF
            elif op == 0x0C:                     # SET_ADSR (curve table id)
                adsr = self.curves.get((w0 >> 8) & 0xFFFF, adsr)
            elif op == 0x10:                     # START_SAMPLE
                s = self.samples.get((w0 >> 8) & 0xFFFF)
                return (s, key, adsr) if s else None
            elif op == 0x08:                     # PLAY_MACRO (spawns another macro)
                r = self._macro_voice((w0 >> 8) & 0xFFFF, key, depth + 1)
                if r:
                    return r
        return None

    def voices(self, program: int, key: int, drum: bool) -> list[Voice]:
        mid = (self.drum_pages if drum else self.pages).get(program)
        if mid is None:
            return []
        out = []
        if mid & 0x8000 and mid in self.layers:
            a, b = self.layers[mid]
            num = struct.unpack_from(">I", self.data, a)[0]
            for i in range(min(num, (b - a - 4) // 12)):
                m, lo_, hi, tr, vol, _prio, pan = struct.unpack_from(">HBBbBhB", self.data, a + 4 + i * 12)
                if lo_ <= key <= hi:
                    r = self._macro_voice(m, key + tr)
                    if r:
                        out.append(Voice(r[0], r[1], vol / 127.0, pan, r[2]))
        elif mid & 0x4000 and mid in self.keymaps:
            a, b = self.keymaps[mid]
            if a + key * 8 + 8 <= b:
                m, tr, pan, _prio, _r = struct.unpack_from(">HbBhH", self.data, a + key * 8)
                if m != 0xFFFF:
                    r = self._macro_voice(m, key + tr)
                    if r:
                        out.append(Voice(r[0], r[1], 1.0, pan, r[2]))
        else:
            r = self._macro_voice(mid, key)
            if r:
                out.append(Voice(r[0], r[1], 1.0, 64, r[2]))
        return out

    def pcm(self, s: musyx.Sample):
        import numpy as np
        arr = self._pcm.get(s.id)
        if arr is None:
            raw = musyx.decode(self.data, self.group, s)
            arr = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
            self._pcm[s.id] = arr
        return arr


def _tempo_map(song: Song):
    """[(tick, seconds_at_tick, seconds_per_tick)] for converting ticks."""
    out = []
    t_prev, sec, bpm = 0, 0.0, song.tempo[0][1] if song.tempo else song.bpm
    for tick, b in sorted(song.tempo):
        sec += (tick - t_prev) * 60.0 / (max(bpm, 1) * PPQ)
        t_prev, bpm = tick, b
        out.append((tick, sec, 60.0 / (max(bpm, 1) * PPQ)))
    if not out or out[0][0] != 0:
        out.insert(0, (0, 0.0, 60.0 / (max(song.bpm, 1) * PPQ)))
    return out


def _seconds(tmap, tick: int) -> float:
    for t, s, spt in reversed(tmap):
        if tick >= t:
            return s + (tick - t) * spt
    return 0.0


def _envelope(np, n: int, held: int, rate: int, adsr: tuple):
    """Linear ADSR over n samples with key-off at `held`."""
    at, dt, sl, rt = adsr
    env = np.ones(n)
    a = min(int(at * rate), held)
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
    d = min(int(dt * rate), max(held - a, 0))
    if d > 0:
        env[a:a + d] = np.linspace(1.0, sl, d, endpoint=False)
    if a + d < held:
        env[a + d:held] = sl if dt > 0 else 1.0
    if n > held:
        level = env[held - 1] if held > 0 else 1.0
        r = n - held
        env[held:] = np.linspace(level, 0.0, r) ** 1.5
    return env


def render(song: Song, bank: Bank, rate: int = OUT_RATE, setup_id: int | None = None) -> bytes:
    """Stereo 16-bit WAV of the song; `setup_id` selects the bank's MIDISETUP
    (initial program, volume and pan per channel) the way the game does."""
    import numpy as np
    tmap = _tempo_map(song)
    max_release = max([v[3] for v in bank.curves.values()] + [RELEASE])
    total = _seconds(tmap, song.ticks) + max_release + 0.1
    n_out = int(total * rate) + 1
    mix = np.zeros((n_out, 2), dtype="float64")
    program = {c: 0 for c in range(16)}
    volume = {c: 100 for c in range(16)}
    pan = {c: 64 for c in range(16)}
    for c, (prog, vol, pn, _rev, _cho) in enumerate(bank.midisetup.get(setup_id, [])):
        if prog in (bank.drum_pages if c == 9 else bank.pages):
            program[c] = prog
        volume[c], pan[c] = vol, pn
    for ev in song.events:  # already sorted by time, programs/controls before notes
        c = ev.channel
        if ev.kind == "program":
            # like DoPrgChange: a program without a page is ignored and the
            # channel keeps its previous instrument
            table = bank.drum_pages if c == 9 else bank.pages
            if ev.a in table:
                program[c] = ev.a
            continue
        if ev.kind == "control":
            if ev.a == 7:
                volume[c] = ev.b
            elif ev.a == 10:
                pan[c] = ev.b
            continue
        start = _seconds(tmap, ev.time)
        dur = max(_seconds(tmap, ev.time + ev.length) - start, 0.02)
        for v in bank.voices(program[c], ev.a, c == 9):
            src = bank.pcm(v.sample)
            if len(src) < 2:
                continue
            ratio = (2.0 ** ((v.key - v.sample.base_note) / 12.0)) * v.sample.rate / rate
            n = int((dur + v.adsr[3]) * rate)
            pos = np.arange(n, dtype="float64") * ratio
            loop = v.sample.loop_length > 0 and v.sample.loop_start + v.sample.loop_length <= len(src)
            if loop:
                ls, ll = v.sample.loop_start, v.sample.loop_length
                over = pos >= ls + ll
                pos[over] = ls + np.mod(pos[over] - ls, ll)
            else:
                keep = pos < len(src) - 1
                n = int(keep.sum())
                pos = pos[:n]
            if n <= 0:
                continue
            samp = np.interp(pos, np.arange(len(src)), src)
            held = min(int(dur * rate), n)
            env = _envelope(np, n, held, rate, v.adsr)
            amp = (ev.b / 127.0) * (volume[c] / 127.0) * v.volume
            p = ((pan[c] + v.pan) / 2.0) / 127.0
            l, r = math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)
            i0 = int(start * rate)
            i1 = min(i0 + n, n_out)
            seg = samp[:i1 - i0] * env[:i1 - i0] * amp
            mix[i0:i1, 0] += seg * l
            mix[i0:i1, 1] += seg * r
    peak = float(np.abs(mix).max()) or 1.0
    pcm = np.clip(mix / peak * 0.9 * 32767, -32768, 32767).astype("<i2")
    return dsp.wav(pcm.tobytes(), rate, 2)
