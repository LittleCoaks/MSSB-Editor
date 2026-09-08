"""COLLADA 1.4.1 (.dae) export of C3 models.

The same content `c3.to_glb` writes, in the interchange format the older
modelling pipelines read: geometry (positions, normals, UVs, vertex colours),
one material per texture and, when an actor is passed, the skeleton as
`<node type="JOINT">`, the body mesh as a `<skin>` controller, and each
animation sequence as an `<animation_clip>` over per-bone matrix channels.

COLLADA indexes every semantic separately, so the C3 (position, normal, UV,
colour) index tuples go in as they are, without the vertex de-duplication
glTF needs. Textures are referenced by file name (`<init_from>`), so the
PNGs live beside the .dae; `Store.extract_models` writes them there.

Matrices are serialised row-major, which is what COLLADA's column-vector
convention wants, and UVs are flipped (COLLADA's origin is bottom-left,
the GX arrays' is top-left).
"""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from .c3 import Mesh, Model, _invert

FLIP = [[1.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
IDENTITY = [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def _f(v: float) -> str:
    return format(float(v), ".9g")


def _mtx(m: list) -> str:
    return " ".join(_f(m[r][c]) for r in range(4) for c in range(4))


def _compose(scale: tuple, quat: tuple, trans: tuple) -> list:
    x, y, z, w = quat
    sx, sy, sz = scale
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    m = [[r[i][0] * sx, r[i][1] * sy, r[i][2] * sz, trans[i]] for i in range(3)]
    m.append([0.0, 0.0, 0.0, 1.0])
    return m


def _mat(tex: int | None) -> str:
    return f"tex{tex}" if tex is not None else "untextured"


def _clamp(i, n: int) -> int:
    return i if i is not None and 0 <= i < n else 0


class _Doc:
    """String builder for the XML, with the source/accessor boilerplate."""

    def __init__(self):
        self.out: list[str] = []

    def add(self, s: str) -> None:
        self.out.append(s)

    def float_source(self, sid: str, rows: list, params: tuple) -> None:
        stride = len(params)
        flat = [c for r in rows for c in r[:stride]]
        self.add(f'<source id="{sid}">')
        self.add(f'<float_array id="{sid}-array" count="{len(flat)}">{" ".join(_f(v) for v in flat)}</float_array>')
        self.add(f'<technique_common><accessor source="#{sid}-array" count="{len(rows)}" stride="{stride}">')
        for p in params:
            self.add(f'<param name="{p}" type="float"/>')
        self.add("</accessor></technique_common></source>")

    def matrix_source(self, sid: str, mats: list) -> None:
        self.add(f'<source id="{sid}"><float_array id="{sid}-array" count="{len(mats) * 16}">'
                 + " ".join(_mtx(m) for m in mats)
                 + f'</float_array><technique_common><accessor source="#{sid}-array" count="{len(mats)}" stride="16">'
                   '<param name="TRANSFORM" type="float4x4"/></accessor></technique_common></source>')

    def name_source(self, sid: str, names: list, param: str) -> None:
        self.add(f'<source id="{sid}">')
        self.add(f'<Name_array id="{sid}-array" count="{len(names)}">{" ".join(names)}</Name_array>')
        self.add(f'<technique_common><accessor source="#{sid}-array" count="{len(names)}" stride="1">'
                 f'<param name="{param}" type="name"/></accessor></technique_common></source>')


def _draw_uses(d, m: Mesh) -> tuple:
    has_n = bool(m.normals) and any(v[1] is not None for tri in d.tris for v in tri)
    has_t = bool(m.uvs) and any(v[2] is not None for tri in d.tris for v in tri)
    # a single colour for the whole mesh carries no information; skip it, as the glTF writer does
    has_c = len(m.colors) > 1 and any(len(v) > 3 and v[3] is not None for tri in d.tris for v in tri)
    return has_n, has_t, has_c


def to_dae(model: Model, texture_names: dict | None = None, bones: list | None = None,
           skin_weights: dict | None = None, banks: list | None = None) -> str:
    """The model as a COLLADA document. `texture_names` maps texture index to
    the PNG file name to reference; `bones`, `skin_weights` and `banks` are
    what `c3.to_glb` takes (see its docstring)."""
    texture_names = texture_names or {}
    d = _Doc()
    drawn = [(mi, m) for mi, m in enumerate(model.meshes) if m.positions and any(dr.tris for dr in m.draws)]
    used = sorted({dr.texture for _mi, m in drawn for dr in m.draws if dr.texture is not None})
    slots = list(used) + ([None] if any(dr.texture is None for _mi, m in drawn for dr in m.draws) else [])

    d.add('<?xml version="1.0" encoding="utf-8"?>')
    d.add('<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">')
    d.add('<asset><contributor><authoring_tool>zzzzdat</authoring_tool></contributor>'
          '<unit meter="1" name="meter"/><up_axis>Y_UP</up_axis></asset>')

    named = [t for t in used if t in texture_names]
    if named:
        d.add("<library_images>")
        for t in named:
            d.add(f'<image id="img{t}" name="tex{t}"><init_from>{escape(texture_names[t])}</init_from></image>')
        d.add("</library_images>")
    if not slots:
        # an empty document still has to parse: the schema wants every library
        # it does carry to hold at least one element
        d.add('<library_visual_scenes><visual_scene id="scene" name="scene"/></library_visual_scenes>')
        d.add('<scene><instance_visual_scene url="#scene"/></scene></COLLADA>')
        return "\n".join(d.out) + "\n"
    d.add("<library_effects>")
    for t in slots:
        d.add(f'<effect id="fx{_mat(t)}"><profile_COMMON>')
        if t in texture_names:
            d.add(f'<newparam sid="surf{t}"><surface type="2D"><init_from>img{t}</init_from></surface></newparam>')
            d.add(f'<newparam sid="samp{t}"><sampler2D><source>surf{t}</source></sampler2D></newparam>')
            d.add(f'<technique sid="common"><lambert><diffuse><texture texture="samp{t}" texcoord="UVSET0"/>'
                  "</diffuse></lambert></technique>")
        else:
            d.add('<technique sid="common"><lambert><diffuse><color>0.8 0.8 0.8 1</color></diffuse>'
                  "</lambert></technique>")
        d.add("</profile_COMMON></effect>")
    d.add("</library_effects>")
    d.add("<library_materials>")
    for t in slots:
        d.add(f'<material id="mat{_mat(t)}" name="{_mat(t)}"><instance_effect url="#fx{_mat(t)}"/></material>')
    d.add("</library_materials>")

    d.add("<library_geometries>")
    for mi, m in drawn:
        _geometry(d, mi, m)
    d.add("</library_geometries>")

    order, joint_of, skinned = [], {}, None
    if bones:
        from .anim import bone_order
        from .c3 import skinned_mesh_index
        order = bone_order(bones)
        joint_of = {b.offset: f"j{i}" for i, b in enumerate(order)}
        if skin_weights:
            skinned = skinned_mesh_index(model, bones)
    if skinned is not None:
        _controller(d, model.meshes[skinned], skinned, order, joint_of, skin_weights)

    clips = _animations(d, order, joint_of, banks) if (bones and banks) else []
    _scene(d, model, drawn, bones, order, joint_of, skinned, texture_names)
    if clips:
        d.add("<library_animation_clips>")
        for cid, name, dur in clips:
            d.add(f'<animation_clip id="{cid}" name={quoteattr(name)} start="0" end="{_f(dur)}">'
                  f'<instance_animation url="#{cid}-a"/></animation_clip>')
        d.add("</library_animation_clips>")
    d.add('<scene><instance_visual_scene url="#scene"/></scene>')
    d.add("</COLLADA>")
    return "\n".join(d.out) + "\n"


def _geometry(d: _Doc, mi: int, m: Mesh) -> None:
    g = f"geo{mi}"
    d.add(f'<geometry id="{g}" name={quoteattr(m.name)}><mesh>')
    d.float_source(f"{g}-pos", m.positions, ("X", "Y", "Z"))
    if m.normals:
        d.float_source(f"{g}-nrm", m.normals, ("X", "Y", "Z"))
    if m.uvs:
        d.float_source(f"{g}-uv", [(u, 1.0 - v) for u, v in m.uvs], ("S", "T"))
    if len(m.colors) > 1:
        d.float_source(f"{g}-col", m.colors, ("R", "G", "B", "A"))
    d.add(f'<vertices id="{g}-vtx"><input semantic="POSITION" source="#{g}-pos"/></vertices>')
    for dr in m.draws:
        if not dr.tris:
            continue
        has_n, has_t, has_c = _draw_uses(dr, m)
        d.add(f'<triangles count="{len(dr.tris)}" material="{_mat(dr.texture)}">')
        off = 0
        d.add(f'<input semantic="VERTEX" source="#{g}-vtx" offset="{off}"/>')
        if has_n:
            off += 1
            d.add(f'<input semantic="NORMAL" source="#{g}-nrm" offset="{off}"/>')
        if has_t:
            off += 1
            d.add(f'<input semantic="TEXCOORD" source="#{g}-uv" offset="{off}" set="0"/>')
        if has_c:
            off += 1
            d.add(f'<input semantic="COLOR" source="#{g}-col" offset="{off}" set="0"/>')
        p = []
        for tri in dr.tris:
            for v in tri:
                p.append(str(_clamp(v[0], len(m.positions))))
                if has_n:
                    p.append(str(_clamp(v[1], len(m.normals))))
                if has_t:
                    p.append(str(_clamp(v[2], len(m.uvs))))
                if has_c:
                    p.append(str(_clamp(v[3] if len(v) > 3 else None, len(m.colors))))
        d.add("<p>" + " ".join(p) + "</p></triangles>")
    d.add("</mesh></geometry>")


def _controller(d: _Doc, m: Mesh, mi: int, order: list, joint_of: dict, skin_weights: dict) -> None:
    """A <skin> over the body mesh's position array: skin weights are keyed by
    position index, which is exactly what COLLADA's <vertex_weights> wants."""
    d.add(f'<library_controllers><controller id="ctrl{mi}" name="skin"><skin source="#geo{mi}">')
    d.add(f"<bind_shape_matrix>{_mtx(IDENTITY)}</bind_shape_matrix>")
    d.name_source(f"ctrl{mi}-joints", [joint_of[b.offset] for b in order], "JOINT")
    d.matrix_source(f"ctrl{mi}-bind", [_invert(b.world) for b in order])
    weights: list = []
    windex: dict = {}
    vcount, v = [], []
    for i in range(len(m.positions)):
        ws = [(b, w) for b, w in (skin_weights.get(i) or [(0, 1.0)])[:4] if b < len(order)] or [(0, 1.0)]
        vcount.append(len(ws))
        for b, w in ws:
            k = windex.get(w)
            if k is None:
                k = windex[w] = len(weights)
                weights.append(w)
            v += [b, k]
    d.float_source(f"ctrl{mi}-weights", [(w,) for w in weights], ("WEIGHT",))
    d.add(f'<joints><input semantic="JOINT" source="#ctrl{mi}-joints"/>'
          f'<input semantic="INV_BIND_MATRIX" source="#ctrl{mi}-bind"/></joints>')
    d.add(f'<vertex_weights count="{len(vcount)}">'
          f'<input semantic="JOINT" source="#ctrl{mi}-joints" offset="0"/>'
          f'<input semantic="WEIGHT" source="#ctrl{mi}-weights" offset="1"/>'
          f'<vcount>{" ".join(str(c) for c in vcount)}</vcount>'
          f'<v>{" ".join(str(x) for x in v)}</v></vertex_weights>')
    d.add("</skin></controller></library_controllers>")


def _bind_material(m: Mesh, texture_names: dict) -> str:
    slots = sorted({dr.texture for dr in m.draws if dr.tris}, key=lambda t: (t is None, t))
    if not slots:
        return ""
    out = ["<bind_material><technique_common>"]
    for t in slots:
        out.append(f'<instance_material symbol="{_mat(t)}" target="#mat{_mat(t)}">')
        if t in texture_names:
            out.append('<bind_vertex_input semantic="UVSET0" input_semantic="TEXCOORD" input_set="0"/>')
        out.append("</instance_material>")
    out.append("</technique_common></bind_material>")
    return "".join(out)


def _geo_node(m: Mesh, mi: int, texture_names: dict) -> str:
    return (f'<node id="node{mi}" name={quoteattr(m.name)} type="NODE"><instance_geometry url="#geo{mi}">'
            f"{_bind_material(m, texture_names)}</instance_geometry></node>")


def _scene(d: _Doc, model: Model, drawn: list, bones: list | None, order: list, joint_of: dict,
           skinned: int | None, texture_names: dict) -> None:
    d.add('<library_visual_scenes><visual_scene id="scene" name="scene">')
    if not bones:
        for mi, m in drawn:
            d.add(_geo_node(m, mi, texture_names))
        d.add("</visual_scene></library_visual_scenes>")
        return
    # actor space stands the character along -Y; the root turns it upright, as the glTF writer does
    d.add('<node id="actor" name="actor" type="NODE">')
    d.add(f'<matrix sid="transform">{_mtx(FLIP)}</matrix>')
    by_id = {b.id: b for b in bones}
    children: dict = {b.offset: [] for b in order}
    roots = []
    for b in order:
        (children[b.parent] if (b.inherit and b.parent in children) else roots).append(b)
    hang: dict = {}
    loose = []
    for mi, m in drawn:
        if mi == skinned:
            continue
        owner = by_id.get(m.attach) if m.attach is not None else next((b for b in order if b.geo == mi), None)
        if owner is not None and owner.offset in children:
            hang.setdefault(owner.offset, []).append(mi)
        else:
            loose.append(mi)

    def node(b) -> None:
        d.add(f'<node id="{joint_of[b.offset]}" sid="{joint_of[b.offset]}" name="bone{b.id}" type="JOINT">')
        d.add(f'<matrix sid="transform">{_mtx(_compose(b.scale, b.quat, b.trans))}</matrix>')
        for c in children[b.offset]:
            node(c)
        for mi in hang.get(b.offset, []):
            d.add(_geo_node(model.meshes[mi], mi, texture_names))
        d.add("</node>")

    for b in roots:
        node(b)
    for mi in loose:
        d.add(_geo_node(model.meshes[mi], mi, texture_names))
    d.add("</node>")
    if skinned is not None:
        # the skin is already in actor space and the joints carry the flip, so
        # the controller's own node stays at identity
        m = model.meshes[skinned]
        d.add(f'<node id="node{skinned}" name={quoteattr(m.name)} type="NODE">'
              f'<instance_controller url="#ctrl{skinned}">'
              + "".join(f"<skeleton>#{joint_of[b.offset]}</skeleton>" for b in roots)
              + f"{_bind_material(m, texture_names)}</instance_controller></node>")
    d.add("</visual_scene></library_visual_scenes>")


def _animations(d: _Doc, order: list, joint_of: dict, banks: list) -> list:
    """One <animation> per sequence holding a matrix channel per animated bone;
    each becomes an <animation_clip> so the sequences stay apart."""
    from .anim import FRAME_RATE, is_static
    by_id = {b.id: b for b in order}
    clips = []
    d.add("<library_animations>")
    for label, bank in banks:
        for seq in bank.sequences:
            if is_static(seq):
                continue          # a placeholder that holds the rest pose: nothing to play
            cid = f"clip{len(clips)}"
            body = _Doc()
            for tr in seq.tracks:
                b = by_id.get(tr.bone)
                if b is None or not tr.keys:
                    continue
                sid = f"{cid}-{joint_of[b.offset]}"
                body.add(f'<animation id="{sid}">')
                body.float_source(f"{sid}-in", [(k.time / FRAME_RATE,) for k in tr.keys], ("TIME",))
                body.matrix_source(f"{sid}-out", [_compose(b.scale, k.quat or b.quat, k.trans or b.trans)
                                                  for k in tr.keys])
                body.name_source(f"{sid}-interp", ["LINEAR"] * len(tr.keys), "INTERPOLATION")
                body.add(f'<sampler id="{sid}-samp"><input semantic="INPUT" source="#{sid}-in"/>'
                         f'<input semantic="OUTPUT" source="#{sid}-out"/>'
                         f'<input semantic="INTERPOLATION" source="#{sid}-interp"/></sampler>')
                body.add(f'<channel source="#{sid}-samp" target="{joint_of[b.offset]}/transform"/>')
                body.add("</animation>")
            if not body.out:
                continue
            name = f"{label} / {seq.name}" if label else seq.name
            d.add(f'<animation id="{cid}-a" name={quoteattr(name)}>')
            d.out.extend(body.out)
            d.add("</animation>")
            clips.append((cid, name, seq.duration / FRAME_RATE))
    d.add("</library_animations>")
    return clips
