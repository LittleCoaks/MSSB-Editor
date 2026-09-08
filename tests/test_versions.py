"""Telling the builds apart, and finding a build's tables in its DOL.

The layout search is exercised against a DOL built here rather than a real
one, so it runs without a copy of the game: the tables are laid out the way
every version lays them out (RELs first, then the MusyX groups, the stadiums
and the master table back to back, the character sub-files behind the chunk
descriptor) at addresses no real build uses.
"""
import struct

import pytest

from zzzzdat import chars, layout, versions

ARCHIVE = 0x2000000
CHUNK = 0x1000000
BASE = 0x80100000          # where the synthetic .data section lives
TEXT_BASE = 0x80003100


# ------------------------------------------------------------- versions --

def header(game_id: bytes, country: int = 1, title: bytes = b"TEST") -> bytes:
    h = bytearray(0x460)
    h[0:6] = game_id
    h[0x20:0x20 + len(title)] = title
    struct.pack_into(">I", h, 0x440 + 0x18, country)
    return bytes(h)


@pytest.mark.parametrize("game_id, country, key, demo", [
    (b"GYQE01", 1, "GYQE01", False),
    (b"GYQP01", 2, "GYQP01", False),
    (b"GYQJ01", 0, "GYQJ01", False),
    (b"RELSAB", 1, "RELSAB-US", True),
    (b"RELSAB", 0, "RELSAB-JP", True),
])
def test_identify(game_id, country, key, demo):
    v = versions.identify(header(game_id, country))
    assert (v.key, v.demo, v.game_id) == (key, demo, game_id.decode())


def test_identify_refuses_another_game():
    with pytest.raises(versions.UnknownVersion) as ex:
        versions.identify(header(b"RMBE01", title=b"Mario Super Sluggers"))
    assert "Mario Super Sluggers" in str(ex.value)


def test_only_the_us_build_is_the_documented_one():
    assert versions.RETAIL["GYQE01"].us
    assert not versions.RETAIL["GYQJ01"].us


# --------------------------------------------------------------- layout --

def descriptor(size: int, off: int, cs: int, lb: int = 0xB, rb: int = 4) -> bytes:
    return struct.pack(">4I", (rb << 8) | lb, (4 << 28) | size, off, cs)


def stored(size: int, off: int) -> bytes:
    return struct.pack(">4I", 0, size, off, size)


def build_dol() -> tuple[bytes, dict]:
    """A DOL holding one of every table this program looks for, and the
    addresses it should find them at."""
    data = bytearray()
    where = {}

    def align() -> None:
        data.extend(bytes(-len(data) % 16))

    def put(name: str, blob: bytes) -> None:
        align()
        where[name] = BASE + len(data)
        data.extend(blob)

    def gap(n: int = 64) -> None:
        data.extend(bytes(n))
        align()

    # the three RELs in aaaa.dat, then the streamed-music table
    put("rels", descriptor(0x100000, 0x800, 0x50000) + descriptor(0x200000, 0x51000, 0x90000)
        + descriptor(0x50000, 0xE1000, 0x20000))
    gap()
    strings_at = BASE + len(data) + 15 * 16 + 64  # the table, a gap, then the paths
    names = [b"snd/my_snd_h/mario_01_h.adp\0", b"snd/my_snd_h/koopa_h.adp\0"]
    put("music", b"".join(struct.pack(">4I", strings_at + (0 if i < 8 else len(names[0])),
                                      0x1000 * (i + 1), 0, 0x1000 * (i + 1)) for i in range(15)))
    gap()
    assert BASE + len(data) == strings_at
    data.extend(b"".join(names))
    gap()
    # the small tables, recognised by their contents
    put("glove", struct.pack(">54H", *[s * 6 for s in range(chars.SLOTS)]))
    put("event_sets", struct.pack(">54H", *[v & 0xFFFF for v in chars.EVENT_SETS]))
    gap()
    put("musyx", b"".join(descriptor(0x8000, 0x400000 + i * 0x1000, 0x4000) for i in range(48)))
    gap()
    # the stadium table runs straight into the master table, whose offsets are
    # inside the ARAM chunk (so 32-byte aligned, and small)
    put("stadiums", b"".join(descriptor(0x40000, 0x1800000 + i * 0x1000, 0x20000) for i in range(21)))
    put("master", b"".join(descriptor(0x8000, i * 0x20, 0x1000) for i in range(516)))
    gap()
    # the chunk itself, then the character tables behind it
    put("chunk", stored(0x400000, CHUNK))
    where["subfiles"] = BASE + len(data)
    n = chars.SLOTS * chars.TRACKS + chars.SLOTS * 6 + (516 - 486)
    data.extend(b"".join(descriptor(0x4000, 0x100000 + i * 0x800, 0x2000) for i in range(n)))
    put("slot_table", struct.pack(">54H", *chars.SLOT_TABLE))
    gap()

    # A DOL header numbers seven text sections then eleven data ones, and the
    # first two data sections are always the exception tables -- descriptors
    # are only looked for in the ones after those.
    text = bytes(0x40)
    body = text + bytes(0x20) + bytes(0x20) + bytes(data)
    parts = [(0, 0x100, len(text), TEXT_BASE),                          # .text
             (7, 0x100 + 0x40, 0x20, 0x80005600),                       # extab
             (8, 0x100 + 0x60, 0x20, 0x80006C00),                       # extabindex
             (9, 0x100 + 0x80, len(data), BASE)]                        # .data
    offs, addrs, sizes = [0] * 18, [0] * 18, [0] * 18
    for i, off, size, addr in parts:
        offs[i], addrs[i], sizes[i] = off, addr, size
    head = struct.pack(">18I", *offs) + struct.pack(">18I", *addrs) + struct.pack(">18I", *sizes)
    dol = bytearray(0x100 + len(body))
    dol[0:len(head)] = head
    dol[0x100:] = body
    return bytes(dol), where


def test_resolve_finds_every_table():
    dol, where = build_dol()
    l = layout.resolve(dol, ARCHIVE, key="TEST")
    assert layout.check(l) == []
    assert l.resolved and l.key == "TEST"
    assert l.aram_chunk == CHUNK
    assert l.rel_table_va == where["rels"]
    assert l.rels == {"menus": (0x800, 0x50000, 0x100000), "game": (0x51000, 0x90000, 0x200000),
                      "debug": (0xE1000, 0x20000, 0x50000)}
    assert l.musyx_va == where["musyx"] and l.musyx_count == 48
    assert l.stadium_va == where["stadiums"] and l.stadiums == 7
    assert l.master_va == where["master"] and l.master_entries == 516
    assert l.subfiles_va == where["subfiles"]
    assert l.hand_table_va == where["subfiles"] + chars.SLOTS * chars.TRACKS * 16
    assert l.slot_table_va == where["slot_table"]
    assert l.glove_va == where["glove"]
    assert l.event_set_va == where["event_sets"]
    assert l.music_table_va == where["music"] and l.music_tracks == 15


def test_resolve_keeps_the_us_addresses_for_what_it_cannot_find():
    l = layout.resolve(bytes(0x200), ARCHIVE, key="TEST")
    assert l.subfiles_va == layout.US.subfiles_va
    assert l.aram_chunk == layout.US.aram_chunk


def test_layout_survives_a_round_trip_through_the_index():
    dol, _ = build_dol()
    l = layout.resolve(dol, ARCHIVE, key="TEST")
    assert layout.Layout.from_dict(l.to_dict()) == l


def test_from_dict_ignores_fields_it_does_not_know():
    d = layout.US.to_dict()
    d["something_added_later"] = 1
    assert layout.Layout.from_dict(d) == layout.US


def test_use_points_the_readers_at_the_layout():
    from zzzzdat import stadiums
    from zzzzdat.music import dolinfo
    dol, where = build_dol()
    l = layout.resolve(dol, ARCHIVE, key="TEST")
    try:
        layout.use(l)
        assert chars.SUBFILES_VA == where["subfiles"]
        assert chars.MASTER_VA == where["master"]
        assert chars.ARAM_CHUNK == CHUNK
        assert stadiums.STADIUM_VA == where["stadiums"]
        assert dolinfo.TABLE_VA == where["music"]
        # and the character tables still classify by the new addresses
        c = chars.classify(where["subfiles"] + (27 * chars.TRACKS) * 16)
        assert c["character"] == "Hammer Bro" and c["track"] == 0
    finally:
        layout.use(layout.US)


def test_us_defaults_are_self_consistent():
    assert layout.check(layout.US) == []


@pytest.mark.game
def test_the_configured_game_resolves(store):
    assert layout.check(store.layout) == []
    assert store.layout.resolved
    v = store.game.version
    if v:
        assert store.layout.key == v.key
