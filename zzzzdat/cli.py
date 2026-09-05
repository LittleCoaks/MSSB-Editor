"""Command line interface: python -m zzzzdat <command> ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .descriptors import coverage
from .store import EXTRACT_DIR, Store


def fmt_size(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f}M"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f}K"
    return str(n)


def cmd_index(a):
    store = Store()
    store.rebuild_index(verify=not a.no_verify, classify=not a.no_classify, scan=not a.no_scan)


def cmd_list(a):
    store = Store()
    ents = store.entries if a.all else store.zzzz_entries()
    if a.kind:
        ents = [e for e in ents if e.kind == a.kind]
    if a.module:
        ents = [e for e in ents if e.module == a.module]
    if a.grep:
        g = a.grep.lower()
        ents = [e for e in ents if g in e.symbol.lower() or g in e.name or g in e.known.lower()
                or any(g in n.lower() for n in e.names)]
    print(f"{'id':>5} {'offset':>10} {'size':>8} {'disc':>8} {'c':1} {'kind':10} {'tex':>4} {'label':22} symbol")
    for e in ents:
        print(f"{e.id:5d} {e.offset:#10x} {fmt_size(e.size):>8} {fmt_size(e.disc_size):>8} "
              f"{'z' if e.compressed else '-'} {e.kind:10} {e.ntex:4d} {(e.known or e.label):22} {e.symbol}")
    print(f"{len(ents)} entries")


def cmd_info(a):
    store = Store()
    e = store.get(a.entry)
    print(f"entry {e.id}  {e.archive} @ {e.offset:#x}  disc {e.disc_size:#x}  size {e.size:#x}  "
          f"{'LZSS L=%d R=%d' % (e.lookback_bits, e.repeat_bits) if e.compressed else 'stored'}")
    print("kind:", e.kind)
    if e.known:
        print("known as:", e.known)
    if e.names:
        print("names:", ", ".join(e.names))
    for r in e.refs:
        print("  ref:", r)
    fi = store.info(e)
    if fi.hvqm4:
        for k, v in fi.hvqm4.items():
            print(f"  {k}: {v}")
    for s in fi.sections:
        print(f"  section {s.index:2d} @ {s.offset:#8x} size {s.size:#8x} magic {s.magic:#010x} {s.kind}"
              + (f" ({len(s.textures)} textures)" if s.textures else ""))
    for n, (sec, t) in enumerate(fi.all_textures()):
        if n >= a.max_textures:
            print(f"  ... {len(fi.all_textures()) - n} more textures")
            break
        print(f"  tex {n:3d}: {t.width}x{t.height} {t.fmt_name} mips={t.mips} @ {t.abs_data_offset:#x}"
              + (f" tlut {t.tlut_count}x{t.tlut_fmt}" if t.tlut_count else ""))


def cmd_hexdump(a):
    store = Store()
    e = store.get(a.entry)
    data = store.raw(e) if a.raw else store.data(e)
    off = a.offset
    end = min(len(data), off + a.length)
    while off < end:
        row = data[off:min(off + 16, end)]
        print(f"{off:08x}  {row.hex(' '):47}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in row)}")
        off += 16


def cmd_extract(a):
    store = Store()
    dest = Path(a.out) if a.out else EXTRACT_DIR
    for name in a.entries:
        e = store.get(name)
        for p in store.extract(e, dest, raw=a.raw, png=a.png):
            print(p)


def cmd_extract_all(a):
    store = Store()
    dest = Path(a.out) if a.out else EXTRACT_DIR
    ents = store.zzzz_entries()
    if a.kind:
        ents = [e for e in ents if e.kind == a.kind]
    n = 0
    for e in ents:
        if e.size > a.max_size:
            print(f"skip {e.id} ({fmt_size(e.size)})")
            continue
        try:
            store.extract(e, dest, raw=a.raw, png=a.png)
            n += 1
        except Exception as ex:
            print(f"entry {e.id}: {ex}", file=sys.stderr)
    print(f"extracted {n} entries to {dest}")


def cmd_textures(a):
    store = Store()
    e = store.get(a.entry)
    dest = Path(a.out) if a.out else EXTRACT_DIR / (store.file_name(e).rsplit(".", 1)[0] + "_tex")
    paths = store.extract_textures(e, dest)
    print(f"{len(paths)} textures -> {dest}")


def cmd_layout(a):
    store = Store()
    ents = sorted(store.zzzz_entries(), key=lambda e: e.offset)
    cov = coverage(ents, store.archive.size)
    cur = 0
    for e in ents:
        if e.offset > cur + 0x800:
            print(f"  GAP     {cur:#10x}-{e.offset:#10x} {fmt_size(e.offset - cur):>8}")
        print(f"  {e.id:5d} {e.offset:#10x}-{e.end:#10x} {fmt_size(e.disc_size):>8} {e.kind:10} {e.symbol}")
        cur = max(cur, e.end)
    if cur < store.archive.size:
        print(f"  GAP     {cur:#10x}-{store.archive.size:#10x} {fmt_size(store.archive.size - cur):>8}")
    print(f"covered {cov['covered'] / 1e6:.1f} MB of {store.archive.size / 1e6:.1f} MB; "
          f"{cov['gaps']} gaps totalling {cov['gap_bytes'] / 1e6:.1f} MB")


def cmd_serve(a):
    from .server import serve
    serve(a.port, open_browser=not a.no_browser)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="zzzzdat", description="Browse, view and extract MSSB's ZZZZ.dat")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("index", help="(re)build index/GYQE01.json by scanning the game executables")
    s.add_argument("--no-verify", action="store_true", help="skip decode verification (faster, noisier)")
    s.add_argument("--no-classify", action="store_true", help="skip content classification")
    s.add_argument("--no-scan", action="store_true", help="skip the AdGCForm and brute-force gap scans")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("list", help="list entries")
    s.add_argument("--kind")
    s.add_argument("--module", help="dol, game, menus or debug")
    s.add_argument("--grep", help="substring of symbol/name")
    s.add_argument("--all", action="store_true", help="include the aaaa.dat REL entries")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("info", help="details for one entry")
    s.add_argument("entry")
    s.add_argument("--max-textures", type=int, default=40)
    s.set_defaults(fn=cmd_info)

    s = sub.add_parser("hexdump", help="hex dump of an entry's (decompressed) contents")
    s.add_argument("entry")
    s.add_argument("--offset", type=lambda v: int(v, 0), default=0)
    s.add_argument("--length", type=lambda v: int(v, 0), default=0x100)
    s.add_argument("--raw", action="store_true", help="dump the on-disc bytes instead")
    s.set_defaults(fn=cmd_hexdump)

    s = sub.add_parser("extract", help="extract one or more entries")
    s.add_argument("entries", nargs="+")
    s.add_argument("-o", "--out")
    s.add_argument("--raw", action="store_true", help="write the compressed on-disc bytes")
    s.add_argument("--png", action="store_true", help="also decode textures to PNG")
    s.set_defaults(fn=cmd_extract)

    s = sub.add_parser("extract-all", help="extract every indexed entry")
    s.add_argument("-o", "--out")
    s.add_argument("--kind")
    s.add_argument("--raw", action="store_true")
    s.add_argument("--png", action="store_true")
    s.add_argument("--max-size", type=lambda v: int(v, 0), default=1 << 30)
    s.set_defaults(fn=cmd_extract_all)

    s = sub.add_parser("textures", help="decode an entry's textures to PNG files")
    s.add_argument("entry")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_textures)

    s = sub.add_parser("layout", help="print the archive layout and coverage")
    s.set_defaults(fn=cmd_layout)

    s = sub.add_parser("serve", help="start the web browser UI")
    s.add_argument("--port", type=int, default=8420)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
