import math

from zzzzdat import c3


def _bone(offset, parent=0, scale=(1, 1, 1), quat=(0, 0, 0, 1), trans=(0, 0, 0), geo=None):
    return c3.Bone(offset, offset, parent, geo, True, scale, quat, trans)


def test_srt_identity():
    m = c3._srt(_bone(0x20))
    assert m == [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def test_quaternion_rotation_and_chain():
    s = math.sqrt(0.5)
    root = _bone(0x20, quat=(s, 0, 0, s))                 # +90 degrees about X
    child = _bone(0x3C, parent=0x20, trans=(0, 1, 0), scale=(2, 2, 2), geo=0)
    c3._compute_world(list((root, child)))
    x, y, z = c3._xform(child.world, (0, 0, 0), 1.0)
    # the child sits 1 unit up its parent's Y, which the root rotates onto +Z
    assert abs(x) < 1e-6 and abs(y) < 1e-6 and abs(z - 1) < 1e-6
    # and its scale is inherited
    px, py, pz = c3._xform(child.world, (1, 0, 0), 0.0)
    assert abs(px - 2) < 1e-6


def test_apply_actor_moves_only_referenced_meshes():
    s = math.sqrt(0.5)
    root = _bone(0x20, quat=(s, 0, 0, s))
    head = _bone(0x3C, parent=0x20, scale=(0.5, 0.5, 0.5), trans=(0, 0, 3), geo=1)
    bones = [root, head]
    c3._compute_world(bones)
    body = c3.Mesh("body", [(0.0, -1.0, 0.0)], [(0.0, 1.0, 0.0)], [], [])
    hd = c3.Mesh("head", [(2.0, 0.0, 0.0)], [(1.0, 0.0, 0.0)], [], [])
    model = c3.Model([body, hd])
    c3.apply_actor(model, bones)
    # skinned body: untouched apart from the upright flip
    assert body.positions[0] == (0.0, 1.0, -0.0)
    # head: scaled, translated, rotated by the chain, then flipped upright
    hx, hy, hz = hd.positions[0]
    assert abs(hx - 1.0) < 1e-6 and abs(hy - 3.0) < 1e-6 and abs(hz) < 1e-6


def test_vertex_layout():
    lay = c3._vertex_layout(0x00002C3C)
    assert lay["stride"] == 7 and lay["pos"] == (0, 2) and lay["norm"] == (2, 2) and lay["uv"] == (4, 2)


def test_primitives_strip_and_quads():
    lay = {"stride": 1, "pos": (0, 1), "norm": (0, 0), "uv": (0, 0)}
    data = bytes([0x98, 0, 4, 0, 1, 2, 3, 0x80, 0, 4, 4, 5, 6, 7, 0x00, 0x61, 1, 2, 3, 4])
    tris = c3._primitives(data, 0, len(data), lay)
    assert len(tris) == 2 + 2
    assert tris[0][0][0] == 0 and tris[1][0][0] == 3   # strip alternates winding: (0,1,2), (3,2,1)
    assert tris[2][0][0] == 4 and tris[3][0][0] == 6   # quad split


def test_glb_is_valid_container():
    m = c3.Model([c3.Mesh("tri", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 0), (1, 0), (0, 1)],
                          [c3.Draw(None, [((0, None, 0), (1, None, 1), (2, None, 2))])])])
    glb = c3.to_glb(m)
    assert glb[:4] == b"glTF"
    assert int.from_bytes(glb[8:12], "little") == len(glb)
    assert b'"POSITION"' in glb and b'"TEXCOORD_0"' in glb
    obj = c3.to_obj(m)
    assert obj.count("\nv ") == 3 and "f 1/1 2/2 3/3" in obj
