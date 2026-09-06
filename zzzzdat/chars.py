"""The character tables in main.dol.

Two 16-byte descriptor tables describe every playable character:

* **Sub-files table** at 0x800F1D78 (DOL file offset 0xEED78): 54 slots x 19
  tracks, index = slot * 19 + track. Track 0 is the character's model pack
  (`<name>00.gpc`), track 1 the equipment/knuckles pack, tracks 2..18 the
  animation banks. Every slot has its own copies. Offsets are absolute in
  ZZZZ.dat.
* **Master descriptors** at 0x800EFD38 (DOL file offset 0xECD38): 516 entries
  whose offsets are relative to the ARAM chunk at 0x1A15E800:
    0..32       the 33 distinct body models (colour variants share one)
    33..53      21 texture sets, one per colour-variant slot
    54..431     7 sub-items per slot: right hand, left hand, bat, alt bat,
                batting grip, pitching grip, catching grip
    432..485    per-slot rig / animation set
    486..515    shared items
* **Glove attachment table** at 0x800EEAAC: one u16 per slot, an offset into
  the bone-id sub-table at 0x800EEB18 (6 u16 per slot).

The slot order below is the game's roster order, confirmed from the model
names embedded in each slot's track-0 pack and from the community's
"First Found" names (which list the slots in order). The body-model and
texture-set mappings were derived from the data: the 21 texture sets were
matched to their models by texture layout; the order inside a family is
assumed to follow slot order. DrSeil's toolkit (github.com/DrSeil/mssb-dtk,
feat/character-cloning-texture-decoupling) first documented the tables but
lists the slots in a different order and assumes one body model per slot.
"""
from __future__ import annotations

SUBFILES_VA = 0x800F1D78
MASTER_VA = 0x800EFD38
GLOVE_VA = 0x800EEAAC
GLOVE_BONES_VA = 0x800EEB18
ARAM_CHUNK = 0x1A15E800
SLOTS = 54
TRACKS = 19
MASTER_ENTRIES = 516
MODELS = 33
ITEMS_BASE = 54
RIGS_BASE = 432
SHARED_BASE = 486

SLOT_NAMES = [
    "Mario", "Luigi", "Donkey Kong", "Diddy Kong", "Peach", "Daisy", "Yoshi", "Baby Mario", "Baby Luigi", "Bowser",
    "Wario", "Waluigi", "Koopa Troopa (red)", "Toad (red)", "Boo", "Toadette", "Shy Guy (red)", "Birdo",
    "Monty Mole", "Bowser Jr.", "Paratroopa (red)", "Pianta (blue)", "Pianta (red)", "Pianta (yellow)",
    "Noki (blue)", "Noki (red)", "Noki (green)", "Hammer Bro", "Toadsworth", "Toad (blue)", "Toad (yellow)",
    "Toad (green)", "Toad (purple)", "Magikoopa (blue)", "Magikoopa (red)", "Magikoopa (green)",
    "Magikoopa (yellow)", "King Boo", "Petey Piranha", "Dixie Kong", "Goomba", "Paragoomba",
    "Koopa Troopa (green)", "Paratroopa (green)", "Shy Guy (blue)", "Shy Guy (yellow)", "Shy Guy (green)",
    "Shy Guy (black)", "Dry Bones (gray)", "Dry Bones (green)", "Dry Bones (red)", "Dry Bones (blue)",
    "Fire Bro", "Boomerang Bro",
]
assert len(SLOT_NAMES) == SLOTS

# master body-model index -> the slots that use it (the first is the base colour)
MODEL_SLOTS: dict[int, list[int]] = {i: [i] for i in range(22)}
MODEL_SLOTS.update({12: [12, 42], 13: [13, 29, 30, 31, 32], 16: [16, 44, 45, 46, 47], 20: [20, 43], 21: [21, 22, 23],
                    22: [24, 25, 26], 23: [28], 24: [33, 34, 35, 36], 25: [37], 26: [38], 27: [39], 28: [40],
                    29: [41], 30: [48, 49, 51], 31: [50], 32: [27, 52, 53]})
SLOT_MODEL = {s: m for m, slots in MODEL_SLOTS.items() for s in slots}
assert len(SLOT_MODEL) == SLOTS

# master texture-set index (33..53) -> the colour-variant slot it recolours
TEXTURE_SET_SLOT = {33: 42, 34: 29, 35: 30, 36: 31, 37: 32, 38: 44, 39: 45, 40: 46, 41: 47, 42: 43, 43: 22, 44: 23,
                    45: 25, 46: 26, 47: 52, 48: 53, 49: 34, 50: 35, 51: 36, 52: 49, 53: 51}
SLOT_TEXTURE_SET = {s: i for i, s in TEXTURE_SET_SLOT.items()}

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
        if i < MODELS:
            slots = MODEL_SLOTS[i]
            shared = f" (also {', '.join(SLOT_NAMES[s] for s in slots[1:])})" if len(slots) > 1 else ""
            return {"table": "master", "slot": slots[0], "character": SLOT_NAMES[slots[0]],
                    "role": "body model (ARAM)" + shared, "index": i, "slots": slots}
        if i < ITEMS_BASE:
            slot = TEXTURE_SET_SLOT[i]
            return {"table": "master", "slot": slot, "character": SLOT_NAMES[slot], "role": "textures (ARAM)", "index": i}
        if i < RIGS_BASE:
            slot, k = divmod(i - ITEMS_BASE, 7)
            return {"table": "master", "slot": slot, "character": SLOT_NAMES[slot], "role": SUB_ITEM_NAMES[k], "index": i}
        if i < SHARED_BASE:
            slot = i - RIGS_BASE
            return {"table": "master", "slot": slot, "character": SLOT_NAMES[slot], "role": "skeleton rig", "index": i}
        return {"table": "master", "slot": None, "character": None, "role": f"shared item {i - SHARED_BASE}", "index": i}
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


# Community ("First Found ...") names -> slot names, so files named that way
# land in the right character group.
COMMUNITY_SLOTS = {
    "Mario": 0, "Luigi": 1, "DK": 2, "Diddy": 3, "Peach": 4, "Daisy": 5, "Yoshi": 6, "Baby Mario": 7, "Baby Luigi": 8,
    "Bowser": 9, "Wario": 10, "Waluigi": 11, "Koopa(R)": 12, "toad_r": 13, "boo": 14, "toadette": 15, "shy_guy_r": 16,
    "birdo": 17, "monty": 18, "bowser_jr": 19, "paratroopa": 20, "pianta_b": 21, "pianta_r": 22, "pianta_y": 23,
    "Noki(B)": 24, "Noki(R)": 25, "Noki(G)": 26, "Bro(H)": 27, "Toadsworth": 28, "Toad(B)": 29, "Toad(Y)": 30,
    "Toad(G)": 31, "Toad(P)": 32, "Magikoopa(B)": 33, "Magikoopa(R)": 34, "Magikoopa(G)": 35, "Magikoopa(Y)": 36,
    "King Boo": 37, "Petey": 38, "Dixie": 39, "Goomba": 40, "Paragoomba": 41, "Koopa(G)": 42, "Paratroopa(G)": 43,
    "Shy Guy(B)": 44, "Shy Guy(Y)": 45, "Shy Guy(G)": 46, "Shy Guy(Bk)": 47, "Dry Bones(Gy)": 48, "Dry Bones(G)": 49,
    "Dry Bones(R)": 50, "Dry Bones(B)": 51, "Bro(F)": 52, "Bro(B)": 53,
}


def slot_from_community(name: str) -> int | None:
    n = name.replace("First Found ", "").strip()
    return COMMUNITY_SLOTS.get(n)
