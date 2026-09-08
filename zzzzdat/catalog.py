"""Group index entries into things a person recognises: characters, stadiums,
menus, movies, music, sounds. Built from the community names, the embedded
.gpc model names and the executable tables each entry is referenced from.
Anything that cannot be placed lands in "Everything else", grouped by table.
"""
from __future__ import annotations

import re

from . import chars
from .descriptors import Entry

# .gpc model stem -> character
CHARACTER_STEMS = {
    "mario": "Mario", "luigi": "Luigi", "peach": "Peach", "daisy": "Daisy", "yoshi": "Yoshi",
    "donkey": "Donkey Kong", "diddy": "Diddy Kong", "dixie": "Dixie Kong", "wario": "Wario", "waluigi": "Waluigi",
    "koopa": "Bowser", "koopa_jr": "Bowser Jr.", "koopa_t": "Koopa Troopa", "nokonoko": "Koopa Troopa",
    "patapata": "Paratroopa", "b_mario": "Baby Mario", "b_luigi": "Baby Luigi", "kinopio": "Toad",
    "kinopico": "Toadette", "kinoji": "Toadsworth", "teresa": "Boo", "king_teresa": "King Boo",
    "heiho": "Shy Guy", "kamekku": "Magikoopa", "karon": "Dry Bones", "bloodykaron": "Dry Bones",
    "monte_b": "Pianta", "monte": "Pianta", "mare": "Noki", "catherine": "Birdo", "choropu": "Monty Mole",
    "kuribo": "Goomba", "patakuri": "Paragoomba", "hb": "Hammer Bro", "boss_packun": "Petey Piranha",
    "jyugem": "Lakitu", "packun": "Piranha Plant", "wanwan": "Chain Chomp",
}
KNOWN_CHAR_RE = re.compile(r"^First Found (.+)$")
PART_STEMS = ("l_hand", "r_hand", "l_glove", "r_glove")
PART_NAMES = {"l_hand": "Left hand", "r_hand": "Right hand", "l_glove": "Left glove", "r_glove": "Right glove"}

# Community names use short / colour-variant forms; group them under one character.
CANONICAL = {
    "Diddy": "Diddy Kong", "DK": "Donkey Kong", "Dixie": "Dixie Kong", "Bowser Jr": "Bowser Jr.", "Petey": "Petey Piranha",
    "Bro(H)": "Hammer Bro", "Bro(F)": "Fire Bro", "Bro(B)": "Boomerang Bro",
}


def canonical(name: str) -> str:
    if name in CANONICAL:
        return CANONICAL[name]
    base = re.sub(r"\s*\([^)]*\)$", "", name)  # Toad(B) -> Toad, Koopa(R) -> Koopa
    return {"Koopa": "Koopa Troopa", "Paratroopa": "Paratroopa"}.get(base, CANONICAL.get(base, base))


def musyx_group_id(e: Entry) -> int | None:
    m = re.search(r"group (\d+)$", e.label or "")
    return int(m.group(1)) if m else None


SOURCE_CATEGORIES = {"b": "batting", "r": "running", "p": "pitching", "f": "fielding", "c": "catching",
                     "e": "reaction", "o": "misc"}


def display_name(e: Entry, by_id: dict[int, Entry] | None = None) -> str:
    """A name a person would use: the character table's slot and role, else the
    community name, else the character/part behind the embedded model name,
    else what the unreferenced-file analysis (twins.py) made of it."""
    c = chars.classify_entry(e.refs)
    if c and c["character"]:
        return f"{c['character']} - {c['role']}"
    if c:
        return c["role"]
    tag = e.tag.split(":")
    if tag[0] == "animsrc":
        cat = SOURCE_CATEGORIES.get(tag[2], "misc")
        who = chars.SLOT_NAMES[int(tag[1])] + " - " if tag[1] != "-" else ""
        twin = by_id.get(e.twin) if by_id and e.twin >= 0 else None
        ct = chars.classify_entry(twin.refs) if twin else None
        same = f" (names {ct['role']})" if ct and ct["role"].startswith("animations") else ""
        return f"{who}{cat} animation source{same}"
    if tag[0] == "proto":
        return f"prototype {SOURCE_CATEGORIES[tag[1]]} animations" if len(tag) > 1 else "prototype " + (e.label.rsplit(".", 1)[0] if e.label else e.kind)
    if e.twin >= 0 and by_id and e.twin in by_id:
        return "copy of " + (display_name(by_id[e.twin], by_id) or f"file {e.twin}")
    tbl = table_of(e)
    if tbl == "event-sets":
        from . import layout
        n = (int(e.refs[0].split(":")[2].split(" ")[0], 16) - layout.current().event_copy_va) // 16
        return f"hand-pose event set {n} (copy outside ARAM)"
    if e.known:
        return e.known.replace("First Found ", "")
    if e.kind == "musyx":
        gid = musyx_group_id(e)
        slots = chars.VOICE_SLOTS.get(gid, []) if gid is not None else []
        if slots and e.naud <= 40:
            names = [chars.SLOT_NAMES[s] for s in slots]
            return f"{names[0]} - sounds" + (f" (also {', '.join(names[1:])})" if len(names) > 1 else "")
        if slots:
            return f"Sound effects group {gid} (shared: {', '.join(chars.SLOT_NAMES[s] for s in slots)})"
    lab = e.label or next((n for n in e.names if n.endswith(".gpc")), "")
    if lab:
        s = _stem(lab)
        if s in PART_NAMES:
            return PART_NAMES[s]
        if s in CHARACTER_STEMS:
            return CHARACTER_STEMS[s]
        return lab.rsplit(".", 1)[0]
    return ""

STADIUM_NAMES = {
    "stadiums": "Stadiums (main files)", "marioStadiumCDR": "Mario Stadium props",
}


def _stem(label: str) -> str:
    s = label.rsplit(".", 1)[0].lower()
    s = re.sub(r"_?\d+$", "", s)  # mario00 -> mario, parts0600_00 -> parts0600
    return s


def character_of(e: Entry) -> str | None:
    slot = chars.slot_from_community(e.known or "")
    if slot is not None:
        return chars.SLOT_NAMES[slot]
    m = KNOWN_CHAR_RE.match(e.known or "")
    if m:
        return canonical(m.group(1))
    for n in [e.label] + e.names:
        if not n or not n.endswith(".gpc"):
            continue
        s = _stem(n)
        if s in PART_STEMS:
            continue
        if s in CHARACTER_STEMS:
            return CHARACTER_STEMS[s]
    return None


# The DOL tables this program knows by sight, named after what they hold
# instead of after a symbol: the decomp's symbol names only exist for the US
# build, and every build puts these tables somewhere else.
def _dol_table(va: int) -> str | None:
    from . import layout
    l = layout.current()
    for name, base, count in (("subfiles", l.subfiles_va, chars.SLOTS * chars.TRACKS),
                              ("hands", l.hand_table_va, chars.SLOTS * 6),
                              ("event-sets", l.event_copy_va, l.master_entries - layout.MASTER_SHARED_BASE),
                              ("master", l.master_va, l.master_entries),
                              ("stadiums", l.stadium_va, l.stadiums * 3),
                              ("musyx", l.musyx_va, l.musyx_count),
                              ("screens", l.rel_table_va, l.rel_table_count)):
        if base <= va < base + count * 16:
            return name
    return None


def ref_runs(entries: list[Entry]) -> dict[str, str]:
    """`module:section:address` -> the address its run of descriptors starts at.

    Without the decomp's symbols -- which only exist for the US build -- every
    descriptor would be its own table and the catalog would fill with one-item
    groups. Descriptors sit in tables of back-to-back 16-byte records, so the
    run an address belongs to stands in for the symbol's name."""
    seen: dict[tuple[str, str], set[int]] = {}
    for e in entries:
        for r in e.refs:
            head = r.split(" ")[0]
            parts = head.split(":")
            if len(parts) == 3 and parts[0] not in ("scan", "disc"):
                seen.setdefault((parts[0], parts[1]), set()).add(int(parts[2], 16))
    out: dict[str, str] = {}
    for (mod, sec), addrs in seen.items():
        for a in sorted(addrs):
            start = out.get(f"{mod}:{sec}:{a - 16:#x}") if a - 16 in addrs else None
            out[f"{mod}:{sec}:{a:#x}"] = start or f"{mod}:{sec}:{a:#x}"
    return out


def table_of(e: Entry, runs: dict[str, str] | None = None) -> str:
    if not e.refs:
        return "unreferenced"
    r = e.refs[0]
    if r.startswith("scan:"):
        return r
    head = r.split(" ")[0]
    if head.startswith("dol:"):
        known = _dol_table(int(head.split(":")[2], 16))
        if known:
            return known
    parts = r.split(" ", 1)
    if len(parts) > 1:
        return parts[1].split("+")[0]
    return (runs or {}).get(head, head)


def thumb_for(e: Entry) -> str | None:
    return f"/api/entry/{e.id}/tex/{e.thumb}.png" if e.ntex else None


def build_catalog(entries: list[Entry]) -> dict:
    cats: dict[str, dict] = {}
    names: dict[int, str] = {}
    by_id = {e.id: e for e in entries}
    runs = ref_runs(entries)

    def group(cat_id: str, cat_name: str, grp_id: str, grp_name: str) -> dict:
        c = cats.setdefault(cat_id, {"id": cat_id, "name": cat_name, "groups": {}})
        return c["groups"].setdefault(grp_id, {"id": grp_id, "name": grp_name, "items": [], "thumb": None})

    for e in entries:
        if e.archive == "aaaa.dat":
            continue
        g = None
        if e.archive == "disc":
            from .music import tracks
            g = group("music", "Music", "streams", "Streamed music")
        elif e.kind == "hvqm4":
            g = group("movies", "Movies", "movies", "Movies")
        elif e.kind == "songs":
            g = group("music", "Music", "songs", "Sequenced songs")
        elif e.kind == "text":
            g = group("other", "Everything else", "text", "Text strings")
        elif e.kind == "musyx":
            gid = musyx_group_id(e)
            slots = chars.VOICE_SLOTS.get(gid, []) if gid is not None else []
            if slots and e.naud <= 40:  # a character's own sound group (big shared groups excluded)
                ch = chars.SLOT_NAMES[slots[0]]
                g = group("characters", "Characters", re.sub(r"\W+", "_", ch.lower()), ch)
            else:
                g = group("sounds", "Sounds", "sfx" if "effects" in e.label else "instruments",
                          "Sound effects" if "effects" in e.label else "Instrument banks")
        elif e.kind in ("adgc", "dsp-adpcm") or e.naud:
            g = group("sounds", "Sounds", "banks", "Sound banks")
        elif e.tag.startswith("animsrc:"):
            slot = e.tag.split(":")[1]
            if slot != "-":
                ch = chars.SLOT_NAMES[int(slot)]
                g = group("characters", "Characters", re.sub(r"\W+", "_", ch.lower()), ch)
            else:
                g = group("unused", "Unused data", "animsrc", "Animation sources (no character)")
        elif e.tag == "mirror" or e.tag.startswith("proto") or e.tag == "leftover":
            g = group("unused", "Unused data", *{"mirror": ("mirror", "Earlier copy of the character data"),
                                                 "proto": ("proto", "Prototype animation library"),
                                                 "leftover": ("leftover", "Leftovers")}[e.tag.split(":")[0]])
        else:
            ch = character_of(e)
            tbl = table_of(e, runs)
            cc = chars.classify_entry(e.refs)
            if cc and cc["character"]:
                ch = cc["character"]
            if ch:
                g = group("characters", "Characters", re.sub(r"\W+", "_", ch.lower()), ch)
            elif cc or tbl == "event-sets":
                g = group("characters", "Characters", "_shared", "Hand-pose event sets")
            elif e.known and ("Stadium" in e.known or "Park" in e.known) or tbl in ("stadiums", "marioStadiumCDR"):
                name = e.known or ({"stadiums": "Stadium files", "marioStadiumCDR": "Mario Stadium props"}.get(tbl, tbl))
                g = group("stadiums", "Stadiums", re.sub(r"\W+", "_", name.lower()), name)
            elif e.kind == "anim" and tbl == "subfiles":
                g = group("characters", "Characters", "_animations", "Animations (unsorted)")
            elif e.module == "menus" and e.ntex:
                g = group("menus", "Menus & UI", "menus_" + tbl, f"Menu textures ({tbl})")
            elif tbl == "screens" and e.ntex:
                g = group("menus", "Menus & UI", "screens", "Screens & UI (main.dol)")
            elif tbl == "lbl_1_data_CC8":
                g = group("menus", "Menus & UI", "debug", "Debug menu")
            elif e.label and e.label.endswith(".gpc"):
                g = group("props", "Props & objects", _stem(e.label), e.label.rsplit(".", 1)[0])
            else:
                g = group("other", "Everything else", tbl, tbl)
        g["items"].append(e.id)
        dn = display_name(e, by_id)
        if dn:
            names[e.id] = dn
        if g["thumb"] is None and e.ntex:
            g["thumb"] = thumb_for(e)

    order = ["characters", "stadiums", "menus", "props", "movies", "music", "sounds", "other", "unused"]
    out = []
    for cid in order:
        if cid not in cats:
            continue
        c = cats[cid]
        groups = sorted(c["groups"].values(), key=lambda g: (g["id"].startswith("_"), g["name"].lower()))
        out.append({"id": cid, "name": c["name"], "count": sum(len(g["items"]) for g in groups), "groups": groups})
    return {"categories": out, "names": names}
