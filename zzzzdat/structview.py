"""Guesses about a file nothing else recognises, for the Data tab.

A table of fixed-size records repeats itself every `stride` bytes: the byte
at i often equals the byte at i + stride (zero padding, small counts, the
high bytes of similar values). `guess_stride` scores that agreement for a
range of strides against the chance level and returns the best few, so the
viewer can lay the bytes out in rows that line the fields up. `column_kinds`
then looks down each column of the chosen stride and says whether it reads
best as floats, shorts or bytes, which is the whole of what can be said
about a table without the code that reads it.
"""
from __future__ import annotations

import struct

SAMPLE = 1 << 16


def _agreement(data: bytes, stride: int) -> float:
    n = min(len(data) - stride, SAMPLE)
    if n <= 0:
        return 0.0
    a = data[:n]
    b = data[stride:stride + n]
    same = sum(1 for x, y in zip(a, b) if x == y)
    return same / n


def guess_stride(data: bytes, limit: int = 5) -> list[dict]:
    """The strides the bytes repeat at, best first: {stride, score} with the
    score the agreement above chance (0 = none, 1 = every byte repeats)."""
    if len(data) < 32:
        return []
    base = _agreement(data, 1)  # runs of equal bytes inflate every stride alike
    zero = data[:SAMPLE].count(0) / min(len(data), SAMPLE)
    chance = max(zero * zero, base * 0.5)
    cands = sorted({s for s in range(2, 65) if s % 2 == 0} | {s for s in range(64, 1025, 4)} | {2, 3, 6})
    scored = []
    for s in cands:
        if s * 2 > len(data):
            break
        a = _agreement(data, s)
        scored.append({"stride": s, "score": round(max(0.0, (a - chance) / max(1e-6, 1 - chance)), 3)})
    if not scored:
        return []
    # a table's stride and its multiples score alike: prefer the shortest
    top = max(d["score"] for d in scored)
    scored.sort(key=lambda d: (d["score"] < top - 0.05, d["stride"] if d["score"] >= top - 0.05 else -d["score"]))
    out: list[dict] = []
    for d in scored:
        # a multiple of a stride already listed repeats for the same reason
        if any(d["stride"] % o["stride"] == 0 and d["score"] <= o["score"] + 0.02 for o in out):
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def _float_ok(v: float) -> bool:
    return v == 0.0 or 1e-6 <= abs(v) <= 1e7


def column_kinds(data: bytes, stride: int, rows: int = 256) -> list[str]:
    """For every 4-byte column of the stride: "f32" when the column reads as
    plausible floats in nearly every row, "s16" when as two shorts of small
    magnitude, else "u8"."""
    if stride < 4 or stride % 4 or len(data) < stride:
        return []
    n = min(rows, len(data) // stride)
    kinds = []
    for c in range(0, stride, 4):
        fl = sh = nz = 0
        for r in range(n):
            o = r * stride + c
            v = struct.unpack_from(">f", data, o)[0]
            if _float_ok(v) and v == v:
                fl += 1
                nz += v != 0.0
            a, b = struct.unpack_from(">hh", data, o)
            if abs(a) < 4096 and abs(b) < 4096:
                sh += 1
        if n and fl >= n * 0.97 and nz >= n * 0.25:
            kinds.append("f32")
        elif n and sh >= n * 0.9:
            kinds.append("s16")
        else:
            kinds.append("u8")
    return kinds


def describe(data: bytes) -> dict:
    strides = guess_stride(data)
    best = strides[0]["stride"] if strides and strides[0]["score"] >= 0.15 else 16
    if best % 4:
        best = 16
    return {"size": len(data), "strides": strides, "stride": best, "columns": column_kinds(data, best)}
