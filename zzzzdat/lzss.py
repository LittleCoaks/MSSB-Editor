"""Bit-stream LZSS used by Mario Superstar Baseball's .dat archives.

Same scheme as the repo's top-level decompress.py (kept behaviour-identical,
just faster). The stream is a sequence of big-endian 32-bit words. Fields are
read from the low end of a bit buffer:

    1 bit  flag      1 = literal, 0 = back-reference
    8 bits literal   (flag == 1)
    L bits distance  (flag == 0)  copy from  out[-1 - distance]
    R bits length    (flag == 0)  copy  length + 2  bytes

When a field does not fit in the remaining bits, the leftover bits become the
HIGH part of the value and the low part is taken from the next word - so this
is *not* a plain LSB-first stream, and the refill has to be lazy.

L (lookback bits) and R (repetition bits) come from the entry descriptor:
0x040b means R = 4, L = 11; 0x050e means R = 5, L = 14.
"""
from __future__ import annotations


class BitReader:
    __slots__ = ("data", "pos", "buf", "nbits", "end")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.buf = 0
        self.nbits = 0
        self.end = len(data) - 3

    def read(self, count: int) -> int:
        if count <= self.nbits:
            value = self.buf & ((1 << count) - 1)
            self.buf >>= count
            self.nbits -= count
            return value
        if self.pos >= self.end:
            raise ValueError("compressed stream ended early")
        word = int.from_bytes(self.data[self.pos:self.pos + 4], "big")
        self.pos += 4
        need = count - self.nbits
        value = (self.buf << need) | (word & ((1 << need) - 1))
        self.buf = word >> need
        self.nbits = 32 - need
        return value

    def exhausted(self) -> bool:
        return self.pos >= self.end and self.buf == 0


def decompress(data: bytes, lookback_bits: int, repeat_bits: int, out_size: int | None) -> bytearray:
    return decompress_ex(data, lookback_bits, repeat_bits, out_size)[0]


def decompress_ex(data: bytes, lookback_bits: int, repeat_bits: int, out_size: int | None,
                  max_out: int = 1 << 28, tolerant: bool = False) -> tuple[bytearray, int]:
    """Decompress and also return how many input bytes were consumed.

    With out_size None the stream is read until the input is exhausted (or,
    when tolerant, until it becomes invalid), which is how sizes of files no
    descriptor references are recovered.
    """
    if lookback_bits == 0 and repeat_bits == 0:
        o = bytearray(data if out_size is None else data[:out_size])
        return o, len(o)

    out = bytearray()
    append = out.append
    rd = BitReader(data)
    read = rd.read
    limit = out_size if out_size is not None else max_out

    try:
        while len(out) < limit:
            if out_size is None and rd.exhausted():
                break
            if read(1):
                append(read(8))
            else:
                dist = read(lookback_bits)
                length = read(repeat_bits) + 2
                n = len(out)
                if dist >= n:
                    raise ValueError(f"bad back-reference: distance {dist} at output {n}")
                src = n - 1 - dist
                if dist + 1 >= length:
                    out += out[src:src + length]
                else:  # overlapping run: byte-wise copy
                    for _ in range(length):
                        append(out[src])
                        src += 1
    except ValueError:
        if not tolerant:
            raise
    if out_size is not None:
        del out[out_size:]
    return out, rd.pos


# ------------------------------------------------------------- compressor --

class BitWriter:
    """Mirror image of BitReader: fills 32-bit words from the low end, and when
    a field straddles a word boundary its HIGH part goes into the old word's
    remaining top bits and its LOW part starts the next word."""
    __slots__ = ("out", "buf", "nbits")

    def __init__(self):
        self.out = bytearray()
        self.buf = 0
        self.nbits = 0

    def write(self, value: int, count: int) -> None:
        space = 32 - self.nbits
        if count <= space:
            self.buf |= value << self.nbits
            self.nbits += count
            if self.nbits == 32:
                self._flush()
        else:
            low = count - space
            self.buf |= (value >> low) << self.nbits
            self.nbits = 32
            self._flush()
            self.buf = value & ((1 << low) - 1)
            self.nbits = low

    def _flush(self) -> None:
        self.out += self.buf.to_bytes(4, "big")
        self.buf = 0
        self.nbits = 0

    def finish(self, align: int = 32) -> bytes:
        if self.nbits:
            self._flush()
        if align:
            while len(self.out) % align:
                self.out.append(0)
        return bytes(self.out)


def compress(data: bytes, lookback_bits: int = 0xB, repeat_bits: int = 4, align: int = 32) -> bytes:
    """Encode with the game's LZSS. Greedy longest-match with a hash chain;
    output decodes byte-for-byte with `decompress` (that is the only contract
    the game needs). Distances are stored as distance-1, lengths as length-2."""
    raw = bytes(data)
    n = len(raw)
    bw = BitWriter()
    if n == 0:
        return bw.finish(align)
    max_dist = 1 << lookback_bits
    max_len = (1 << repeat_bits) - 1 + 2
    head: dict[int, int] = {}
    prev = [-1] * n
    pos = 0

    def insert(p: int) -> None:
        if p + 1 < n:
            h = (raw[p] << 8) | raw[p + 1]
            prev[p] = head.get(h, -1)
            head[h] = p

    def find(pos: int) -> tuple[int, int]:
        limit = min(max_len, n - pos)
        best_len = 0
        best_dist = 0
        if limit >= 2 and pos + 1 < n:
            win = max(0, pos - max_dist)
            p = head.get((raw[pos] << 8) | raw[pos + 1], -1)
            depth = 0
            while p >= win and depth < 256:
                l = 2
                while l < limit and raw[p + l] == raw[pos + l]:
                    l += 1
                if l > best_len:
                    best_len, best_dist = l, pos - p
                    if l == limit:
                        break
                p = prev[p]
                depth += 1
        return best_len, best_dist

    while pos < n:
        best_len, best_dist = find(pos)
        if best_len >= 2 and pos + 1 < n:
            # lazy matching: a literal now may enable a longer match next byte
            nl, _ = find(pos + 1)
            if nl > best_len:
                best_len = 0
        if best_len >= 2:
            bw.write(0, 1)
            bw.write(best_dist - 1, lookback_bits)
            bw.write(best_len - 2, repeat_bits)
            for i in range(best_len):
                insert(pos + i)
            pos += best_len
        else:
            bw.write(1, 1)
            bw.write(raw[pos], 8)
            insert(pos)
            pos += 1
    return bw.finish(align)
