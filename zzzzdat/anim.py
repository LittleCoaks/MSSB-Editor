"""Nintendo CharPipeline (C3) animation banks and skin files.

**ANIM bank** (`ANIMBank`, version word 0x007B7960 like actors; offsets are
relative to the bank):

    0x00 u32 version   0x04 ptr sequences   0x08 u16 bankID  u16 numSequences
    0x0C u16 numTracks u16 numKeyFrames     0x10 u32 userDataSize  ptr userData
    ANIMSequences (0xC): ptr name, ptr tracks, u16 totalTracks, pad
    ANIMTrack     (0x10): f32 animTime, ptr keyFrames, u16 totalFrames,
                          u16 trackID (= bone id), u8 quantizeInfo, u8 animType,
                          u8 interpolationType, u8 replaceHierarchyCtrl
    KeyFrame      (0xC): f32 time (frames), ptr setting, ptr interpolation

Worked out from the data (the SDK's flag names do not match what the
exporter wrote): the setting holds a quaternion first when animType & 8
(4 x s16, always 14 fraction bits) then a translation when animType & 1
(3 x s16, fraction bits = quantizeInfo & 0xF). Other animType bits are not
seen in this game except 0x2A on a few dozen tracks, which are skipped.
interpolationType packs two 3-bit fields: bits 5-7 for the quaternion,
bits 0-2 for the vector (0 = step, otherwise curve; the game uses hermite
tangents which are approximated here by linear / slerp interpolation).

**Skin** (`sHdr`, the section with u16 counts at its start):

    0x00 u16 numSk1 u16 numSk2 u16 numSkAcc u8 posNrmShift pad
    0x08 ptr sk1List ptr sk2List ptr skAccList ptr bzeroBase u32 bzeroSize ...
    SK1List (0x40): Mtx34, ptr vertSrc, ptr vertDst, u16 boneIndex, u16 count, u8 srcOffset
    SK2List (0x74): Mtx34 x2, ptr vertSrc, ptr weights, ptr vertDst, u16 bone0, u16 bone1, u16 count, u8 srcOffset
    SKAccList (0x44): Mtx34, ptr vertSrc, ptr vertIndices, ptr vertDst, ptr weights, u16 boneIndex, u16 count

`vertDst` is a byte offset into the skinned mesh's interleaved position +
normal array (6 x s16 per vertex). Source vertices equal the rest pose, so
this is ordinary inverse-bind skinning. `boneIndex` counts bones in pre-order
traversal of the actor's tree (the order ACTGet fills its bone array).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .c3 import ACT_VERSION, Bone, _cstr, is_actor

QUAT_SCALE = 16384.0
FRAME_RATE = 60.0


@dataclass
class Key:
    time: float                    # frames
    quat: tuple | None
    trans: tuple | None


@dataclass
class Track:
    bone: int                      # bone id (ANIMTrack.trackID)
    keys: list[Key]
    duration: float
    quat_step: bool = False
    trans_step: bool = False


@dataclass
class Sequence:
    name: str
    tracks: list[Track]

    @property
    def duration(self) -> float:
        return max((t.duration for t in self.tracks), default=0.0)


@dataclass
class Bank:
    sequences: list[Sequence]
    skipped: int = 0               # tracks with unsupported animType


def is_bank(data: bytes, base: int) -> bool:
    if base + 0x18 > len(data) or is_actor(data, base):
        return False
    v, pseq, _bank, nseq, ntr, _nkf = struct.unpack_from(">IIHHHH", data, base)
    return v == ACT_VERSION and pseq == 0x18 and 0 < nseq < 4096 and base + pseq + nseq * 12 <= len(data)


def parse_bank(data: bytes, base: int) -> Bank | None:
    if not is_bank(data, base):
        return None
    _v, pseq, _bank, nseq, _ntr, _nkf = struct.unpack_from(">IIHHHH", data, base)
    seqs = []
    skipped = 0
    for s in range(nseq):
        pname, ptracks, ntracks, _pad = struct.unpack_from(">IIHH", data, base + pseq + s * 12)
        name = _cstr(data, base + pname) if pname and base + pname < len(data) else ""
        tracks = []
        for t in range(ntracks):
            at = base + ptracks + t * 16
            if at + 16 > len(data):
                break
            atime, pkf, total, tid, q, aty, ity, _rep = struct.unpack_from(">fIHHBBBB", data, at)
            has_q, has_t = bool(aty & 8), bool(aty & 1)
            if aty & ~9 or not (has_q or has_t):
                skipped += 1
                continue
            frac = float(1 << (q & 0xF))
            keys = []
            for k in range(total):
                ko = base + pkf + k * 12
                if ko + 12 > len(data):
                    break
                kt, pset, _pint = struct.unpack_from(">fII", data, ko)
                so = base + pset
                quat = trans = None
                if has_q:
                    x, y, z, w = struct.unpack_from(">4h", data, so)
                    quat = (x / QUAT_SCALE, y / QUAT_SCALE, z / QUAT_SCALE, w / QUAT_SCALE)
                    so += 8
                if has_t:
                    x, y, z = struct.unpack_from(">3h", data, so)
                    trans = (x / frac, y / frac, z / frac)
                keys.append(Key(kt, quat, trans))
            if keys:
                tracks.append(Track(tid, keys, atime, quat_step=(ity >> 5) == 0, trans_step=(ity & 7) == 0))
        seqs.append(Sequence(name or f"sequence {s + 1}", tracks))
    return Bank(seqs, skipped)


# ------------------------------------------------------------------ skin --
@dataclass
class Skin:
    weights: dict[int, list[tuple[int, float]]] = field(default_factory=dict)  # vertex -> [(bone array index, w)]
    vertex_count: int = 0


def is_skin(data: bytes, base: int) -> bool:
    if base + 0x24 > len(data):
        return False
    n1, n2, na, shift, _pad, p1, p2, pa = struct.unpack_from(">HHHBBIII", data, base)
    return p1 == 0x24 and shift <= 16 and n1 + n2 + na > 0 and (n1 + n2 + na) < 4096


def parse_skin(data: bytes, base: int) -> Skin | None:
    if not is_skin(data, base):
        return None
    n1, n2, na, _shift, _pad, p1, p2, pa = struct.unpack_from(">HHHBBIII", data, base)
    sk = Skin()

    def add(v: int, bone: int, w: float) -> None:
        if w > 0:
            sk.weights.setdefault(v, []).append((bone, w))
            sk.vertex_count = max(sk.vertex_count, v + 1)

    for i in range(n1):
        _src, dst, bone, cnt, _so = struct.unpack_from(">IIHHB", data, base + p1 + i * 0x40 + 0x30)
        for k in range(cnt):
            add(dst // 12 + k, bone, 1.0)
    for i in range(n2):
        _src, pw, dst, b0, b1, cnt, _so = struct.unpack_from(">IIIHHHB", data, base + p2 + i * 0x74 + 0x60)
        ws = data[base + pw:base + pw + cnt]
        for k in range(cnt):
            w = ws[k] / 255.0 if k < len(ws) else 0.5
            add(dst // 12 + k, b0, w)
            add(dst // 12 + k, b1, 1.0 - w)
    for i in range(na):
        _src, pidx, _dst, pw, bone, cnt = struct.unpack_from(">IIIIHH", data, base + pa + i * 0x44 + 0x30)
        idx = struct.unpack_from(f">{cnt}H", data, base + pidx)
        ws = data[base + pw:base + pw + cnt]
        for k in range(cnt):
            add(idx[k], bone, (ws[k] / 255.0) if k < len(ws) else 0.0)
    for v, lst in sk.weights.items():
        merged: dict[int, float] = {}
        for b, w in lst:
            merged[b] = merged.get(b, 0.0) + w
        tot = sum(merged.values()) or 1.0
        sk.weights[v] = sorted(((b, w / tot) for b, w in merged.items()), key=lambda x: -x[1])[:4]
    return sk


def bone_order(bones: list[Bone]) -> list[Bone]:
    """Bones in pre-order traversal of the actor's tree (the SDK's bone array
    order, used by skin lists)."""
    by_off = {b.offset: b for b in bones}
    out: list[Bone] = []
    seen: set[int] = set()

    def visit(b: Bone) -> None:
        if b.offset in seen:
            return
        seen.add(b.offset)
        out.append(b)
        c = by_off.get(b.children) if b.children else None
        while c:
            visit(c)
            c = by_off.get(c.next) if c.next else None

    roots = [b for b in bones if not b.parent]
    if roots:
        r = roots[0]
        while r:
            visit(r)
            r = by_off.get(r.next) if r.next else None
    for b in bones:  # anything unreachable through the links keeps array order
        visit(b)
    return out
