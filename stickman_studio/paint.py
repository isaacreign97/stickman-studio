"""PAINT (v3.2): the picture maths behind 05 ANIMATE's paint tools and the PAINT… window. No AI, no Tk.

A picture is painted pixels (RGBA) plus a list of vector shapes drawn on top. Shapes stay editable: their points
can be dragged, recoloured or deleted at any time. A shape is plain JSON:

    {"type": "line" | "rect" | "ellipse" | "polygon" | "curve", "pts": [[x, y], ...], "stroke": "#rrggbb" or None,
     "width": px, "fill": "#rrggbb" or None, "opacity": 0..1, "closed": bool (curve), "grad": None or
     {"p0": [x, y], "p1": [x, y], "c0": "#rrggbb", "c1": "#rrggbb"}}

A rectangle and an ellipse keep their 4 corners (top-left, top-right, bottom-right, bottom-left), so turning or
flipping them stays exact. A curve goes smoothly THROUGH its points (Catmull-Rom).
"""
import json
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

TYPES = ("line", "rect", "ellipse", "polygon", "curve")
SS = 4                      # shapes are drawn 4x larger and scaled down: smooth edges
PALETTE = ["#111111", "#ffffff", "#7f7f7f", "#e3222b", "#e37a22", "#e3c022", "#2fb35a", "#16a5a5", "#1e6eff",
           "#9b59d0", "#d0407c", "#8b5a2b", "#f2c9a0", "#7ec8ff", "#b6e3a8", "#3a2a1a"]


class PaintError(Exception):
    pass


# ---------------------------------------------------------------- colours
def rgb(colour):
    c = str(colour or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError as e:
        raise PaintError(f"Not a colour: {colour}") from e


def hexcol(r, g, b):
    return "#%02x%02x%02x" % (int(r), int(g), int(b))


# ---------------------------------------------------------------- shapes
def make_shape(kind, pts, stroke="#111111", width=4.0, fill=None, opacity=1.0, closed=False, grad=None):
    """A new shape. rect / ellipse take two opposite corners (a drag) and keep all 4."""
    if kind not in TYPES:
        raise PaintError(f"Unknown shape {kind}.")
    pts = [[float(x), float(y)] for x, y in pts]
    if kind in ("rect", "ellipse") and len(pts) == 2:   # a drag: two opposite corners (4 corners are kept as given)
        (x0, y0), (x1, y1) = pts
        pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    need = {"line": 2, "rect": 4, "ellipse": 4, "polygon": 3, "curve": 2}[kind]
    if len(pts) < need:
        raise PaintError(f"A {kind} needs at least {need} points.")
    return {"type": kind, "pts": pts, "stroke": stroke, "width": float(width), "fill": fill,
            "opacity": float(opacity), "closed": bool(closed), "grad": grad}


def curve_points(pts, closed=False, steps=14):
    """Catmull-Rom through every point (smooth, and it passes through each one)."""
    P = [tuple(p) for p in pts]
    if len(P) < 3 and not closed:
        return P
    n = len(P)
    out = []
    segs = n if closed else n - 1
    for i in range(segs):
        p0 = P[(i - 1) % n] if closed or i > 0 else P[0]
        p1, p2 = P[i % n], P[(i + 1) % n]
        p3 = P[(i + 2) % n] if closed or i + 2 < n else P[-1]
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    out.append(P[0] if closed else P[-1])
    return out


def outline(s):
    """The shape as a list of points to draw through, and whether it's closed."""
    t, pts = s["type"], [tuple(p) for p in s["pts"]]
    if t == "line":
        return pts, False
    if t in ("rect", "polygon"):
        return pts, True
    if t == "ellipse":
        p0, p1, _, p3 = pts
        c = ((pts[0][0] + pts[2][0]) / 2, (pts[0][1] + pts[2][1]) / 2)
        u = ((p1[0] - p0[0]) / 2, (p1[1] - p0[1]) / 2)
        v = ((p3[0] - p0[0]) / 2, (p3[1] - p0[1]) / 2)
        out = []
        for k in range(96):
            a = 2 * math.pi * k / 96
            out.append((c[0] + math.cos(a) * u[0] + math.sin(a) * v[0], c[1] + math.cos(a) * u[1] + math.sin(a) * v[1]))
        return out, True
    closed = bool(s.get("closed"))
    return curve_points(pts, closed), closed


def bbox(s):
    pts, _ = outline(s)
    pad = s.get("width", 0) / 2 + 2
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def gradient(size, p0, p1, c0, c1, origin=(0, 0)):
    """An RGB picture that goes from colour c0 at p0 to c1 at p1 (flat before p0 and after p1)."""
    W, H = size
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    xs += origin[0]
    ys += origin[1]
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = dx * dx + dy * dy
    t = np.zeros((H, W), np.float32) if L < 1e-9 else np.clip(((xs - p0[0]) * dx + (ys - p0[1]) * dy) / L, 0, 1)
    a, b = np.array(rgb(c0), np.float32), np.array(rgb(c1), np.float32)
    px = a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]
    return Image.fromarray(px.astype(np.uint8), "RGB")


def draw_shape(img, s):
    """img (RGBA) with the shape drawn on it: a new picture."""
    out = img.copy()
    draw_shape_into(out, s)
    return out


def draw_shape_into(out, s):
    """Draw the shape onto out (RGBA) in place."""
    img = out
    x0, y0, x1, y1 = bbox(s)
    x0, y0 = max(0, int(math.floor(x0))), max(0, int(math.floor(y0)))
    x1, y1 = min(img.width, int(math.ceil(x1)) + 1), min(img.height, int(math.ceil(y1)) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    w, h = x1 - x0, y1 - y0
    pts, closed = outline(s)
    sp = [((x - x0) * SS, (y - y0) * SS) for x, y in pts]
    op = max(0.0, min(1.0, float(s.get("opacity", 1.0))))
    if closed and (s.get("fill") or s.get("grad")) and len(sp) >= 3:
        m = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(m).polygon(sp, fill=255)
        m = m.reduce(SS)
        if op < 1:
            m = m.point(lambda v: int(v * op))
        g = s.get("grad")
        if g:
            col = gradient((w, h), g["p0"], g["p1"], g["c0"], g["c1"], (x0, y0)).convert("RGBA")
        else:
            col = Image.new("RGBA", (w, h), rgb(s["fill"]) + (0,))
        col.putalpha(m)
        out.alpha_composite(col, (x0, y0))
    if s.get("stroke") and s.get("width", 0) > 0:
        m = Image.new("L", (w * SS, h * SS), 0)
        d = ImageDraw.Draw(m)
        wd = max(1, round(s["width"] * SS))
        line = sp + ([sp[0]] if closed else [])
        if len(line) > 1:
            d.line(line, fill=255, width=wd, joint="curve")
        r = wd / 2
        for x, y in (line if s["type"] in ("rect", "polygon") or len(line) < 3 else [line[0], line[-1]]):
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
        m = m.reduce(SS)
        if op < 1:
            m = m.point(lambda v: int(v * op))
        col = Image.new("RGBA", (w, h), rgb(s["stroke"]) + (0,))
        col.putalpha(m)
        out.alpha_composite(col, (x0, y0))


def render_shapes(img, shapes):
    if not shapes:
        return img
    out = img.copy()
    for s in shapes:
        draw_shape_into(out, s)
    return out


def flatten(img, shapes):
    """The picture as you see it: painted pixels with the shapes on top."""
    return render_shapes(img, shapes) if shapes else img


def shapes_key(shapes):
    return json.dumps(shapes or [], sort_keys=True)


def hit_shape(shapes, x, y, tol=6.0):
    """Index of the top shape under (x, y) (on its outline, or inside a filled one), or None."""
    for i in range(len(shapes) - 1, -1, -1):
        s = shapes[i]
        pts, closed = outline(s)
        reach = tol + s.get("width", 0) / 2
        seq = pts + ([pts[0]] if closed else [])
        for a, b in zip(seq, seq[1:]):
            if seg_dist((x, y), a, b) <= reach:
                return i
        if closed and (s.get("fill") or s.get("grad")) and inside(pts, x, y):
            return i
    return None


def seg_dist(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    t = 0.0 if L < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)


def inside(poly, x, y):
    n, c = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


# ---------------------------------------------------------------- affine maps (2x3: [[a, b, c], [d, e, f]])
def identity():
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def compose(M, N):
    """M after N."""
    A = np.vstack([np.array(M, float), [0, 0, 1]]) @ np.vstack([np.array(N, float), [0, 0, 1]])
    return A[:2].tolist()


def about(M, cx, cy):
    """M applied around the point (cx, cy) instead of the origin."""
    return compose([[1, 0, cx], [0, 1, cy]], compose(M, [[1, 0, -cx], [0, 1, -cy]]))


def rotation(deg, cx=0.0, cy=0.0):
    r = math.radians(deg)
    return about([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0]], cx, cy)


def scaling(sx, sy, cx=0.0, cy=0.0):
    return about([[sx, 0, 0], [0, sy, 0]], cx, cy)


def apply(M, x, y):
    return M[0][0] * x + M[0][1] * y + M[0][2], M[1][0] * x + M[1][1] * y + M[1][2]


def transform_shape(s, M):
    out = json.loads(json.dumps(s))
    out["pts"] = [list(apply(M, *p)) for p in s["pts"]]
    if out.get("grad"):
        out["grad"]["p0"] = list(apply(M, *out["grad"]["p0"]))
        out["grad"]["p1"] = list(apply(M, *out["grad"]["p1"]))
    k = math.sqrt(abs(M[0][0] * M[1][1] - M[0][1] * M[1][0]))
    out["width"] = s.get("width", 0) * k
    return out


def warp(piece, M, size, origin=(0, 0)):
    """piece (RGBA, its top-left at origin in canvas coordinates) moved by M onto a transparent canvas of size."""
    A = np.vstack([np.array(M, float), [0, 0, 1]]) @ np.array([[1, 0, origin[0]], [0, 1, origin[1]], [0, 0, 1]])
    inv = np.linalg.inv(A)
    data = tuple(inv[0]) + tuple(inv[1])
    return piece.transform(size, Image.AFFINE, data, resample=Image.BICUBIC)


# ---------------------------------------------------------------- fill bucket, eyedropper
def region(look, x, y, tol=32):
    """The connected area around (x, y) whose colour is close to the one there (see-through counts as one colour).
    -> an "L" mask (255 inside)."""
    a = np.asarray(look.convert("RGBA")).astype(np.int16)
    H, W = a.shape[:2]
    x, y = int(x), int(y)
    if not (0 <= x < W and 0 <= y < H):
        raise PaintError("That's outside the picture.")
    alpha = a[..., 3:4]
    pm = np.concatenate([a[..., :3] * alpha // 255, alpha], axis=2)
    diff = np.abs(pm - pm[y, x]).max(axis=2)
    import cv2   # connected areas (Pillow 13's floodfill doesn't work on masks)
    _, labels = cv2.connectedComponents((diff <= tol).astype(np.uint8), connectivity=4)
    return Image.fromarray(((labels == labels[y, x]) * 255).astype(np.uint8), "L")


def fill(img, x, y, colour, tol=32, look=None, opacity=1.0, grad=None):
    """Paint bucket: the area around (x, y) gets the colour (or a gradient). The area is found in `look` (the
    picture itself, or everything you see); its 1-pixel rim goes UNDER the existing pixels, so outlines stay
    crisp and leave no gap. -> a new picture."""
    inner = region(look if look is not None else img, x, y, tol)
    return fill_mask(img, inner, colour, opacity, grad)


def fill_mask(img, inner, colour, opacity=1.0, grad=None):
    grown = inner.filter(ImageFilter.MaxFilter(3))
    rim = ImageChops.subtract(grown, inner)
    if grad:
        col = gradient(img.size, grad["p0"], grad["p1"], grad["c0"], grad["c1"]).convert("RGBA")
    else:
        col = Image.new("RGBA", img.size, rgb(colour) + (255,))
    a = int(255 * max(0.0, min(1.0, opacity)))
    out = img.copy()
    if a >= 255:
        out.paste(col, (0, 0), inner)
    else:
        top = col.copy()
        top.putalpha(inner.point(lambda v: v * a // 255))
        out.alpha_composite(top)
    under = col.copy()
    under.putalpha(rim.point(lambda v: v * a // 255))
    return Image.alpha_composite(under, out)


def pick(img, x, y):
    """Eyedropper: the colour at (x, y) as #rrggbb (see-through pixels give None)."""
    x, y = int(x), int(y)
    if not (0 <= x < img.width and 0 <= y < img.height):
        return None
    r, g, b, a = img.convert("RGBA").getpixel((x, y))
    return None if a == 0 else hexcol(r, g, b)


# ---------------------------------------------------------------- selections
def rect_mask(size, x0, y0, x1, y1):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill=255)
    return m


def lasso_mask(size, pts):
    m = Image.new("L", size, 0)
    if len(pts) >= 3:
        ImageDraw.Draw(m).polygon([tuple(p) for p in pts], fill=255)
    return m


class Floating:
    """A lifted selection: its pixels and the shapes that were inside it, moved together by one affine map until
    it's put down. Nothing is changed in the picture until then (undo stays one step)."""

    def __init__(self, piece, origin, shapes=(), M=None):
        self.piece = piece              # RGBA, cropped to the selection's box
        self.origin = origin            # its top-left in the picture before any move
        self.shapes = [json.loads(json.dumps(s)) for s in shapes]
        self.M = M or identity()

    def centre(self):
        w, h = self.piece.size
        return apply(self.M, self.origin[0] + w / 2, self.origin[1] + h / 2)

    def corners(self):
        x, y = self.origin
        w, h = self.piece.size
        return [apply(self.M, *p) for p in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]

    def move(self, dx, dy):
        self.M = compose([[1, 0, dx], [0, 1, dy]], self.M)

    def turn(self, deg):
        self.M = compose(rotation(deg, *self.centre()), self.M)

    def scale(self, sx, sy=None):
        self.M = compose(scaling(sx, sx if sy is None else sy, *self.centre()), self.M)

    def flip(self, horizontal=True):
        self.scale(-1, 1) if horizontal else self.scale(1, -1)

    def layer(self, size):
        """Its pixels where they are now, on a transparent picture of `size`."""
        return warp(self.piece, self.M, size, self.origin)

    def placed_shapes(self):
        return [transform_shape(s, self.M) for s in self.shapes]

    def copy(self):
        return Floating(self.piece.copy(), self.origin, self.shapes, [list(r) for r in self.M])


def lift(img, shapes, mask):
    """Cut the selection out: -> (picture with a hole, shapes left, Floating). Shapes go along when all their
    points are inside the selection."""
    box = mask.getbbox()
    if not box:
        raise PaintError("Nothing is selected.")
    piece = img.crop(box)
    a = ImageChops.multiply(piece.getchannel("A"), mask.crop(box))
    piece.putalpha(a)
    hole = img.copy()
    hole.putalpha(ImageChops.multiply(img.getchannel("A"), ImageChops.invert(mask)))
    m = np.asarray(mask)

    def taken(s):
        for x, y in s["pts"]:
            xi, yi = int(x), int(y)
            if not (0 <= xi < mask.width and 0 <= yi < mask.height) or m[yi, xi] == 0:
                return False
        return True
    moved = [s for s in shapes if taken(s)]
    left = [s for s in shapes if not taken(s)]
    return hole, left, Floating(piece, (box[0], box[1]), moved)


def put_down(img, shapes, fl):
    """Put the floating selection back into the picture where it is now. -> (picture, shapes)."""
    out = img.copy()
    out.alpha_composite(fl.layer(img.size))
    return out, list(shapes) + fl.placed_shapes()


def from_picture(src, size, fit=0.8):
    """A picture file (any size) as a Floating selection in the middle of a picture of `size`, shrunk to fit."""
    src = src.convert("RGBA")
    W, H = size
    k = min(1.0, fit * W / max(1, src.width), fit * H / max(1, src.height))
    if k < 1:
        src = src.resize((max(1, int(src.width * k)), max(1, int(src.height * k))), Image.LANCZOS)
    return Floating(src, ((W - src.width) // 2, (H - src.height) // 2))


# ---------------------------------------------------------------- strokes (pen / brush / eraser)
def stroke(img, pts, tool="pen", colour="#000000", size=4.0, opacity=1.0):
    """Same as 05 ANIMATE's pen, brush and eraser."""
    import animate
    return animate.paint(img, pts, tool, colour, size, opacity)


def simplify(pts, eps=3.0):
    """Fewer points along a hand-drawn line (Ramer-Douglas-Peucker): keeps its shape within eps pixels."""
    pts = [tuple(p) for p in pts]
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, k = -1.0, None
        for m in range(i + 1, j):
            d = seg_dist(pts[m], pts[i], pts[j])
            if d > best:
                best, k = d, m
        if k is not None and best > eps:
            keep[k] = True
            stack += [(i, k), (k, j)]
    return [p for p, kp in zip(pts, keep) if kp]


def checker(size, cell=10):
    """A light grey checkerboard (shows see-through parts)."""
    W, H = size
    ys, xs = np.mgrid[0:H, 0:W]
    v = np.where(((xs // cell) + (ys // cell)) % 2, 232, 250).astype(np.uint8)
    return Image.fromarray(np.dstack([v, v, v, np.full_like(v, 255)]), "RGBA")
