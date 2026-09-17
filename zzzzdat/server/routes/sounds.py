"""Every MusyX sound group in one list, for the Audio page's sound-effect browser."""
from __future__ import annotations

from ... import chars, roster, stadiums
from .. import Request, router


# the seven parks' sound groups, in stadium order (identified by ear by the user, 2026-09-17)
STADIUM_GROUPS = [42, 43, 44, 52, 2, 1, 6]


@router.get(r"/api/sounds")
def get_sounds(req: Request):
    st = req.ctx.require_store()
    names = {c["id"]: c["name"] for c in roster.character_ids()}
    voice = {gid: names[cid] for cid, gid in enumerate(chars.ID_VOICE_GROUP) if cid in names}
    out = []
    for e in st.zzzz_entries():
        if e.kind != "musyx":
            continue
        fi = st.info(e)
        g = fi.group or {}
        who = voice.get(g.get("id")) if g.get("type") == 1 else None
        park = stadiums.NAMES[STADIUM_GROUPS.index(g["id"])] if g.get("type") == 1 and g.get("id") in STADIUM_GROUPS else None
        out.append({"stadium": park, "entry": e.id, "group": g.get("id"), "kind": g.get("kind", "sound group"),
                    "character": who, "name": f"{who}'s voice" if who else park if park else ("Instrument bank" if g.get("type") == 0 else f"Group {g.get('id')}"),
                    "samples": len(fi.audio), "sfx": len(fi.sfx or []),
                    "seconds": round(sum(a["seconds"] for a in fi.audio), 1)})
    # two files can hold the same group id (the US disc has two makes of group 28): tell them apart
    names_seen = [g["name"] for g in out]
    for g in out:
        if names_seen.count(g["name"]) > 1:
            g["name"] += f" (file {g['entry']})"
    req.json({"groups": out})
