"""The character tables in main.dol, after DrSeil's character-cloning work
(github.com/DrSeil/mssb-dtk, feat/character-cloning-texture-decoupling).

Two 16-byte descriptor tables describe every playable character:

* **Sub-files table** at 0x800F1D78 (DOL file offset 0xEED78): 54 slots x 19
  tracks, index = slot * 19 + track. Track 0 is the character's model pack
  (`<name>00.gpc`), track 1 the equipment/knuckles pack (`<name>01.gpc`),
  tracks 2..18 animation banks. Offsets are absolute in ZZZZ.dat.
* **Master descriptors** at 0x800EFD38 (DOL file offset 0xECD38): 516 entries
  whose offsets are relative to the ARAM chunk at 0x1A15E800:
    0..53       standalone body model per slot
    54..431     7 sub-items per slot: right hand, left hand, bat, alt bat,
                batting grip, pitching grip, catching grip
    432..485    skeletal rig per slot
    486..515    shared items
* **Glove attachment table** at 0x800EEAAC: one u16 per slot.
"""
from __future__ import annotations

SUBFILES_VA = 0x800F1D78
MASTER_VA = 0x800EFD38
GLOVE_VA = 0x800EEAAC
ARAM_CHUNK = 0x1A15E800
SLOTS = 54
TRACKS = 19
MASTER_ENTRIES = 516

SLOT_NAMES = [
    "Mario", "Luigi", "Donkey Kong", "Peach", "Daisy", "Yoshi", "Birdo", "Wario", "Waluigi", "Bowser",
    "Koopa Troopa (green)", "Koopa Troopa (red)", "Paratroopa (red)", "Paratroopa (green)",
    "Magikoopa (blue)", "Magikoopa (red)", "Magikoopa (green)", "Magikoopa (yellow)",
    "Hammer Bro", "Bowser Jr.", "Boomerang Bro", "Pianta (blue)", "Pianta (red)", "Pianta (yellow)",
    "Noki (blue)", "Noki (red)", "Noki (green)", "Toad (red)", "Toad (blue)", "Toad (yellow)",
    "Toad (green)", "Toad (purple)", "Toadette", "Toadsworth", "Baby Mario", "Baby Luigi",
    "Dry Bones (gray)", "Dry Bones (red)", "Petey Piranha", "Diddy Kong", "Pianta (blue, alt)",
    "Pianta (red, alt)", "Pianta (yellow, alt)", "King Boo", "Dixie Kong", "Goomba", "Paragoomba",
    "Monty Mole", "Shy Guy (red)", "Shy Guy (blue)", "Shy Guy (yellow)", "Shy Guy (green)",
    "Shy Guy (black)", "Boo",
]

TRACK_NAMES = {0: "model", 1: "equipment", **{t: f"animations {t - 1}" for t in range(2, TRACKS)}}
SUB_ITEM_NAMES = ["right hand", "left hand", "bat", "alternate bat", "batting grip", "pitching grip", "catching grip"]


def base_name(slot_name: str) -> str:
    """'Toad (red)' -> 'Toad'."""
    return slot_name.split(" (")[0]


def classify(va: int) -> dict | None:
    """What a descriptor at DOL address `va` describes, or None."""
    if SUBFILES_VA <= va < SUBFILES_VA + SLOTS * TRACKS * 16 and (va - SUBFILES_VA) % 16 == 0:
        i = (va - SUBFILES_VA) // 16
        slot, track = divmod(i, TRACKS)
        return {"table": "subfiles", "slot": slot, "character": SLOT_NAMES[slot], "track": track,
                "role": TRACK_NAMES[track], "index": i}
    if MASTER_VA <= va < MASTER_VA + MASTER_ENTRIES * 16 and (va - MASTER_VA) % 16 == 0:
        i = (va - MASTER_VA) // 16
        if i < SLOTS:
            return {"table": "master", "slot": i, "character": SLOT_NAMES[i], "role": "body model (ARAM)", "index": i}
        if i < 54 + SLOTS * 7:
            slot, k = divmod(i - 54, 7)
            return {"table": "master", "slot": slot, "character": SLOT_NAMES[slot], "role": SUB_ITEM_NAMES[k], "index": i}
        if i < 432 + SLOTS:
            slot = i - 432
            return {"table": "master", "slot": slot, "character": SLOT_NAMES[slot], "role": "skeleton rig", "index": i}
        return {"table": "master", "slot": None, "character": None, "role": f"shared item {i - 486}", "index": i}
    return None


def classify_entry(refs: list[str]) -> dict | None:
    """First character-table classification among an entry's references."""
    for r in refs:
        if r.startswith("dol:.data:"):
            va = int(r.split(":")[2].split(" ")[0], 16)
            c = classify(va)
            if c:
                return c
    return None
