"""The character tables in main.dol.

Two 16-byte descriptor tables describe every playable character:

* **Sub-files table** at 0x800F1D78 (DOL file offset 0xEED78): 54 slots x 19
  tracks, index = slot * 19 + track. Track 0 is the character's model pack
  (`<name>00.gpc`), track 1 a low-detail copy of the same model (about half
  the triangles, for distant cameras), tracks 2..18 the animation banks. Every slot has its own copies. Offsets are absolute in
  ZZZZ.dat.
* **Master descriptors** at 0x800EFD38 (DOL file offset 0xECD38): 516 entries
  whose offsets are relative to the ARAM chunk at 0x1A15E800:
    0..32       the 33 distinct body models (colour variants share one)
    33..53      21 texture sets, one per colour-variant slot
    54..431     7 sub-items per slot: right hand, left hand, bat, alt bat,
                batting grip, pitching grip, catching grip
    432..485    per-slot rig / animation set
    486..515    shared items
* **Slot table** at 0x800F73B8: one u16 per slot, `model << 8 | textureSet`,
  where model indexes the 33 body models (master entries 0..32) and
  textureSet the 21 recolour sets (master entries 33..53, 0xFF = none). This
  is what makes a colour variant: the same model with another texture set.
* **Hand table** at 0x800F5D98: 320 descriptors, six per slot, indexed
  through the u16 table at 0x800EEAAC (`GLOVE_VA`, value = slot * 6):
  left hand, right hand, left glove, right glove, then the same two hands
  again. The two hand copies differ only in their last section, the
  hand-pose event track (21 entries = batting for the first pair, 28 =
  pitching for the second), so `animateModelArmsGlovesBats` picks the pair
  for the situation. Goomba, Paragoomba and Petey have bat models in the
  hand slots. The per-slot sub-items 4..6 in the master table are the same
  event-track sections on their own (batting, pitching, catching).
* **Event-track sets** at 0x800EEB18: one s16 per slot, an id 0..28 into
  the 29 shared master items 486+ (also mirrored outside ARAM in the table
  at 0x800F71D8), colour variants sharing one; -1 for Boo, King Boo, Shy Guy
  and Petey. `fn_80021ADC` loads the set for a player from either copy, in
  the model setup path that also calls `animateModelArmsGlovesBats`.
  Every record (sub-items and shared) has the same layout: u32 count, 0x28,
  end of the offset table, 6, 30, 16, then `count` u32 offsets to entries
  of u16 (total frames, key count, flags, then (frame, code) pairs; codes
  0x64xx select a hand pose, 0x40xx/0x50xx/0x80xx are other cues).
* **Sub-file names**: debug.rel keeps the development paths: each base
  character was `char/ninNN/` (NN = base slot) holding `model0.dat`,
  `model1.dat` and the 17 banks `motb, motr, motf, motp, motc, mote, moto,
  motbs, motbt, motrt, motrm, motfm, motrtoy, motes, motem, motec, motpm`
  in track order (the debug menu labels the categories Batter, Runner,
  Fielder, Pitcher, Catcher, Dir, Other); colour-variant slots only had the
  two model files.
* **Character ids**: the game numbers the 32 base characters separately from
  the roster; `findCharacterID` (0x800698F8) maps a slot to its id through
  the table at 0x80108DB8 (id -> base slot) and folds colour variants onto
  their base. game.rel then loads the voice group `gid_by_id[id]` from its
  own byte table (.data + 0x8148) when a character enters play. The u16
  tables at 0x800EEAAC and 0x800EEB18 are something else (not sound).

The slot order below is the game's roster order, confirmed from the model
names embedded in each slot's track-0 pack and from the community's
"First Found" names (which list the slots in order). The body-model and
texture-set mappings come from the slot table (they also match the texture
layouts). Note the table's own quirk: the Hammer Bro slot uses texture set
47 while the Fire Bro slot uses the HB model's built-in textures. DrSeil's toolkit (github.com/DrSeil/mssb-dtk,
feat/character-cloning-texture-decoupling) first documented the tables but
lists the slots in a different order and assumes one body model per slot.
"""
from __future__ import annotations

SUBFILES_VA = 0x800F1D78
MASTER_VA = 0x800EFD38
GLOVE_VA = 0x800EEAAC
CHARACTER_ID_VA = 0x80108DB8
# character id -> base slot (the DOL table findCharacterID walks)
ID_BASE_SLOT = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 24, 27, 28, 33, 37, 38,
                39, 40, 41, 48]
# character id -> MusyX voice group (game.rel .data + 0x8148)
ID_VOICE_GROUP = [27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 35, 7, 9, 33, 34, 8, 48, 46,
                  39, 47, 50, 37, 36, 38]
_SLOT_ID = {slot: cid for cid, slot in enumerate(ID_BASE_SLOT)}
for _m, _slots in {12: [12, 42], 13: [13, 29, 30, 31, 32], 16: [16, 44, 45, 46, 47], 20: [20, 43], 21: [21, 22, 23],
                   22: [24, 25, 26], 24: [33, 34, 35, 36], 30: [48, 49, 50, 51], 32: [27, 52, 53]}.items():
    for _s in _slots[1:]:
        _SLOT_ID.setdefault(_s, _SLOT_ID[_slots[0]])
CHARACTER_ID = [_SLOT_ID[s] for s in range(54)]
VOICE_GROUP = [ID_VOICE_GROUP[cid] for cid in CHARACTER_ID]
VOICE_SLOTS: dict[int, list[int]] = {}
for _s, _g in enumerate(VOICE_GROUP):
    if _g is not None:
        VOICE_SLOTS.setdefault(_g, []).append(_s)
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

SLOT_TABLE_VA = 0x800F73B8
# the slot table as shipped: model << 8 | texture set (0xFF = the model's own textures)
SLOT_TABLE = [0x00FF, 0x01FF, 0x02FF, 0x03FF, 0x04FF, 0x05FF, 0x06FF, 0x07FF, 0x08FF, 0x09FF, 0x0AFF, 0x0BFF, 0x0CFF,
              0x0DFF, 0x0EFF, 0x0FFF, 0x10FF, 0x11FF, 0x12FF, 0x13FF, 0x14FF, 0x15FF, 0x152B, 0x152C, 0x16FF, 0x162D,
              0x162E, 0x202F, 0x17FF, 0x0D22, 0x0D23, 0x0D24, 0x0D25, 0x18FF, 0x1831, 0x1832, 0x1833, 0x19FF, 0x1AFF,
              0x1BFF, 0x1CFF, 0x1DFF, 0x0C21, 0x142A, 0x1026, 0x1027, 0x1028, 0x1029, 0x1EFF, 0x1E34, 0x1FFF, 0x1E35,
              0x20FF, 0x2030]
assert len(SLOT_TABLE) == SLOTS
SLOT_MODEL = {s: v >> 8 for s, v in enumerate(SLOT_TABLE)}
SLOT_TEXTURE_SET = {s: v & 0xFF for s, v in enumerate(SLOT_TABLE) if v & 0xFF != 0xFF}
TEXTURE_SET_SLOT = {t: s for s, t in SLOT_TEXTURE_SET.items()}
# master body-model index -> the slots that use it (the first has the model's own textures when any does)
MODEL_SLOTS: dict[int, list[int]] = {}
for _s in range(SLOTS):
    MODEL_SLOTS.setdefault(SLOT_MODEL[_s], []).append(_s)
for _m, _slots in MODEL_SLOTS.items():
    _slots.sort(key=lambda s: (s in SLOT_TEXTURE_SET, s))


def variants_of(slot: int) -> list[int]:
    """Slots that share this slot's body model (itself first)."""
    return [slot] + [s for s in MODEL_SLOTS[SLOT_MODEL[slot]] if s != slot]

TRACK_NAMES = {0: "model", 1: "low-detail model", **{t: f"animations {t - 1}" for t in range(2, TRACKS)}}
# the development file name of each sub-file track (from debug.rel's path list, char/ninNN/<name>.dat)
TRACK_FILES = ["model0", "model1", "motb", "motr", "motf", "motp", "motc", "mote", "moto", "motbs", "motbt", "motrt",
               "motrm", "motfm", "motrtoy", "motes", "motem", "motec", "motpm"]
assert len(TRACK_FILES) == TRACKS
SUB_ITEM_NAMES = ["left hand", "right hand", "left glove", "right glove", "batting hand-pose track",
                  "pitching hand-pose track", "catching hand-pose track"]
HAND_TABLE_VA = 0x800F5D98
HAND_TABLE_ROLES = ["left hand (batting)", "right hand (batting)", "left glove", "right glove",
                    "left hand (pitching)", "right hand (pitching)"]
EVENT_SET_VA = 0x800EEB18


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
        return {"table": "master", "slot": None, "character": None, "role": f"hand-pose event set {i - SHARED_BASE}", "index": i}
    if HAND_TABLE_VA <= va < HAND_TABLE_VA + SLOTS * 6 * 16 and (va - HAND_TABLE_VA) % 16 == 0:
        i = (va - HAND_TABLE_VA) // 16
        slot, k = divmod(i, 6)
        if slot < SLOTS:
            return {"table": "hands", "slot": slot, "character": SLOT_NAMES[slot], "role": HAND_TABLE_ROLES[k], "index": i}
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
