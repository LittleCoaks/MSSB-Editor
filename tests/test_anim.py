"""ANIM bank / skin parsing and the rigged glTF export, on synthetic data."""
import json
import struct

from zzzzdat import anim, c3


def _actor():
    """Three bones: root 0 at origin, child 1 translated (0, 1, 0), child 2 of 1 at (0, 1, 0)."""
    nb = 3
    hdr = struct.pack(">IHHIIIHHII", c3.ACT_VERSION, 0, nb, 0xC, 0x20, 0, 0, 0, 0, 0)
    bones = bytearray()
    ctrl_base = 0x20 + nb * 0x1C
    offs = [0x20 + i * 0x1C for i in range(nb)]
    specs = [(0, 0, offs[1], (0, 0, 0)), (offs[0], 0, offs[2], (0, 1, 0)), (offs[1], 0, 0, (0, 1, 0))]
    for i, (parent, nxt, child, trans) in enumerate(specs):
        bones += struct.pack(">IIIIIHHBBH", ctrl_base + i * 0x34, 0, nxt, parent, child, 0xFFFF, i, 1, 0, 0)
    ctrls = bytearray()
    for i, (_p, _n, _c, trans) in enumerate(specs):
        ctrls += struct.pack(">B3x3f4f3f", 0xD, 1, 1, 1, 0, 0, 0, 1, *trans) + bytes(0x34 - 4 - 40)
    return bytes(hdr + bones + ctrls)


def _bank():
    """One sequence, two tracks: bone 1 rotates 90 degrees about Z over 10 frames
    (quat only), bone 0 translates (quat + trans, 14 fraction bits)."""
    seqs = 0x18
    tracks = seqs + 12
    kf = tracks + 2 * 16
    settings = kf + 4 * 12
    out = bytearray(struct.pack(">IIHHHHII", c3.ACT_VERSION, seqs, 0, 1, 2, 4, 0, 0))
    out += struct.pack(">IIHH", 0, tracks, 2, 0)
    out += struct.pack(">fIHHBBBB", 10.0, kf, 2, 1, 0x30, 8, 0x60, 1)
    out += struct.pack(">fIHHBBBB", 10.0, kf + 24, 2, 0, 0x3E, 9, 0x63, 1)
    s = 0.70710678
    q = lambda x, y, z, w: struct.pack(">4h", *(int(round(v * 16384)) for v in (x, y, z, w)))
    body = bytearray()
    k = []
    for t, setting in ((0.0, q(0, 0, 0, 1)), (10.0, q(0, 0, s, s)),
                       (0.0, q(0, 0, 0, 1) + struct.pack(">3h", 0, 0, 0)),
                       (10.0, q(0, 0, 0, 1) + struct.pack(">3h", 16384, 0, 0))):
        k.append(struct.pack(">fII", t, settings + len(body), 0))
        body += setting
    out += b"".join(k) + body
    return bytes(out)


def test_bank_parses():
    data = _bank()
    assert anim.is_bank(data, 0) and not c3.is_actor(data, 0)
    b = anim.parse_bank(data, 0)
    assert b and len(b.sequences) == 1 and b.skipped == 0
    tr = {t.bone: t for t in b.sequences[0].tracks}
    assert tr[1].keys[0].quat == (0.0, 0.0, 0.0, 1.0) and tr[1].keys[0].trans is None
    assert abs(tr[1].keys[1].quat[2] - 0.7071) < 1e-3 and tr[1].keys[1].time == 10.0
    assert tr[0].keys[1].trans == (1.0, 0.0, 0.0) and tr[0].keys[1].quat == (0.0, 0.0, 0.0, 1.0)
    assert not tr[1].quat_step and not tr[0].trans_step
    assert b.sequences[0].duration == 10.0


def test_actor_tree_order_and_rig_export():
    data = _actor()
    bones = c3.parse_actor(data, 0)
    assert bones and [b.id for b in anim.bone_order(bones)] == [0, 1, 2]
    assert bones[2].world[1][3] == 2.0  # child of child sits two units up
    mesh = c3.Mesh("body", [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 2.0, 0.0)], [], [],
                   [c3.Draw(None, [((0, None, None), (1, None, None), (2, None, None))])])
    weights = {0: [(0, 1.0)], 1: [(1, 1.0)], 2: [(2, 1.0)]}
    bank = anim.parse_bank(_bank(), 0)
    glb = c3.to_glb(c3.Model([mesh]), {}, bones=bones, skin_weights=weights, banks=[("test", bank)])
    n = struct.unpack_from("<I", glb, 12)[0]
    doc = json.loads(glb[20:20 + n])
    assert len(doc["skins"]) == 1 and doc["skins"][0]["joints"] == [1, 2, 3]
    assert doc["nodes"][0]["skin"] == 0 and doc["nodes"][4]["name"] == "actor"
    assert doc["nodes"][2]["translation"] == [0.0, 1.0, 0.0]
    a = doc["animations"][0]
    assert a["name"] == "test / sequence 1"
    paths = sorted((c["target"]["node"], c["target"]["path"]) for c in a["channels"])
    assert paths == [(1, "rotation"), (1, "translation"), (2, "rotation")]
    assert doc["accessors"][a["samplers"][0]["input"]]["max"] == [10.0 / anim.FRAME_RATE]


def test_invert():
    m = [[0.0, -1.0, 0.0, 3.0], [1.0, 0.0, 0.0, -2.0], [0.0, 0.0, 2.0, 1.0], [0.0, 0.0, 0.0, 1.0]]
    ident = c3._mul(m, c3._invert(m))
    assert all(abs(ident[i][j] - (i == j)) < 1e-12 for i in range(4) for j in range(4))
