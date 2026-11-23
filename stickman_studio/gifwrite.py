"""One GIF writer for the studio (v3.3): 05 ANIMATE's export and 01 Source's G both use it. No AI.

- ONE palette for the whole animation (made from frames sampled across it), so a colour can't shift or flicker
  from one frame to the next as it did when every frame got its own palette.
- Drawn animation is written without dithering (flat colours stay flat and clean); video frames can be dithered
  (photos need it), still on the same palette.
- GIF delays are whole 1/100 s: they are spread so the total time is exactly right (24 fps does not become 25).
- See-through GIFs keep one palette slot for "transparent" and clear each frame before the next (disposal 2).
"""
from PIL import Image

SAMPLE = 16     # frames sampled to build the palette
SIDE = 480      # sampled frames are shrunk to at most this size (speed; the palette barely changes)


def durations(count, fps):
    """Delays in ms, spread over 1/100 s steps so the total is round(count * 100 / fps) / 100 s."""
    out, prev = [], 0
    for k in range(1, count + 1):
        end = round(k * 100 / fps)
        out.append(max(2, end - prev) * 10)
        prev = end
    return out


def palette(frames, colors):
    """A P-mode picture whose palette suits every frame (median cut over a mosaic of sampled frames)."""
    n = len(frames)
    picks = frames if n <= SAMPLE else [frames[round(i * (n - 1) / (SAMPLE - 1))] for i in range(SAMPLE)]
    w, h = picks[0].size
    k = min(1.0, SIDE / max(w, h))
    sw, sh = max(1, round(w * k)), max(1, round(h * k))
    mosaic = Image.new("RGB", (sw, sh * len(picks)))
    for i, im in enumerate(picks):
        mosaic.paste(im.convert("RGB").resize((sw, sh), Image.NEAREST) if k < 1 else im.convert("RGB"), (0, i * sh))
    return mosaic.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def write_gif(path, frames, fps, transparent=False, dither=False):
    """frames: PIL pictures (RGB, or RGBA when transparent). -> number of frames written."""
    if not frames:
        raise ValueError("No frames to write.")
    if transparent:   # see-through pixels become one plain colour (they cost at most one palette slot)
        rgb = []
        for im in frames:
            flat = Image.new("RGB", im.size, (0, 0, 0))
            flat.paste(im.convert("RGB"), (0, 0), im.getchannel("A").point(lambda v: 255 if v >= 128 else 0))
            rgb.append(flat)
        pal = palette(rgb, 255)    # slot 255 is kept for "transparent"
    else:
        rgb = [im.convert("RGB") for im in frames]
        pal = palette(rgb, 256)
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    out = []
    for im, r in zip(frames, rgb):
        q = r.quantize(palette=pal, dither=mode)
        if transparent:
            q.paste(255, (0, 0), im.getchannel("A").point(lambda v: 255 if v < 128 else 0))
        out.append(q)
    kw = dict(save_all=True, append_images=out[1:], duration=durations(len(out), fps), loop=0, optimize=False)
    if transparent:
        kw.update(transparency=255, disposal=2)
    else:
        kw.update(disposal=1)
    out[0].save(path, **kw)
    return len(out)
