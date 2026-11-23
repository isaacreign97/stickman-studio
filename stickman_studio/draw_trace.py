"""Draw a trace (trace.json) over the reference frames, one tile per traced frame.

usage: python -I draw_trace.py <trace.json> <frames_dir> <out.png>
Colours: blue = back limbs, orange = front limbs, green = torso (hip > waist > neck > head).
Yellow rings = joints listed as estimated (hidden or off-screen).
"""
import json
import sys

from PIL import Image, ImageDraw, ImageFont

CHAINS = [("hip", "backKnee", "backFoot"), ("hip", "frontKnee", "frontFoot"), ("hip", "waist", "neck", "head"),
          ("neck", "frontElbow", "frontHand"), ("neck", "backElbow", "backHand")]


def main():
    trace, frames_dir, out = sys.argv[1], sys.argv[2], sys.argv[3]
    J = json.load(open(trace))
    est_all = J.get("estimated", [[] for _ in J["frames"]])
    try:
        font = ImageFont.truetype("arial.ttf", 18)
        small = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = small = ImageFont.load_default()
    tiles = []
    for f, P, est in zip(J["frames"], J["pts"], est_all):
        im = Image.open(f"{frames_dir}/f{f:02d}.png").convert("RGB")
        pad = 80  # room for estimated joints above/below the frame
        big = Image.new("RGB", (im.width, im.height + 2 * pad), (40, 40, 40))
        big.paste(im, (0, pad))
        d = ImageDraw.Draw(big)
        Q = {k: (v[0], v[1] + pad) for k, v in P.items()}
        for c in CHAINS:
            col = (30, 200, 60) if c[1] == "waist" else (255, 140, 0) if c[1].startswith("front") else (30, 110, 255)
            d.line([Q[n] for n in c], fill=col, width=4)
        for n, (x, y) in Q.items():
            r = 6
            if n in est:
                d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 0), width=2)
            else:
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255), outline=(0, 0, 0))
        xs = [q[0] for q in Q.values()]
        ys = [q[1] for q in Q.values()]
        box = (max(0, int(min(xs)) - 60), max(0, int(min(ys)) - 40), min(big.width, int(max(xs)) + 60), min(big.height, int(max(ys)) + 40))
        t = big.crop(box)
        t = t.resize((int(t.width * 1.4), int(t.height * 1.4)))
        tiles.append((f, t))
    W = sum(t.width for _, t in tiles) + 10 * len(tiles)
    H = max(t.height for _, t in tiles) + 70
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    x = 0
    for f, t in tiles:
        sheet.paste(t, (x, 40))
        d.text((x + 10, 10), f"frame {f}", fill="black", font=font)
        x += t.width + 10
    d.text((10, H - 25), "blue = back limbs, orange = front limbs, green = torso. Yellow rings = estimated (hidden or off-screen).", fill="black", font=small)
    sheet.save(out)
    print("wrote", out, sheet.size)


if __name__ == "__main__":
    main()
