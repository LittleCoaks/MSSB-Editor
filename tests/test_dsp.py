import math
import struct

from zzzzdat import dsp
from zzzzdat.music import dtkadpcm


def _sine(n, rate=48000, hz=440.0, amp=8000):
    return [int(amp * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)]


def test_dtk_roundtrip_matches_custom_music_encoder():
    """Our DTK decoder must agree with the Custom Music tool's bit-exact decoder
    on frames produced by its encoder, and the result must resemble the input."""
    n = 28 * 200
    left, right = _sine(n), _sine(n, hz=660.0)
    adp = dtkadpcm.encode(left, right)
    ours = dsp.dtk_decode(adp)
    theirs = dtkadpcm.decode(adp)
    l2, r2 = [p[0] for p in theirs], [p[1] for p in theirs]
    got = struct.unpack("<%dh" % (len(ours) // 2), ours)
    assert list(got[0::2][:len(l2)]) == list(l2)
    assert list(got[1::2][:len(r2)]) == list(r2)
    # decoded audio tracks the source within the codec's error
    err = sum(abs(a - b) for a, b in zip(got[0::2], left)) / n
    assert err < 200


def test_dtk_stream_equals_whole():
    n = 28 * 3000
    adp = dtkadpcm.encode(_sine(n), _sine(n, hz=300.0))
    whole = dsp.dtk_wav(adp)
    streamed = b"".join(dsp.dtk_wav_stream(adp, chunk_frames=97))
    assert whole == streamed
    assert len(whole) == dsp.dtk_wav_size(len(adp))


def test_dsp_header_rejects_garbage():
    assert dsp.parse_header(bytes(0x60)) is None
    assert dsp.find_dsp_streams(bytes(4096)) == []


def test_wav_header():
    w = dsp.wav(b"\0\0" * 10, 32000, 1)
    assert w[:4] == b"RIFF" and w[8:12] == b"WAVE"
    assert struct.unpack("<I", w[24:28])[0] == 32000
