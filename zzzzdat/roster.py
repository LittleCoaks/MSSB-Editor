"""The roster: the game's 32 characters with everything that belongs to each.

The DOL tables in `chars.py` describe 54 slots; colour variants (the five
Toads, four Shy Guys, ...) are separate slots that share one body model and
one set of animations and sounds. The game itself numbers 32 characters
(`chars.ID_BASE_SLOT`), and that is the list a person expects to see. This
module folds the slots onto those 32 and gathers, per character:

* the models: the slot's model pack, its low-detail copy (the second
  sub-file, used at a distance) and the body model in the ARAM chunk;
* the colour variants: every slot sharing the model, with the texture set
  that recolours it;
* the equipment: hands and gloves from the master table's sub-items;
* the 17 animation banks, labelled by what they animate (batting, running,
  ...) from the sequence names the source banks kept;
* the voice group: the MusyX sound-effect group game.rel loads for the
  character, with its samples;
* every file the slot owns, for downloading.
"""
from __future__ import annotations

import re
from collections import Counter

from . import chars
from .descriptors import Entry
from .twins import CATEGORIES, SEQ_RE

MODEL_ROLES = {0: "model", 1: "low-detail model"}
PART_ROLES = {0: "left hand", 1: "right hand", 2: "left glove", 3: "right glove"}
ITEM_ROLES = {4: "batting grip", 5: "pitching grip", 6: "catching grip"}


def _by_va(store) -> dict[int, Entry]:
    out: dict[int, Entry] = {}
    for e in store.zzzz_entries():
        for r in e.refs:
            if r.startswith("dol:.data:"):
                out.setdefault(int(r.split(":")[2].split(" ")[0], 16), e)
    return out


def _sub(by_va, slot: int, track: int) -> Entry | None:
    return by_va.get(chars.SUBFILES_VA + (slot * chars.TRACKS + track) * 16)


def _master(by_va, i: int) -> Entry | None:
    return by_va.get(chars.MASTER_VA + i * 16)


def _voice_entry(store, cid: int) -> Entry | None:
    gid = chars.ID_VOICE_GROUP[cid]
    for e in store.zzzz_entries():
        if e.kind == "musyx" and e.label.endswith(f"group {gid}"):
            return e
    return None


def _bank_category(names: list[str]) -> str:
    """'batting', 'running', ... from the sequence names, else ''."""
    c = Counter()
    for n in names:
        m = SEQ_RE.match(n)
        if m and m.group(1) in CATEGORIES:
            c[m.group(1)] += 1
    if not c:
        return ""
    letter, n = c.most_common(1)[0]
    return CATEGORIES[letter]


def character_ids() -> list[dict]:
    """The 32 characters in the game's own order: id, name and slots."""
    out = []
    for cid, base in enumerate(chars.ID_BASE_SLOT):
        slots = [s for s in range(chars.SLOTS) if chars.CHARACTER_ID[s] == cid]
        out.append({"id": cid, "name": chars.base_name(chars.SLOT_NAMES[base]), "slot": base,
                    "slots": [{"slot": s, "name": chars.SLOT_NAMES[s]} for s in slots]})
    return out


def summary(store) -> list[dict]:
    by_va = _by_va(store)
    out = []
    for c in character_ids():
        e = _sub(by_va, c["slot"], 0)
        voice = _voice_entry(store, c["id"])
        out.append({**c, "thumb": e.id if e is not None and e.ntex else None, "model_entry": e.id if e else None,
                    "sound_entry": voice.id if voice else None, "variants": len(c["slots"])})
    return out


def _model_summary(store, e: Entry, role: str) -> dict | None:
    if e is None or store.info(e).kind != "container":
        return None
    ms = store.models(e)
    if not ms:
        return None
    m = ms[0]
    return {"role": role, "entry": e.id, "section": m["section"], "meshes": m["meshes"], "triangles": m["triangles"],
            "textures": e.ntex, "size": e.size, "models": ms}


def detail(store, cid: int) -> dict:
    """Everything about character `cid`; cached on the store (a new Store is
    made whenever the game changes, so the cache never goes stale)."""
    if not 0 <= cid < len(chars.ID_BASE_SLOT):
        raise KeyError(f"no character {cid}")
    cache = store.__dict__.setdefault("_roster_cache", {})
    if cid not in cache:
        cache[cid] = _detail(store, cid)
    return cache[cid]


def _detail(store, cid: int) -> dict:
    by_va = _by_va(store)
    c = character_ids()[cid]
    base = c["slot"]
    files: list[dict] = []

    def add_file(e: Entry | None, role: str, slot: int | None = None) -> None:
        if e is None or any(f["entry"] == e.id and f["role"] == role for f in files):
            return
        files.append({"entry": e.id, "role": role, "kind": e.kind, "size": e.size,
                      "slot": slot, "textures": e.ntex, "audio": e.naud})

    # models: the base slot's packs and the ARAM body
    models = []
    for t, role in MODEL_ROLES.items():
        e = _sub(by_va, base, t)
        m = _model_summary(store, e, role)
        if m:
            models.append(m)
        add_file(e, role, base)
    body = _master(by_va, chars.SLOT_MODEL[base])
    m = _model_summary(store, body, "body model (ARAM copy)")
    if m:
        models.append(m)
    add_file(body, "body model (ARAM copy)", base)

    # colour variants: every slot on this model, with its texture set
    sets = {}
    for e in store.zzzz_entries():
        cx = chars.classify_entry(e.refs)
        if cx and cx.get("role") == "textures (ARAM)":
            sets[cx["slot"]] = e
    variants = []
    for s in [base] + [x["slot"] for x in c["slots"] if x["slot"] != base]:
        t = sets.get(s)
        variants.append({"slot": s, "name": chars.SLOT_NAMES[s], "texture_entry": t.id if t else None,
                         "own": s == base or t is None})
        add_file(t, "texture set", s)
        if s != base:  # the variant's own copies of the packs
            for tr, role in MODEL_ROLES.items():
                add_file(_sub(by_va, s, tr), f"{role} ({chars.SLOT_NAMES[s]})", s)

    # equipment
    parts = []
    attach: set[str] = set()   # what the viewer can hang on the wrists: "hand", "glove"
    for k, role in PART_ROLES.items():
        e = _master(by_va, chars.ITEMS_BASE + base * 7 + k)
        m = _model_summary(store, e, role)
        if m:
            attach.add(role.split(" ")[1])
            hp = store.poses(e, m["section"])
            m["poses"] = hp.count if hp else 0
            m["bat_pose"] = hp.bat_pose() if hp else None
            if m["bat_pose"] is not None:
                attach.add("bat")
            if any("bat" in n.lower() for n in m["meshes"]):  # handless characters hold the bat directly
                role = m["role"] = role.split(" ")[0] + " bat"
                attach.add("bat")
            parts.append(m)
        add_file(e, role, base)
    for k, role in ITEM_ROLES.items():
        add_file(_master(by_va, chars.ITEMS_BASE + base * 7 + k), role, base)
    add_file(_master(by_va, chars.RIGS_BASE + base), "skeleton rig", base)

    # animation banks
    banks = []
    for t in range(2, chars.TRACKS):
        e = _sub(by_va, base, t)
        if e is None:
            continue
        lb = store.bank(f"{e.id}:0")
        names = [s.name for s in lb[1].sequences] if lb else []
        cat = _bank_category(names)
        dev = chars.TRACK_FILES[t]
        banks.append({"key": f"{e.id}:0", "entry": e.id, "track": t - 1, "category": cat, "file": dev,
                      "label": f"{dev} · {cat}" if cat else dev,
                      "sequences": names,
                      # sixteen copies of "other01" are a placeholder, not names
                      "named": not all(n.startswith("sequence ") for n in names) and len(set(names)) > 1})
        add_file(e, f"animations {t - 1} ({dev}" + (f", {cat})" if cat else ")"), base)

    # voice group
    voice = _voice_entry(store, cid)
    sounds = None
    if voice is not None:
        fi = store.info(voice)
        sounds = {"entry": voice.id, "group": fi.group["id"] if fi.group else None,
                  "samples": [{"n": n, "seconds": a["seconds"], "rate": a["rate"], "label": a.get("label", "")}
                              for n, a in enumerate(fi.audio)],
                  "sfx": fi.sfx}
        add_file(voice, "voice group", None)

    e0 = _sub(by_va, base, 0)
    return {**c, "thumb": e0.id if e0 is not None and e0.ntex else None, "models": models, "variants": variants,
            "parts": parts, "banks": banks, "sounds": sounds, "files": files,
            "viewer_parts": sorted(attach)}


def export(store, cid: int, dest, what: set[str]) -> list:
    """Write a character's models (glb + obj), textures, sounds and animation
    banks under `dest/<name>/`; returns the paths written."""
    from pathlib import Path
    d = detail(store, cid)
    folder = Path(dest) / re.sub(r"[^A-Za-z0-9_.-]+", "_", d["name"])
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    if "models" in what:
        for m in d["models"] + d["parts"]:
            e = store.get(m["entry"])
            stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", m["role"])
            p = folder / f"{stem}.glb"
            rig = store.actor(e) is not None and m["role"] in MODEL_ROLES.values()
            keys = tuple(b["key"] for b in d["banks"]) if rig and m["role"] == "model" else ()
            p.write_bytes(store.glb(e, m["section"], rig=rig, bank_keys=keys))
            out.append(p)
            out += store.extract_models(e, folder / f"{stem}_obj", "obj")
        for v in d["variants"]:
            if v["texture_entry"] is not None and d["models"]:
                m = d["models"][0]
                p = folder / f"model_{re.sub(r'[^A-Za-z0-9_.-]+', '_', v['name'])}.glb"
                p.write_bytes(store.glb(store.get(m["entry"]), m["section"], variant=v["slot"]))
                out.append(p)
    if "textures" in what:
        for m in d["models"][:1]:
            out += store.extract_textures(store.get(m["entry"]), folder / "textures")
        for v in d["variants"]:
            if v["texture_entry"] is not None:
                out += store.extract_textures(store.get(v["texture_entry"]),
                                              folder / f"textures_{re.sub(r'[^A-Za-z0-9_.-]+', '_', v['name'])}")
    if "sounds" in what and d["sounds"]:
        out += store.extract_audio(store.get(d["sounds"]["entry"]), folder / "sounds")
    if "files" in what:
        for f in d["files"]:
            e = store.get(f["entry"])
            p = folder / "files" / store.file_name(e)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(store.data(e))
            out.append(p)
    return out
