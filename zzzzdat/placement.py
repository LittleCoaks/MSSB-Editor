"""Where the game stands a stadium's instanced props: tables in game.rel.

A prop pack's actors place the scenery that exists once (the waves, the
river, the smoke). Objects the park uses several times - palm trees, Thwomps,
Chain Chomps - sit at the pack's origin, and game.rel's .data lists where each
copy goes. The tables differ per park but share a shape: records of a
position (x, y, z floats, actor space: -Y is up, +Z is the outfield), a
four-byte tag whose first byte is the record type and third the copy number,
and for some a Y rotation in degrees and a scale; a record of another type
ends the table.

    Mario Stadium  `marioStadiumTrees` (US .data+0x17B98): five palm trees
    Bowser Castle  `thwompStaticValues` (+0x17514): six Thwomps, 18 up;
                   +0x17704: two upright and six flat star panels
    Wario Palace   `chompPlacementConfig` (+0x182C8): the two Chain Chomps;
                   +0x185D0: eight bench plants;
                   `sandStarPlacementConfig` (+0x18730): three sand stars
    Yoshi Park     `parkPlantData` (+0x18ED0): six Piranha Plants
    Peach's Garden `blocks` (+0x1BA98): sixteen floating blocks, 9-12 up
    DK Jungle      `barrelLauncherDataStruct` (+0x1B884): the two cannons;
                   `jungleKlaptrapData` (+0x1B9A4): three Klaptraps in the river
    Toy Field      +0x19090: eight floor panels

The tables are found by their first record's bytes, not by address, so every
build that carries the same values works. The tag's first byte is the object's
number in the pack - in most parks simply the n-th model (Mario 2 = the palm,
Bowser 2/4/5 = Thwomp and the two star panels, Peach 0-3 = brick, brick made
of pieces, ? block, note block, Toy 0/2/4/5 = panels). DK Jungle counts the
barrel and its broken twin as one (1 = cannon, 2 = Klaptrap), so each table
names its sections outright. Records left at the origin (Peach's nine block
shadows) and the things that only appear mid-game (Wario Palace's sandstorms,
Bowser's fireballs, DK's rolling barrels) are not drawn.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Table:
    first: tuple[float, float, float]   # the first record's position: the anchor searched for
    stride: int
    tag: int                            # offset of the 4-byte tag
    sections: dict                      # record type -> section, or (type, copy) -> section
    rot: int | None = None              # offset of the Y rotation (degrees)
    scale: int | None = None            # offset of the 3-float scale


# per stadium (stadiums.NAMES order)
TABLES: dict[int, list[Table]] = {
    0: [Table((24.4, 0.0, 117.2), 0x20, 0x1C, {2: 7}, rot=0x18, scale=0x0C)],
    1: [Table((-51.592, -18.0, 68.051), 0x14, 0x10, {2: 6}, rot=0x0C),
        Table((-12.891, -5.93, 87.961), 0x14, 0x10, {4: 10, 5: 12}, rot=0x0C)],
    2: [Table((55.0, 0.0, 40.0), 0x34, 0x0C, {(0, 1): 2, (0, 2): 4}, rot=0x14),
        Table((37.4, 0.0, 8.0), 0x20, 0x0C, {7: 17}, rot=0x1C, scale=0x10),
        Table((0.0, 0.15, 60.0), 0x10, 0x0C, {(8, 1): 20, (8, 2): 22, (8, 3): 24})],
    3: [Table((-18.0, 0.0, 52.0), 0x1C, 0x10, {0: 2}, rot=0x0C)],
    4: [Table((-12.0, -12.0, 55.0), 0x14, 0x10, {0: 2, 1: 4, 2: 7, 3: 9}, rot=0x0C)],
    5: [Table((32.536, 4.0, 100.625), 0x14, 0x10, {1: 8}, rot=0x0C),
        Table((-22.621, 0.0, 66.963), 0x18, 0x10, {2: 10}, rot=0x0C)],
    6: [Table((17.6, 0.11, 36.0), 0x14, 0x10, {0: 2, 2: 6, 4: 10, 5: 12}, rot=0x0C)],
}
# a pack's day and night twins of the same object (Mario Stadium: the boat and the palm)
NIGHT_TWINS: dict[int, dict[int, int]] = {0: {4: 10, 7: 13}}


def _find(data: bytes, t: Table) -> int | None:
    pat = struct.pack(">3f", *t.first)
    at = data.find(pat)
    while at >= 0:
        if at % 4 == 0 and at + t.stride <= len(data) and _section(t, data[at + t.tag:at + t.tag + 4]) is not None:
            return at
        at = data.find(pat, at + 1)
    return None


def _section(t: Table, tag: bytes) -> int | None:
    if len(tag) < 4:
        return None
    s = t.sections.get((tag[0], tag[2]))
    return s if s is not None else t.sections.get(tag[0])


def instances(rel_data: bytes, stadium: int) -> dict[int, list[dict]]:
    """{section: [{pos, rot, scale}]} in the viewer's space (the static export's
    half-turn about X: x, -y, -z, and a Y rotation that turns the other way)."""
    out: dict[int, list[dict]] = {}
    for t in TABLES.get(stadium, []):
        at = _find(rel_data, t)
        if at is None:
            continue
        for _ in range(64):
            if at + t.stride > len(rel_data):
                break
            sec = _section(t, rel_data[at + t.tag:at + t.tag + 4])
            if sec is None:
                break
            x, y, z = struct.unpack_from(">3f", rel_data, at)
            if not (x or y or z):
                at += t.stride      # parked at the origin until the game needs it
                continue
            rot = struct.unpack_from(">f", rel_data, at + t.rot)[0] if t.rot is not None else 0.0
            scale = struct.unpack_from(">3f", rel_data, at + t.scale) if t.scale is not None else (1.0, 1.0, 1.0)
            out.setdefault(sec, []).append({"pos": [x, -y, -z], "rot": -rot, "scale": list(scale)})
            at += t.stride
    for day, night in (NIGHT_TWINS.get(stadium) or {}).items():
        if day in out:
            out[night] = out[day]
    return out
