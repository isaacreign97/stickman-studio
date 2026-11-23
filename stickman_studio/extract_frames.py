"""Split a GIF into frames and make a labelled contact sheet.

usage: python -I extract_frames.py <reference.gif> <out_dir>
writes <out_dir>/f00.png, f01.png, ... and <out_dir>/all.png (frames in a grid, index in yellow)
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont, ImageSequence


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    im = Image.open(src)
    frames = []
    for i, f in enumerate(ImageSequence.Iterator(im)):
        rgb = f.convert("RGB")
        rgb.save(os.path.join(out, f"f{i:02d}.png"))
        frames.append((rgb, f.info.get("duration")))
    w, h = frames[0][0].size
    cols = 2 if len(frames) > 1 else 1
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), "white")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for i, (f, _) in enumerate(frames):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(f, (x, y))
        d.rectangle([x, y, x + 42, y + 32], fill="yellow")
        d.text((x + 8, y + 4), str(i), fill="black", font=font)
    sheet.save(os.path.join(out, "all.png"))
    total = sum(dur or 100 for _, dur in frames)
    with open(os.path.join(out, "timing.json"), "w") as fh:   # real speed, for trace_player.py
        json.dump({"fps": round(1000 * len(frames) / max(1, total), 3)}, fh)
    print(f"size {w}x{h}, {len(frames)} frames, durations (ms): {[dur for _, dur in frames]}")
    print("contact sheet:", os.path.join(out, "all.png"))


if __name__ == "__main__":
    main()
