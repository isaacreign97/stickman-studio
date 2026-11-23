"""Draw studio.ico: a black HUD badge with a red ring gauge and a white stickman (16 to 256 px).

usage: python -I make_icon.py [out.ico]
"""
import math
import os
import sys

from PIL import Image, ImageDraw


def badge(size=1024):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.18, fill=(12, 12, 14, 255))
    c = s / 2
    r = s * 0.40
    for i in range(60):                                  # gauge ticks
        a = math.radians(i * 6 - 90)
        long = i % 5 == 0
        r0 = r - s * (0.05 if long else 0.025)
        d.line((c + r0 * math.cos(a), c + r0 * math.sin(a), c + r * math.cos(a), c + r * math.sin(a)),
               fill=(80, 80, 90, 255), width=max(1, int(s * (0.008 if long else 0.004))))
    w = int(s * 0.045)
    box = (c - r - w, c - r - w, c + r + w, c + r + w)
    d.arc(box, start=-90, end=200, fill=(227, 34, 43, 255), width=w)   # the red arc
    k = s / 100                                          # the stickman, in a 100-unit box
    white = (240, 240, 242, 255)
    lw = int(5.5 * k)

    def line(*pts):
        p = [(c + x * k, c + y * k) for x, y in pts]
        d.line(p, fill=white, width=lw, joint="curve")
        for x, y in p:
            d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=white)

    hx, hy, hr = 2, -21, 8
    d.ellipse((c + (hx - hr) * k, c + (hy - hr) * k, c + (hx + hr) * k, c + (hy + hr) * k), fill=white)
    line((1, -13), (0, 2), (-1, 10))                     # body
    line((-1, 10), (-10, 21), (-16, 29))                 # back leg
    line((-1, 10), (9, 19), (8, 30))                     # front leg
    line((0, -9), (-9, -1), (-6, 8))                     # back arm
    line((0, -9), (11, -4), (21, -11))                   # front arm (a punch)
    return im


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio.ico")
    big = badge(1024)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.resize((256, 256), Image.LANCZOS).save(out, sizes=sizes)
    big.resize((256, 256), Image.LANCZOS).save(os.path.splitext(out)[0] + ".png")
    print("wrote", out)


if __name__ == "__main__":
    main()
