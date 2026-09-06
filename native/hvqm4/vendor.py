"""Re-vendor Tilka's decoder:  python native/hvqm4/vendor.py path/to/h4m_audio_decode.c

Applies the small changes listed at the top of h4m_decoder.c so the decoder
can be driven by hvqm4dec.c. Run it when updating from upstream
(github.com/Tilka/hvqm4).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HEADER = '''/* HVQM4 1.3/1.5 decoder by Tilka (github.com/Tilka/hvqm4), based on the
 * audio decoder by hcs. LGPL v2 or later - see COPYING.LESSER.
 *
 * Changes for MSSB Editor (see hvqm4dec.c for the driver, vendor.py applies them):
 *  - main() became h4m_decode(inpath, wavpath) and returns 0 instead of
 *    printing "Done!";
 *  - decoded frames go to emit_frame(player, display_index) instead of PPM
 *    files under output/;
 *  - the audio decode call that upstream compiles out with "#if 0" is enabled.
 */
'''


def vendor(src: Path, dst: Path) -> None:
    s = src.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    s, n = re.subn(r'int main\(int argc, char \*\*argv\)\n\{\n.*?exit\(EXIT_FAILURE\);\n    \}\n',
                   'int h4m_decode(const char *inpath, const char *wavpath)\n{\n    const char *argv[3] = {"h4m", inpath, wavpath};\n',
                   s, count=1, flags=re.S)
    assert n == 1, "main() not found"
    s, n = re.subn(r'        char name\[50\];\n        sprintf\(name, "output/video_rgb_%u\.ppm", gop_start \+ disp_id\);\n.*?dumpRGB\(player, name\);',
                   '        emit_frame(player, gop_start + disp_id);', s, count=1, flags=re.S)
    assert n == 1, "frame dump not found"
    s = s.replace("static void decode_video(Player *player, FILE *infile, uint32_t gop_start, uint16_t frame_type, uint32_t frame_size)",
                  "static void emit_frame(Player *player, uint32_t index);\nstatic void decode_video(Player *player, FILE *infile, uint32_t gop_start, uint16_t frame_type, uint32_t frame_size)", 1)
    s, n = re.subn(r'#if 0\n(\s+decode_audio\()', r'#if 1\n\1', s, count=1)
    assert n == 1, "audio #if 0 not found"
    s, n = re.subn(r'    printf\("Done!\\n"\);\n\}\n#endif', '    return 0;\n}\n#endif', s, count=1)
    assert n == 1, "end of main not found"
    dst.write_text(HEADER + s, encoding="utf-8", newline="\n")
    print(f"wrote {dst} ({len(s)} bytes)")


if __name__ == "__main__":
    vendor(Path(sys.argv[1]), Path(__file__).resolve().parent / "h4m_decoder.c")
