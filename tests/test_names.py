from zzzzdat import chars, names
from zzzzdat.descriptors import Entry


def mk(i, refs, **kw):
    return Entry(i, i * 0x800, 0x800, 0x800, 0, 0, 0, name=f"{i * 0x800:08x}", refs=refs, **kw)


def test_character_table_slots_name_their_files():
    va = chars.SUBFILES_VA + (11 * chars.TRACKS) * 16
    model = mk(1, [f"dol:.data:{va:#x}"], kind="container", label="waluigi00.gpc")
    batting = mk(2, [f"dol:.data:{va + 2 * 16:#x}"], kind="anim")
    pose = mk(3, [f"dol:.data:{chars.MASTER_VA + (chars.ITEMS_BASE + 4) * 16:#x}"], kind="unknown")
    p = names.asset_paths([model, batting, pose])
    assert p == {1: "char/waluigi/model", 2: "char/waluigi/anim_motb", 3: "char/mario/handpose_batting"}


def test_copies_follow_their_twin_and_repeats_are_numbered():
    a = mk(1, ["menus:.data:0x10 SomeTable"], kind="container", label="ball.gpc", category="prop model")
    b = mk(2, ["menus:.data:0x20 SomeTable+0x10"], kind="container", label="ball.gpc", category="prop model")
    c = mk(3, ["scan:lzss-probe"], kind="container", twin=1, tag="mirror")
    d = mk(4, ["scan:lzss-probe"], kind="unknown", tag="leftover")
    p = names.asset_paths([a, b, c, d])
    assert p == {1: "prop/ball", 2: "prop/ball_2", 3: "unreferenced/prop/ball", 4: "unidentified/unknown_00002000"}
