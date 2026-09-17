"""A canonical path-like name for every entry: `<domain>/<subject>/<role>`.

The game has no file names for its assets, only descriptor tables, so a file
is named after the table slot that points at it: `CharacterFiles[11][0]` is
`char/waluigi/model`. The roles of the character tables come from `chars`
(the animation tracks keep the development file names debug.rel lists for
them: motb, motr, motf...). Everything else is named after the asset name
embedded in it, under a domain taken from its category. Unreferenced files
take the name of the referenced file they copy or feed.

Paths are lowercase, unique within an index, and do not depend on the build:
they are made of table positions and embedded names, never of offsets, except
for the files nothing identifies.
"""
from __future__ import annotations

import re

from . import catalog, chars
from .descriptors import Entry

ITEM_ROLES = ["hand_l", "hand_r", "glove_l", "glove_r", "handpose_batting", "handpose_pitching", "handpose_catching"]
HAND_ROLES = ["hand_l_batting", "hand_r_batting", "glove_l", "glove_r", "hand_l_pitching", "hand_r_pitching"]
DOMAINS = {"stadium": "stadium", "stadium props": "stadium/props", "prop model": "prop", "hand model": "hand",
           "glove model": "glove", "character model": "char", "texture set": "char", "textures": "tex",
           "sound effects": "audio", "instrument bank": "audio", "sound bank": "audio", "sequenced music": "audio",
           "text": "text", "movie": "movie", "code module": "code", "game data": "data", "camera data": "data",
           "animation": "anim", "hand-pose track": "handpose", "data": "data"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _character_path(c: dict) -> str:
    who = f"char/{slug(c['character'])}" if c["character"] else "char/shared"
    i = c["index"]
    if c["table"] == "subfiles":
        t = c["track"]
        return f"{who}/" + ("model" if t == 0 else "model_lod" if t == 1 else f"anim_{chars.TRACK_FILES[t]}")
    if c["table"] == "hands":
        return f"{who}/{HAND_ROLES[i % 6]}"
    if i < chars.MODELS:
        return f"{who}/aram_model"
    if i < chars.ITEMS_BASE:
        return f"{who}/aram_textures"
    if i < chars.RIGS_BASE:
        return f"{who}/{ITEM_ROLES[(i - chars.ITEMS_BASE) % 7]}"
    if i < chars.SHARED_BASE:
        return f"{who}/aram_rig"
    return f"char/shared/handpose_event_set_{i - chars.SHARED_BASE:02d}"


def _own_path(e: Entry) -> str:
    c = chars.classify_entry(e.refs)
    if c:
        return _character_path(c)
    if catalog.table_of(e) == "event-sets":
        from . import layout
        n = (int(e.refs[0].split(":")[2].split(" ")[0], 16) - layout.current().event_copy_va) // 16
        return f"char/shared/handpose_event_set_{n:02d}_copy"
    domain = DOMAINS.get(e.category, "data")
    gid = catalog.musyx_group_id(e) if e.kind == "musyx" else None
    if gid is not None:
        return f"audio/group_{gid:02d}"
    lab = e.label or next((n for n in e.names if n.endswith((".gpc", ".tpl"))), "")
    # a community name says more than the embedded one (thirteen files embed "stadium0")
    if e.known:
        return f"{domain}/{slug(e.known.replace('First Found ', '').rsplit('.', 1)[0])[:48].strip('_')}"
    if lab:
        return f"{domain}/{slug(lab.rsplit('.', 1)[0])}"
    return ""


def asset_paths(entries: list[Entry]) -> dict[int, str]:
    """{entry id: path} for a whole index."""
    by_id = {e.id: e for e in entries}
    out: dict[int, str] = {}
    for e in entries:
        tag = e.tag.split(":")
        p = ""
        if e.archive == "disc":   # a real file on the disc keeps its real path
            p = "disc/" + e.name.rsplit(".", 1)[0].lower()
        elif e.refs and e.refs[0].startswith("scan:"):
            twin = by_id.get(e.twin)
            base = _own_path(twin) if twin else ""
            if tag[0] == "animsrc":
                who = f"char/{slug(chars.SLOT_NAMES[int(tag[1])])}" if tag[1] != "-" else "char/shared"
                p = f"unreferenced/{who}/animsrc_{catalog.SOURCE_CATEGORIES.get(tag[2], 'misc')}"
            elif tag[0] == "proto":
                p = "unreferenced/proto/" + (f"anim_{catalog.SOURCE_CATEGORIES[tag[1]]}" if len(tag) > 1
                                             else slug(e.label.rsplit(".", 1)[0]) if e.label else e.kind)
            elif base:
                p = f"unreferenced/{base}"
            else:
                own = _own_path(e)
                p = f"unreferenced/{own}" if own else ""
        elif not e.refs:   # a cloned slot's own files: still in the archive, no longer loaded
            own = _own_path(e)
            p = f"displaced/{own}" if own else f"displaced/{e.kind}_{e.offset:08x}"
        else:
            p = _own_path(e)
        out[e.id] = p or f"unidentified/{e.kind}_{e.offset:08x}"
    # the same embedded name in several files (stadium variants, shared hands): number them in archive order
    seen: dict[str, int] = {}
    for e in sorted(entries, key=lambda e: (e.archive != "ZZZZ.dat", e.offset)):
        p = out[e.id]
        seen[p] = seen.get(p, 0) + 1
        if seen[p] > 1:
            out[e.id] = f"{p}_{seen[p]}"
    return out
