"""COLLADA export: the document parses, and carries the geometry, the
materials, the skeleton, the skin and one clip per animation sequence."""
import math
from xml.etree import ElementTree as ET

from zzzzdat import anim, c3, dae

NS = "{http://www.collada.org/2005/11/COLLADASchema}"


def _tri_mesh():
    return c3.Mesh("tri", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                   [(0.0, 0.0, 1.0)] * 3, [(0.0, 0.0), (1.0, 0.0), (0.0, 0.25)],
                   [c3.Draw(0, [((0, 0, 0, 0), (1, 1, 1, 1), (2, 2, 2, 2))])],
                   colors=[(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0)])


def _floats(root, sid):
    a = next(x for x in root.iter(NS + "float_array") if x.get("id") == sid + "-array")
    return [float(v) for v in a.text.split()]


def test_plain_model():
    x = dae.to_dae(c3.Model([_tri_mesh()]), {0: "tri_tex0.png"})
    root = ET.fromstring(x)
    assert root.get("version") == "1.4.1"
    assert [i.find(NS + "init_from").text for i in root.iter(NS + "image")] == ["tri_tex0.png"]
    assert [m.get("id") for m in root.iter(NS + "material")] == ["mattex0"]
    assert _floats(root, "geo0-pos") == [0, 0, 0, 1, 0, 0, 0, 1, 0]
    # COLLADA's texture origin is the bottom-left one, so V is flipped
    assert _floats(root, "geo0-uv") == [0, 1, 1, 1, 0, 0.75]
    assert len(_floats(root, "geo0-col")) == 12
    tris = next(root.iter(NS + "triangles"))
    assert tris.get("count") == "1" and tris.get("material") == "tex0"
    # VERTEX, NORMAL, TEXCOORD and COLOR, so four indices per vertex
    assert [i.get("semantic") for i in tris.findall(NS + "input")] == ["VERTEX", "NORMAL", "TEXCOORD", "COLOR"]
    assert tris.find(NS + "p").text.split() == ["0", "0", "0", "0", "1", "1", "1", "1", "2", "2", "2", "2"]
    node = next(n for n in root.iter(NS + "node"))
    assert node.find(NS + "instance_geometry").get("url") == "#geo0"


def test_missing_indices_are_clamped_not_dropped():
    """A draw whose vertices carry no normal or UV still writes three indices
    per triangle, and an out-of-range index falls back to 0."""
    m = c3.Mesh("m", [(0.0, 0.0, 0.0)] * 3, [], [],
                [c3.Draw(None, [((0, None, None, None), (9, None, None, None), (2, None, None, None))])])
    root = ET.fromstring(dae.to_dae(c3.Model([m])))
    tris = next(root.iter(NS + "triangles"))
    assert [i.get("semantic") for i in tris.findall(NS + "input")] == ["VERTEX"]
    assert tris.find(NS + "p").text.split() == ["0", "0", "2"]
    assert [mt.get("id") for mt in root.iter(NS + "material")] == ["matuntextured"]


def _rig():
    s = math.sqrt(0.5)
    root = c3.Bone(0x20, 0, 0, None, True, (1, 1, 1), (s, 0, 0, s), (0, 0, 0))
    hand = c3.Bone(0x3C, 1, 0x20, 1, True, (1, 1, 1), (0, 0, 0, 1), (0, 1, 0))
    bones = [root, hand]
    c3._compute_world(bones)
    return bones


def test_skeleton_skin_and_clips():
    bones = _rig()
    hand = c3.Mesh("hand", [(0.0, 0.0, 0.0)] * 3, [], [],
                   [c3.Draw(None, [((0, None, None, None), (1, None, None, None), (2, None, None, None))])])
    model = c3.Model([_tri_mesh(), hand])
    seq = anim.Sequence("wave", [anim.Track(1, [anim.Key(0.0, (0, 0, 0, 1), (0, 0, 0)),
                                                anim.Key(30.0, (0, 0, 0, 1), (0, 2, 0))], 30.0)])
    x = dae.to_dae(model, {0: "t.png"}, bones=bones,
                   skin_weights={0: [(0, 1.0)], 1: [(1, 1.0)], 2: [(0, 0.5), (1, 0.5)]},
                   banks=[("bank13", anim.Bank([seq]))])
    root = ET.fromstring(x)
    joints = [n for n in root.iter(NS + "node") if n.get("type") == "JOINT"]
    assert [n.get("id") for n in joints] == ["j0", "j1"]
    # the bone tree is nested, and the mesh the actor points at hangs from its bone
    assert joints[1] in list(joints[0])
    assert joints[1].find(NS + "node").find(NS + "instance_geometry").get("url") == "#geo1"
    # the skinned mesh instances the controller instead, at identity, naming the root joint
    ctrl = next(root.iter(NS + "instance_controller"))
    assert ctrl.get("url") == "#ctrl0" and [s.text for s in ctrl.findall(NS + "skeleton")] == ["#j0"]
    vw = next(root.iter(NS + "vertex_weights"))
    assert vw.get("count") == "3" and vw.find(NS + "vcount").text.split() == ["1", "1", "2"]
    assert len(_floats(root, "ctrl0-bind")) == 32   # one inverse bind matrix per joint
    # one clip per sequence, with a matrix channel on the animated bone only
    clips = list(root.iter(NS + "animation_clip"))
    assert [c.get("name") for c in clips] == ["bank13 / wave"]
    assert clips[0].find(NS + "instance_animation").get("url") == "#clip0-a"
    assert [c.get("target") for c in root.iter(NS + "channel")] == ["j1/transform"]
    assert len(_floats(root, "clip0-j1-out")) == 32  # two keys as 4x4 matrices
    assert _floats(root, "clip0-j1-in") == [0.0, 30.0 / anim.FRAME_RATE]  # the fixture keys frames 0 and 30


def test_animation_matrix_carries_the_key_translation():
    bones = _rig()
    seq = anim.Sequence("s", [anim.Track(1, [anim.Key(0.0, None, (3.0, 4.0, 5.0)),
                                             anim.Key(30.0, None, (3.0, 9.0, 5.0))], 30.0)])
    root = ET.fromstring(dae.to_dae(c3.Model([_tri_mesh()]), bones=bones,
                                    banks=[("", anim.Bank([seq]))]))
    m = _floats(root, "clip0-j1-out")
    assert len(m) == 32                       # one 4x4 per key
    # row-major, so each key's translation is the last column
    assert m[:16][3::4] == [3.0, 4.0, 5.0, 1.0]
    assert m[16:][3::4] == [3.0, 9.0, 5.0, 1.0]


def test_sequences_that_never_move_are_left_out():
    """A third of the game's sequences hold the rest pose for their whole
    length; offering them as something to play is just noise."""
    bones = _rig()
    still = anim.Sequence("placeholder", [anim.Track(1, [anim.Key(t, (0, 0, 0, 1), (0, 1, 0))
                                                         for t in (0.0, 20.0, 40.0)], 40.0)])
    moves = anim.Sequence("wave", [anim.Track(1, [anim.Key(0.0, (0, 0, 0, 1), (0, 1, 0)),
                                                  anim.Key(30.0, (0, 0, 0, 1), (0, 2, 0))], 30.0)])
    root = ET.fromstring(dae.to_dae(c3.Model([_tri_mesh()]), bones=bones,
                                    banks=[("", anim.Bank([still, moves]))]))
    assert [c.get("name") for c in root.iter(NS + "animation_clip")] == ["wave"]


def test_empty_model_still_parses():
    """No drawable mesh: the libraries the schema wants non-empty are left out."""
    root = ET.fromstring(dae.to_dae(c3.Model([c3.Mesh("m", [], [], [], [])])))
    assert not list(root.iter(NS + "library_effects"))
    assert next(root.iter(NS + "visual_scene")).get("id") == "scene"


def _scaled_rig():
    """A root, and a child bone that shrinks what hangs off it - the shape of
    every character's head bone (Mario's is 0.1426)."""
    root = c3.Bone(0x20, 0, 0, None, True, (1, 1, 1), (0, 0, 0, 1), (0, 0, 0))
    head = c3.Bone(0x3C, 1, 0x20, 1, True, (0.25, 0.25, 0.25), (0, 0, 0, 1), (0, 4, 0))
    tip = c3.Bone(0x58, 2, 0x3C, None, True, (1, 1, 1), (0, 0, 0, 1), (0, 8, 0))
    bones = [root, head, tip]
    c3._compute_world(bones)
    return bones


def _scale_of(m):
    """The length of each column of the 3x3, read out of a row-major 4x4."""
    return [math.sqrt(sum(m[r * 4 + c] ** 2 for r in range(3))) for c in range(3)]


def _node_matrix(n):
    return [float(v) for v in n.find(NS + "matrix").text.split()]


def test_joints_carry_no_scale():
    """A Blender armature bone is head/tail/roll and cannot hold a scale, so an
    importer drops one that rides on a JOINT: the head inflates by 1/scale and
    leaves the body. The scale goes on the geometry's own node instead, and is
    accumulated into the child translations so the rest of the chain stays put."""
    head_mesh = c3.Mesh("head", [(0.0, 0.0, 0.0)] * 3, [], [],
                        [c3.Draw(None, [((0, None, None, None), (1, None, None, None),
                                         (2, None, None, None))])])
    root = ET.fromstring(dae.to_dae(c3.Model([_tri_mesh(), head_mesh]), bones=_scaled_rig()))
    joints = {n.get("id"): n for n in root.iter(NS + "node") if n.get("type") == "JOINT"}
    assert list(joints) == ["j0", "j1", "j2"]
    for jid, n in joints.items():
        assert _scale_of(_node_matrix(n)) == [1.0, 1.0, 1.0], f"{jid} still carries a scale"
    # the mesh hangs off the scaled bone, so its own node takes the scale over
    # (it follows the child joints, so pick it out rather than taking the first)
    geo = next(n for n in joints["j1"] if n.tag == NS + "node"
               and n.find(NS + "instance_geometry") is not None)
    assert geo.find(NS + "instance_geometry").get("url") == "#geo1"
    assert _scale_of(_node_matrix(geo)) == [0.25, 0.25, 0.25]
    # j2's translation is measured in its parent's accumulated scale, so dropping
    # the scale off j1 does not move it: 8 * 0.25 = 2 below a j1 still at y 4
    assert _node_matrix(joints["j2"])[3::4] == [0.0, 2.0, 0.0, 1.0]
    assert _node_matrix(joints["j1"])[3::4] == [0.0, 4.0, 0.0, 1.0]


def test_animated_translation_is_scaled_like_the_rest_pose():
    """A key's translation is a local one, so it lives in the same accumulated
    scale the rest translation was rewritten into."""
    bones = _scaled_rig()
    seq = anim.Sequence("s", [anim.Track(2, [anim.Key(0.0, None, (0.0, 8.0, 0.0)),
                                             anim.Key(30.0, None, (0.0, 16.0, 0.0))], 30.0)])
    root = ET.fromstring(dae.to_dae(c3.Model([_tri_mesh()]), bones=bones,
                                    banks=[("", anim.Bank([seq]))]))
    m = _floats(root, "clip0-j2-out")
    assert m[:16][3::4] == [0.0, 2.0, 0.0, 1.0]     # 8 * 0.25, matching the rest pose
    assert m[16:][3::4] == [0.0, 4.0, 0.0, 1.0]     # 16 * 0.25
    assert _scale_of(m[:16]) == [1.0, 1.0, 1.0]


def test_inverse_binds_match_the_scale_free_skeleton():
    """The bind pose has to be the skeleton as written, not as the game holds
    it, or the skinned mesh comes apart at every scaled joint."""
    bones = _scaled_rig()
    root = ET.fromstring(dae.to_dae(c3.Model([_tri_mesh()]), bones=bones,
                                    skin_weights={0: [(1, 1.0)], 1: [(1, 1.0)], 2: [(2, 1.0)]}))
    ib = _floats(root, "ctrl0-bind")
    assert len(ib) == 48                            # three joints
    for k in range(3):
        assert _scale_of(ib[k * 16:(k + 1) * 16]) == [1.0, 1.0, 1.0]
    # j1 sits at y 4 with no scale, so its inverse bind translates by -4
    assert ib[16:32][3::4] == [0.0, -4.0, 0.0, 1.0]
