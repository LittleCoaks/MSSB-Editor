"""MusyX sound groups (Factor 5's audio engine, which this game uses).

The 48 files in the DOL table at 0x800EF508 are MusyX *group files*: one
sound-effect group each (plus one instrument bank for sequenced music),
bundling the four MusyX resources the engine's `sndPushGroup` takes:

    0x00  u32 projOff, u32 projSize      project: GROUP_DATA + id lists + FX table
    0x08  u32 sdirOff, u32 sdirSize      sample directory
    0x10  u32 poolOff, u32 poolSize      macros / curves / keymaps / layers
    0x18  u32 sampOff, u32 sampSize      DSP-ADPCM sample data

Structures (big-endian, from the decomp's musyx_priv.h):

* GROUP_DATA: u32 nextOff, u16 id, u16 type (0 song, 1 sfx), u32 macroOff,
  sampleOff, curveOff, keymapOff, layerOff, then u32 tableOff for sfx groups.
  The offsets point at 0xFFFF-terminated u16 id lists; the FX table is
  u16 count, pad, then 10-byte entries: u16 sfxId, u16 macroId, u8 defKey?,
  u8 defVel?, u8 priority, u8 maxVoices, u8 key, u8 pan.
* SDIR_DATA (0x20): u16 id, u16 refCnt, u32 offset (into samp), u32 addr,
  u32 info (base note << 24 | sample rate), u32 length (samples), u32 loop
  start, u32 loop length, u32 adpcmOff (into sdir). Terminated by id 0xFFFF.
  ADPCM block (0x28): u16 bytesPerFrame, u8 predScale, u8 loopPredScale,
  s16 loopHist2, s16 loopHist1, s16 coef[16].
* POOL_DATA: u32 macroOff, curveOff, keymapOff, layerOff; each a list of
  MEM_DATA {u32 nextOff (0xFFFFFFFF ends), u16 id, u16 pad, data}. A macro's
  data is 8-byte steps; the low 7 bits of the first word are the opcode and
  opcode 0x10 (START_SAMPLE) carries the sample id in bits 8..23.

Sounds are therefore reached as sfx id -> macro -> sample(s); samples decode
with the ordinary DSP-ADPCM decoder.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import dsp

OP_END = 0
OP_START_SAMPLE = 0x10
OP_PLAY_MACRO = 0x0D  # spawns another macro; followed for sample discovery


@dataclass
class Sample:
    id: int
    offset: int          # into the samp section
    rate: int
    base_note: int
    count: int
    loop_start: int
    loop_length: int
    pred_scale: int
    coefs: tuple

    @property
    def seconds(self) -> float:
        return self.count / self.rate if self.rate else 0.0

    @property
    def byte_length(self) -> int:
        return (self.count + 13) // 14 * 8


@dataclass
class Sfx:
    id: int
    macro: int
    priority: int
    max_voices: int
    key: int
    pan: int
    samples: list[int] = field(default_factory=list)  # sample ids the macro plays


@dataclass
class Group:
    id: int
    type: int            # 0 song (instrument bank), 1 sound effects
    samples: list[Sample]
    sfx: list[Sfx]
    macros: dict[int, list[int]]  # macro id -> sample ids
    samp_off: int

    @property
    def kind(self) -> str:
        return "sound effects" if self.type == 1 else "instrument bank"

    def sample(self, sid: int) -> Sample | None:
        return next((s for s in self.samples if s.id == sid), None)


def sections(data: bytes) -> list[tuple[int, int]] | None:
    if len(data) < 0x20:
        return None
    v = struct.unpack_from(">8I", data, 0)
    pairs = [(v[i], v[i + 1]) for i in range(0, 8, 2)]
    if pairs[0][0] != 0x20 or any(s == 0 for _o, s in pairs[:3]):
        return None
    for i in range(3):
        if pairs[i][0] + pairs[i][1] > pairs[i + 1][0]:
            return None
    if pairs[3][0] + pairs[3][1] != len(data):
        return None
    return pairs


def is_group(data: bytes) -> bool:
    p = sections(data)
    if not p:
        return False
    nxt, _gid, typ = struct.unpack_from(">IHH", data, p[0][0])
    return typ in (0, 1) and nxt <= p[0][1]


def _id_list(data: bytes, pos: int, limit: int) -> list[int]:
    out = []
    while pos + 2 <= limit:
        v = struct.unpack_from(">H", data, pos)[0]
        if v == 0xFFFF:
            break
        out.append(v)
        pos += 2
    return out


def parse_group(data: bytes) -> Group | None:
    p = sections(data)
    if not p or not is_group(data):
        return None
    (po, ps), (so, ss), (lo, ls), (mo, ms) = p
    _nxt, gid, typ, mac_off, smp_off, _cv, _km, _ly = struct.unpack_from(">IHHIIIII", data, po)
    # sample directory
    samples = []
    pos = so
    while pos + 0x20 <= so + ss:
        sid, _rc, off, _addr, info, ln, lst, lln, adp = struct.unpack_from(">HHIIIIIII", data, pos)
        if sid == 0xFFFF:
            break
        ps_ = 0
        coefs = (0,) * 16
        if so + adp + 0x28 <= so + ss:
            _bpf, ps_, _lps, _lh2, _lh1 = struct.unpack_from(">HBBhh", data, so + adp)
            coefs = struct.unpack_from(">16h", data, so + adp + 8)
        samples.append(Sample(sid, off, info & 0xFFFFFF, info >> 24, ln, lst, lln, ps_, coefs))
        pos += 0x20
    # pool macros -> sample ids
    macros: dict[int, list[int]] = {}
    spawns: dict[int, list[int]] = {}   # macro id -> macros it starts (PLAY_MACRO)
    mem: dict[str, dict[int, tuple[int, int]]] = {"macros": {}, "keymaps": {}, "layers": {}}

    def mem_list(off: int) -> dict[int, tuple[int, int]]:
        """MEM_DATA chain at pool + off: {id: (data start, data end)}."""
        out: dict[int, tuple[int, int]] = {}
        pos = lo + off
        while off and pos + 8 <= lo + ls:
            nxt, mid = struct.unpack_from(">IH", data, pos)
            if nxt == 0xFFFFFFFF:
                break
            out[mid] = (pos + 8, min(pos + nxt, lo + ls))
            if nxt == 0:
                break
            pos += nxt
        return out
    if lo + 16 <= lo + ls:
        macro_off, _curve_off, keymap_off, layer_off = struct.unpack_from(">4I", data, lo)
        mem["macros"] = mem_list(macro_off)
        mem["keymaps"] = mem_list(keymap_off)
        mem["layers"] = mem_list(layer_off)
        for mid, (a, end) in mem["macros"].items():
            ids, sub = [], []
            q = a
            while q + 8 <= end:
                w0, _w1 = struct.unpack_from(">II", data, q)
                op = w0 & 0x7F
                if op == OP_START_SAMPLE:
                    sid = (w0 >> 8) & 0xFFFF
                    if sid not in ids:
                        ids.append(sid)
                elif op == OP_PLAY_MACRO:
                    sub.append((w0 >> 8) & 0xFFFF)
                q += 8
            macros[mid] = ids
            spawns[mid] = sub

    def samples_of(mid: int, seen: set | None = None) -> list[int]:
        """Every sample an sfx object plays: a macro (following the macros it
        spawns), a layer (id | 0x8000: its macros over every key range) or a
        keymap (id | 0x4000: one macro per key)."""
        seen = seen if seen is not None else set()
        if mid in seen:
            return []
        seen.add(mid)
        out: list[int] = []

        def add(ms):
            for m in ms:
                for sid in samples_of(m, seen):
                    if sid not in out:
                        out.append(sid)
        if mid & 0x8000 and mid in mem["layers"]:
            a, b = mem["layers"][mid]
            num = struct.unpack_from(">I", data, a)[0] if a + 4 <= b else 0
            add(struct.unpack_from(">H", data, a + 4 + i * 12)[0] for i in range(min(num, (b - a - 4) // 12)))
        elif mid & 0x4000 and mid in mem["keymaps"]:
            a, b = mem["keymaps"][mid]
            add({struct.unpack_from(">H", data, a + k * 8)[0] for k in range((b - a) // 8)} - {0xFFFF})
        else:
            out.extend(macros.get(mid, []))
            add(spawns.get(mid, []))
        return out
    # fx table
    sfx = []
    if typ == 1:
        tab = struct.unpack_from(">I", data, po + 0x1C)[0]
        t = po + tab
        if t + 4 <= po + ps:
            n = struct.unpack_from(">H", data, t)[0]
            for i in range(n):
                q = t + 4 + i * 10
                if q + 10 > po + ps:
                    break
                fid, mid, _k, _v, prio, maxv, key, pan = struct.unpack_from(">HHBBBBBB", data, q)
                sfx.append(Sfx(fid, mid, prio, maxv, key, pan, samples_of(mid)))
    return Group(gid, typ, samples, sfx, macros, mo)


def dsp_header(s: Sample) -> dsp.DspHeader:
    return dsp.DspHeader(s.count, s.count * 16 // 14, s.rate, 1 if s.loop_length else 0, 0,
                         s.loop_start, s.loop_start + s.loop_length, s.coefs, s.pred_scale, 0, 0)


def decode(data: bytes, g: Group, s: Sample, max_seconds: float | None = None) -> bytes:
    """PCM16 mono for one sample."""
    frames = data[g.samp_off + s.offset: g.samp_off + s.offset + s.byte_length]
    limit = int(max_seconds * s.rate) if max_seconds else None
    return dsp.decode(dsp_header(s), frames, limit)


def wav(data: bytes, g: Group, s: Sample, max_seconds: float | None = None) -> bytes:
    return dsp.wav(decode(data, g, s, max_seconds), s.rate)
