"""The character stat table and preset line-ups: the first file game.rel
loads (`rosterFileDescriptorGame`, 18,144 bytes).

Two tables, worked out from the data with the decomp's struct for the rows:

* **54 `CharacterStats` rows** of 0xA0 bytes, one per character in roster
  order (include/game/character_stats.h): a 0x3B-byte stat block, a 54-byte
  chemistry table (one byte per other character, roster order), three spare
  bytes and 22 spare shorts. game.rel copies nine of them into `inMemRoster`
  for each team in play, so this is where a character's pitching, batting,
  running and fielding numbers, star abilities and chemistry live.
* **528 line-up records** of 18 bytes at 0x21C0: nine character ids
  (0xFF = empty) then nine bytes that are always 0x0A. The first 481 are
  blank; the 48 that follow come in groups of four per captain, in the
  challenge-mode captain order (Mario, Peach, Wario, DK, Yoshi, Bowser, then
  Luigi, Daisy, Waluigi, Diddy, Birdo, Bowser Jr.): the captain's full nine,
  a shorter squad or two, the captain alone, and an empty one (all 0xFF). Which menu reads them is
  not known from code; the contents are the game's starting teams.
"""
from __future__ import annotations

import struct

from . import chars

ROW = 0xA0
ROWS = chars.SLOTS
STATS_SIZE = ROW * ROWS          # 0x21C0
LINEUP = 18
LINEUPS = 528
SIZE = STATS_SIZE + LINEUP * LINEUPS   # 18144

FIELDING_ABILITIES = ["wall splat", "wall jump", "clamber", "sliding catch", "laser", "quick throw", "super jump",
                      "magical catch", "tongue catch", "suction", "super catch", "ball dash", "body check",
                      "super curve", "unassigned", "unassigned 2"]
CLASSES = {0: "balance", 1: "power", 2: "speed", 3: "technique"}  # CHARACTER_CLASS in the decomp

# (name, offset) of the u8 fields of the stat block
FIELDS = [
    ("curve_ball_speed", 0x00), ("fast_ball_speed", 0x01), ("cursed_ball", 0x02), ("curve", 0x03),
    ("curve_control", 0x04),
    ("fielding_arm", 0x26), ("batting_stance", 0x27), ("slap_contact", 0x28), ("charge_contact", 0x29),
    ("slap_power", 0x2A), ("charge_power", 0x2B), ("bunting_contact", 0x2C), ("trajectory_push_pull", 0x2D),
    ("trajectory_high_low", 0x2E), ("speed", 0x2F), ("throwing_arm", 0x30), ("character_class", 0x31),
    ("weight", 0x32), ("captain", 0x33), ("captain_star_hit_pitch", 0x34), ("star_swing", 0x35),
    ("star_pitch", 0x36), ("batting_bar", 0x37), ("pitching_bar", 0x38), ("running_bar", 0x39),
    ("fielding_bar", 0x3A),
]


def is_roster(data: bytes) -> bool:
    if len(data) != SIZE:
        return False
    ids = [struct.unpack_from(">h", data, p * ROW + 0x24)[0] for p in range(ROWS)]
    return ids == list(range(ROWS))


def player(row: bytes) -> dict:
    cid = struct.unpack_from(">h", row, 0x24)[0]
    d: dict = {"char_id": cid, "name": chars.SLOT_NAMES[cid] if 0 <= cid < chars.SLOTS else "(none)"}
    for name, off in FIELDS:
        d[name] = row[off]
    flags = struct.unpack_from(">I", row, 0x20)[0]
    d["fielding_flags"] = flags
    d["fielding_abilities"] = [n for i, n in enumerate(FIELDING_ABILITIES) if flags >> i & 1]
    d["class_name"] = CLASSES.get(d["character_class"], str(d["character_class"]))
    d["chemistry"] = list(row[0x3B:0x3B + chars.SLOTS])
    d["spare"] = row[0x05:0x20].hex() + row[0x71:ROW].hex()
    return d


def stats(data: bytes) -> list[dict]:
    return [player(data[p * ROW:(p + 1) * ROW]) for p in range(ROWS)]


def lineups(data: bytes) -> list[dict]:
    """The filled line-up records: {n, members (character ids), tail}."""
    out = []
    for n in range(LINEUPS):
        o = STATS_SIZE + n * LINEUP
        r = data[o:o + LINEUP]
        if not any(r):
            continue
        out.append({"n": n, "members": [x for x in r[:9] if x != 0xFF], "tail": r[9:].hex()})
    return out


def parse(data: bytes) -> dict:
    return {"stats": stats(data), "lineups": lineups(data), "names": list(chars.SLOT_NAMES),
            "abilities": FIELDING_ABILITIES, "fields": [f for f, _ in FIELDS]}


def summary(data: bytes) -> dict:
    return {"rows": ROWS, "lineups": len(lineups(data))}
