"""Nintendo CharPipeline (C3) GeoPalette models -> triangles, OBJ and glTF.

Layout (all offsets relative to the GeoPalette section start unless noted),
after roeming/MSSB-Export-Models `helper_c3.py`:

    GeoPaletteHeader   u32 version (0x005BBC61), u32 userDataSize, u32 pUserData,
                       u32 numDescriptors, u32 pDescriptorArray
    GeoDescriptor      u32 pDisplayObject, u32 pName
    DisplayObjectLayout (offsets relative to the layout itself)
                       u32 pPosition, u32 pColor, u32 pTexture, u32 pLighting,
                       u32 pDisplay, u8 numTextures, pad[3]
    Position/Normal    u32 pArray, u16 count, u8 quantize, u8 numComponents (+f32 ambient for lighting)
    Texture            u32 pCoords, u16 count, u8 quantize, u8 numComponents, u32 pTplName, u32 pPalette
    Display            u32 pPrimitiveBank, u32 pStateList, u16 numStates
    DisplayState       u8 id, pad[3], u32 setting, u32 pPrimitiveList, u32 byteLength

quantize: high nibble = GX component type (0 = u8, 1 = s8, 2 = u16, 3 = s16,
4 = f32), low nibble = fixed-point fraction bits (ignored for f32). Display state ids: 1 = texture
(setting & 0xFF is the texture index when byte 1 of setting is 0x11),
2 = vertex descriptor (13 components x 2 bits, GX order: pos-matrix, pos,
normal, color0, color1, tex0..tex7; 0 = absent, 2 = u8 index, 3 = u16 index),
3 = matrix load. Primitive lists are GX display lists: 0x61 = BP register
(skip 4), 0x00 = nop, 0x80 quads, 0x90 triangles, 0x98 strip, 0xA0 fan
(each followed by u16 vertex count and packed index vertices).
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

GEOPALETTE_VERSION = 0x005BBC61

_QUANT = {0: (1, False), 1: (1, True), 2: (2, False), 3: (2, True), 4: (4, True)}  # GX_U8, S8, U16, S16, F32


@dataclass
class Draw:
    texture: int | None
    tris: list[tuple]  # ((p,n,t),(p,n,t),(p,n,t)) index triples; None where absent
    matrix: tuple | None = None


@dataclass
class Mesh:
    name: str
    positions: list[tuple]
    normals: list[tuple]
    uvs: list[tuple]
    draws: list[Draw]
    tpl_names: list[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(len(d.tris) for d in self.draws)


@dataclass
class Model:
    meshes: list[Mesh]

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes)


def _cstr(data: bytes, off: int, limit: int = 128) -> str:
    end = data.find(b"\0", off, off + limit)
    return data[off:end if end != -1 else off + limit].decode("ascii", "replace")


def _array(data: bytes, off: int, count: int, quant: int, ncomp: int, want: int) -> list[tuple]:
    fmt = quant >> 4
    shift = quant & 0xF
    size, signed = _QUANT.get(fmt, (2, True))
    stride = size * ncomp
    out = []
    scale = float(1 << shift)
    for i in range(count):
        base = off + i * stride
        comps = []
        for c in range(want):
            b = data[base + c * size:base + c * size + size]
            if len(b) < size:
                comps.append(0.0)
                continue
            if fmt == 4:
                comps.append(struct.unpack(">f", b)[0])
            else:
                comps.append(int.from_bytes(b, "big", signed=signed) / scale)
        out.append(tuple(comps))
    return out


def _vertex_layout(setting: int) -> dict:
    sizes = []
    for j in range(13):
        v = (setting >> (j * 2)) & 3
        sizes.append({0: 0, 1: 0, 2: 1, 3: 2}[v])
    offs = [sum(sizes[:k]) for k in range(13)]
    return {"stride": sum(sizes), "pos": (offs[1], sizes[1]), "norm": (offs[2], sizes[2]), "uv": (offs[5], sizes[5])}


def _read_idx(v: bytes, spec: tuple) -> int | None:
    off, size = spec
    return int.from_bytes(v[off:off + size], "big") if size else None


def _primitives(data: bytes, off: int, length: int, layout: dict) -> list[tuple]:
    tris = []
    end = off + length
    p = off
    stride = layout["stride"]
    while p < end:
        cmd = data[p]
        p += 1
        if cmd == 0x61:
            p += 4
            continue
        if cmd == 0x00:
            continue
        kind = cmd >> 3
        if kind not in (0x10, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17) or stride == 0:
            break  # unknown command: stop rather than mis-parse
        n = struct.unpack_from(">H", data, p)[0]
        p += 2
        verts = []
        for _ in range(n):
            v = data[p:p + stride]
            p += stride
            verts.append((_read_idx(v, layout["pos"]), _read_idx(v, layout["norm"]), _read_idx(v, layout["uv"])))
        if kind == 0x10:
            for i in range(0, len(verts) - 3, 4):
                a, b, c, d = verts[i:i + 4]
                tris += [(a, b, c), (c, d, a)]
        elif kind == 0x12:
            for i in range(0, len(verts) - 2, 3):
                tris.append(tuple(verts[i:i + 3]))
        elif kind == 0x13:
            for i in range(len(verts) - 2):
                a, b, c = verts[i:i + 3]
                tris.append((a, b, c) if i % 2 == 0 else (c, b, a))
        elif kind == 0x14:
            for i in range(1, len(verts) - 1):
                tris.append((verts[0], verts[i], verts[i + 1]))
        # lines / points: ignored
    return tris


def parse_geopalette(data: bytes, base: int) -> Model | None:
    if base + 20 > len(data):
        return None
    version, _uds, _pud, ndesc, pdesc = struct.unpack_from(">IIIII", data, base)
    if version != GEOPALETTE_VERSION or ndesc == 0 or ndesc > 512:
        return None
    meshes = []
    for i in range(ndesc):
        pobj, pname = struct.unpack_from(">II", data, base + pdesc + i * 8)
        name = _cstr(data, base + pname) if pname else f"mesh{i}"
        dol = base + pobj
        ppos, pcol, ptex, plight, pdisp, ntex = struct.unpack_from(">IIIIIB", data, dol)
        positions = normals = uvs = []
        tpl_names = []
        if ppos:
            a, cnt, q, nc = struct.unpack_from(">IHBB", data, dol + ppos)
            positions = _array(data, dol + a, cnt, q, nc, 3)
        if plight:
            a, cnt, q, nc = struct.unpack_from(">IHBB", data, dol + plight)
            normals = _array(data, dol + a, cnt, q, nc, 3)
        if ptex:
            for t in range(ntex):
                a, cnt, q, nc, pn, _pp = struct.unpack_from(">IHBBII", data, dol + ptex + t * 16)
                if pn and dol + pn < len(data):
                    nm = _cstr(data, dol + pn)
                    if nm and nm.isprintable() and nm.isascii():
                        tpl_names.append(nm)
                if t == 0:
                    uvs = _array(data, dol + a, cnt, q, nc, 2)
        draws = []
        if pdisp:
            pbank, pstates, nstates = struct.unpack_from(">IIH", data, dol + pdisp)
            layout = None
            tex = None
            mtx = None
            for s in range(nstates):
                sid, setting, plist, blen = struct.unpack_from(">BxxxIII", data, dol + pstates + s * 16)
                if sid == 1:
                    if (setting >> 16) & 0xFF == 0x11:
                        tex = setting & 0xFF
                elif sid == 2:
                    layout = _vertex_layout(setting)
                elif sid == 3:
                    mtx = (setting >> 16, setting & 0xFFFF)
                if plist and layout:
                    tris = _primitives(data, dol + plist, blen, layout)
                    if tris:
                        draws.append(Draw(tex, tris, mtx))
        meshes.append(Mesh(name, positions, normals, uvs, draws, tpl_names))
    return Model(meshes)


# ------------------------------------------------------------------ OBJ --

def to_obj(model: Model, mtl_name: str | None = None) -> str:
    lines = []
    if mtl_name:
        lines.append(f"mtllib {mtl_name}")
    vbase = nbase = tbase = 0
    for m in model.meshes:
        lines.append(f"o {m.name}")
        for x, y, z in m.positions:
            lines.append(f"v {x} {y} {z}")
        for x, y, z in m.normals:
            lines.append(f"vn {x} {y} {z}")
        for u, v in m.uvs:
            lines.append(f"vt {u} {1 - v}")
        for k, d in enumerate(m.draws):
            lines.append(f"g {m.name}_{k}")
            if d.texture is not None:
                lines.append(f"usemtl tex{d.texture}")
            for tri in d.tris:
                parts = []
                for p, n, t in tri:
                    if p is None:
                        break
                    s = str(p + 1 + vbase)
                    if t is not None or n is not None:
                        s += "/" + (str(t + 1 + tbase) if t is not None else "")
                    if n is not None:
                        s += "/" + str(n + 1 + nbase)
                    parts.append(s)
                if len(parts) == 3:
                    lines.append("f " + " ".join(parts))
        vbase += len(m.positions)
        nbase += len(m.normals)
        tbase += len(m.uvs)
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- glTF --

def to_glb(model: Model, textures: dict[int, bytes] | None = None, bones: list | None = None,
           skin_weights: dict | None = None, banks: list | None = None) -> bytes:
    """Build a binary glTF 2.0 with one primitive per draw and embedded PNG textures.

    With `bones` (from `parse_actor`, unposed model) the file carries the
    skeleton as a node hierarchy: rigid meshes hang from their bone, the
    skinned mesh (per-vertex `skin_weights`, bone indices in pre-order, see
    anim.py) gets a glTF skin, and each (label, Bank) in `banks` becomes a set
    of glTF animations named "label / sequence". Without bones the meshes are
    exported flat, as `apply_actor` left them."""
    textures = textures or {}
    bufs = bytearray()
    views = []
    accessors = []
    meshes = []
    nodes = []
    images = []
    gtextures = []
    materials = []
    mat_for_tex: dict[int | None, int] = {}

    def add_view(blob: bytes, target: int | None = None) -> int:
        while len(bufs) % 4:
            bufs.append(0)
        views.append({"buffer": 0, "byteOffset": len(bufs), "byteLength": len(blob), **({"target": target} if target else {})})
        bufs.extend(blob)
        return len(views) - 1

    def add_accessor(view: int, count: int, ctype: int, atype: str, mn=None, mx=None) -> int:
        acc = {"bufferView": view, "componentType": ctype, "count": count, "type": atype}
        if mn is not None:
            acc["min"], acc["max"] = mn, mx
        accessors.append(acc)
        return len(accessors) - 1

    def material(tex: int | None) -> int:
        if tex in mat_for_tex:
            return mat_for_tex[tex]
        mat = {"name": f"tex{tex}" if tex is not None else "untextured", "doubleSided": True,
               "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0}}
        if tex is not None and tex in textures:
            view = add_view(textures[tex])
            images.append({"bufferView": view, "mimeType": "image/png"})
            gtextures.append({"source": len(images) - 1, "sampler": 0})
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(gtextures) - 1}
            mat["alphaMode"] = "MASK"
            mat["alphaCutoff"] = 0.5
        materials.append(mat)
        mat_for_tex[tex] = len(materials) - 1
        return mat_for_tex[tex]

    skinned_mesh = None
    if bones and skin_weights:
        attached = {b.geo for b in bones if b.geo is not None}
        skinned_mesh = next((i for i, m in enumerate(model.meshes) if i not in attached and m.positions), None)
    mesh_node_of: dict[int, int] = {}
    for mi, m in enumerate(model.meshes):
        prims = []
        for d in m.draws:
            vmap: dict[tuple, int] = {}
            pos, nrm, uv, idx = [], [], [], []
            joints, weights = [], []
            has_n = any(v[1] is not None for tri in d.tris for v in tri) and m.normals
            has_t = any(v[2] is not None for tri in d.tris for v in tri) and m.uvs
            for tri in d.tris:
                for key in tri:
                    if key[0] is None or key[0] >= len(m.positions):
                        idx.append(0)
                        continue
                    if key not in vmap:
                        vmap[key] = len(pos)
                        pos.append(m.positions[key[0]])
                        if mi == skinned_mesh:
                            ws = (skin_weights.get(key[0]) or [(0, 1.0)])[:4]
                            ws += [(0, 0.0)] * (4 - len(ws))
                            joints.append([b for b, _ in ws])
                            weights.append([w for _, w in ws])
                        if has_n:
                            n = m.normals[key[1]] if key[1] is not None and key[1] < len(m.normals) else (0.0, 1.0, 0.0)
                            nrm.append(n)
                        if has_t:
                            t = m.uvs[key[2]] if key[2] is not None and key[2] < len(m.uvs) else (0.0, 0.0)
                            uv.append(t)
                    idx.append(vmap[key])
            if not pos:
                continue
            pblob = b"".join(struct.pack("<fff", *p) for p in pos)
            mn = [min(p[i] for p in pos) for i in range(3)]
            mx = [max(p[i] for p in pos) for i in range(3)]
            attrs = {"POSITION": add_accessor(add_view(pblob, 34962), len(pos), 5126, "VEC3", mn, mx)}
            if has_n:
                attrs["NORMAL"] = add_accessor(add_view(b"".join(struct.pack("<fff", *_unit(n)) for n in nrm), 34962), len(nrm), 5126, "VEC3")
            if has_t:
                attrs["TEXCOORD_0"] = add_accessor(add_view(b"".join(struct.pack("<ff", *t) for t in uv), 34962), len(uv), 5126, "VEC2")
            if mi == skinned_mesh:
                attrs["JOINTS_0"] = add_accessor(add_view(b"".join(struct.pack("<4H", *j) for j in joints), 34962), len(joints), 5123, "VEC4")
                attrs["WEIGHTS_0"] = add_accessor(add_view(b"".join(struct.pack("<4f", *w) for w in weights), 34962), len(weights), 5126, "VEC4")
            iblob = b"".join(struct.pack("<I", i) for i in idx)
            prims.append({"attributes": attrs, "indices": add_accessor(add_view(iblob, 34963), len(idx), 5125, "SCALAR"),
                          "material": material(d.texture), "mode": 4})
        if prims:
            meshes.append({"name": m.name, "primitives": prims})
            nodes.append({"mesh": len(meshes) - 1, "name": m.name})
            mesh_node_of[mi] = len(nodes) - 1

    scene_nodes = list(range(len(nodes)))
    skins = []
    animations = []
    if bones:
        scene_nodes, skins, animations = _rig(nodes, bones, mesh_node_of, skinned_mesh, banks or [],
                                              add_view, add_accessor)
    doc = {"asset": {"version": "2.0", "generator": "zzzzdat"}, "scene": 0,
           "scenes": [{"nodes": scene_nodes}], "nodes": nodes, "meshes": meshes,
           "materials": materials, "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(bufs)}],
           "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]}
    if skins:
        doc["skins"] = skins
    if animations:
        doc["animations"] = animations
    if images:
        doc["images"] = images
        doc["textures"] = gtextures
    js = json.dumps(doc, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    while len(bufs) % 4:
        bufs.append(0)
    total = 12 + 8 + len(js) + 8 + len(bufs)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(js)) + b"JSON" + js
            + struct.pack("<I", len(bufs)) + b"BIN\0" + bytes(bufs))


def _rig(nodes: list, bones: list, mesh_node_of: dict, skinned_mesh, banks: list, add_view, add_accessor):
    """Append bone nodes (and a root that turns the actor upright) to `nodes`;
    return (scene root nodes, skins, animations). Bone node order is the
    pre-order traversal so skin joint indices need no remapping."""
    from .anim import FRAME_RATE, bone_order
    order = bone_order(bones)
    node_of: dict[int, int] = {}   # bone offset -> node index
    for b in order:
        node_of[b.offset] = len(nodes)
        nodes.append({"name": f"bone{b.id}", "translation": list(b.trans), "rotation": list(b.quat),
                      "scale": list(b.scale), "children": []})
    for b in order:
        pb = node_of.get(b.parent) if b.parent else None
        if pb is not None and b.inherit:
            nodes[pb]["children"].append(node_of[b.offset])
    flip = len(nodes)
    nodes.append({"name": "actor", "rotation": [1.0, 0.0, 0.0, 0.0], "children": []})  # 180 deg about X
    for b in order:
        pb = node_of.get(b.parent) if b.parent else None
        if pb is None or not b.inherit:
            nodes[flip]["children"].append(node_of[b.offset])
    for mi, ni in mesh_node_of.items():
        owner = next((b for b in order if b.geo == mi), None)
        if owner and mi != skinned_mesh:
            nodes[node_of[owner.offset]]["children"].append(ni)
        else:
            nodes[flip]["children"].append(ni)
    for n in nodes:
        if "children" in n and not n["children"]:
            del n["children"]
    skins = []
    if skinned_mesh is not None and skinned_mesh in mesh_node_of:
        ibm = b"".join(_mtx_column_major(_invert(b.world)) for b in order)
        skins.append({"joints": [node_of[b.offset] for b in order], "skeleton": flip,
                      "inverseBindMatrices": add_accessor(add_view(ibm), len(order), 5126, "MAT4")})
        nodes[mesh_node_of[skinned_mesh]]["skin"] = 0
    by_id = {b.id: b for b in bones}
    animations = []
    for label, bank in banks:
        for seq in bank.sequences:
            samplers, channels = [], []
            for tr in seq.tracks:
                b = by_id.get(tr.bone)
                if b is None or not tr.keys:
                    continue
                times = b"".join(struct.pack("<f", k.time / FRAME_RATE) for k in tr.keys)
                tacc = add_accessor(add_view(times), len(tr.keys), 5126, "SCALAR",
                                    [tr.keys[0].time / FRAME_RATE], [tr.keys[-1].time / FRAME_RATE])
                if tr.keys[0].quat is not None:
                    q = b"".join(struct.pack("<4f", *(k.quat or (0, 0, 0, 1))) for k in tr.keys)
                    samplers.append({"input": tacc, "output": add_accessor(add_view(q), len(tr.keys), 5126, "VEC4"),
                                     "interpolation": "STEP" if tr.quat_step else "LINEAR"})
                    channels.append({"sampler": len(samplers) - 1, "target": {"node": node_of[b.offset], "path": "rotation"}})
                if tr.keys[0].trans is not None:
                    t = b"".join(struct.pack("<3f", *(k.trans or (0, 0, 0))) for k in tr.keys)
                    samplers.append({"input": tacc, "output": add_accessor(add_view(t), len(tr.keys), 5126, "VEC3"),
                                     "interpolation": "STEP" if tr.trans_step else "LINEAR"})
                    channels.append({"sampler": len(samplers) - 1, "target": {"node": node_of[b.offset], "path": "translation"}})
            if channels:
                animations.append({"name": f"{label} / {seq.name}" if label else seq.name, "samplers": samplers, "channels": channels})
    return [flip], skins, animations


def _mtx_column_major(m: list) -> bytes:
    return b"".join(struct.pack("<f", m[r][c]) for c in range(4) for r in range(4))


def _invert(m: list) -> list:
    """Inverse of an affine 4x4 (rows = [R|t] and [0 0 0 1])."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-12:
        return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    inv = [[(a[1][1] * a[2][2] - a[1][2] * a[2][1]) / det, (a[0][2] * a[2][1] - a[0][1] * a[2][2]) / det, (a[0][1] * a[1][2] - a[0][2] * a[1][1]) / det],
           [(a[1][2] * a[2][0] - a[1][0] * a[2][2]) / det, (a[0][0] * a[2][2] - a[0][2] * a[2][0]) / det, (a[0][2] * a[1][0] - a[0][0] * a[1][2]) / det],
           [(a[1][0] * a[2][1] - a[1][1] * a[2][0]) / det, (a[0][1] * a[2][0] - a[0][0] * a[2][1]) / det, (a[0][0] * a[1][1] - a[0][1] * a[1][0]) / det]]
    t = [m[r][3] for r in range(3)]
    out = [inv[r] + [-sum(inv[r][k] * t[k] for k in range(3))] for r in range(3)]
    out.append([0.0, 0.0, 0.0, 1.0])
    return out


def _unit(n):
    x, y, z = n
    l = (x * x + y * y + z * z) ** 0.5
    return (x / l, y / l, z / l) if l > 1e-9 else (0.0, 1.0, 0.0)


# ---------------------------------------------------------------- actors --
# ACT (actor) sections share the 0x007B7960 version word with ANIM banks.
# Layout (Nintendo CharPipeline ACTLayout, offsets relative to the section):
#   0x00 version  0x04 u16 actorID, u16 totalBones  0x08 DSTree{offset 0xc, root 0x20}
#   0x10 geoPalette id  0x14 u16 skinFileID ...  bones from 0x20, 0x1c each:
#   u32 pControl, DSBranch{prev,next,parent,children}, u16 geoFileID (0xffff = none),
#   u16 boneID, u8 inheritanceFlag, u8 drawingPriority
# CTRLControl (0x34): u8 type flags (1 scale, 2 euler, 4 quat, 8 translation),
#   pad[3], Vec scale, Quaternion (x,y,z,w), Vec translation, pad.

ACT_VERSION = 0x007B7960


@dataclass
class Bone:
    offset: int
    id: int
    parent: int  # offset, 0 = root
    geo: int | None
    inherit: bool
    scale: tuple
    quat: tuple
    trans: tuple
    world: list | None = None
    children: int = 0  # offset of the first child (DSBranch), 0 = none
    next: int = 0      # offset of the next sibling, 0 = none


def is_actor(data: bytes, base: int) -> bool:
    if base + 0x20 > len(data):
        return False
    v, _a, off, root = struct.unpack_from(">IIII", data, base)
    return v == ACT_VERSION and off == 0xC and root == 0x20


def parse_actor(data: bytes, base: int) -> list[Bone] | None:
    if not is_actor(data, base):
        return None
    nb = struct.unpack_from(">H", data, base + 6)[0]
    bones = []
    for i in range(nb):
        off = 0x20 + i * 0x1C
        ctrl, _prev, nxt, parent, child, geo, bid, inh, _prio = struct.unpack_from(">IIIIIHHBB", data, base + off)
        typ = data[base + ctrl]
        scale = struct.unpack_from(">3f", data, base + ctrl + 4)
        quat = struct.unpack_from(">4f", data, base + ctrl + 16)
        trans = struct.unpack_from(">3f", data, base + ctrl + 32)
        if not typ & 1:
            scale = (1.0, 1.0, 1.0)
        if not typ & 4:
            quat = (0.0, 0.0, 0.0, 1.0)
        if not typ & 8:
            trans = (0.0, 0.0, 0.0)
        bones.append(Bone(off, bid, parent, None if geo == 0xFFFF else geo, bool(inh), scale, quat, trans,
                          children=child, next=nxt))
    _compute_world(bones)
    return bones


def _srt(b: Bone) -> list:
    x, y, z, w = b.quat
    sx, sy, sz = b.scale
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    m = [[r[i][0] * sx, r[i][1] * sy, r[i][2] * sz, b.trans[i]] for i in range(3)]
    m.append([0.0, 0.0, 0.0, 1.0])
    return m


def _mul(a: list, b: list) -> list:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _compute_world(bones: list[Bone]) -> None:
    by_off = {b.offset: b for b in bones}

    def world(b: Bone) -> list:
        if b.world is None:
            local = _srt(b)
            p = by_off.get(b.parent) if b.parent else None
            b.world = _mul(world(p), local) if (p and b.inherit) else local
        return b.world

    for b in bones:
        world(b)


def skeleton_root(bones: list[Bone]) -> Bone | None:
    """The root bone that actually carries the hierarchy (has children)."""
    parents = {b.parent for b in bones if b.parent}
    roots = [b for b in bones if not b.parent]
    for r in roots:
        if r.offset in parents:
            return r
    return roots[0] if roots else None


def apply_actor(model: "Model", bones: list[Bone]) -> None:
    """Move each mesh into actor space using its bone's world matrix. Meshes no
    bone points at (skinned bodies such as mario_body) are already stored in
    actor space and are left alone."""
    for i, m in enumerate(model.meshes):
        b = next((b for b in bones if b.geo == i), None)
        if b:
            w = b.world
            m.positions = [_xform(w, p, 1.0) for p in m.positions]
            m.normals = [_unit(_xform(w, n, 0.0)) for n in m.normals]
        # actor space has the character standing along -Y; turn it upright
        # (180 degrees about X keeps the winding intact)
        m.positions = [(x, -y, -z) for x, y, z in m.positions]
        m.normals = [(x, -y, -z) for x, y, z in m.normals]


def _xform(m: list, v: tuple, w: float) -> tuple:
    x, y, z = v
    return tuple(m[i][0] * x + m[i][1] * y + m[i][2] * z + m[i][3] * w for i in range(3))
