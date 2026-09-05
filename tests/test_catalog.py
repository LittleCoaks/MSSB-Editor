from zzzzdat import catalog, chars
from zzzzdat.descriptors import Entry


def mk(id_, refs, label="", known="", kind="container", ntex=0, archive="ZZZZ.dat", names=None):
    return Entry(id_, 0x1000 * id_, 0x800, 0x800, 4, 11, 4, name=f"{id_:08x}", refs=refs, archive=archive,
                 kind=kind, ntex=ntex, label=label, known=known, names=names or [])


def test_character_table_classification():
    c = chars.classify(chars.SUBFILES_VA + (27 * 19 + 0) * 16)
    assert c["character"] == "Toad (red)" and c["role"] == "model"
    c = chars.classify(chars.MASTER_VA + (54 + 9 * 7 + 5) * 16)
    assert c["character"] == "Bowser" and c["role"] == "pitching grip"
    c = chars.classify(chars.MASTER_VA + (432 + 53) * 16)
    assert c["character"] == "Boo" and c["role"] == "skeleton rig"
    assert chars.classify(chars.MASTER_VA - 16) is None


def test_canonical_names():
    assert catalog.canonical("Toad(B)") == "Toad"
    assert catalog.canonical("Koopa(R)") == "Koopa Troopa"
    assert catalog.canonical("Bro(H)") == "Hammer Bro"
    assert catalog.canonical("DK") == "Donkey Kong"


def test_display_name_and_grouping():
    e_slot = mk(1, [f"dol:.data:{chars.SUBFILES_VA + 16:#x} lbl_800F1D78+0x10"], label="mario00.gpc")
    e_known = mk(2, ["menus:.data:0x241c lbl_2_data_241C"], known="First Found Baby Luigi", label="b_luigi00.gpc")
    e_gpc = mk(3, ["scan:lzss-probe"], label="kinopio00.gpc")
    e_hand = mk(4, ["scan:lzss-probe"], label="L_hand07.gpc", names=["L_hand07.gpc", "mario00.gpc"])
    e_movie = mk(5, ["dol:.data:0x801092c8 lbl_801092C8"], kind="hvqm4", known="movie1.HVQM4")
    cat = catalog.build_catalog([e_slot, e_known, e_gpc, e_hand, e_movie])
    names = cat["names"]
    assert names[1] == "Mario - equipment"
    assert names[2] == "Baby Luigi"
    assert names[3] == "Toad"
    assert names[4] == "Left hand"
    by_id = {c["id"]: c for c in cat["categories"]}
    groups = {g["name"]: g["items"] for g in by_id["characters"]["groups"]}
    assert 1 in groups["Mario"] and 4 in groups["Mario"]   # the hand is filed by its owner's model name
    assert 2 in groups["Baby Luigi"] and 3 in groups["Toad"]
    assert 5 in by_id["movies"]["groups"][0]["items"]
