"""The stadiums: the seven parks with their file variants and props.

The DOL table `StadiumFiles` (0x800EFBE8 in the US build; `layout.py` finds
it in the others) has 21 descriptors, three per stadium in the game's stadium
order. Some stadiums use three distinct files
(Mario Stadium), some two, some one file for all three slots. Every stadium
file is a section container: one or two big GeoPalettes (the park and its
sky dome), tiny placeholder meshes, per-section actors, a texture table and
0x..4300 tables of float records (placement/collision data, not decoded).
Mario Stadium also has a props table (`marioStadiumCDR` in game.rel).
"""
from __future__ import annotations

from . import catalog, placement
from .descriptors import Entry

STADIUM_VA = 0x800EFBE8
SLOTS_PER_STADIUM = 3
# in table order; identified from the rendered parks (lava arena, palace, jungle river, toy sign)
NAMES = ["Mario Stadium", "Bowser Castle", "Wario Palace", "Yoshi Park", "Peach's Garden", "DK Jungle", "Toy Field"]
# each park's prop pack, in the same order: the seven descriptors of game.rel's
# `marioStadiumCDR` table (named by the decomp on the US disc; the packs' own
# embedded names find them on the other builds). Waves for the stadium by the
# sea, Bowser's parts, Chain Chomps and the sandstorm, Piranha Plants, the
# garden's parts, barrels with the Klaptrap and the river, the toy parts.
PROP_LABELS = ["sea00.gpc", "Parts01.gpc", "wanwan_00.gpc", "packun.gpc", "parts00_00.gpc", "taru00.gpc", "parts0600_00.gpc"]


def prop_packs(store) -> list[Entry | None]:
    """The prop pack of each stadium, in NAMES order (None where not found)."""
    tbl = [e for e in store.zzzz_entries() if catalog.table_of(e) == "marioStadiumCDR" and e.kind == "container"]
    if len(tbl) == len(NAMES):
        return tbl
    by_label = {}
    for e in store.zzzz_entries():
        if e.kind == "container" and e.label in PROP_LABELS and e.label not in by_label and not e.tag:
            by_label[e.label] = e
    return [by_label.get(lb) for lb in PROP_LABELS]


def _by_va(store) -> dict[int, Entry]:
    out: dict[int, Entry] = {}
    for e in store.zzzz_entries():
        for r in e.refs:
            if r.startswith("dol:.data:"):
                out.setdefault(int(r.split(":")[2].split(" ")[0], 16), e)
    return out


def _slot_entries(store) -> list[Entry | None]:
    by_va = _by_va(store)
    return [by_va.get(STADIUM_VA + i * 16) for i in range(len(NAMES) * SLOTS_PER_STADIUM)]


def summary(store) -> list[dict]:
    slots = _slot_entries(store)
    out = []
    for i, name in enumerate(NAMES):
        files = []
        for e in slots[i * SLOTS_PER_STADIUM:(i + 1) * SLOTS_PER_STADIUM]:
            if e is not None and e.id not in [f["entry"] for f in files]:
                files.append({"entry": e.id, "textures": e.ntex, "size": e.size})
        thumb = files[0]["entry"] if files else None
        out.append({"id": i, "name": name, "files": files, "thumb": thumb})
    return out


def _sky(store, e: Entry) -> dict | None:
    """Mean colour of the sky dome's textures and whether it reads as night."""
    import io
    try:
        from PIL import Image
    except ImportError:
        return None
    data = store.data(e)
    sky = next((s for s in store.info(e).sections if s.kind == "geopalette" and s.index == 4), None)
    if sky is None:
        return None
    from . import c3
    m = c3.parse_geopalette(data, sky.offset)
    used = sorted({d.texture for mm in m.meshes for d in mm.draws if d.texture is not None}) if m else []
    if not used:
        return None
    rgb = [0, 0, 0]
    for n in used:
        im = Image.open(io.BytesIO(store.texture_png(e, n))).convert("RGB").resize((4, 4))
        px = list(im.getdata())
        for i in range(3):
            rgb[i] += sum(p[i] for p in px) / 16 / len(used)
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return {"rgb": [int(x) for x in rgb], "night": lum < 60}


def _model_rows(store, e: Entry) -> list[dict]:
    rows = []
    for m in store.models(e):
        rows.append({"section": m["section"], "meshes": m["meshes"], "triangles": m["triangles"],
                     "textures": len(m["textures"])})
    return rows


def _game_rel_data(store) -> bytes:
    """game.rel's .data section (decompressed once per store)."""
    cache = store.__dict__.setdefault("_game_rel_data", {})
    if "d" not in cache:
        from . import descriptors
        cache["d"] = b""
        for b in descriptors.load_binaries(store.game, store.resolve_layout()):
            if b.module == "game":
                o, n = next(((o, n) for o, n, name, _ in b.sections if name == ".data"), (0, 0))
                cache["d"] = b.data[o:o + n]
    return cache["d"]


def _prop_rows(store, sid: int, pack: Entry) -> list[dict]:
    """The pack's models with what the scene needs to draw each: whether the
    pack's own actor places it (`fixed`), where game.rel stands its copies
    (`instances`), which sky it belongs to (`when`) and the banks that move it."""
    rows = _model_rows(store, pack)
    try:
        inst = placement.instances(_game_rel_data(store), sid)
    except Exception:
        inst = {}
    twins = placement.NIGHT_TWINS.get(sid) or {}
    banks = store.banks(pack)
    for r in rows:
        sec = r["section"]
        m = store.model(pack, sec, posed=True)
        ps = [p for mm in m.meshes for p in mm.positions]
        cx = (max(p[0] for p in ps) + min(p[0] for p in ps)) / 2 if ps else 0.0
        cz = (max(p[2] for p in ps) + min(p[2] for p in ps)) / 2 if ps else 0.0
        # an object the pack places itself stands away from the origin; the
        # instanced ones are modelled around it
        r["fixed"] = (cx * cx + cz * cz) ** 0.5 > 5.0
        r["instances"] = inst.get(sec, [])
        r["when"] = "day" if sec in twins else "night" if sec in twins.values() else None
        r["banks"] = [{"key": b["key"], "name": b["label"]} for b in banks if b.get("model") == sec and b["sequences"]]
        # what to call it in a list: its first mesh, its animation's name when that says more (みき01 -> yashinoki)
        r["title"] = r["meshes"][0] + (f" · {r['banks'][0]['name']}" if r["banks"] and r["banks"][0]["name"] not in r["meshes"][0] else "")
        if r["when"]:
            r["title"] += f" ({r['when']})"
    return rows


def detail(store, sid: int) -> dict:
    if not 0 <= sid < len(NAMES):
        raise KeyError(f"no stadium {sid}")
    cache = store.__dict__.setdefault("_stadium_cache", {})
    if sid in cache:
        return cache[sid]
    slots = _slot_entries(store)
    files = []
    for k, e in enumerate(slots[sid * SLOTS_PER_STADIUM:(sid + 1) * SLOTS_PER_STADIUM]):
        if e is None:
            continue
        f = next((f for f in files if f["entry"] == e.id), None)
        if f:
            f["slots"].append(k)
            continue
        files.append({"entry": e.id, "slots": [k], "textures": e.ntex, "size": e.size, "sky": _sky(store, e),
                      "models": _model_rows(store, e), "triangles": sum(m["triangles"] for m in store.models(e)),
                      "sections": len(store.info(e).sections)})
    props = []
    pack = prop_packs(store)[sid]
    if pack is not None:
        ms = store.models(pack)
        if ms:
            props.append({"entry": pack.id, "name": (pack.label or "").rsplit(".", 1)[0], "triangles": sum(m["triangles"] for m in ms),
                          "textures": pack.ntex, "models": _prop_rows(store, sid, pack),
                          "banks": store.banks(pack)})
    d = {"id": sid, "name": NAMES[sid], "files": files, "props": props,
         "thumb": files[0]["entry"] if files else None}
    cache[sid] = d
    return d
