"""Zoom into part of a frame with a pixel grid, to read joint positions precisely.

usage: python -I grid_crop.py <frame.png> x0 y0 x1 y1 zoom <out.png>
Grid lines every 10 px (cyan + labels every 50 px), in ORIGINAL frame coordinates.
A point at (X, Y) in the zoomed image is frame pixel (x0 + X/zoom, y0 + Y/zoom).
Coordinates outside the frame (e.g. negative y) are allowed; they show as empty.
"""
import sys

from PIL import Image, ImageDraw, ImageFont


def main():
    f = sys.argv[1]
    x0, y0, x1, y1, z = (int(v) for v in sys.argv[2:7])
    out = sys.argv[7]
    src = Image.open(f).convert("RGB")
    canvas = Image.new("RGB", (x1 - x0, y1 - y0), (40, 40, 40))
    canvas.paste(src, (-x0, -y0))
    im = canvas.resize(((x1 - x0) * z, (y1 - y0) * z), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for gx in range((x0 // 10 + 1) * 10, x1, 10):
        X = (gx - x0) * z
        d.line([(X, 0), (X, im.height)], fill=(0, 255, 255) if gx % 50 == 0 else (90, 90, 90), width=1)
        if gx % 50 == 0:
            d.text((X + 2, 2), str(gx), fill=(255, 255, 0), font=font)
    for gy in range((y0 // 10 + 1) * 10, y1, 10):
        Y = (gy - y0) * z
        d.line([(0, Y), (im.width, Y)], fill=(0, 255, 255) if gy % 50 == 0 else (90, 90, 90), width=1)
        if gy % 50 == 0:
            d.text((2, Y + 2), str(gy), fill=(255, 255, 0), font=font)
    im.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
