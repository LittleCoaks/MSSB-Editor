"""The stadiums: the seven parks with their file variants and props.

The DOL table `StadiumFiles` at 0x800EFBE8 has 21 descriptors, three per
stadium in the game's stadium order. Some stadiums use three distinct files
(Mario Stadium), some two, some one file for all three slots. Every stadium
file is a section container: one or two big GeoPalettes (the park and its
sky dome), tiny placeholder meshes, per-section actors, a texture table and
0x..4300 tables of float records (placement/collision data, not decoded).
Mario Stadium also has a props table (`marioStadiumCDR` in game.rel).
"""
from __future__ import annotations

from . import catalog
from .descriptors import Entry

STADIUM_VA = 0x800EFBE8
SLOTS_PER_STADIUM = 3
# in table order; identified from the rendered parks (lava arena, palace, jungle river, toy sign)
NAMES = ["Mario Stadium", "Bowser Castle", "Wario Palace", "Yoshi Park", "Peach's Garden", "DK Jungle", "Toy Field"]


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
    if sid == 0:
        for e in store.zzzz_entries():
            if catalog.table_of(e) == "marioStadiumCDR" and e.kind == "container":
                ms = store.models(e)
                if ms:
                    props.append({"entry": e.id, "name": (e.label or "").rsplit(".", 1)[0], "triangles": sum(m["triangles"] for m in ms),
                                  "textures": e.ntex, "models": _model_rows(store, e)})
    d = {"id": sid, "name": NAMES[sid], "files": files, "props": props,
         "thumb": files[0]["entry"] if files else None}
    cache[sid] = d
    return d
