"""Stadium collision meshes: the fence, wall, ground and dugout surfaces of a park.

Every stadium pack carries, right after its skeletons, a section whose magic
is `00 NN 43 00` (NN = record count) followed by NN u32 record offsets.
Record 0 lists a bounding box per record; the others are runs of GX-style
primitives:

    u16 kind, u16 n        kind 1: triangle strip, n triangles, n + 2 points
                           kind 0: triangle list,  n triangles, 3n points
    points of f32 x, f32 y, f32 z, u16 tag, u16 0   (tag = surface code:
                           3, 6, 0x83, 0x85 ...; the 0x80 bit and the low
                           values are not decoded)

A record ends with a 4-byte trailer. Coordinates are in the stadium's actor
space, so they line up with the posed meshes.
"""
from __future__ import annotations

import struct

Point = tuple[float, float, float]


def is_table(magic: int) -> bool:
    return (magic & 0xFFFF) == 0x4300 and (magic >> 16) != 0


def triangles(section: bytes) -> tuple[list[tuple[Point, Point, Point]], list[int], list[str]]:
    """(triangles, surface tag per triangle, problems)."""
    n = section[1]
    if n < 2 or 4 + n * 4 > len(section):
        return [], [], ["no records"]
    offs = struct.unpack_from(f">{n}I", section, 4)
    tris: list[tuple[Point, Point, Point]] = []
    tags: list[int] = []
    problems: list[str] = []
    for i in range(1, n):
        o = offs[i]
        end = offs[i + 1] if i + 1 < n else len(section)
        pos = o
        while pos + 4 <= end:
            kind, count = struct.unpack_from(">HH", section, pos)
            if kind not in (0, 1):
                if end - pos > 4:
                    problems.append(f"record {i}: unknown element kind {kind:#x} at +{pos - o:#x}")
                break
            npts = count + 2 if kind == 1 else count * 3
            if pos + 4 + npts * 16 > end:
                problems.append(f"record {i}: element at +{pos - o:#x} overruns the record")
                break
            pts = []
            for k in range(npts):
                x, y, z, tag, _ = struct.unpack_from(">fffHH", section, pos + 4 + k * 16)
                pts.append(((x, y, z), tag))
            if kind == 1:
                for k in range(count):
                    a, b, c = pts[k], pts[k + 1], pts[k + 2]
                    tris.append((a[0], b[0], c[0]) if k % 2 == 0 else (c[0], b[0], a[0]))
                    tags.append(a[1])
            else:
                for k in range(count):
                    a, b, c = pts[3 * k], pts[3 * k + 1], pts[3 * k + 2]
                    tris.append((a[0], b[0], c[0]))
                    tags.append(a[1])
            pos += 4 + npts * 16
    return tris, tags, problems
