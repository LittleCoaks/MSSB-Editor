"""Hand-pose sections: the vertex sets a hand model switches between.

Every hand container (the L/R_hand and glove files of the master table and
the hand table at 0x800F5D98) carries a section with version word 0x40001
after its GeoPalette. It holds `n` complete position sets for the hand's
vertices, in the mesh's own quantisation, and the animation event tracks
(codes 0x64xx in the sub-items 4..6 and the shared sets) pick one per frame.

    0x00 u32 0x40001   0x04 u32 0x10000   0x08 u32 0x24 (offset of the header below)
    0x24 u16 poses  u16 1   ...   0x32 u16 vertex count
    0x3c u32 offset[poses]  (each block: vertex count x 3 x s16)

This is also where the bat lives: the batting hands (`L/R_hand07`, 556
triangles) model the bat as triangles collapsed onto the palm in the rest
pose; poses 2 and 3 pull them out into a 1.8-unit bat held in the fist. The
simpler hands (`L/R_hand00`) have three poses: open, holding the bat, and
hidden. There is no separate bat file for characters with hands.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

POSE_VERSION = 0x40001


@dataclass
class Poses:
    count: int
    vertices: int
    blocks: list[list[tuple[float, float, float]]]   # per pose, one position per vertex
    extents: list[float]                              # longest bounding-box side of each pose

    def bat_pose(self) -> int | None:
        """The pose that grows the mesh most (the bat coming out), if any pose
        is at least twice the size of the rest pose."""
        rest = self.extents[0] if self.extents else 0.0
        if not rest:
            return None
        k = max(range(self.count), key=lambda i: self.extents[i])
        return k if self.extents[k] >= 2 * rest else None


def is_poses(data: bytes, base: int) -> bool:
    return base + 0x40 <= len(data) and struct.unpack_from(">I", data, base)[0] == POSE_VERSION


def parse_poses(data: bytes, base: int, rest: list[tuple] | None = None) -> Poses | None:
    """Parse a 0x40001 section. `rest` (the mesh's positions) fixes the
    quantisation shift: pose 0 is always the rest pose, so the shift that
    reproduces it is the right one; without it 10 fraction bits are assumed."""
    if not is_poses(data, base):
        return None
    n, one = struct.unpack_from(">HH", data, base + 0x24)
    nv = struct.unpack_from(">H", data, base + 0x32)[0]
    if not n or not nv or one != 1 or base + 0x3c + n * 4 > len(data):
        return None
    offs = struct.unpack_from(f">{n}I", data, base + 0x3c)
    raw = []
    for o in offs:
        p = base + o
        if p + nv * 6 > len(data):
            return None
        raw.append(struct.unpack_from(f">{nv * 3}h", data, p))
    shift = 10
    if rest and len(rest) == nv:
        for s in range(4, 16):
            sc = float(1 << s)
            if all(abs(raw[0][i * 3 + c] / sc - rest[i][c]) < 1e-6 for i in range(min(nv, 32)) for c in range(3)):
                shift = s
                break
    sc = float(1 << shift)
    blocks = [[(v[i * 3] / sc, v[i * 3 + 1] / sc, v[i * 3 + 2] / sc) for i in range(nv)] for v in raw]
    extents = []
    for b in blocks:
        lo = [min(p[i] for p in b) for i in range(3)]
        hi = [max(p[i] for p in b) for i in range(3)]
        extents.append(max(h - l for l, h in zip(lo, hi)))
    return Poses(n, nv, blocks, extents)
