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
    if lookback_bits == 0 and repeat_bits == 0:
        return bytearray(data if out_size is None else data[:out_size])

    out = bytearray()
    append = out.append
    rd = BitReader(data)
    read = rd.read
    limit = out_size if out_size is not None else 1 << 62

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
    if out_size is not None:
        del out[out_size:]
    return out
