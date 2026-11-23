"""Build the review pack the user looks at: trace comparison sheet + slow and real-speed GIFs.

usage: python -I make_review.py <trace.json> <frames_dir> <bake_report_dir> <out_dir> [--scales s1,s2,...] [--crop x0,y0,x1,y1] [--titles "a|b|c"]

bake_report_dir must hold (written by the bake's Verify step):
  report.txt  with a line  JOINTS [[[x,y] x12], ...]  = each traced key's joints relative to the Hips (world units),
              in trace order: head, neck, waist, hip, backKnee, backFoot, frontKnee, frontFoot, frontElbow, frontHand, backElbow, backHand
  key0.png .. keyN.png   full 1280x720 renders of the stickman alone at each traced key
  seq000.png ...         full 1280x720 renders of the whole sequence at 30 fps
--scales: world units per reference px for each traced frame (default 0.0112 for all)
--crop:   region of the sequence frames used for the GIFs (default 180,40,1120,620)

writes <out_dir>/compare.png (rows: trace / stickman red over trace blue / Unity render),
       <out_dir>/anim.gif, <out_dir>/anim_slow.gif (1/3 speed), <out_dir>/contact.png (in-between frames)
"""
import argparse
import glob
import json
import os
import re

from PIL import Image, ImageDraw, ImageFont

NAMES = ["head", "neck", "waist", "hip", "backKnee", "backFoot", "frontKnee", "frontFoot", "frontElbow", "frontHand", "backElbow", "backHand"]
CHAINS = [("hip", "backKnee", "backFoot"), ("hip", "frontKnee", "frontFoot"), ("hip", "waist", "neck", "head"),
          ("neck", "frontElbow", "frontHand"), ("neck", "backElbow", "backHand")]
TW, TH = 330, 300


def draw(dr, P, col, w, r):
    for c in CHAINS:
        dr.line([tuple(P[n]) for n in c], fill=col, width=w)
    for n in NAMES:
        x, y = P[n]
        dr.ellipse([x - r, y - r, x + r, y + r], fill=col)


def tile(im, P):
    xs = [p[0] for p in P.values()]
    ys = [p[1] for p in P.values()]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 40
    pad = Image.new("RGB", (im.width + 800, im.height + 800), (40, 40, 40))
    pad.paste(im, (400, 400))
    t = pad.crop((int(cx - half) + 400, int(cy - half) + 400, int(cx + half) + 400, int(cy + half) + 400))
    return t.resize((TW, TH))


def render_tile(path):
    k = Image.open(path).convert("RGB")
    px = k.load()
    pts = [(x, y) for x in range(0, k.width, 2) for y in range(0, 570, 2) if sum(px[x, y]) < 90]  # dark stickman pixels above the ground line
    if not pts:
        return k.resize((TW, TH))
    X = [p[0] for p in pts]
    Y = [p[1] for p in pts]
    cx, cy = (min(X) + max(X)) / 2, (min(Y) + max(Y)) / 2
    half = max(max(X) - min(X), max(Y) - min(Y)) / 2 + 40
    return k.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half))).resize((TW, TH))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace"); ap.add_argument("frames_dir"); ap.add_argument("report_dir"); ap.add_argument("out_dir")
    ap.add_argument("--scales", default=None); ap.add_argument("--crop", default="180,40,1120,620"); ap.add_argument("--titles", default=None)
    ap.add_argument("--facing", default="right", choices=["right", "left"],
                    help="which way the character in the Reference faces; 'right' = mirrored onto the left-facing man (default), 'left' = same facing, no mirror")
    ap.add_argument("--zoom", type=float, default=1.0, help="enlarge reference frames before drawing (for tiny characters)")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    J = json.load(open(a.trace))
    n = len(J["frames"])
    scales = [float(s) for s in a.scales.split(",")] if a.scales else [0.0112] * n
    rep = open(os.path.join(a.report_dir, "report.txt")).read()
    JT = json.loads("[" + re.search(r"JOINTS (.*)", rep).group(1).replace(",]", "]").rstrip(",") + "]")
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    rows = [[], [], []]
    sx = -1.0 if a.facing == "right" else 1.0   # world x -> reference px direction
    z = a.zoom
    for i, (f, P0) in enumerate(zip(J["frames"], J["pts"])):
        fr = Image.open(f"{a.frames_dir}/f{f:02d}.png").convert("RGB")
        if z != 1.0:
            fr = fr.resize((int(fr.width * z), int(fr.height * z)), Image.LANCZOS)
        P = {k: (v[0] * z, v[1] * z) for k, v in P0.items()}
        w, r = max(2, int(2 * z ** 0.5)), max(3, int(3 * z ** 0.5))
        t0 = fr.copy(); draw(ImageDraw.Draw(t0), P, (30, 110, 255), w + 1, r); rows[0].append(tile(t0, P))
        b = Image.blend(fr, Image.new("RGB", fr.size, (255, 255, 255)), 0.55); db = ImageDraw.Draw(b)
        hx, hy = P["hip"]
        Q = {nm: (hx + sx * JT[i][k][0] / scales[i] * z, hy - JT[i][k][1] / scales[i] * z) for k, nm in enumerate(NAMES)}
        draw(db, P, (30, 110, 255), w + 4, r + 1); draw(db, Q, (230, 30, 30), w, r - 1); rows[1].append(tile(b, P))
        rows[2].append(render_tile(os.path.join(a.report_dir, f"key{i}.png")))
    titles = a.titles.split("|") if a.titles else [f"frame {f}" for f in J["frames"]]
    lab = 210
    sheet = Image.new("RGB", (lab + n * (TW + 10), 40 + 3 * (TH + 10)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, t in enumerate(titles):
        dr.text((lab + i * (TW + 10) + 80, 10), t, fill="black", font=font)
    for r, (row, label) in enumerate(zip(rows, ["My trace", "Stickman (red)\nover the trace (blue)", "Stickman in Unity"])):
        y = 40 + r * (TH + 10)
        dr.text((10, y + TH // 2 - 20), label, fill="black", font=font)
        for i, im in enumerate(row):
            sheet.paste(im, (lab + i * (TW + 10), y))
    sheet.save(os.path.join(a.out_dir, "compare.png"))

    crop = tuple(int(v) for v in a.crop.split(","))
    seq = sorted(glob.glob(os.path.join(a.report_dir, "seq*.png")))
    w, h = crop[2] - crop[0], crop[3] - crop[1]
    fr = [Image.open(p).convert("RGB").crop(crop).resize((int(w * 0.75), int(h * 0.75))) for p in seq]
    fr[0].save(os.path.join(a.out_dir, "anim.gif"), save_all=True, append_images=fr[1:], duration=33, loop=0)
    slow = [im for im in fr for _ in range(3)]
    slow[0].save(os.path.join(a.out_dir, "anim_slow.gif"), save_all=True, append_images=slow[1:], duration=33, loop=0)
    pick = fr[::2][:20]
    cw, ch = pick[0].width // 2, pick[0].height // 2
    cols = 5
    cs = Image.new("RGB", (cols * cw, ((len(pick) + cols - 1) // cols) * ch), "white")
    for k, im in enumerate(pick):
        cs.paste(im.resize((cw, ch)), ((k % cols) * cw, (k // cols) * ch))
    cs.save(os.path.join(a.out_dir, "contact.png"))
    print("wrote compare.png, anim.gif, anim_slow.gif, contact.png to", a.out_dir, "|", len(fr), "frames")


if __name__ == "__main__":
    main()
