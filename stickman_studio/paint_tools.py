"""The paint tools (v3.2), shared by 05 ANIMATE's stage (on drawing layers) and the PAINT… window. No AI.

The host (the stage or the PAINT window) provides:
    host.canvas                          the Tk canvas
    host.to_model(x, y) / host.to_screen(x, y)
    host.paint_target()                  -> (pixels RGBA, shapes) being edited, or None (host says why)
    host.paint_commit(img, shapes, label)   store a finished change (one undo step)
    host.paint_look()                    -> what you see (RGBA, same size), for FILL "what you see" and PICK
    host.paint_refresh()                 redraw (it asks live() for the picture to show)
    host.msg(text)
"""
import math
import tkinter as tk

import paint

TOOLS = [("pen", "PEN", "P"), ("brush", "BRUSH", "B"), ("eraser", "ERASER", "E"), ("line", "LINE", "L"),
         ("rect", "BOX", ""), ("ellipse", "ELLIPSE", ""), ("polygon", "POLYGON", ""), ("curve", "CURVE", ""),
         ("fill", "FILL", "F"), ("gradient", "GRADIENT", "G"), ("pick", "PICK", "I"), ("select", "SELECT", "S"),
         ("lasso", "LASSO", ""), ("shapes", "Edit Shapes", "D")]
NAMES = {k: n for k, n, _ in TOOLS}
HELP = {
    "pen": "Pen: drag to draw.", "brush": "Brush: soft-edged strokes.", "eraser": "Eraser: drag to rub out.",
    "line": "Line: drag from one end to the other (Shift: straight across, up or at 45°).",
    "rect": "Box: drag corner to corner (Shift: a square). Uses Colour for the outline and Fill inside.",
    "ellipse": "Ellipse: drag corner to corner (Shift: a circle).",
    "polygon": "Polygon: click each corner; double-click or Enter finishes, Esc cancels.",
    "curve": "Curve: click points the curve goes through; double-click or Enter finishes (end on the first point "
             "to close it).",
    "fill": "Fill: click an area to fill it with Colour (it stops at lines).",
    "gradient": "Gradient: drag across an area: it fades from Colour to Fill.",
    "pick": "Pick: click to take a colour as Colour (right-click: as Fill).",
    "select": "Select: drag a box. Then drag it to move, a corner to resize, the round handle to turn. "
              "Ctrl+C / X / V copy, cut, paste; Delete removes it; Enter or a click outside puts it down.",
    "lasso": "Lasso: draw around what you want to select, then move / resize / turn it like Select.",
    "shapes": "Edit Shapes: click a shape to pick it, drag its points, drag the shape to move it. Delete removes it; "
              "Apply Colours gives it the current colours and size.",
}
CLIPBOARD = {"fl": None}      # shared by the stage and the PAINT window (copy here, paste there)


class PaintTools:
    def __init__(self, host):
        self.h = host
        self.tool = "pen"
        self.colour = "#111111"
        self.fill = "#e3222b"
        self.no_fill = tk.BooleanVar(value=True)
        self.size = tk.DoubleVar(value=4.0)
        self.opacity = tk.DoubleVar(value=1.0)
        self.tolerance = tk.IntVar(value=32)
        self.look_all = tk.BooleanVar(value=True)      # FILL / GRADIENT find the area in what you see
        self.floating = None        # (hole pixels, shapes left, paint.Floating) while a selection is lifted
        self.pending = []           # polygon / curve points being clicked
        self.shape_i = None         # EDIT SHAPES: the picked shape
        self.work = None            # EDIT SHAPES: (pixels, shapes) being changed, not stored yet
        self.drag = None
        self.version = 0

    # ---------------------------------------------------------------- state
    def fill_colour(self):
        return None if self.no_fill.get() else self.fill

    def live(self):
        """(pixels, shapes) to show instead of the stored ones while something isn't put down yet, else None."""
        if self.floating:
            hole, left, fl = self.floating
            return paint.put_down(hole, left, fl)
        if self.work:
            return self.work
        return None

    def busy(self):
        return bool(self.floating or self.pending or self.work)

    def set_tool(self, tool):
        if tool != self.tool:
            self.finish()
        self.tool = tool
        self.h.msg(HELP.get(tool, ""))

    def finish(self):
        """Put down / store anything still in progress."""
        if self.floating:
            self.put_down()
        if self.pending:
            self.end_pending()
        if self.work:
            img, shapes = self.work
            self.work = None
            self.h.paint_commit(img, shapes, "edit a shape")
        self.shape_i = None

    def cancel(self):
        if self.pending:
            self.pending = []
        elif self.floating:
            self.floating = None   # nothing was stored: the picture stays as it was
        elif self.work:
            self.work = None
        self.shape_i = None
        self.changed()

    def changed(self):
        self.version += 1
        self.h.paint_refresh()

    # ---------------------------------------------------------------- mouse
    def press(self, e, right=False):
        x, y = self.h.to_model(e.x, e.y)
        shift = bool(e.state & 0x0001)
        t = self.tool
        got = self.h.paint_target()
        if got is None:
            return
        img, shapes = got
        if t == "pick":
            col = paint.pick(self.h.paint_look() or img, x, y)
            if col:
                if right:
                    self.fill = col
                    self.no_fill.set(False)
                else:
                    self.colour = col
                self.h.msg(f"Picked {col} as {'FILL' if right else 'COLOUR'}.")
                self.changed()
            return
        if right:
            return
        if t in ("pen", "brush", "eraser"):
            self.drag = {"kind": "stroke", "pts": [(x, y)], "last": (e.x, e.y)}
        elif t in ("line", "rect", "ellipse", "gradient"):
            self.drag = {"kind": "band", "a": (x, y), "b": (x, y), "shift": shift}
        elif t in ("polygon", "curve"):
            if self.pending and math.dist(self.h.to_screen(*self.pending[0]), (e.x, e.y)) < 9 and len(self.pending) > 2:
                self.end_pending(closed=True)
                return
            self.pending.append((x, y))
            self.changed()
        elif t == "fill":
            look = self.h.paint_look() if self.look_all.get() else img
            try:
                out = paint.fill(img, x, y, self.colour, self.tolerance.get(), look if look is not None else img,
                                 self.opacity.get())
            except paint.PaintError as err:
                self.h.msg(str(err))
                return
            self.h.paint_commit(out, shapes, "fill")
        elif t in ("select", "lasso"):
            if self.floating:
                hit = self.float_hit(e.x, e.y)
                if hit:
                    fl = self.floating[2]
                    self.drag = {"kind": hit, "last": (x, y), "c": fl.centre(), "start": (x, y), "M0": fl.M}
                    return
                self.put_down()
                got = self.h.paint_target()
                if got is None:
                    return
                img, shapes = got
            self.drag = {"kind": "marquee" if t == "select" else "lasso", "a": (x, y), "b": (x, y), "pts": [(x, y)]}
        elif t == "shapes":
            cur = self.work or (img, shapes)
            if self.shape_i is not None and self.shape_i < len(cur[1]):
                s = cur[1][self.shape_i]
                for k, p in enumerate(s["pts"]):
                    if math.dist(self.h.to_screen(*p), (e.x, e.y)) < 8:
                        self.drag = {"kind": "point", "k": k}
                        self.work = (cur[0], [dict(q) for q in cur[1]])
                        return
            z = self.zoom()
            i = paint.hit_shape(cur[1], x, y, 6 / max(z, 1e-6))
            self.shape_i = i
            if i is not None:
                self.work = (cur[0], [dict(q) for q in cur[1]])
                self.drag = {"kind": "shape", "last": (x, y)}
                self.h.msg(f"Shape {i + 1} of {len(cur[1])} ({cur[1][i]['type']}): drag it or its points; "
                           "Delete removes it.")
            else:
                self.finish_work()
            self.changed()

    def motion(self, e):
        d = self.drag
        if not d:
            return
        x, y = self.h.to_model(e.x, e.y)
        k = d["kind"]
        if k == "stroke":
            d["pts"].append((x, y))
            c = self.h.canvas
            col = "#f3f3f3" if self.tool == "eraser" else self.colour
            c.create_line(*d["last"], e.x, e.y, fill=col, width=max(1, self.size.get() * self.zoom()),
                          capstyle="round", tags="paintlive")
            d["last"] = (e.x, e.y)
            return
        if k in ("band", "marquee"):
            d["b"] = (x, y)
            d["shift"] = bool(e.state & 0x0001)
        elif k == "lasso":
            d["pts"].append((x, y))
        elif k in ("move", "scale", "turn"):
            fl = self.floating[2]
            if k == "move":
                fl.move(x - d["last"][0], y - d["last"][1])
                d["last"] = (x, y)
            elif k == "scale":
                cx, cy = d["c"]
                r0 = max(1e-6, math.dist(d["start"], (cx, cy)))
                fl.M = d["M0"]
                s = max(0.02, math.dist((x, y), (cx, cy)) / r0)
                fl.M = paint.compose(paint.scaling(s, s, cx, cy), d["M0"])
            else:
                cx, cy = d["c"]
                a = math.degrees(math.atan2(y - cy, x - cx) - math.atan2(d["start"][1] - cy, d["start"][0] - cx))
                if e.state & 0x0001:
                    a = round(a / 15) * 15
                fl.M = paint.compose(paint.rotation(a, cx, cy), d["M0"])
        elif k == "point":
            img, shapes = self.work
            s = dict(shapes[self.shape_i])
            pts = [list(p) for p in s["pts"]]
            if s["type"] in ("rect", "ellipse"):   # still a box at the same angle: the opposite corner stays
                i = d["k"]
                o, nxt, prv = pts[(i + 2) % 4], pts[(i + 1) % 4], pts[(i - 1) % 4]
                u = (nxt[0] - pts[i][0], nxt[1] - pts[i][1])
                v = (prv[0] - pts[i][0], prv[1] - pts[i][1])
                det = u[0] * v[1] - u[1] * v[0]
                if abs(det) > 1e-9:
                    rx, ry = o[0] - x, o[1] - y
                    a = (rx * v[1] - ry * v[0]) / det
                    b = (u[0] * ry - u[1] * rx) / det
                    pts[i] = [x, y]
                    pts[(i + 1) % 4] = [x + a * u[0], y + a * u[1]]
                    pts[(i - 1) % 4] = [x + b * v[0], y + b * v[1]]
                    s["pts"] = pts
            else:
                pts[d["k"]] = [x, y]
                s["pts"] = pts
            shapes[self.shape_i] = s
        elif k == "shape":
            img, shapes = self.work
            dx, dy = x - d["last"][0], y - d["last"][1]
            shapes[self.shape_i] = paint.transform_shape(shapes[self.shape_i], [[1, 0, dx], [0, 1, dy]])
            d["last"] = (x, y)
        self.changed()

    def release(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        got = self.h.paint_target()
        if got is None:
            return
        img, shapes = got
        k = d["kind"]
        if k == "stroke":
            out = paint.stroke(img, d["pts"], self.tool, self.colour, self.size.get(), self.opacity.get())
            self.h.paint_commit(out, shapes, self.tool)
        elif k == "band":
            a, b = d["a"], self.snap(d["a"], d["b"], d.get("shift"))
            if math.dist(a, b) < 1.5:
                self.changed()
                return
            if self.tool == "gradient":
                look = self.h.paint_look() if self.look_all.get() else img
                grad = {"p0": list(a), "p1": list(b), "c0": self.colour, "c1": self.fill_colour() or "#ffffff"}
                try:
                    out = paint.fill(img, a[0], a[1], None, self.tolerance.get(), look if look is not None else img,
                                     self.opacity.get(), grad)
                except paint.PaintError as err:
                    self.h.msg(str(err))
                    return
                self.h.paint_commit(out, shapes, "gradient")
                return
            s = paint.make_shape(self.tool, [a, b], stroke=self.colour, width=self.size.get(),
                                 fill=None if self.tool == "line" else self.fill_colour(), opacity=self.opacity.get())
            self.h.paint_commit(img, list(shapes) + [s], NAMES[self.tool].lower())
        elif k in ("marquee", "lasso"):
            if k == "marquee":
                (x0, y0), (x1, y1) = d["a"], d["b"]
                if abs(x1 - x0) < 2 or abs(y1 - y0) < 2:
                    self.changed()
                    return
                mask = paint.rect_mask(img.size, x0, y0, x1, y1)
            else:
                if len(d["pts"]) < 3:
                    self.changed()
                    return
                mask = paint.lasso_mask(img.size, d["pts"])
            try:
                self.floating = paint.lift(img, shapes, mask)
            except paint.PaintError as err:
                self.h.msg(str(err))
            else:
                self.h.msg("Selected: drag to move, a corner to resize, the round handle to turn. Enter puts it down.")
        self.changed()

    def double(self, e):
        if self.tool in ("polygon", "curve") and self.pending:
            if len(self.pending) > 1 and math.dist(self.h.to_screen(*self.pending[-1]), (e.x, e.y)) < 6:
                self.pending.pop()     # the double-click's second click added the same point again
            self.end_pending()

    def snap(self, a, b, shift):
        if not shift:
            return b
        dx, dy = b[0] - a[0], b[1] - a[1]
        if self.tool in ("rect", "ellipse"):
            m = max(abs(dx), abs(dy))
            return a[0] + math.copysign(m, dx or 1), a[1] + math.copysign(m, dy or 1)
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        r = math.hypot(dx, dy)
        return a[0] + r * math.cos(ang), a[1] + r * math.sin(ang)

    def zoom(self):
        a, b = self.h.to_screen(0, 0), self.h.to_screen(100, 0)
        return abs(b[0] - a[0]) / 100.0

    # ---------------------------------------------------------------- finishing
    def end_pending(self, closed=False):
        pts, self.pending = self.pending, []
        got = self.h.paint_target()
        if got is None:
            return
        img, shapes = got
        need = 3 if self.tool == "polygon" else 2
        if len(pts) < need:
            self.h.msg(f"A {self.tool} needs at least {need} points.")
            self.changed()
            return
        kind = self.tool if self.tool in ("polygon", "curve") else "polygon"
        s = paint.make_shape(kind, pts, stroke=self.colour, width=self.size.get(),
                             fill=self.fill_colour() if (kind == "polygon" or closed) else None,
                             opacity=self.opacity.get(), closed=closed)
        self.h.paint_commit(img, list(shapes) + [s], kind)
        self.changed()

    def put_down(self):
        if not self.floating:
            return
        hole, left, fl = self.floating
        self.floating = None
        img, shapes = paint.put_down(hole, left, fl)
        self.h.paint_commit(img, shapes, "move a selection")

    def finish_work(self):
        if self.work:
            img, shapes = self.work
            self.work = None
            self.h.paint_commit(img, shapes, "edit a shape")

    # ---------------------------------------------------------------- commands (buttons / keys)
    def key(self, name):
        """Delete / Escape / Return / copy / cut / paste. -> True when the paint tools used the key."""
        if name == "Escape":
            if self.busy():
                self.cancel()
                return True
            return False
        if name == "Return":
            if self.pending:
                self.end_pending()
                return True
            if self.floating:
                self.put_down()
                self.changed()
                return True
            if self.work:
                self.finish_work()
                self.shape_i = None
                self.changed()
                return True
            return False
        if name == "Delete":
            return self.delete()
        if name == "copy":
            return self.copy()
        if name == "cut":
            return self.copy() and self.delete()
        if name == "paste":
            return self.paste()
        return False

    def delete(self):
        if self.floating:
            hole, left, _ = self.floating
            self.floating = None
            self.h.paint_commit(hole, left, "delete the selection")
            self.changed()
            return True
        if self.shape_i is not None:
            img, shapes = self.work or self.h.paint_target() or (None, [])
            if img is not None and self.shape_i < len(shapes):
                shapes = [s for k, s in enumerate(shapes) if k != self.shape_i]
                self.work = None
                self.shape_i = None
                self.h.paint_commit(img, shapes, "delete a shape")
                self.changed()
                return True
        return False

    def copy(self):
        if not self.floating:
            self.h.msg("Select or Lasso something first.")
            return False
        CLIPBOARD["fl"] = self.floating[2].copy()
        self.h.msg("Copied: Ctrl+V pastes it here, on another frame or in Paint.")
        return True

    def paste(self):
        fl = CLIPBOARD["fl"]
        if fl is None:
            self.h.msg("Nothing copied yet.")
            return False
        self.finish()
        got = self.h.paint_target()
        if got is None:
            return False
        img, shapes = got
        new = fl.copy()
        new.move(12, 12)
        self.floating = (img, list(shapes), new)
        self.tool = "select"
        self.changed()
        return True

    def transform(self, what):
        """Buttons for a lifted selection (or the picked shape): flip ↔ / ↕, turn 90°."""
        if self.floating:
            fl = self.floating[2]
            {"fliph": lambda: fl.flip(True), "flipv": lambda: fl.flip(False), "turn": lambda: fl.turn(90)}[what]()
            self.changed()
            return True
        if self.shape_i is not None:
            cur = self.work or self.h.paint_target()
            if cur:
                img, shapes = cur
                s = shapes[self.shape_i]
                x0, y0, x1, y1 = paint.bbox(s)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                M = {"fliph": paint.scaling(-1, 1, cx, cy), "flipv": paint.scaling(1, -1, cx, cy),
                     "turn": paint.rotation(90, cx, cy)}[what]
                shapes = list(shapes)
                shapes[self.shape_i] = paint.transform_shape(s, M)
                self.work = (img, shapes)
                self.finish_work()
                self.changed()
                return True
        self.h.msg("Select something (Select / Lasso) or pick a shape (Edit Shapes) first.")
        return False

    def apply_colours(self):
        """Give the picked shape the current COLOUR, FILL and SIZE."""
        cur = self.work or self.h.paint_target()
        if self.shape_i is None or not cur:
            self.h.msg("Pick a shape with Edit Shapes first.")
            return False
        img, shapes = cur
        shapes = [dict(s) for s in shapes]
        s = shapes[self.shape_i]
        s["stroke"] = self.colour
        s["width"] = self.size.get()
        s["opacity"] = self.opacity.get()
        if s["type"] != "line":
            s["fill"] = self.fill_colour()
            s["grad"] = None
        self.work = (img, shapes)
        self.finish_work()
        self.changed()
        return True

    def import_picture(self, src):
        """A picture file as a selection in the middle, to move and resize before putting it down."""
        self.finish()
        got = self.h.paint_target()
        if got is None:
            return False
        img, shapes = got
        self.floating = (img, list(shapes), paint.from_picture(src, img.size))
        self.tool = "select"
        self.h.msg("Picture in: drag it, resize it with a corner, turn it with the round handle; Enter puts it down.")
        self.changed()
        return True

    # ---------------------------------------------------------------- the selection's handles
    def handles(self):
        """Screen points of the lifted selection: 4 corners and the turn handle."""
        fl = self.floating[2]
        cs = [self.h.to_screen(*p) for p in fl.corners()]
        top = ((cs[0][0] + cs[1][0]) / 2, (cs[0][1] + cs[1][1]) / 2)
        cx, cy = self.h.to_screen(*fl.centre())
        L = math.dist(top, (cx, cy)) or 1
        turn = (top[0] + (top[0] - cx) / L * 22, top[1] + (top[1] - cy) / L * 22)
        return cs, turn

    def float_hit(self, sx, sy):
        cs, turn = self.handles()
        if math.dist(turn, (sx, sy)) < 9:
            return "turn"
        if any(math.dist(c, (sx, sy)) < 9 for c in cs):
            return "scale"
        if paint.inside(cs, sx, sy):
            return "move"
        return None

    def overlay(self):
        """Draw what's in progress on the host's canvas (call after the picture is drawn)."""
        c = self.h.canvas
        c.delete("paintlive")
        S = self.h.to_screen
        d = self.drag
        if d and d["kind"] == "band":
            a, b = S(*d["a"]), S(*self.snap(d["a"], d["b"], d.get("shift")))
            if self.tool == "line" or self.tool == "gradient":
                c.create_line(*a, *b, fill=self.colour, width=max(1, self.size.get() * self.zoom()),
                              arrow="last" if self.tool == "gradient" else None, tags="paintlive")
            else:
                make = c.create_rectangle if self.tool == "rect" else c.create_oval
                make(*a, *b, outline=self.colour, width=max(1, self.size.get() * self.zoom()),
                     fill=self.fill_colour() or "", stipple="gray50" if self.fill_colour() else "", tags="paintlive")
        if d and d["kind"] == "marquee":
            c.create_rectangle(*S(*d["a"]), *S(*d["b"]), outline="#ffffff", dash=(4, 3), tags="paintlive")
        if d and d["kind"] == "lasso" and len(d["pts"]) > 1:
            c.create_line(*[v for p in d["pts"] for v in S(*p)], fill="#ffffff", dash=(4, 3), tags="paintlive")
        if self.pending:
            pts = self.pending if self.tool == "polygon" else paint.curve_points(self.pending)
            if len(pts) > 1:
                c.create_line(*[v for p in pts for v in S(*p)], fill=self.colour,
                              width=max(1, self.size.get() * self.zoom()), tags="paintlive")
            for p in self.pending:
                x, y = S(*p)
                c.create_rectangle(x - 4, y - 4, x + 4, y + 4, outline="#ffffff", fill=self.colour, tags="paintlive")
        if self.floating:
            cs, turn = self.handles()
            c.create_polygon(*[v for p in cs for v in p], outline="#ffffff", fill="", dash=(5, 3), tags="paintlive")
            for x, y in cs:
                c.create_rectangle(x - 5, y - 5, x + 5, y + 5, fill="#ffffff", outline="#e3222b", tags="paintlive")
            top = ((cs[0][0] + cs[1][0]) / 2, (cs[0][1] + cs[1][1]) / 2)
            c.create_line(*top, *turn, fill="#ffffff", tags="paintlive")
            c.create_oval(turn[0] - 6, turn[1] - 6, turn[0] + 6, turn[1] + 6, fill="#e3a23a", outline="#ffffff",
                          tags="paintlive")
        if self.tool == "shapes" and self.shape_i is not None:
            cur = self.work or self.h.paint_target()
            if cur and self.shape_i < len(cur[1]):
                s = cur[1][self.shape_i]
                pts, closed = paint.outline(s)
                seq = pts + ([pts[0]] if closed else [])
                if len(seq) > 1:
                    c.create_line(*[v for p in seq for v in S(*p)], fill="#e3a23a", dash=(4, 3), tags="paintlive")
                for p in s["pts"]:
                    x, y = S(*p)
                    c.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#ffffff", outline="#e3a23a", width=2,
                                  tags="paintlive")
