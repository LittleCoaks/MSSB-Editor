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


def display_name(e: Entry) -> str:
    """A name a person would use: the character table's slot and role, else the
    community name, else the character/part behind the embedded model name."""
    c = chars.classify_entry(e.refs)
    if c and c["character"]:
        return f"{c['character']} - {c['role']}"
    if c:
        return c["role"]
    if e.known:
        return e.known.replace("First Found ", "")
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
    "StadiumFiles": "Stadiums (main files)", "marioStadiumCDR": "Mario Stadium props",
}


def _stem(label: str) -> str:
    s = label.rsplit(".", 1)[0].lower()
    s = re.sub(r"_?\d+$", "", s)  # mario00 -> mario, parts0600_00 -> parts0600
    return s


def character_of(e: Entry) -> str | None:
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


def table_of(e: Entry) -> str:
    if not e.refs:
        return "unreferenced"
    r = e.refs[0]
    if r.startswith("scan:"):
        return r
    parts = r.split(" ", 1)
    return parts[1].split("+")[0] if len(parts) > 1 else parts[0]


def thumb_for(e: Entry) -> str | None:
    return f"/api/entry/{e.id}/tex/{e.thumb}.png" if e.ntex else None


def build_catalog(entries: list[Entry]) -> dict:
    cats: dict[str, dict] = {}
    names: dict[int, str] = {}

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
        elif e.kind in ("adgc", "dsp-adpcm") or e.naud:
            g = group("sounds", "Sounds", "banks", "Sound banks")
        else:
            ch = character_of(e)
            tbl = table_of(e)
            cc = chars.classify_entry(e.refs)
            if cc and cc["character"]:
                ch = chars.base_name(cc["character"])
            if ch:
                g = group("characters", "Characters", re.sub(r"\W+", "_", ch.lower()), ch)
            elif e.known and ("Stadium" in e.known or "Park" in e.known) or tbl in ("StadiumFiles", "marioStadiumCDR"):
                name = e.known or ({"StadiumFiles": "Stadium files", "marioStadiumCDR": "Mario Stadium props"}.get(tbl, tbl))
                g = group("stadiums", "Stadiums", re.sub(r"\W+", "_", name.lower()), name)
            elif e.kind == "anim" and tbl == "lbl_800F1D78":
                g = group("characters", "Characters", "_animations", "Animations (unsorted)")
            elif e.module == "menus" and e.ntex:
                g = group("menus", "Menus & UI", "menus_" + tbl, f"Menu textures ({tbl})")
            elif e.label and e.label.endswith(".gpc"):
                g = group("props", "Props & objects", _stem(e.label), e.label.rsplit(".", 1)[0])
            else:
                g = group("other", "Everything else", tbl, tbl)
        g["items"].append(e.id)
        dn = display_name(e)
        if dn:
            names[e.id] = dn
        if g["thumb"] is None and e.ntex:
            g["thumb"] = thumb_for(e)

    order = ["characters", "stadiums", "menus", "props", "movies", "music", "sounds", "other"]
    out = []
    for cid in order:
        if cid not in cats:
            continue
        c = cats[cid]
        groups = sorted(c["groups"].values(), key=lambda g: (g["id"].startswith("_"), g["name"].lower()))
        out.append({"id": cid, "name": c["name"], "count": sum(len(g["items"]) for g in groups), "groups": groups})
    return {"categories": out, "names": names}
