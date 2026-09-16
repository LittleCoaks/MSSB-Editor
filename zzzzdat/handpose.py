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
    axes: list[tuple[float, float, float]]            # bounding-box size of each pose per axis
    groups: list[list[int]] | None = None             # the mesh's draws, as vertex ids (from the GeoPalette)

    def diagonal(self, k: int, ids) -> float:
        pts = [self.blocks[k][i] for i in ids]
        return sum((max(q[c] for q in pts) - min(q[c] for q in pts)) ** 2 for c in range(3)) ** 0.5

    def bat_pose(self) -> int | None:
        """The pose that pulls the bat out. The bat is a draw of its own that
        lies collapsed inside the palm at rest (a few hundredths of a unit
        across) and unfolds to a bat's length in the bat poses; Donkey Kong's
        fist closes at the same time, so the whole mesh does not grow. Without
        the draws, fall back to the pose that grows the mesh most along an
        axis, if it grows by at least 1.6x."""
        if not self.count:
            return None
        if self.groups:
            # measured over every character: bats unfold from under 0.06 to
            # 0.99 (Peach) .. 2.93 (Bowser); the ball in the palm and the
            # gloves' hidden draws reach 0.29 .. 0.86
            best, best_len = None, 0.0
            for ids in self.groups:
                if len(ids) < 4 or self.diagonal(0, ids) > 0.1:
                    continue
                for k in range(1, self.count):
                    d = self.diagonal(k, ids)
                    if d >= 0.9 and d > best_len:
                        best, best_len = k, d
            if best is not None:
                return best
            # Dry Bones' bat shares the hand's draw, so fall through
        if not self.axes or not all(self.axes[0]):
            return None
        rest = self.axes[0]

        def growth(i: int) -> float:
            return max(a / b for a, b in zip(self.axes[i], rest))
        k = max(range(self.count), key=growth)
        return k if growth(k) >= 1.6 else None


def _align(raw0, sc: float, rest) -> list[int] | None:
    """Mesh vertex index for each posed vertex, if pose 0 at scale `sc` is the
    rest mesh (in order, possibly skipping some mesh vertices); else None."""
    nv = len(raw0) // 3
    if nv > len(rest):
        return None
    order, j = [], 0
    for i in range(nv):
        q = (raw0[i * 3] / sc, raw0[i * 3 + 1] / sc, raw0[i * 3 + 2] / sc)
        while j < len(rest) and any(abs(q[c] - rest[j][c]) >= 1e-6 for c in range(3)):
            j += 1
        if j == len(rest):
            return None
        order.append(j)
        j += 1
    return order


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
    shift, order = 10, None
    if rest:
        for s in range(4, 16):
            sc = float(1 << s)
            order = _align(raw[0], sc, rest)
            if order is not None:
                shift = s
                break
    sc = float(1 << shift)
    blocks = [[(v[i * 3] / sc, v[i * 3 + 1] / sc, v[i * 3 + 2] / sc) for i in range(nv)] for v in raw]
    if order is not None and len(order) != len(rest):
        # the mesh has vertices the pose sets leave alone (Donkey Kong's hands:
        # 327 in the mesh, 301 posed): those keep their rest position
        full = []
        for b in blocks:
            fb = list(rest)
            for i, j in enumerate(order):
                fb[j] = b[i]
            full.append(fb)
        blocks, nv = full, len(rest)
    extents, axes = [], []
    for b in blocks:
        lo = [min(p[i] for p in b) for i in range(3)]
        hi = [max(p[i] for p in b) for i in range(3)]
        size = tuple(h - l for l, h in zip(lo, hi))
        axes.append(size)
        extents.append(max(size))
    return Poses(n, nv, blocks, extents, axes)
