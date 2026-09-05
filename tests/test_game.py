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
    assert store.modified_ids() == []


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
