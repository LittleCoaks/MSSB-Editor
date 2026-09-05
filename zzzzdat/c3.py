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

quantize: high nibble = component type (1 = s32/f32, 2 = u16, 3 = s16, 4 = u8,
5 = s8), low nibble = fixed-point fraction bits. Display state ids: 1 = texture
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

_QUANT = {1: (4, True), 2: (2, False), 3: (2, True), 4: (1, False), 5: (1, True)}


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
            if fmt == 1 and shift == 0:
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

def to_glb(model: Model, textures: dict[int, bytes] | None = None) -> bytes:
    """Build a binary glTF 2.0 with one primitive per draw and embedded PNG textures."""
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

    for m in model.meshes:
        prims = []
        for d in m.draws:
            vmap: dict[tuple, int] = {}
            pos, nrm, uv, idx = [], [], [], []
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
            iblob = b"".join(struct.pack("<I", i) for i in idx)
            prims.append({"attributes": attrs, "indices": add_accessor(add_view(iblob, 34963), len(idx), 5125, "SCALAR"),
                          "material": material(d.texture), "mode": 4})
        if prims:
            meshes.append({"name": m.name, "primitives": prims})
            nodes.append({"mesh": len(meshes) - 1, "name": m.name})

    doc = {"asset": {"version": "2.0", "generator": "zzzzdat"}, "scene": 0,
           "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
           "materials": materials, "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(bufs)}],
           "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]}
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


def _unit(n):
    x, y, z = n
    l = (x * x + y * y + z * z) ** 0.5
    return (x / l, y / l, z / l) if l > 1e-9 else (0.0, 1.0, 0.0)
