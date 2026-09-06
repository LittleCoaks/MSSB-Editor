"""The index, the catalog and per-entry information."""
from __future__ import annotations

import json

from ...paths import EXTRACT_DIR
from .. import Request, router


def entry_summary(e) -> dict:
    return {"id": e.id, "offset": e.offset, "disc_size": e.disc_size, "size": e.size,
            "compressed": e.compressed, "lookback_bits": e.lookback_bits, "repeat_bits": e.repeat_bits,
            "kind": e.kind, "ntex": e.ntex, "nsec": e.nsec, "naud": e.naud, "thumb": e.thumb,
            "module": e.module, "symbol": e.symbol, "archive": e.archive, "name": e.name, "refs": e.refs,
            "label": e.label, "names": e.names, "known": e.known}


def entry_detail(store, e) -> dict:
    d = entry_summary(e)
    fi = store.info(e)
    d["file_kind"] = fi.kind
    d["hvqm4"] = fi.hvqm4
    d["sections"] = [{"index": s.index, "offset": s.offset, "size": s.size, "kind": s.kind,
                      "magic": s.magic, "ntex": len(s.textures)} for s in fi.sections]
    d["textures"] = [{"n": n, "section": sec.index if sec else None, "index": t.index, "width": t.width,
                      "height": t.height, "fmt": t.fmt_name, "mips": t.mips, "offset": t.abs_data_offset,
                      "size": t.data_size, "tlut": t.tlut_count, "flags": t.flags.hex()}
                     for n, (sec, t) in enumerate(fi.all_textures())]
    d["audio"] = fi.audio
    d["sfx"] = fi.sfx
    d["group"] = fi.group
    d["models"] = store.models(e) if fi.kind == "container" else []
    d["banks"] = store.banks(e) if d["models"] else []
    d["file_name"] = store.file_name(e)
    return d


@router.get(r"/api/index")
def get_index(req: Request):
    st = req.ctx.store
    if st is None:
        return req.json({"meta": {}, "archive": None, "archive_size": 0, "entries": [],
                         "error": req.ctx.store_error or "no game selected"})
    doc = json.loads(st.index_path.read_text(encoding="utf-8")) if st.index_path.exists() else {}
    req.json({"meta": doc.get("meta", {}), "archive": str(st.archive.path), "archive_size": st.archive.size,
              "extract_dir": str(EXTRACT_DIR), "entries": [entry_summary(e) for e in st.entries]})


@router.get(r"/api/catalog")
def get_catalog(req: Request):
    req.ctx.require_store()
    req.json(req.ctx.catalog())


@router.get(r"/api/modified")
def get_modified(req: Request):
    req.json({"ids": req.ctx.require_store().modified_ids()})


@router.get(r"/api/entry/(?P<eid>\d+)")
def get_entry(req: Request, eid: str):
    st = req.ctx.require_store()
    req.json(entry_detail(st, st.get(eid)))


@router.get(r"/api/entry/(?P<eid>\d+)/hex")
def get_hex(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    data = st.raw(e) if req.flag("raw") else st.data(e)
    off = int(req.q("offset", "0"), 0)
    ln = min(int(req.q("length", "4096"), 0), 65536)
    req.json({"offset": off, "total": len(data), "hex": data[off:off + ln].hex()})


@router.get(r"/api/entry/(?P<eid>\d+)/data")
def get_data(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    req.bytes(st.data(e), "application/octet-stream", st.file_name(e))


@router.get(r"/api/entry/(?P<eid>\d+)/raw")
def get_raw(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    req.bytes(st.raw(e), "application/octet-stream", st.file_name(e, "lz" if e.compressed else "bin"))


@router.get(r"/api/entry/(?P<eid>\d+)/section/(?P<n>\d+)")
def get_section(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    s = st.info(e).sections[int(n)]
    req.bytes(st.data(e)[s.offset:s.offset + s.size], "application/octet-stream",
              f"{st.file_name(e).rsplit('.', 1)[0]}_sec{s.index}.bin")


@router.get(r"/api/entry/(?P<eid>\d+)/extract")
def get_extract(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    paths = st.extract(e, EXTRACT_DIR, raw=req.flag("raw"), png=req.flag("png"), wav=req.flag("wav"),
                       model=req.q("model") or None)
    req.json({"written": [str(p) for p in paths]})
