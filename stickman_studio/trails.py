"""Motion trails (upgrade Phase 5): the path a joint travels across frames, drawn as a see-through layer.

Used by 02 TRACE (trace_clicker.py, over the reference frame) and 03 PLAY / FIX (trace_player.py, over the stickman).
Plain drawing of your own coordinates, no AI.

    PAST    solid line in the joint's colour, filled dots, fading the further back it goes
    FUTURE  dashed line, a lighter shade of the same colour, hollow dots, also fading with distance
"""
from PIL import Image, ImageDraw

DEFAULT_JOINTS = ["head", "frontHand", "backHand", "frontFoot", "backFoot"]
PRESETS = {"hands": ["frontHand", "backHand"], "feet": ["frontFoot", "backFoot"], "head": ["head"]}
LENGTHS = ["1", "2", "3", "4", "6", "8", "12", "ALL"]   # key frames before / after the current one
DEFAULT_LENGTH = "4"
DEFAULT_ALPHA = 0.85


def colour(name):
    """Same family of colours as the skeleton: front orange, back blue, torso green."""
    if name.startswith("front"):
        return (255, 140, 0)
    if name.startswith("back"):
        return (60, 130, 255)
    return (40, 210, 80)


def lighter(c, k=0.5):
    return tuple(int(v + (255 - v) * k) for v in c)


def split(positions, frames, cur, length):
    """positions = {frame: (x, y)} for one joint; frames = the key frames in order; cur = the current frame.
    length = key frames each side (int) or "ALL". -> (past, future): lists of (frame, (x, y)), oldest first and
    nearest first; the current frame (when it has a position) ends past and starts future, so both lines touch it."""
    have = [f for f in frames if f in positions]
    before = [f for f in have if f < cur]
    after = [f for f in have if f > cur]
    if length != "ALL":
        n = int(length)
        before, after = before[-n:] if n else [], after[:n]
    here = [cur] if cur in positions else []
    past = [(f, positions[f]) for f in before + here]
    future = [(f, positions[f]) for f in here + after]
    return past, future


def dashed(d, p, q, fill, width, dash=7.0, gap=5.0):
    (x0, y0), (x1, y1) = p, q
    L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if L < 1e-6:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    s = 0.0
    while s < L:
        e = min(L, s + dash)
        d.line((x0 + ux * s, y0 + uy * s, x0 + ux * e, y0 + uy * e), fill=fill, width=width)
        s = e + gap


def draw(img, paths, to_screen, alpha=DEFAULT_ALPHA, show_past=True, show_future=True, width=3):
    """Draw trails on an RGB or RGBA image (in place, alpha-blended). paths = {joint: (past, future)} from split();
    to_screen(x, y) -> image pixel coordinates."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    strokes(ImageDraw.Draw(layer), paths, to_screen, alpha, show_past, show_future, width)
    if img.mode == "RGBA":
        img.alpha_composite(layer)
        return img
    out = Image.alpha_composite(img.convert("RGBA"), layer).convert(img.mode)
    img.paste(out)
    return img


def layer(size, paths, to_screen, alpha=DEFAULT_ALPHA, show_past=True, show_future=True, width=3):
    """A transparent RGBA image of the given size with only the trails on it (for the TRACE canvas)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    strokes(ImageDraw.Draw(img), paths, to_screen, alpha, show_past, show_future, width)
    return img


def strokes(d, paths, to_screen, alpha, show_past, show_future, width):
    for name, (past, future) in paths.items():
        base = colour(name)
        if show_past and len(past) >= 1:
            pts = [to_screen(*p) for _, p in past]
            n = len(pts)
            for i in range(n - 1):                       # oldest segment is the faintest
                a = alpha * (0.3 + 0.7 * (i + 1) / max(n - 1, 1))
                d.line((*pts[i], *pts[i + 1]), fill=base + (int(255 * a),), width=width)
            for i, (x, y) in enumerate(pts[:-1] if past[-1:] and future[:1] and past[-1] == future[0] else pts):
                a = alpha * (0.3 + 0.7 * (i + 1) / max(n, 1))
                d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=base + (int(255 * a),))
        if show_future and len(future) >= 1:
            light = lighter(base)
            pts = [to_screen(*p) for _, p in future]
            n = len(pts)
            for i in range(n - 1):                       # nearest future segment is the strongest
                a = alpha * (1.0 - 0.6 * i / max(n - 1, 1))
                dashed(d, pts[i], pts[i + 1], light + (int(255 * a),), max(1, width - 1))
            start = 1 if future and past and past[-1] == future[0] else 0
            for i, (x, y) in enumerate(pts[start:], start):
                a = alpha * (1.0 - 0.6 * i / max(n, 1))
                d.ellipse((x - 3, y - 3, x + 3, y + 3), outline=light + (int(255 * a),), width=2)
