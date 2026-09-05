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
