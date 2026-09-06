"""Draw the app icon: a plain black-and-white baseball.  python tools/make_icon.py

One description of the shape (a white ball with a black outline and two
plain seams bowing towards the centre) is written out as

    frontend/public/favicon.svg   the browser-tab icon (Vite copies it into the UI bundle)
    zzzzdat/ui/icon.png           the window icon on macOS/Linux
    zzzzdat/ui/icon.ico           the window icon on Windows and the executable's icon

The raster files are drawn with Pillow (pip install pillow) at 16x oversampling
so the small sizes stay crisp. Re-run after changing the geometry, then
`npm run build` in frontend/ and commit the results.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Geometry in a 64x64 box.
SIZE = 64
CENTRE = (32.0, 32.0)
RADIUS = 29.0
OUTLINE = 3.0        # outline stroke width
SEAM = 4.5           # seam stroke width

# Each seam is a quadratic Bezier from P0 through control C to P2. The
# control point sits past the ball's centre so the seam bows inward.
# The ends sit just inside the outline so the round caps do not poke past it.
SEAMS = [((19.0, 10.0), (33.5, 32.0), (19.0, 54.0)),
         ((45.0, 10.0), (30.5, 32.0), (45.0, 54.0))]


def bezier(p0, c, p2, t):
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t ** 2 * p2[1]
    return x, y


def svg() -> str:
    seams = " ".join(f"M{p0[0]} {p0[1]} Q{c[0]} {c[1]} {p2[0]} {p2[1]}" for p0, c, p2 in SEAMS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">\n'
            f'  <circle cx="{CENTRE[0]}" cy="{CENTRE[1]}" r="{RADIUS}" fill="#fff" stroke="#000" stroke-width="{OUTLINE}"/>\n'
            f'  <path d="{seams}" fill="none" stroke="#000" stroke-width="{SEAM}" stroke-linecap="round"/>\n'
            f'</svg>\n')


def raster(px: int, oversample: int = 16):
    from PIL import Image, ImageDraw
    s = px * oversample / SIZE            # box units -> big-image pixels
    big = Image.new("RGBA", (px * oversample, px * oversample), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)

    def pt(p):
        return p[0] * s, p[1] * s

    def stroke(points, width):
        w = max(1, round(width * s))
        d.line([pt(p) for p in points], fill=(0, 0, 0, 255), width=w, joint="curve")
        r = w / 2                          # round caps
        for p in (points[0], points[-1]):
            x, y = pt(p)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(0, 0, 0, 255))

    cx, cy = pt(CENTRE)
    r = RADIUS * s
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=max(1, round(OUTLINE * s)))
    for p0, c, p2 in SEAMS:
        stroke([bezier(p0, c, p2, i / 64) for i in range(65)], SEAM)
    return big.resize((px, px), Image.LANCZOS)


def main() -> None:
    fav = ROOT / "frontend" / "public" / "favicon.svg"
    fav.write_text(svg(), encoding="utf-8", newline="\n")
    print("wrote", fav)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = {n: raster(n) for n in sizes}
    png = ROOT / "zzzzdat" / "ui" / "icon.png"
    images[256].save(png)
    print("wrote", png)
    ico = ROOT / "zzzzdat" / "ui" / "icon.ico"
    # Pillow's ICO writer builds every size from the image given, so hand it
    # the largest and let append_images supply the properly drawn smaller ones.
    images[256].save(ico, sizes=[(n, n) for n in sizes], append_images=[images[n] for n in sizes if n != 256])
    print("wrote", ico)


if __name__ == "__main__":
    main()
