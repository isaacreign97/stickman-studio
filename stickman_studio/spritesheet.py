"""Sprite Sheet Export (v3.0): one pipeline for TRACE moves and ANIMATE projects -> PNG sprite sheets + JSON metadata
("stickman-spritesheet/1") for game engines such as Unity. Sources are only read; every export goes into a new
folder or new file names, never over existing files. No AI.

Frames come from the existing code: TRACE = export.prepare (every in-between, as PLAY / FIX) drawn by
export.render_stickman / render_scene; ANIMATE = animate.render with the other tracks left out.
"""
import json
import math
import os
import re
import time

from PIL import Image

import export
import trace_io

FORMAT = "stickman-spritesheet/1"
DEFAULTS = {"layout": "grid", "columns": 8, "rows": 0, "per_sheet": 0, "spacing_x": 2, "spacing_y": 2, "padding": 0,
            "transparent": True, "colour": "#ffffff", "height": 256, "scale": 1.0, "trim": True, "frame_w": 0,
            "frame_h": 0, "frames": "", "sequences": "", "combine": False, "free_layers": False, "fixed": True,
            "metadata": True, "in_place": True}
LAYOUTS = ("horizontal", "vertical", "grid")


class SheetError(Exception):
    pass


def slug(name):
    return export.slug(name) or "sprite"


# ---------------------------------------------------------------- frame selection
def parse_frames(text, n):
    """"1-10, 15, 20-24" (1-based positions in the animation) -> [0-based positions], in the order written.
    Empty = every frame."""
    text = (text or "").strip()
    if not text:
        return list(range(n))
    out = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise SheetError(f"“{part}” isn't a frame or a range like 5-12.")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if not (1 <= a <= n and 1 <= b <= n):
            raise SheetError(f"Frames go from 1 to {n}; “{part}” is outside that.")
        out += list(range(a - 1, b)) if a <= b else list(range(a - 1, b - 2, -1))
    return out


def parse_sequences(text, n):
    """"run: 1-32; slash: 33-50" -> [(name, [positions])]. Empty -> []."""
    out = []
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        if ":" not in part:
            raise SheetError(f"Write a sequence as name: frames, e.g. run: 1-12 (not “{part.strip()}”).")
        name, frames = part.split(":", 1)
        name = name.strip()
        if not name:
            raise SheetError("A sequence needs a name.")
        out.append((name, parse_frames(frames, n)))
    return out


# ---------------------------------------------------------------- sources
class Source:
    """A finished animation, read only. kind "trace" (a move folder in Images) or "animate" (an ANIMATE project)."""

    def __init__(self, kind, path, fixed=True):
        self.kind, self.path, self.fixed = kind, os.path.normpath(path), fixed
        self.name = os.path.basename(self.path)
        self.cache = {}
        if kind == "animate":
            import animate
            self.proj = animate.Project.open(self.path)
            self.fps = float(self.proj.doc["fps"])
            self.frames = list(range(self.proj.doc["length"]))
            self.characters = [(c["id"], c["name"]) for c in self.proj.doc["characters"]]
        elif kind == "trace":
            import characters as chars
            st = dict(export.DEFAULTS, version="auto" if fixed else "trace", data="every", stickman_png=True)
            self.prepared = {}
            for c in chars.list_characters(self.path):
                m = export.prepare(self.path, st, trace_dir=c["trace_dir"] if chars.is_multi(self.path) else None,
                                   label=c["name"])
                full = {f: P for f, P in m["poses"].items() if export.complete(P)}
                if not m["errors"] and full:
                    self.prepared[c["id"]] = (c, m, full)
            if not self.prepared:
                raise SheetError(f"{self.name} has no finished traced frames to make a sprite sheet from.")
            self.characters = [(cid, v[0]["name"]) for cid, v in self.prepared.items()]
            self.fps = float(next(iter(self.prepared.values()))[1]["fps"])
            self.frames = sorted({f for _, _, full in self.prepared.values() for f in full})
        else:
            raise SheetError(f"Unknown animation kind {kind}.")

    def label(self):
        return f"{'ANIMATE' if self.kind == 'animate' else 'TRACE'} · {self.name}"

    def render(self, ids, positions, height, free_layers=False):
        """{position: (RGBA picture, hip (x, y) in it)} for the chosen characters together, every picture the same
        size and in one fixed frame, so the motion is kept. Cached."""
        key = (tuple(ids), height, free_layers)
        got = self.cache.setdefault(key, {})
        need = [p for p in positions if p not in got]
        if need:
            got.update(self._render(ids, need, height, free_layers))
        return {p: got[p] for p in positions}

    def _render(self, ids, positions, height, free_layers):
        import animate as A
        out = {}
        if self.kind == "animate":
            p = self.proj
            keep = set(ids) | {L["id"] for L in p.doc["layers"] if L["owner"] in ids or (free_layers and
                                                                                       not L["owner"])}
            skip = set(p.doc["stack"]) - keep
            for pos in positions:
                f = self.frames[pos]
                img = A.render(p, f, paper=False, skip=skip)
                hip = p.points_at(p.char(ids[0]), f)["hip"]
                out[pos] = (img, (float(hip[0]), float(hip[1])))
            return out
        import trace_player as tp
        figs = [self.prepared[i] for i in ids]
        looks = {c["id"]: tp.Look(sorted(full.items())) for c, _, full in figs}
        boxes = [looks[c["id"]].box for c, _, _ in figs]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        margin = max(4, height // 30)
        k = (height - 2 * margin) / max(1e-6, box[3] - box[1])
        single = len(figs) == 1
        for pos in positions:
            f = self.frames[pos]
            shown = [(full[f], looks[c["id"]], (0, 0, 0) if single else
                      tuple(int(c["colour"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)))
                     for c, _, full in figs if f in full]
            if shown:
                img = export.render_scene(shown, box, height, True)
            else:   # this character isn't on this frame: an empty frame keeps the timing
                w = max(8, int(round((box[2] - box[0]) * k)) + 2 * margin)
                img = Image.new("RGBA", (w, height), (0, 0, 0, 0))
            c0, _, full0 = figs[0]
            P = full0.get(f) or full0[min(full0, key=lambda g: abs(g - f))]
            hip = ((P["hip"][0] - box[0]) * k + margin, (P["hip"][1] - box[1]) * k + margin)
            out[pos] = (img.convert("RGBA"), hip)
        return out


def sources(images):
    """Every animation a sprite sheet can be made from: [(kind, path)] — traced moves, then ANIMATE projects."""
    import animate as A
    out = [("trace", m) for m in A.traced_moves(images)]
    out += [("animate", os.path.join(A.projects_dir(images), n)) for n in A.list_projects(images)]
    return out


# ---------------------------------------------------------------- jobs, layout, sheets
def jobs(src, settings, char_ids):
    """What gets exported: one job per character (or one for all of them when combine is on) and per sequence."""
    s = dict(DEFAULTS, **settings)
    names = dict(src.characters)
    if not char_ids:
        raise SheetError("Tick at least one character.")
    groups = [list(char_ids)] if s["combine"] or len(char_ids) == 1 else [[c] for c in char_ids]
    seqs = parse_sequences(s["sequences"], len(src.frames)) or [(src.name, parse_frames(s["frames"],
                                                                                         len(src.frames)))]
    out = []
    for g in groups:
        for seq, pos in seqs:
            if not pos:
                raise SheetError(f"The sequence {seq} has no frames.")
            out.append({"ids": g, "character": " + ".join(names[i] for i in g), "sequence": seq, "positions": pos})
    return out


def grid(n, s):
    """-> (columns, rows or 0 = as many as needed, frames per sheet) for n frames."""
    per = int(s["per_sheet"] or 0)
    if s["layout"] == "horizontal":
        per = per or n
        return min(per, n), 1, per
    if s["layout"] == "vertical":
        per = per or n
        return 1, min(per, n), per
    cols, rows = max(1, int(s["columns"] or 1)), max(0, int(s["rows"] or 0))
    if rows:
        per = min(per or cols * rows, cols * rows)
    return cols, rows, per or n


def cells(count, cols, rows, layout):
    """(columns, rows) of one sheet holding count frames."""
    if layout == "horizontal":
        return count, 1
    if layout == "vertical":
        return 1, count
    c = min(cols, count) if not rows else cols
    return c, rows or math.ceil(count / c)


def frames_for(src, job, s):
    """The job's frames, trimmed and scaled the same way (so they stay aligned) -> ([(position, img, hip)], (w, h))."""
    got = src.render(job["ids"], job["positions"], int(s["height"]), bool(s["free_layers"]))
    items = [(p, got[p][0], got[p][1]) for p in job["positions"]]
    if s["in_place"]:   # every frame moved sideways so the hip stays at one x (up and down movement is kept)
        x0 = items[0][2][0]
        shifts = [round(x0 - h[0]) for _, _, h in items]
        m = max(abs(d) for d in shifts)
        new = []
        for (p, im, h), d in zip(items, shifts):
            big = Image.new("RGBA", (im.width + 2 * m, im.height), (0, 0, 0, 0))
            big.paste(im, (m + d, 0))
            new.append((p, big, (h[0] + m + d, h[1])))
        items = new
    if s["trim"]:
        box = None
        for _, im, _ in items:
            b = im.getchannel("A").getbbox()
            if b:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]),
                                             max(box[3], b[3]))
        if box:
            items = [(p, im.crop(box), (h[0] - box[0], h[1] - box[1])) for p, im, h in items]
    k = float(s["scale"] or 1.0)
    if k != 1.0:
        items = [(p, im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS),
                  (h[0] * k, h[1] * k)) for p, im, h in items]
    w, h = items[0][1].size
    fw, fh = int(s["frame_w"] or 0), int(s["frame_h"] or 0)
    if fw or fh:      # fit into the asked cell size: proportions kept, centred, standing on the bottom edge
        fw, fh = fw or w, fh or h
        z = min(fw / w, fh / h)
        nw, nh = max(1, round(w * z)), max(1, round(h * z))
        ox, oy = (fw - nw) // 2, fh - nh
        new = []
        for p, im, hp in items:
            cell = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
            cell.alpha_composite(im.resize((nw, nh), Image.LANCZOS) if (nw, nh) != im.size else im, (ox, oy))
            new.append((p, cell, (hp[0] * z + ox, hp[1] * z + oy)))
        items, (w, h) = new, (fw, fh)
    return items, (w, h)


def make(src, job, settings):
    """-> (sheets [RGBA images], metadata dict without file names). The sheets are made in memory only."""
    s = dict(DEFAULTS, **settings)
    items, (fw, fh) = frames_for(src, job, s)
    cols, rows, per = grid(len(items), s)
    sx, sy, pad = int(s["spacing_x"]), int(s["spacing_y"]), int(s["padding"])
    bg = (0, 0, 0, 0) if s["transparent"] else tuple(int(s["colour"].lstrip("#")[i:i + 2], 16)
                                                       for i in (0, 2, 4)) + (255,)
    sheets, frames = [], []
    dur = 1000.0 / src.fps
    for start in range(0, len(items), per):
        chunk = items[start:start + per]
        c, r = cells(len(chunk), cols, rows, s["layout"])
        W, H = 2 * pad + c * fw + (c - 1) * sx, 2 * pad + r * fh + (r - 1) * sy
        sheet = Image.new("RGBA", (W, H), bg)
        for i, (p, im, hp) in enumerate(chunk):
            x, y = pad + (i % c) * (fw + sx), pad + (i // c) * (fh + sy)
            if s["transparent"]:
                sheet.paste(im, (x, y))
            else:
                sheet.alpha_composite(im, (x, y))
            frames.append({"index": len(frames), "source_frame": src.frames[p], "sheet": len(sheets),
                           "x": x, "y": y, "w": fw, "h": fh, "duration_ms": round(dur, 3),
                           "pivot": [round(hp[0], 2), round(hp[1], 2)],
                           "pivot_normalized": [round(hp[0] / fw, 4), round(1 - hp[1] / fh, 4)]})
        sheets.append({"image": sheet, "columns": c, "rows": r, "width": W, "height": H})
    meta = {"format": FORMAT, "animation": src.name, "source": {"kind": src.kind, "path": src.path,
                                                                  "fixed_trace": src.fixed if src.kind == "trace"
                                                                  else None},
            "character": job["character"], "sequence": job["sequence"], "fps": src.fps,
            "frame_duration_ms": round(dur, 3), "frame_count": len(frames), "frame_width": fw, "frame_height": fh,
            "layout": {"type": s["layout"], "columns": cols, "rows": rows, "frames_per_sheet": per,
                       "spacing_x": sx, "spacing_y": sy, "padding": pad},
            "background": "transparent" if s["transparent"] else s["colour"],
            "scale": float(s["scale"]), "trimmed": bool(s["trim"]),
            "sequences": [{"name": job["sequence"], "from": 0, "to": len(frames) - 1, "loop": True}],
            "pivot_note": "pivot = the hip of the first character, in frame pixels (x right, y down); "
                          "pivot_normalized = Unity style (0..1, y up)",
            "sheets": [{k: v for k, v in sh.items() if k != "image"} for sh in sheets], "frames": frames,
            "made": time.strftime("%Y-%m-%d %H:%M:%S"), "made_by": "Stickman Studio sprite sheet export"}
    return [sh["image"] for sh in sheets], meta


def unique(path):
    base, ext = os.path.splitext(path)
    k = 2
    while os.path.exists(path):
        path, k = f"{base}_{k}{ext}", k + 1
    return path


def default_dest(images, src):
    return os.path.join(os.path.dirname(os.path.normpath(images)), "Exports",
                        f"{src.name} sprites {time.strftime('%Y-%m-%d %H%M%S')}")


def run(src, settings, char_ids, dest):
    """Write every job's sheets (PNG) and metadata (JSON) into dest (made if needed; nothing in it is ever
    overwritten: a taken name gets _2, _3 …). -> [written paths]."""
    s = dict(DEFAULTS, **settings)
    os.makedirs(dest, exist_ok=True)
    written = []
    for job in jobs(src, s, char_ids):
        sheets, meta = make(src, job, s)
        stem = "_".join(dict.fromkeys([slug(src.name), slug(job["character"]), slug(job["sequence"])]))
        for i, (im, info) in enumerate(zip(sheets, meta["sheets"])):
            p = unique(os.path.join(dest, f"{stem}{'' if len(sheets) == 1 else f'_sheet{i + 1}'}.png"))
            im.save(p)
            info["file"] = os.path.basename(p)
            written.append(p)
        if s["metadata"]:
            p = unique(os.path.join(dest, f"{stem}.json"))
            trace_io.write_atomic(p, json.dumps(meta, indent=1))
            written.append(p)
    return written
