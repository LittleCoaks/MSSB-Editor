"""Round-trips against a real copy of the game. Skipped when none is configured."""
import hashlib

import pytest

from zzzzdat.lzss import compress, decompress

pytestmark = pytest.mark.game


def test_index_loads(store):
    assert len(store.zzzz_entries()) > 2000
    assert store.archive.size >= 450041856  # grows when the editor appends


@pytest.mark.parametrize("eid", [8, 893, 92])
def test_recompress_roundtrip(store, eid):
    e = store.get(eid)
    data = store.data(e)
    comp = compress(data, e.lookback_bits, e.repeat_bits)
    assert bytes(decompress(comp, e.lookback_bits, e.repeat_bits, len(data))) == data
    assert len(comp) <= e.disc_size * 1.02


def test_textures_and_models(store):
    e = store.get(893)  # First Found Mario
    fi = store.info(e)
    assert len(fi.all_textures()) == 9
    png = store.texture_png(e, 0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    m = store.model(e, 2)
    assert {mm.name for mm in m.meshes} == {"mario_body", "mario_head"}
    ys = [p[1] for mm in m.meshes for p in mm.positions]
    assert min(ys) >= -0.1 and max(ys) > 1.5   # upright, feet near the origin


def test_audio(store):
    e = store.get(89)
    assert store.info(e).audio[0]["seconds"] > 280
    wav = store.wav(e, 0, 1.0)
    assert wav[:4] == b"RIFF" and len(wav) == 44 + 32000 * 2


def test_replace_restore_is_exact(store):
    from zzzzdat.edit import Editor, EditError
    try:
        ed = Editor(store.game)
    except EditError:
        pytest.skip("game folder not prepared for editing")
    sha = lambda p: hashlib.sha1(p.read_bytes()).hexdigest()
    dol0, aaaa0 = sha(ed.dol), sha(ed.aaaa)
    modified0 = store.modified_ids()
    for eid in (92, 893):  # DOL-referenced and menus.rel-referenced
        e = store.get(eid)
        orig = store.data(e)
        big = orig + bytes(range(256)) * 100
        r = ed.replace(e, big)
        store.forget(e)
        assert store.data(e) == big and r["descriptors"] >= 1
        ed.restore(e)
        store.forget(e)
        assert store.data(e) == orig
    assert sha(ed.dol) == dol0 and sha(ed.aaaa) == aaaa0
    assert store.modified_ids() == modified0


def test_replace_texture_is_exact(store):
    from zzzzdat import gx
    from zzzzdat.edit import Editor, EditError
    from zzzzdat.texedit import replace_texture
    try:
        ed = Editor(store.game)
    except EditError:
        pytest.skip("game folder not prepared for editing")
    e = store.get(8)  # DOL-referenced menu pack; texture 12 is 256x256 CMPR with 3 mip levels
    orig = store.data(e)
    fi = store.info(e)
    sec, t = fi.all_textures()[12]
    assert (t.width, t.height, t.fmt_name, t.mips) == (256, 256, "CMPR", 3)
    img = bytearray(t.decode_rgba(orig))
    for y in range(t.height):
        i = (y * t.width + y) * 4
        img[i:i + 4] = bytes((255, 0, 0, 255))
    new, info = replace_texture(orig, fi, 12, gx.to_png(t.width, t.height, img))
    assert info.levels == 4 and not info.truncated and len(new) == len(orig)
    ed.replace(e, new)
    store.forget(e)
    back = store.data(e)
    t2 = store.info(e).all_textures()[12][1]
    dec = t2.decode_rgba(back)
    assert sum(abs(a - b) for a, b in zip(img, dec)) / len(img) < 2
    others = [k for k in range(len(fi.all_textures())) if k != 12]
    assert all(fi.all_textures()[k][1].decode_rgba(back) == fi.all_textures()[k][1].decode_rgba(orig) for k in others)
    ed.restore(e)
    store.forget(e)
    assert store.data(e) == orig


def test_rigged_glb_with_animations(store):
    import json
    import struct
    e = store.get(893)  # menu Mario: actor, skin and a 3-sequence bank in one container
    banks = store.banks(e)
    assert banks and banks[0]["key"] == "893:4" and banks[0]["sequences"] == 3
    sk = store.skin(e)
    assert sk and sk.vertex_count == 679 and sk.weights[200][0][0] == 4
    glb = store.glb(e, 2, rig=True, bank_keys=("893:4",))
    n = struct.unpack_from("<I", glb, 12)[0]
    doc = json.loads(glb[20:20 + n])
    assert len(doc["skins"]) == 1 and len(doc["skins"][0]["joints"]) == 37
    assert [a["name"] for a in doc["animations"]] == ["section 4 / sequence 1", "section 4 / sequence 2", "section 4 / sequence 3"]
    assert sum(len(a["channels"]) for a in doc["animations"]) == 75


def test_clone_character_and_restore(store):
    import hashlib
    from zzzzdat.clone import Cloner
    from zzzzdat.edit import Editor, EditError
    from zzzzdat.store import CLONE_ID_BASE, Store
    try:
        ed = Editor(store.game)
    except EditError:
        pytest.skip("game folder not prepared for editing")
    sha = hashlib.sha1(ed.dol.read_bytes()).hexdigest()
    sha_aaaa = hashlib.sha1(ed.aaaa.read_bytes()).hexdigest()
    target = next(s for s in (1, 5, 6, 4) if str(s) not in Cloner(ed).clones())  # a slot with its own body model
    r = Cloner(ed).clone(2, target, copy=True)  # Donkey Kong onto it
    assert r["copied"] == 22 and r["shared"] == 7 and len(r["inplace"]) == 2  # 19 sub-files + 3 menu packs
    st2 = Store()
    e = st2.get(CLONE_ID_BASE + target * 64)  # track 0 now holds a copy of donkey00.gpc
    assert e.label == "donkey00.gpc" and len(st2.data(e)) == 119736
    with pytest.raises(EditError):
        Cloner(Editor(st2.game)).clone(0, target)
    Cloner(Editor(st2.game)).restore(target)
    assert hashlib.sha1(ed.dol.read_bytes()).hexdigest() == sha
    assert hashlib.sha1(ed.aaaa.read_bytes()).hexdigest() == sha_aaaa
    assert str(target) not in Editor(store.game).journal.get("_clones", {})
    assert len(Store().entries) == len(store.entries)


def test_musyx_group(store):
    e = store.get(30)
    fi = store.info(e)
    assert fi.kind == "musyx" and fi.group["id"] == 30 and len(fi.audio) == 12 and len(fi.sfx) == 13
    assert all(f["streams"] for f in fi.sfx)
    w = store.wav(e, 0)
    assert w[:4] == b"RIFF" and len(w) == 44 + 34098 * 2
    assert store.wav_size(e, 0) == len(w)
    assert e.label == "Sound effects group 30"


def test_attached_parts(store):
    import json
    import struct
    e = store.get(91)  # Mario: hands and gloves come from the master table items
    assert sorted({p["name"] for p in store.parts(e)}) == ["L_glove", "L_hand", "R_glove", "R_hand"]
    glb = store.glb(e, 2, rig=True, parts="hands")
    n = struct.unpack_from("<I", glb, 12)[0]
    doc = json.loads(glb[20:20 + n])
    names = {i: nd["name"] for i, nd in enumerate(doc["nodes"])}
    node_of = {v: k for k, v in names.items()}
    assert node_of["L_hand"] in doc["nodes"][node_of["bone25"]]["children"]
    assert node_of["R_hand"] in doc["nodes"][node_of["bone19"]]["children"]
    e2 = store.get(893)  # menu Mario carries its hands in the same container
    assert sorted({p["name"] for p in store.parts(e2)}) == ["L_hand", "R_hand"]


def test_sequenced_songs(store):
    e = store.get(28)
    fi = store.info(e)
    assert fi.kind == "songs" and len(fi.songs) == 19 and fi.songs[0]["bpm"] == 190 and fi.songs[0]["tracks"] == 5
    mid = store.midi(e, 0)
    assert mid[:4] == b"MThd" and mid.count(b"MTrk") == 6
    assert store.info(store.get(82)).kind == "text"


def test_render_song(store):
    pytest.importorskip("numpy")
    e = store.get(28)
    bank = store.instrument_bank()
    assert bank is not None and bank.pages and bank.drum_pages
    assert bank.voices(0, 60, False) and bank.voices(0, 36, True)
    w = store.song_wav(e, 2)  # the 2 s jingle
    assert w[:4] == b"RIFF" and 2.0 * 32000 * 4 < len(w) < 4.0 * 32000 * 4


def test_movie_decode(store):
    from zzzzdat import hvqm
    from zzzzdat.thumbs import game_key
    if hvqm.helper_path() is None:
        pytest.skip("hvqm4dec helper not built")
    e = store.get(2)  # the 300-frame movie
    m = hvqm.decode(game_key(store.game), e.id, store.data(e))
    assert m.ready and m.info["frames"] == 300 and m.info["width"] == 640
    assert m.frame(0)[:2] == bytes((0xFF, 0xD8)) and m.frame(299)[-2:] == bytes((0xFF, 0xD9))
    assert m.audio().stat().st_size > 300 * 32028 * 2 // 30


def test_static_model_is_upright_when_actor_follows_geometry(store):
    # the prototype packs store the skeleton after the geometry; the static
    # export used to skip the upright flip for them and draw them upside down
    e = store.get(841)  # prototype mario00.gpc
    secs = store.info(e).sections
    geo = next(s.index for s in secs if s.kind == "geopalette")
    from zzzzdat import c3
    assert not any(s.magic == c3.ACT_VERSION for s in secs[:geo])
    m = store.model(e, geo, posed=True)
    ys = [p[1] for mm in m.meshes for p in mm.positions]
    assert min(ys) > -0.1 and max(ys) > 1.0  # feet on the ground, head above


def test_roster(store):
    from zzzzdat import roster
    s = roster.summary(store)
    assert [c["name"] for c in s[:3]] == ["Mario", "Luigi", "Donkey Kong"] and len(s) == 32
    d = roster.detail(store, 0)
    assert [m["role"] for m in d["models"]] == ["model", "low-detail model", "body model (ARAM copy)"]
    assert [p["role"] for p in d["parts"]] == ["left hand", "right hand", "left glove", "right glove"]
    assert len(d["banks"]) == 17 and d["banks"][0]["category"] == "batting" and d["banks"][0]["sequences"][0] == "b00_wa_000"
    assert d["sounds"]["group"] == 27 and len(d["sounds"]["samples"]) == 10
    toad = roster.detail(store, 13)
    assert [v["name"] for v in toad["variants"]] == ["Toad (red)", "Toad (blue)", "Toad (yellow)", "Toad (green)", "Toad (purple)"]
    assert toad["variants"][1]["texture_entry"] is not None
    goomba = roster.detail(store, 29)
    assert goomba["parts"][0]["role"] == "left bat" and goomba["viewer_parts"] == ["bat", "glove", "hand"]
    assert d["parts"][0]["bat_pose"] == 2 and "bat" in d["viewer_parts"]
    assert roster.detail(store, 0) is d  # cached


def test_hand_poses_hold_the_bat(store):
    e = store.get(2222)  # Mario's left hand (master sub-item 0)
    hp = store.poses(e)
    assert hp and hp.count == 12 and hp.vertices == 284
    assert hp.extents[0] < 0.5 and hp.bat_pose() == 2 and hp.extents[2] > 1.7
    m = store.model(e, 1, pose=2)
    ys = [p[1] for p in m.meshes[0].positions]
    assert max(ys) - min(ys) > 1.5  # the bat, pulled out of the palm
    glb = store.glb(store.get(91), 2, rig=True, parts="bat")
    assert len(glb) > 150000


def test_stadiums(store):
    from zzzzdat import stadiums
    s = stadiums.summary(store)
    assert [x["name"] for x in s][:3] == ["Mario Stadium", "Bowser Castle", "Wario Palace"] and len(s) == 7
    d = stadiums.detail(store, 0)
    assert len(d["files"]) == 3 and len(d["props"]) == 7
    wario = stadiums.detail(store, 2)
    assert wario["files"][0]["triangles"] > 12000   # the version-0 GeoPalette field pack parses
    glb = store.scene_glb(store.get(wario["files"][0]["entry"]))
    assert len(glb) > 1000000
