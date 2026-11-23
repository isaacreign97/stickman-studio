"""ANIMATE (v3.0): a hybrid stickman animation project. Skeleton keys (Pivot-style) and frame-by-frame drawing
layers (FlipaClip-style) on one shared timeline, optional drawing-to-skeleton rigs, several characters.

No AI / ML / pose detection: plain geometry (forward kinematics, monotone cubic interpolation) and Pillow / numpy.

A pose is stored as the hip position, a whole-body turn and one angle per bone RELATIVE to its parent bone, so a
bone's length can only change on purpose (proportions unlocked + Ctrl+drag). That is what stops the wobble: an
in-between can turn the limbs but never stretch them.

Project folder  <Images parent>\\Animations\\<name>\\
  animation.json            this module's data (format "stickman-animate/1")
  cels\\<cel id>.png         drawing cels (RGBA, canvas size)
  rigs\\<char id>_art.png    a rigged character's working artwork; _original.png (never changed); _map.png (binding)
  pictures\\<picture id>.png   v3.2: painted pictures (props, backgrounds, pictures on a figure's bones)
  backups\\animation_<stamp>.json   the previous animation.json, before each save (the last 30 kept)
TRACE moves are only read: importing copies their points into the project.
"""
import copy
import json
import math
import os
import re
import shutil
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import trace_io

FORMAT = "stickman-animate/1"
FORMAT2 = "stickman-animate/2"   # v3.2: figures, attachments, paths, pictures, shapes, story (only when used)
ROOT = "hip"                     # every track's root joint (a figure's too): the red handle that moves it
SEG_SHAPES = ("line", "circle", "box", "ellipse", "none")
ORDER = trace_io.ORDER
PARENT = {"hip": None, "waist": "hip", "neck": "waist", "head": "neck", "backKnee": "hip", "backFoot": "backKnee",
          "frontKnee": "hip", "frontFoot": "frontKnee", "frontElbow": "neck", "frontHand": "frontElbow",
          "backElbow": "neck", "backHand": "backElbow"}
FK = ["hip", "waist", "neck", "head", "backKnee", "backFoot", "frontKnee", "frontFoot", "frontElbow", "frontHand",
      "backElbow", "backHand"]
BONES = FK[1:]        # a bone is named after its end joint: the 11 bones of the 12 required joints, as TRACE
EXTRAS = trace_io.EXTRAS   # v3.0: optional shoulders, hand tips, toes (never required; rigs use the 12)
FK_ALL = ["waist", "neck", "head", "backKnee", "backFoot", "backToe", "frontKnee", "frontFoot", "frontToe",
          "frontShoulder", "frontElbow", "frontHand", "frontHandTip", "backShoulder", "backElbow", "backHand",
          "backHandTip"]
EXTRA_GROUPS = {"shoulders": ("frontShoulder", "backShoulder"), "handtips": ("frontHandTip", "backHandTip"),
                "toes": ("frontToe", "backToe")}
DRAW_ORDER = ["backKnee", "backFoot", "backElbow", "backHand", "waist", "neck", "head", "frontKnee", "frontFoot",
              "frontElbow", "frontHand"]
INTERP = ("smooth", "linear", "hold")
PALETTE = ["#111111", "#1e6eff", "#e3222b", "#2fb35a", "#e3a23a", "#9b59d0", "#16a5a5", "#d0407c"]
MAX_UNDO = 80
SEAM = 3              # rigid rig parts overlap their neighbours by this many pixels (no gaps at turned joints)
REST = {"head": (0, -178), "neck": (0, -146), "waist": (0, -76), "hip": (0, 0), "backKnee": (-14, 52),
        "backFoot": (-22, 104), "frontKnee": (16, 52), "frontFoot": (24, 104), "frontElbow": (14, -102),
        "frontHand": (30, -62), "backElbow": (-12, -102), "backHand": (-26, -62)}


class AnimateError(Exception):
    pass


# ---------------------------------------------------------------- skeleton maths
def wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def parent_of(j, present=()):
    """The joint j hangs from. v3.0: an elbow hangs from its shoulder when the character has one; the optional
    hand tips and toes hang from the hand and the foot."""
    if j.endswith("Elbow") and j.replace("Elbow", "Shoulder") in present:
        return j.replace("Elbow", "Shoulder")
    return PARENT.get(j) or trace_io.EXTRA_PARENT[j]


def bones_of(present=()):
    """The bones in forward-kinematics order: the 11, plus the optional ones present (each after its parent)."""
    return [j for j in FK_ALL if j in BONES or j in present]


def pose_from_points(P, rot=0.0):
    """{joint: (x, y)} -> (pose, lengths). pose = {"root": [x, y], "rot": deg, "ang": {bone: deg relative}}.
    Optional joints in P (shoulders, hand tips, toes) become bones of their own."""
    present = {e for e in EXTRAS if e in P}
    ab, ang, lens = {}, {}, {}
    for j in bones_of(present):
        p = parent_of(j, present)
        dx, dy = P[j][0] - P[p][0], P[j][1] - P[p][1]
        ab[j] = math.degrees(math.atan2(dy, dx))
        lens[j] = math.hypot(dx, dy)
        base = rot if p == "hip" else ab[p]
        ang[j] = wrap(ab[j] - base)
    return {"root": [float(P["hip"][0]), float(P["hip"][1])], "rot": float(rot), "ang": ang}, lens


def points(pose, lengths):
    """Forward kinematics: pose + bone lengths -> {joint: (x, y)}. Lengths come from the character (or the key's
    own "len" when proportions were changed on purpose)."""
    L = dict(lengths)
    L.update(pose.get("len") or {})
    P = {"hip": (pose["root"][0], pose["root"][1])}
    present = set(pose["ang"])
    ab = {}
    for j in bones_of(present):
        p = parent_of(j, present)
        ab[j] = (pose["rot"] if p == "hip" else ab[p]) + pose["ang"][j]
        r = math.radians(ab[j])
        P[j] = (P[p][0] + L[j] * math.cos(r), P[p][1] + L[j] * math.sin(r))
    return P


def absolute_angles(pose):
    present = set(pose["ang"])
    ab = {}
    for j in bones_of(present):
        p = parent_of(j, present)
        ab[j] = (pose["rot"] if p == "hip" else ab[p]) + pose["ang"][j]
    return ab


def joint_parent(c, j, present=()):
    """The joint j hangs from, for any kind of track (v3.2: a figure's bones say it themselves)."""
    if c["kind"] == "figure":
        for s in c["figure"]["segs"]:
            if s["id"] == j:
                return s["parent"] or ROOT
        return ROOT
    return parent_of(j, present)


def fk(c, pose):
    """-> ({joint: (x, y)}, {bone: angle on screen}) for a stickman, a rigged drawing or a figure."""
    if c["kind"] != "figure":
        return points(pose, c["lengths"]), absolute_angles(pose)
    L = dict(c["lengths"])
    L.update(pose.get("len") or {})
    P = {ROOT: (pose["root"][0], pose["root"][1])}
    ab = {}
    for s in c["figure"]["segs"]:   # parents always come before their children
        j, p = s["id"], s["parent"] or ROOT
        if j not in pose["ang"] or p not in P or j not in L:
            continue
        ab[j] = (pose["rot"] if p == ROOT else ab[p]) + pose["ang"][j]
        r = math.radians(ab[j])
        P[j] = (P[p][0] + L[j] * math.cos(r), P[p][1] + L[j] * math.sin(r))
    return P, ab


def limbs(c, P):
    """Pairs of joints to draw as lines (handles, onion skin)."""
    if c["kind"] == "figure":
        return [(s["parent"] or ROOT, s["id"]) for s in c["figure"]["segs"] if s["id"] in P]
    return [(a, b) for limb in trace_io.chains(P) for a, b in zip(limb, limb[1:])]


_PATHS = {}


def path_curve(path):
    """The path as dense points along the curve and the distance travelled to each."""
    key = json.dumps([path["pts"], bool(path.get("closed"))])
    if key not in _PATHS:
        import paint
        pts = paint.curve_points(path["pts"], bool(path.get("closed")) and len(path["pts"]) > 2)
        d = [0.0]
        for a, b in zip(pts, pts[1:]):
            d.append(d[-1] + math.dist(a, b))
        if len(_PATHS) > 200:
            _PATHS.clear()
        _PATHS[key] = (pts, d)
    return _PATHS[key]


def path_at(path, f):
    """(x, y, direction in degrees) on the path on frame f: from its start frame to its end frame, evenly along the
    curve (smooth = slow in and out). Before the start it waits at the beginning, after the end at the end."""
    pts, d = path_curve(path)
    s, e = path.get("start", 0), path.get("end", 1)
    t = 0.0 if e <= s else max(0.0, min(1.0, (f - s) / (e - s)))
    if path.get("ease", "smooth") == "smooth":
        t = t * t * (3 - 2 * t)
    want = t * d[-1]
    i = 0
    while i < len(d) - 2 and d[i + 1] < want:
        i += 1
    a, b = pts[i], pts[min(i + 1, len(pts) - 1)]
    seg = d[min(i + 1, len(d) - 1)] - d[i]
    u = 0.0 if seg < 1e-9 else (want - d[i]) / seg
    x, y = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
    if seg < 1e-9:   # a standing point: the direction of the nearest real piece
        k = next((k for k in range(len(pts) - 1) if math.dist(pts[k], pts[k + 1]) > 1e-9), 0)
        a, b = pts[k], pts[min(k + 1, len(pts) - 1)]
    return x, y, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def rest_pose(x=0.0, y=0.0, scale=1.0):
    P = {n: (x + v[0] * scale, y + v[1] * scale) for n, v in REST.items()}
    return pose_from_points(P)


def monotone(xs, ys, x):
    """Monotone cubic (Fritsch-Carlson) through (xs, ys) at x: smooth, and never overshoots past a key."""
    n = len(xs)
    if n == 1 or x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = max(k for k in range(n - 1) if xs[k] <= x)
    d = [(ys[k + 1] - ys[k]) / (xs[k + 1] - xs[k]) for k in range(n - 1)]
    m = [d[0]] + [0.0 if d[k - 1] * d[k] <= 0 else (d[k - 1] + d[k]) / 2 for k in range(1, n - 1)] + [d[-1]]
    for k in range(n - 1):
        if d[k] == 0:
            m[k] = m[k + 1] = 0.0
        else:
            a, b = m[k] / d[k], m[k + 1] / d[k]
            s = a * a + b * b
            if s > 9:
                t = 3 / math.sqrt(s)
                m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    h = xs[i + 1] - xs[i]
    t = (x - xs[i]) / h
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1]


def unwrapped(vals):
    out = [vals[0]]
    for v in vals[1:]:
        out.append(out[-1] + wrap(v - out[-1]))
    return out


# ---------------------------------------------------------------- the project
def new_id(prefix, taken):
    while True:
        i = prefix + os.urandom(3).hex()
        if i not in taken:
            return i


def clean_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name or "")).strip().strip(".")
    if not name:
        raise AnimateError("Give it a name.")
    return name[:60]


def projects_dir(images):
    return os.path.join(os.path.dirname(os.path.normpath(images)), "Animations")


def list_projects(images):
    d = projects_dir(images)
    try:
        return sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "animation.json")))
    except OSError:
        return []


class Project:
    """An ANIMATE project in memory. doc is plain JSON data; cel / rig pictures live in self.images (PIL)."""

    def __init__(self, folder, doc=None):
        self.folder = folder
        self.doc = doc or {"format": FORMAT, "name": os.path.basename(folder), "fps": 12, "length": 24,
                           "width": 960, "height": 540, "loop": True, "onion": [1, 1], "rigging": False,
                           "characters": [], "layers": [], "stack": []}
        self.images = {}          # "cel:<id>" / "art:<cid>" / "orig:<cid>" / "map:<cid>" -> PIL image (loaded lazily)
        self.dirty_images = set()
        self.undo_stack, self.redo_stack = [], []
        self.changed = False
        self.version = 0          # bumped on every change: render caches compare it

    # ---- files
    @classmethod
    def create(cls, images, name, fps=12, length=24, width=960, height=540):
        name = clean_name(name)
        folder = os.path.join(projects_dir(images), name)
        if os.path.exists(folder):
            raise AnimateError(f"There's already an animation called {name}.")
        p = cls(folder)
        p.doc.update(name=name, fps=int(fps), length=max(1, int(length)), width=int(width), height=int(height))
        p.save()
        return p

    @classmethod
    def open(cls, folder):
        try:
            doc = trace_io.read_json(os.path.join(folder, "animation.json"))
        except (OSError, ValueError) as e:
            raise AnimateError(f"It couldn't be read: {e}") from e
        if doc.get("format") not in (FORMAT, FORMAT2):
            raise AnimateError("That isn't an Animate project.")
        for c in doc["characters"]:
            c["keys"] = {int(f): k for f, k in c["keys"].items()}
        return cls(folder, doc)

    def uses_v32(self):
        """True when the animation uses something new in v3.2 (it's then saved as format 2)."""
        d = self.doc
        return bool(d.get("pictures") or d.get("story") or any(c["kind"] == "figure" or c.get("attach") or c.get("path")
                                                                for c in d["characters"])
                    or any(c.get("shapes") for L in d["layers"] for c in L["cels"]))

    def save(self):
        os.makedirs(os.path.join(self.folder, "cels"), exist_ok=True)
        os.makedirs(os.path.join(self.folder, "rigs"), exist_ok=True)
        if self.doc.get("pictures"):
            os.makedirs(os.path.join(self.folder, "pictures"), exist_ok=True)
        js = os.path.join(self.folder, "animation.json")
        if os.path.exists(js):   # the previous version is kept
            b = os.path.join(self.folder, "backups")
            os.makedirs(b, exist_ok=True)
            shutil.copy2(js, os.path.join(b, f"animation_{time.strftime('%Y%m%d-%H%M%S')}_{self.version}.json"))
            old = sorted(os.listdir(b))
            for n in old[:-30]:
                os.remove(os.path.join(b, n))
        for key in sorted(self.dirty_images):
            if key in self.images:
                self.images[key].save(self.image_path(key))
        self.dirty_images.clear()
        used = {c["img"] + ".png" for L in self.doc["layers"] for c in L["cels"]}
        pics = {p + ".png" for p in self.doc.get("pictures") or {}}
        for key, im in self.images.items():   # v3.2: a drawing brought back by undo after a save is written again
            kind, i = key.split(":", 1)
            if (kind == "cel" and i + ".png" in used or kind == "pic" and i + ".png" in pics) and \
                    not os.path.exists(self.image_path(key)):
                im.save(self.image_path(key))
        for n in os.listdir(os.path.join(self.folder, "cels")):
            if n.lower().endswith(".png") and n not in used:
                os.remove(os.path.join(self.folder, "cels", n))
        pd = os.path.join(self.folder, "pictures")
        if os.path.isdir(pd):
            for n in os.listdir(pd):
                if n.lower().endswith(".png") and n not in pics:
                    os.remove(os.path.join(pd, n))
        doc = dict(self.doc, characters=[dict(c, keys={str(f): k for f, k in sorted(c["keys"].items())})
                                         for c in self.doc["characters"]])
        doc["format"] = FORMAT2 if self.uses_v32() else FORMAT
        trace_io.write_atomic(js, json.dumps(doc, indent=1))
        self.changed = False

    def image_path(self, key):
        kind, i = key.split(":", 1)
        if kind == "cel":
            return os.path.join(self.folder, "cels", i + ".png")
        if kind == "pic":
            return os.path.join(self.folder, "pictures", i + ".png")
        suffix = {"art": "art", "orig": "original", "map": "map"}[kind]
        return os.path.join(self.folder, "rigs", f"{i}_{suffix}.png")

    def image(self, key):
        if key not in self.images:
            p = self.image_path(key)
            if os.path.exists(p):
                with Image.open(p) as im:
                    self.images[key] = im.convert("L" if key.startswith("map:") else "RGBA")
            elif key.startswith("cel:"):
                self.images[key] = Image.new("RGBA", self.size, (0, 0, 0, 0))
            else:
                return None
        return self.images[key]

    def set_image(self, key, img):
        self.images[key] = img
        self.dirty_images.add(key)

    @property
    def size(self):
        return self.doc["width"], self.doc["height"]

    # ---- undo
    def snapshot(self, label, keys=()):
        """Call BEFORE a change. keys = the pictures the change will touch (copied so undo can bring them back)."""
        self.undo_stack.append((label, copy.deepcopy(self.doc), {k: self.image(k).copy() for k in keys
                                                                 if self.image(k) is not None}))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()
        self.touch()

    def touch(self):
        self.changed = True
        self.version += 1

    def _swap(self, src, dst):
        if not src:
            return None
        label, doc, imgs = src.pop()
        dst.append((label, self.doc, {k: self.image(k).copy() for k in imgs if self.image(k) is not None}))
        self.doc = doc
        for k, im in imgs.items():
            self.set_image(k, im)
        self.touch()
        return label

    def undo(self):
        return self._swap(self.undo_stack, self.redo_stack)

    def redo(self):
        return self._swap(self.redo_stack, self.undo_stack)

    # ---- tracks
    def ids(self):
        return {c["id"] for c in self.doc["characters"]} | {L["id"] for L in self.doc["layers"]}

    def char(self, cid):
        for c in self.doc["characters"]:
            if c["id"] == cid:
                return c
        raise AnimateError("That character isn't in this animation.")

    def layer(self, lid):
        for L in self.doc["layers"]:
            if L["id"] == lid:
                return L
        raise AnimateError("That layer isn't in this animation.")

    def add_character(self, name=None, kind="stick", x=None, y=None, scale=1.0):
        self.snapshot("add a character")
        n = len(self.doc["characters"])
        W, H = self.size
        pose, lens = rest_pose(W * (0.3 + 0.2 * (n % 3)) if x is None else x, H * 0.78 if y is None else y, scale)
        c = {"id": new_id("ch_", self.ids()), "name": clean_name(name or f"Character {n + 1}"),
             "colour": PALETTE[n % len(PALETTE)], "visible": True, "locked": False, "kind": kind, "facing": 1,
             "lengths": lens, "lock": True, "interp": "smooth", "keys": {0: pose}, "rig": None}
        self.doc["characters"].append(c)
        self.doc["stack"].append(c["id"])
        return c

    def add_layer(self, name=None, owner=None):
        self.snapshot("add a drawing layer")
        L = {"id": new_id("ly_", self.ids()), "name": clean_name(name or f"Layer {len(self.doc['layers']) + 1}"),
             "owner": owner, "visible": True, "locked": False, "opacity": 1.0, "cels": []}
        self.doc["layers"].append(L)
        self.doc["stack"].append(L["id"])
        return L

    def remove_track(self, tid):
        for c in self.doc["characters"]:   # v3.2: things attached to it stay where they are on screen
            if (c.get("attach") or {}).get("to") == tid:
                self._rebase(c, lambda c=c: c.pop("attach", None), 0)
        self.snapshot("delete a track")
        self.doc["characters"] = [c for c in self.doc["characters"] if c["id"] != tid]
        self.doc["layers"] = [L for L in self.doc["layers"] if L["id"] != tid]
        for L in self.doc["layers"]:
            if L["owner"] == tid:
                L["owner"] = None
        self.doc["stack"] = [i for i in self.doc["stack"] if i != tid]

    def restack(self, tid, d):
        s = self.doc["stack"]
        i = s.index(tid)
        j = max(0, min(len(s) - 1, i + d))
        if i != j:
            self.snapshot("change the drawing order")
            s.insert(j, s.pop(i))

    def editable(self, tid):
        """False for a locked track, or a layer whose character is locked."""
        try:
            t = self.char(tid)
        except AnimateError:
            t = self.layer(tid)
            if t["owner"]:
                try:
                    if self.char(t["owner"])["locked"]:
                        return False
                except AnimateError:
                    pass
        return not t["locked"]

    def shown(self, tid):
        try:
            t = self.char(tid)
        except AnimateError:
            t = self.layer(tid)
            if t["owner"]:
                try:
                    if not self.char(t["owner"])["visible"]:
                        return False
                except AnimateError:
                    pass
        return t["visible"]

    # ---- skeleton keys
    def pose_at(self, c, f):
        """The character's pose on frame f: its key, or the in-between (smooth, linear or hold)."""
        keys = c["keys"]
        if f in keys:
            return keys[f]
        fs = sorted(keys)
        if not fs:
            return rest_pose()[0]
        if f <= fs[0]:
            return keys[fs[0]]
        if f >= fs[-1]:
            return keys[fs[-1]]
        if c["interp"] == "hold":
            return keys[max(k for k in fs if k <= f)]
        if c["interp"] == "linear":
            a = max(k for k in fs if k <= f)
            fs = [a, min(k for k in fs if k > f)]
        ks = [keys[k] for k in fs]
        bones = [j for j in ks[0]["ang"] if all(j in k["ang"] for k in ks)]   # incl. optional joints it has
        out = {"root": [monotone(fs, [k["root"][i] for k in ks], f) for i in (0, 1)],
               "rot": monotone(fs, unwrapped([k["rot"] for k in ks]), f),
               "ang": {j: wrap(monotone(fs, unwrapped([k["ang"][j] for k in ks]), f)) for j in bones}}
        if any(k.get("len") for k in ks):
            out["len"] = {j: monotone(fs, [(k.get("len") or {}).get(j, c["lengths"][j]) for k in ks], f)
                          for j in bones}
        return out

    def points_at(self, c, f):
        return fk(c, self.world_pose(c, f))[0]

    def angles_at(self, c, f):
        """Every bone's angle on screen (degrees) on frame f, and the root's as "hip"."""
        w = self.world_pose(c, f)
        ab = dict(fk(c, w)[1])
        ab[ROOT] = w["rot"]
        return ab

    # ---- v3.2: attachments and motion paths
    def base(self, c, f, depth=0):
        """Where a track's own coordinates sit on frame f: (x, y, angle) of the joint it's attached to, or (0, 0, 0)."""
        at = c.get("attach")
        if not at or depth > 30:
            return 0.0, 0.0, 0.0
        try:
            par = self.char(at["to"])
        except AnimateError:
            return 0.0, 0.0, 0.0
        w = self.world_pose(par, f, depth + 1)
        P, ab = fk(par, w)
        j = at["joint"] if at["joint"] in P else ROOT
        return P[j][0], P[j][1], (w["rot"] if j == ROOT else ab[j])

    def world_pose(self, c, f, depth=0):
        """The pose on screen: the key / in-between, with the root on its path and inside what it's attached to."""
        pose = self.pose_at(c, f)
        root, rot = list(pose["root"]), pose["rot"]
        if c.get("path") and len(c["path"]["pts"]) >= 2:
            x, y, tang = path_at(c["path"], f)
            root = [x, y]
            if c["path"].get("orient"):
                rot = rot + tang
        if c.get("attach"):
            bx, by, ba = self.base(c, f, depth)
            r = math.radians(ba)
            root = [bx + root[0] * math.cos(r) - root[1] * math.sin(r), by + root[0] * math.sin(r) + root[1] * math.cos(r)]
            rot = rot + ba
        out = dict(pose, root=root, rot=rot)
        return out

    def to_local(self, c, f, x, y):
        """A point on screen in the track's own coordinates (inside what it's attached to)."""
        bx, by, ba = self.base(c, f)
        r = math.radians(-ba)
        dx, dy = x - bx, y - by
        return [dx * math.cos(r) - dy * math.sin(r), dx * math.sin(r) + dy * math.cos(r)]

    def attachable(self, c, to):
        """None when c can be attached to the track `to`, else the reason why not."""
        if to == c["id"]:
            return "A track can't be attached to itself."
        t = to
        for _ in range(60):
            if t == c["id"]:
                return "That would attach it to something that's already attached to it."
            try:
                nxt = (self.char(t).get("attach") or {}).get("to")
            except AnimateError:
                return "That track isn't in this animation."
            if not nxt:
                return None
            t = nxt
        return "Too many attachments in a row."

    def _rebase(self, c, change, f):
        """Change what c is attached to (change() edits c["attach"]) without anything moving: every key keeps its
        place on screen (and its path, on frame f)."""
        before = {k: self.world_pose(c, k) for k in c["keys"]}
        path0 = None
        if c.get("path"):
            bx, by, ba = self.base(c, f)
            r = math.radians(ba)
            path0 = [[bx + x * math.cos(r) - y * math.sin(r), by + x * math.sin(r) + y * math.cos(r)]
                     for x, y in c["path"]["pts"]]
        change()
        if path0:   # the path first: its direction counts for "follow the path"
            c["path"]["pts"] = [self.to_local(c, f, x, y) for x, y in path0]
        for k, w in before.items():
            bx, by, ba = self.base(c, k)
            key = c["keys"][k]
            orient = 0.0
            if c.get("path") and c["path"].get("orient") and len(c["path"]["pts"]) >= 2:
                orient = path_at(c["path"], k)[2]
            if not c.get("path"):
                key["root"] = self.to_local(c, k, *w["root"])
            key["rot"] = wrap(w["rot"] - ba - orient)

    def attach(self, c, to, joint, f=0):
        """Attach track c to a joint of track `to` (a sword to a hand, a rider to a cart): it then follows it on
        every frame, and its own keys are kept as they look now."""
        why = self.attachable(c, to)
        if why:
            raise AnimateError(why)
        if joint not in self.points_at(self.char(to), f):
            raise AnimateError("That joint isn't on it.")
        self.snapshot("attach")
        self._rebase(c, lambda: c.__setitem__("attach", {"to": to, "joint": joint}), f)

    def detach(self, c, f=0):
        if not c.get("attach"):
            return False
        self.snapshot("detach")
        if f not in c["keys"]:   # it stays exactly where it is on this frame
            self.set_key(c, f, self.pose_at(c, f))
        self._rebase(c, lambda: c.pop("attach", None), f)
        return True

    def set_path(self, c, pts, f=0, start=None, end=None):
        """A motion path: the root travels along the curve through pts (points on screen) from frame start to end."""
        if len(pts) < 2:
            raise AnimateError("A path needs at least two points.")
        self.snapshot("motion path")
        old = c.get("path") or {}
        keys = sorted(c["keys"])
        c["path"] = {"pts": [self.to_local(c, f, x, y) for x, y in pts],
                     "start": int(old.get("start", 0) if start is None else start),
                     "end": int(old.get("end", self.doc["length"] - 1) if end is None else end),
                     "ease": old.get("ease", "smooth"), "orient": bool(old.get("orient", False)),
                     "closed": bool(old.get("closed", False))}
        if c["path"]["end"] <= c["path"]["start"]:
            c["path"]["end"] = max(c["path"]["start"] + 1, keys[-1] if keys else 1)
        return c["path"]

    def clear_path(self, c):
        """Take the path away: the track stays where the path had it on each key frame."""
        if not c.get("path"):
            return False
        self.snapshot("clear the path")
        for k in c["keys"]:
            x, y, tang = path_at(c["path"], k)
            c["keys"][k]["root"] = [x, y]
            if c["path"].get("orient"):
                c["keys"][k]["rot"] = wrap(c["keys"][k]["rot"] + tang)
        c.pop("path")
        return True

    def path_points_on_screen(self, c, f):
        if not c.get("path"):
            return []
        bx, by, ba = self.base(c, f)
        r = math.radians(ba)
        return [(bx + x * math.cos(r) - y * math.sin(r), by + x * math.sin(r) + y * math.cos(r))
                for x, y in c["path"]["pts"]]

    def move_path(self, c, f, dx, dy):
        """Move the whole path by (dx, dy) on screen."""
        r = math.radians(-self.base(c, f)[2])
        lx, ly = dx * math.cos(r) - dy * math.sin(r), dx * math.sin(r) + dy * math.cos(r)
        c["path"]["pts"] = [[x + lx, y + ly] for x, y in c["path"]["pts"]]

    def set_key(self, c, f, pose):
        c["keys"][f] = copy.deepcopy(pose)

    def drag_joint(self, c, f, joint, x, y, stretch=False):
        """Pivot-style: the hip moves the figure; any other joint turns its bone around its parent joint and the
        joints below it follow. stretch=True (proportions unlocked only) changes that bone's length on this key."""
        pose = copy.deepcopy(self.pose_at(c, f))
        if joint == ROOT:
            if c.get("path"):   # v3.2: a track on a path: the path moves with it
                P = self.points_at(c, f)
                self.move_path(c, f, x - P[ROOT][0], y - P[ROOT][1])
                return
            pose["root"] = [float(v) for v in self.to_local(c, f, x, y)]
        else:
            P, ab = fk(c, self.world_pose(c, f))
            p = P[joint_parent(c, joint, pose["ang"])]
            new = math.degrees(math.atan2(y - p[1], x - p[0]))
            old = ab[joint]
            pose["ang"][joint] = wrap(pose["ang"][joint] + wrap(new - old))
            if stretch:
                if c["lock"]:
                    raise AnimateError("Proportions are locked: untick Lock Proportions to stretch a bone.")
                pose.setdefault("len", {})[joint] = max(2.0, math.hypot(x - p[0], y - p[1]))
        self.set_key(c, f, pose)

    def turn_body(self, c, f, x, y, x0, y0):
        """Turn the whole figure around its hip by the angle the mouse moved through."""
        pose = copy.deepcopy(self.pose_at(c, f))
        h = self.points_at(c, f)[ROOT]
        d = math.degrees(math.atan2(y - h[1], x - h[0]) - math.atan2(y0 - h[1], x0 - h[0]))
        pose["rot"] = wrap(pose["rot"] + d)
        self.set_key(c, f, pose)

    def move_chars(self, cids, f, dx, dy):
        """Group move: every character keeps its pose and their distances stay exactly the same."""
        moving = set(cids)
        for cid in cids:
            c = self.char(cid)
            if (c.get("attach") or {}).get("to") in moving:   # v3.2: it goes along with what it's attached to
                continue
            if c.get("path"):
                self.move_path(c, f, dx, dy)
                continue
            pose = copy.deepcopy(self.pose_at(c, f))
            r = math.radians(-self.base(c, f)[2])
            pose["root"] = [pose["root"][0] + dx * math.cos(r) - dy * math.sin(r),
                            pose["root"][1] + dx * math.sin(r) + dy * math.cos(r)]
            self.set_key(c, f, pose)

    def reset_proportions(self, c, f):
        if f in c["keys"]:
            c["keys"][f].pop("len", None)

    def bone_spread(self, c, frames=None):
        """Largest change of any bone's length over the frames, as a fraction (0 = perfectly stable)."""
        worst = 0.0
        frames = range(self.doc["length"]) if frames is None else frames
        pts = [self.points_at(c, f) for f in frames]
        present = set(c.get("extras") or ())
        if c["kind"] == "figure":
            for s in c["figure"]["segs"]:
                v = [math.dist(P[s["id"]], P[s["parent"] or ROOT]) for P in pts]
                worst = max(worst, (max(v) - min(v)) / max(1e-9, c["lengths"][s["id"]]))
            return worst
        for j in bones_of(present):
            v = [math.dist(P[j], P[parent_of(j, present)]) for P in pts]
            worst = max(worst, (max(v) - min(v)) / max(1e-9, c["lengths"][j]))
        return worst

    def set_extras(self, c, group, on):
        """v3.0: give a stickman (or take away) optional joints: "shoulders", "handtips" or "toes", both sides.
        Every key keeps its pose: a new shoulder starts on the upper arm near the neck, a hand tip carries on from
        the forearm, a toe points the foot forward from the shin (as drawn without one)."""
        if c["kind"] == "rig":
            raise AnimateError("Rigged drawings use the 12 joints; optional joints are for stickmen.")
        if c["kind"] == "figure":
            raise AnimateError("A figure has its own bones: Build (J) adds one anywhere.")
        names = EXTRA_GROUPS[group]
        have = set(c.get("extras") or ())
        want = (have | set(names)) if on else (have - set(names))
        if want == have:
            return False
        self.snapshot(("add " if on else "remove ") + group)
        import trace_player as tp
        look = look_for(c)
        new = {}
        for f, k in c["keys"].items():
            P = dict(points(k, c["lengths"]))
            for n in names:
                if not on:
                    P.pop(n, None)
                    continue
                side = "front" if n.startswith("front") else "back"
                if n.endswith("Shoulder"):
                    nk, el = P["neck"], P[side + "Elbow"]
                    P[n] = (nk[0] + 0.2 * (el[0] - nk[0]), nk[1] + 0.2 * (el[1] - nk[1]))
                elif n.endswith("HandTip"):
                    el, hd = P[side + "Elbow"], P[side + "Hand"]
                    P[n] = (hd[0] + 0.35 * (hd[0] - el[0]), hd[1] + 0.35 * (hd[1] - el[1]))
                else:
                    P[n] = tp.foot_tip(P[side + "Knee"], P[side + "Foot"], look)
            new[f] = pose_from_points(P, k["rot"])
        bones = list(next(iter(new.values()))[0]["ang"])
        med = {j: sorted(L[j] for _, L in new.values())[len(new) // 2] for j in bones}
        c["keys"] = {}
        for f, (pose, L) in new.items():
            odd = {j: L[j] for j in bones if abs(L[j] - med[j]) > 0.5}   # a stretched key stays as it was
            if odd:
                pose["len"] = odd
            c["keys"][f] = pose
        c["lengths"] = med
        c["extras"] = [e for e in EXTRAS if e in want]
        return True

    # ---- v3.2: pictures (painted pixels + editable shapes), used by figures, props and backgrounds
    def add_picture(self, img, shapes=None, name="Picture"):
        """Keep a picture in the animation. -> its id. (Call snapshot() first: this is part of a change.)"""
        pics = self.doc.setdefault("pictures", {})
        pid = new_id("pic_", set(pics))
        pics[pid] = {"name": str(name)[:60], "shapes": copy.deepcopy(shapes or [])}
        self.set_image(f"pic:{pid}", img.convert("RGBA").copy())
        return pid

    def set_picture(self, pid, img, shapes):
        self.snapshot("edit the picture", [f"pic:{pid}"])
        self.doc["pictures"][pid]["shapes"] = copy.deepcopy(shapes or [])
        self.set_image(f"pic:{pid}", img.convert("RGBA").copy())

    def picture_raw(self, pid):
        """(painted pixels, shapes) of a picture, to edit."""
        im = self.image(f"pic:{pid}")
        return (im.copy() if im is not None else None), copy.deepcopy(self.doc["pictures"][pid]["shapes"])

    _flat = None

    def picture(self, pid):
        """A picture as you see it (pixels + shapes), cached."""
        im = self.image(f"pic:{pid}")
        if im is None:
            return None
        return self._flatten(im, self.doc["pictures"][pid].get("shapes"))

    def cel_picture(self, cel):
        return self._flatten(self.image(f"cel:{cel['img']}"), cel.get("shapes"))

    def _flatten(self, im, shapes):
        if not shapes:
            return im
        import paint
        if self._flat is None:
            self._flat = {}
        key = (id(im), paint.shapes_key(shapes))
        if key not in self._flat:
            if len(self._flat) > 120:
                self._flat.clear()
            self._flat[key] = (im, paint.flatten(im, shapes))   # im kept so its id can't be reused
        return self._flat[key][1]

    def set_cel_content(self, lid, f, img, shapes, label="paint"):
        """Replace the drawing on frame f of a layer (pixels and shapes) as one undo step."""
        L = self.layer(lid)
        if not self.editable(lid):
            raise AnimateError("That layer is locked.")
        before = self.cel_at(L, f)
        self.snapshot(label, [f"cel:{before['img']}"] if before else [])
        cel = self.cel_for_drawing(L, f)
        self.set_image(f"cel:{cel['img']}", img.convert("RGBA").copy())
        if shapes:
            cel["shapes"] = copy.deepcopy(shapes)
        else:
            cel.pop("shapes", None)
        return cel

    # ---- v3.2: figures (your own skeletons: bones branching from any joint, Pivot-style)
    def add_figure(self, name=None, x=None, y=None, role="figure", f=0, bone=True):
        """A new figure: a root (the red handle) and, unless bone=False, one bone pointing up to grab."""
        self.snapshot("add a figure")
        n = len(self.doc["characters"])
        W, H = self.size
        c = {"id": new_id("fg_", self.ids()), "name": clean_name(name or f"Figure {n + 1}"),
             "colour": PALETTE[n % len(PALETTE)], "visible": True, "locked": False, "kind": "figure", "facing": 1,
             "lengths": {}, "lock": True, "interp": "smooth",
             "keys": {f: {"root": [float(W / 2 if x is None else x), float(H * 0.7 if y is None else y)], "rot": 0.0,
                          "ang": {}}},
             "rig": None, "figure": {"segs": [], "role": role}}
        self.doc["characters"].append(c)
        if role == "background":
            self.doc["stack"].insert(0, c["id"])
        else:
            self.doc["stack"].append(c["id"])
        if bone:
            r = c["keys"][f]["root"]
            self._new_bone(c, ROOT, r[0], r[1] - 70, f)
        return c

    def seg(self, c, j):
        for s in c["figure"]["segs"]:
            if s["id"] == j:
                return s
        raise AnimateError("That bone isn't on this figure.")

    def _new_bone(self, c, parent, x, y, f, **look):
        if c["kind"] != "figure":
            raise AnimateError("Bones can be added to figures (a stickman: Turn into Figure first).")
        P, ab = fk(c, self.world_pose(c, f))
        if parent not in P:
            raise AnimateError("That joint isn't on this figure.")
        w = self.world_pose(c, f)
        base = w["rot"] if parent == ROOT else ab[parent]
        new = math.degrees(math.atan2(y - P[parent][1], x - P[parent][0]))
        j = new_id("b", {s["id"] for s in c["figure"]["segs"]} | {ROOT})
        segs = c["figure"]["segs"]
        s = {"id": j, "name": f"bone {len(segs) + 1}", "parent": None if parent == ROOT else parent, "shape": "line",
             "width": 6.0, "thick": 18.0, "colour": None, "fill": None, "outline": False,
             "z": max([x.get("z", 0) for x in segs], default=0) + 1, "pic": None}
        s.update(look)
        segs.append(s)
        c["lengths"][j] = max(2.0, math.dist(P[parent], (x, y)))
        rel = wrap(new - base)
        for k in c["keys"].values():   # every key gets it, at the same angle to its parent bone
            k["ang"][j] = rel
        return s

    def add_bone(self, c, parent, x, y, f, **look):
        """Grow a new bone from the joint `parent` to (x, y) on screen. It's added to every key."""
        self.snapshot("add a bone")
        return self._new_bone(c, parent, x, y, f, **look)

    def remove_bone(self, c, j):
        """Delete a bone and every bone that hangs from it. Things attached to them are attached to the root."""
        segs = c["figure"]["segs"]
        gone = {j}
        for s in segs:
            if s["parent"] in gone:
                gone.add(s["id"])
        self.snapshot("delete a bone")
        for o in self.doc["characters"]:
            at = o.get("attach")
            if at and at["to"] == c["id"] and at["joint"] in gone:
                self._rebase(o, lambda at=at: at.__setitem__("joint", ROOT), 0)
        c["figure"]["segs"] = [s for s in segs if s["id"] not in gone]
        for k in c["keys"].values():
            for g in gone:
                k["ang"].pop(g, None)
                (k.get("len") or {}).pop(g, None)
        for g in gone:
            c["lengths"].pop(g, None)
        return gone

    def build_move(self, c, j, x, y, f):
        """BUILD: drag a joint to reshape the figure. Its bone gets this length on every frame (the figure's
        proportions) and this angle on this frame's key."""
        if j == ROOT:
            return self.drag_joint(c, f, ROOT, x, y)
        P = self.points_at(c, f)
        p = P[joint_parent(c, j)]
        c["lengths"][j] = max(2.0, math.dist(p, (x, y)))
        for k in c["keys"].values():
            (k.get("len") or {}).pop(j, None)
        self.drag_joint(c, f, j, x, y)

    def set_bone(self, c, j, **look):
        s = self.seg(c, j)
        self.snapshot("bone look")
        for k, v in look.items():
            s[k] = v
        return s

    def bone_order(self, c, j, d):
        """Draw the bone one step higher (d=1, in front) or lower (d=-1)."""
        segs = sorted(c["figure"]["segs"], key=lambda s: s.get("z", 0))
        i = next(k for k, s in enumerate(segs) if s["id"] == j)
        k = max(0, min(len(segs) - 1, i + d))
        if k == i:
            return False
        self.snapshot("bone order")
        segs.insert(k, segs.pop(i))
        for z, s in enumerate(segs, 1):
            s["z"] = z
        return True

    def bone_picture(self, c, j, pid, f):
        """Put a picture on a bone: it's placed upright, centred on the bone as it is on frame f, and then turns,
        moves and flips with the bone."""
        import paint
        s = self.seg(c, j)
        P, ab = fk(c, self.world_pose(c, f))
        im = self.picture(pid)
        w, h = im.size
        L = math.dist(P[s["parent"] or ROOT], P[j])
        m = paint.compose([[1, 0, L / 2], [0, 1, 0]], paint.compose(paint.rotation(-ab[j]), [[1, 0, -w / 2], [0, 1, -h / 2]]))
        s["pic"] = {"id": pid, "m": m}
        return s

    def nudge_picture(self, c, j, f, dx=0.0, dy=0.0, turn=0.0, scale=1.0, flip=False):
        """Move (on screen), turn, resize or flip a bone's picture around its middle."""
        import paint
        s = self.seg(c, j)
        if not s.get("pic"):
            raise AnimateError("That bone has no picture.")
        self.snapshot("move the picture")
        m = s["pic"]["m"]
        im = self.picture(s["pic"]["id"])
        cx, cy = paint.apply(m, im.width / 2, im.height / 2)
        if dx or dy:
            a = math.radians(-self.angles_at(c, f)[j])
            m = paint.compose([[1, 0, dx * math.cos(a) - dy * math.sin(a)], [0, 1, dx * math.sin(a) + dy * math.cos(a)]], m)
        if turn:
            m = paint.compose(paint.rotation(turn, cx, cy), m)
        if scale != 1.0:
            m = paint.compose(paint.scaling(scale, scale, cx, cy), m)
        if flip:
            m = paint.compose(paint.scaling(1, -1, cx, cy), m)
        s["pic"]["m"] = m

    def picture_track(self, pid, role="prop", name=None, f=0, x=None, y=None):
        """A prop or a background made of one picture: a figure with one invisible bone carrying it. A background
        goes to the back and is centred on the stage."""
        W, H = self.size
        if role == "background":
            x, y = W / 2, H / 2
        c = self.add_figure(name or ("Background" if role == "background" else "Prop"), W / 2 if x is None else x,
                            H / 2 if y is None else y, role=role, f=f, bone=False)
        r = c["keys"][f]["root"]
        s = self._new_bone(c, ROOT, r[0] + 1, r[1], f, shape="none", name="picture")
        self.bone_picture(c, s["id"], pid, f)
        im = self.picture(pid)
        s["pic"]["m"] = [[1, 0, -im.width / 2], [0, 1, -im.height / 2]]   # centred on the root
        return c

    def to_figure(self, c, f=0):
        """A copy of a stickman as a figure, with the same bones and keys, to give it more (a tail, wings, a hat).
        The stickman is hidden, not deleted."""
        if c["kind"] != "stick":
            raise AnimateError("Only a stickman can be turned into a figure.")
        self.snapshot("turn into a figure")
        new = copy.deepcopy(c)
        new.update(id=new_id("fg_", self.ids()), name=clean_name(f"{c['name']} figure"), kind="figure",
                   figure={"segs": [], "role": "figure"})
        new.pop("extras", None)
        new.pop("source", None)
        present = set(c.get("extras") or ())
        z = 0
        for j in bones_of(present):
            z += 1
            p = parent_of(j, present)
            look = {"shape": "circle", "fill": None} if j == "head" else {}
            s = {"id": j, "name": j, "parent": None if p == ROOT else p, "shape": "line", "width": 7.0, "thick": 18.0,
                 "colour": None, "fill": None, "outline": False, "z": z, "pic": None}
            s.update(look)
            new["figure"]["segs"].append(s)
        self.doc["characters"].append(new)
        self.doc["stack"].insert(self.doc["stack"].index(c["id"]) + 1, new["id"])
        c["visible"] = False
        for o in self.doc["characters"]:   # what was attached to the stickman follows the figure
            if (o.get("attach") or {}).get("to") == c["id"]:
                o["attach"]["to"] = new["id"]
        return new

    def flip_figure(self, c):
        """Mirror a figure left-right around its root, pictures included."""
        import paint
        self.snapshot("flip facing")
        for k in c["keys"].values():
            k["rot"] = wrap(180.0 - k["rot"])
            k["ang"] = {j: wrap(-a) for j, a in k["ang"].items()}
        for s in c["figure"]["segs"]:
            if s.get("pic"):
                s["pic"]["m"] = paint.compose([[1, 0, 0], [0, -1, 0]], s["pic"]["m"])
        c["facing"] = -c["facing"]

    # ---- drawing cels
    def cel_at(self, L, f):
        for c in L["cels"]:
            if c["start"] <= f < c["start"] + c["len"]:
                return c
        return None

    def cel_for_drawing(self, L, f):
        c = self.cel_at(L, f)
        if c is None:
            c = {"start": f, "len": 1, "img": new_id("cel_", {x["img"] for x in L["cels"]})}
            L["cels"].append(c)
            L["cels"].sort(key=lambda x: x["start"])
        return c

    def stroke(self, lid, f, pts, tool="pen", colour="#000000", size=4.0, opacity=1.0):
        """Draw a stroke (pen: hard, brush: soft, eraser: clears) onto the layer's cel on frame f."""
        L = self.layer(lid)
        if not self.editable(lid):
            raise AnimateError("That layer is locked.")
        before = self.cel_at(L, f)
        self.snapshot(tool, [f"cel:{before['img']}"] if before else [])
        cel = self.cel_for_drawing(L, f)
        key = f"cel:{cel['img']}"
        self.set_image(key, paint(self.image(key), pts, tool, colour, size, opacity))
        return cel

    def stroke_art(self, cid, pts, tool="pen", colour="#000000", size=4.0):
        """Draw on a rigged character's working artwork (the original stays as it was)."""
        key = f"art:{cid}"
        self.snapshot("edit the artwork", [key])
        self.set_image(key, paint(self.image(key), pts, tool, colour, size))

    def clear_cel(self, lid, f):
        L = self.layer(lid)
        c = self.cel_at(L, f)
        if c:
            self.snapshot("clear the drawing")
            L["cels"].remove(c)

    def exposure(self, lid, f, d):
        """Hold the cel on frame f for one frame more (+1) or less (-1); the layer's later cels move with it."""
        L = self.layer(lid)
        c = self.cel_at(L, f)
        if c is None or (d < 0 and c["len"] <= 1):
            return False
        self.snapshot("exposure")
        c["len"] += d
        for o in L["cels"]:
            if o["start"] > c["start"]:
                o["start"] += d
        end = max(o["start"] + o["len"] for o in L["cels"])
        self.doc["length"] = max(self.doc["length"], end)
        return True

    # ---- the shared timeline
    def _shift_times(self, f, n):
        """v3.2: story scenes and motion-path timings after frame f move by n frames (n < 0: frame f was deleted)."""
        def sh(v, end=False):
            if n > 0:
                return v + n if v >= f else v
            return v - 1 if v > f or (v == f and end and v > 0) else v
        st = self.doc.get("story")
        for s in (st or {}).get("scenes", []):
            s["start"], s["end"] = sh(s["start"]), sh(s["end"], True)
            s["end"] = max(s["start"], s["end"])
        for c in self.doc["characters"]:
            p = c.get("path")
            if p:
                p["start"], p["end"] = sh(p["start"]), sh(p["end"], True)
                p["end"] = max(p["start"] + 1, p["end"])

    def insert_frames(self, f, n=1):
        """n empty frames before frame f: keys and cels after it move along; a cel shown across f is held longer."""
        self.snapshot("insert frame")
        self._shift_times(f, n)
        for c in self.doc["characters"]:
            c["keys"] = {(k + n if k >= f else k): v for k, v in c["keys"].items()}
        for L in self.doc["layers"]:
            for c in L["cels"]:
                if c["start"] >= f:
                    c["start"] += n
                elif c["start"] + c["len"] > f:
                    c["len"] += n
        self.doc["length"] += n

    def delete_frame(self, f):
        if self.doc["length"] <= 1:
            return False
        self.snapshot("delete frame")
        self._shift_times(f, -1)
        for c in self.doc["characters"]:
            keep = {(k - 1 if k > f else k): v for k, v in c["keys"].items() if k != f}
            c["keys"] = keep or {0: self.pose_at(c, f)}
        for L in self.doc["layers"]:
            out = []
            for c in L["cels"]:
                if c["start"] > f:
                    c["start"] -= 1
                elif c["start"] + c["len"] > f:
                    c["len"] -= 1
                if c["len"] > 0:
                    out.append(c)
            L["cels"] = out
        self.doc["length"] -= 1
        return True

    def duplicate_frame(self, f):
        """Frame f + 1 becomes a copy of frame f: a key with the same pose for every character, and a separate copy
        of every drawing, so each can be changed on its own."""
        poses = {c["id"]: copy.deepcopy(self.pose_at(c, f)) for c in self.doc["characters"]}
        self.snapshot("duplicate frame")
        self._shift_times(f + 1, 1)
        for c in self.doc["characters"]:
            c["keys"] = {(k + 1 if k > f else k): v for k, v in c["keys"].items()}
            c["keys"][f + 1] = poses[c["id"]]
        for L in self.doc["layers"]:
            cur = self.cel_at(L, f)
            for c in L["cels"]:
                if c["start"] > f:
                    c["start"] += 1
            if cur:
                end = cur["start"] + cur["len"]          # frames after f already moved one along
                cur["len"] = f - cur["start"] + 1
                new = {"start": f + 1, "len": end - f, "img": new_id("cel_", {x["img"] for x in L["cels"]})}
                if cur.get("shapes"):
                    new["shapes"] = copy.deepcopy(cur["shapes"])
                self.set_image(f"cel:{new['img']}", self.image(f"cel:{cur['img']}").copy())
                L["cels"].append(new)
                L["cels"].sort(key=lambda x: x["start"])
        self.doc["length"] += 1

    def key_frames(self):
        return sorted({f for c in self.doc["characters"] for f in c["keys"]})

    # ---- rigs (drawing-to-skeleton, optional)
    def make_rig(self, art, name=None):
        """A new rigged character from artwork (RGBA, canvas size). The artwork is kept as it was (_original) and a
        working copy is what gets bound. Its joints start as a stickman fitted to the drawing, for you to place."""
        box = art.getchannel("A").getbbox()
        if not box:
            raise AnimateError("There's nothing drawn to rig.")
        x0, y0, x1, y1 = box
        scale = (y1 - y0) / 290.0
        c = self.add_character(name or f"Rigged {len(self.doc['characters']) + 1}", "rig",
                               (x0 + x1) / 2, y0 + 180 * scale + 6, scale)
        c["rig"] = {"mode": "rigid", "rest": None, "bound": False}
        self.set_image(f"orig:{c['id']}", art.copy())
        self.set_image(f"art:{c['id']}", art.copy())
        self.set_rest(c, points(c["keys"][0], c["lengths"]))
        return c

    def set_rest(self, c, P):
        """Where you placed the 12 joints on the artwork. Its bone lengths become the character's; a character with
        one key starts in this pose, keys already made keep their angles."""
        pose, lens = pose_from_points(P)
        c["lengths"] = lens
        c["rig"]["rest"] = {n: [float(P[n][0]), float(P[n][1])] for n in ORDER}
        for k in c["keys"].values():
            k.pop("len", None)
        if len(c["keys"]) == 1:
            c["keys"] = {min(c["keys"]): pose}

    def bind(self, c):
        """Give every drawn pixel to its nearest bone (you can repaint it with the bind brush)."""
        art = self.image(f"art:{c['id']}")
        R = c["rig"]["rest"]
        a = np.asarray(art.getchannel("A")) > 0
        ys, xs = np.nonzero(a)
        best = np.full(xs.shape, np.inf)
        lab = np.zeros(xs.shape, np.uint8)
        for i, j in enumerate(BONES, 1):
            (ax, ay), (bx, by) = R[PARENT[j]], R[j]
            vx, vy = bx - ax, by - ay
            t = np.clip(((xs - ax) * vx + (ys - ay) * vy) / max(1e-9, vx * vx + vy * vy), 0, 1)
            d = (xs - ax - t * vx) ** 2 + (ys - ay - t * vy) ** 2
            if j == "head":
                d = np.minimum(d, (xs - bx) ** 2 + (ys - by) ** 2)
            lab = np.where(d < best, i, lab)
            best = np.minimum(best, d)
        m = np.zeros(a.shape, np.uint8)
        m[ys, xs] = lab
        self.set_image(f"map:{c['id']}", Image.fromarray(m, "L"))
        c["rig"]["bound"] = True

    def paint_bind(self, c, bone, pts, size):
        m = self.image(f"map:{c['id']}").copy()
        art = self.image(f"art:{c['id']}")
        stroke = Image.new("L", m.size, 0)
        d = ImageDraw.Draw(stroke)
        r = size / 2
        if len(pts) > 1:
            d.line(pts, fill=255, width=max(1, round(size)))
        for x, y in pts:
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
        hit = ImageChops.multiply(stroke, art.getchannel("A").point(lambda v: 255 if v else 0))
        m.paste(BONES.index(bone) + 1, (0, 0), hit)
        self.set_image(f"map:{c['id']}", m)

    def bone_matrices(self, c, pose):
        """Per bone: the 2x3 affine taking the artwork (rest pose) to the pose (turn, stretch along the bone, move)."""
        R = c["rig"]["rest"]
        P = points(pose, c["lengths"])
        out = {}
        for j in BONES:
            a0, b0, a1, b1 = R[PARENT[j]], R[j], P[PARENT[j]], P[j]
            u0 = (b0[0] - a0[0], b0[1] - a0[1])
            u1 = (b1[0] - a1[0], b1[1] - a1[1])
            l0, l1 = math.hypot(*u0) or 1.0, math.hypot(*u1) or 1.0
            c0, s0 = u0[0] / l0, u0[1] / l0
            c1, s1 = u1[0] / l1, u1[1] / l1
            k = l1 / l0
            # into the rest bone's frame (along, across), stretch along, out of the pose bone's frame
            M0 = np.array([[c0, s0], [-s0, c0]])
            M1 = np.array([[c1, -s1], [s1, c1]])
            A = M1 @ np.diag([k, 1.0]) @ M0
            t = np.array(a1) - A @ np.array(a0)
            out[j] = np.hstack([A, t[:, None]])
        return out


def paint(img, pts, tool="pen", colour="#000000", size=4.0, opacity=1.0):
    """img with a stroke on it (a new picture). pen = hard edge, brush = soft edge, eraser = clears."""
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    w = max(1.0, float(size))
    pts = [(float(x), float(y)) for x, y in pts]
    if len(pts) > 1:
        d.line(pts, fill=255, width=max(1, round(w)), joint="curve")
    for x, y in (pts if len(pts) < 3 else [pts[0], pts[-1]]):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w / 4 if tool == "brush" else 0.6))
    if opacity < 1:
        mask = mask.point(lambda v: int(v * opacity))
    if tool == "eraser":
        img = img.copy()
        img.putalpha(ImageChops.multiply(img.getchannel("A"), ImageChops.invert(mask)))
        return img
    rgb = tuple(int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    top = Image.new("RGBA", img.size, rgb + (0,))
    top.putalpha(mask)
    return Image.alpha_composite(img, top)


# ---------------------------------------------------------------- drawing a frame
_LOOKS = {}


def look_for(c):
    import trace_player as tp
    key = (tuple(round(c["lengths"][j], 2) for j in BONES), c["facing"])
    if key not in _LOOKS:
        P = points({"root": [0, 0], "rot": 0.0, "ang": pose_from_points(REST)[0]["ang"]}, c["lengths"])
        lk = tp.Look([(0, P)])
        lk.facing = c["facing"]
        _LOOKS[key] = lk
    return _LOOKS[key]


def draw_stick(canvas, c, P):
    """The game's stickman (as PLAY draws it) in the character's colour, drawn only around its own box."""
    import trace_player as tp
    lk = look_for(c)
    pad = lk.r + lk.foot_len + lk.leg_w + 4
    xs, ys = [v[0] for v in P.values()], [v[1] for v in P.values()]
    x0, y0 = int(min(xs) - pad), int(min(ys) - pad)
    x1, y1 = int(max(xs) + pad) + 1, int(max(ys) + pad) + 1
    W, H = x1 - x0, y1 - y0
    if W <= 0 or H <= 0 or W > 8000 or H > 8000:
        return
    ss = tp.SS
    back, front = Image.new("L", (W * ss, H * ss), 0), Image.new("L", (W * ss, H * ss), 0)
    tp.draw_stickman(P, lk, lambda x, y: ((x - x0) * ss, (y - y0) * ss), ImageDraw.Draw(back), ImageDraw.Draw(front),
                     ss)
    mask = ImageChops.lighter(back.reduce(ss), front.reduce(ss))
    rgb = tuple(int(c["colour"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    piece = Image.new("RGBA", (W, H), rgb + (0,))
    piece.putalpha(mask)
    canvas.alpha_composite(*_clip(canvas, piece, x0, y0))


def _clip(canvas, piece, x, y):
    """alpha_composite arguments for a piece at (x, y) that may hang off the canvas."""
    sx, sy = max(0, -x), max(0, -y)
    dx, dy = max(0, x), max(0, y)
    w = min(piece.width - sx, canvas.width - dx)
    h = min(piece.height - sy, canvas.height - dy)
    if w <= 0 or h <= 0:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0)), (0, 0)
    return piece.crop((sx, sy, sx + w, sy + h)), (dx, dy)


def draw_rig(canvas, proj, c, pose):
    art = proj.image(f"art:{c['id']}")
    m = proj.image(f"map:{c['id']}")
    if art is None:
        return
    if not c["rig"].get("bound") or m is None:
        canvas.alpha_composite(art)
        return
    mats = proj.bone_matrices(c, pose)
    if c["rig"]["mode"] == "mesh":
        canvas.alpha_composite(mesh_deform(art, m, c["rig"]["rest"], mats))
        return
    ma = np.asarray(m)
    for j in DRAW_ORDER:
        i = BONES.index(j) + 1
        part_mask = Image.fromarray(((ma == i) * 255).astype(np.uint8), "L")
        box = part_mask.getbbox()
        if not box:
            continue
        g = SEAM + 1   # each part reaches SEAM px into its neighbours, so a turned joint shows no gap
        box = (max(0, box[0] - g), max(0, box[1] - g), min(art.width, box[2] + g), min(art.height, box[3] + g))
        grown = part_mask.crop(box).filter(ImageFilter.MaxFilter(2 * SEAM + 1))
        part = art.crop(box)
        a = ImageChops.multiply(part.getchannel("A"), grown)
        part.putalpha(a)
        M = mats[j]
        x0, y0, x1, y1 = box
        corners = [M @ np.array([x, y, 1.0]) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        ox0, oy0 = math.floor(min(p[0] for p in corners)) - 1, math.floor(min(p[1] for p in corners)) - 1
        ox1, oy1 = math.ceil(max(p[0] for p in corners)) + 1, math.ceil(max(p[1] for p in corners)) + 1
        inv = np.linalg.inv(np.vstack([M, [0, 0, 1]]))   # output -> artwork, shifted for the two crops
        a_, b_, c_ = inv[0]
        d_, e_, f_ = inv[1]
        data = (a_, b_, a_ * ox0 + b_ * oy0 + c_ - x0, d_, e_, d_ * ox0 + e_ * oy0 + f_ - y0)
        out = part.transform((ox1 - ox0, oy1 - oy0), Image.AFFINE, data, resample=Image.BILINEAR)
        canvas.alpha_composite(*_clip(canvas, out, ox0, oy0))


def mesh_deform(art, m, rest, mats, step=14):
    """Mesh deformation: a triangle grid over the drawing; each corner follows its nearby bones, blended by
    distance (the bone it's bound to counts most), and every triangle is mapped with its own affine."""
    box = art.getchannel("A").getbbox()
    W, H = art.size
    if not box:
        return Image.new("RGBA", art.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box[0] - step, box[1] - step, box[2] + step, box[3] + step
    gx = np.arange(x0, x1 + step, step, dtype=float)
    gy = np.arange(y0, y1 + step, step, dtype=float)
    VX, VY = np.meshgrid(gx, gy)
    ma = np.asarray(m)
    wsum = np.zeros(VX.shape)
    out = np.zeros(VX.shape + (2,))
    lab = ma[np.clip(VY.astype(int), 0, H - 1), np.clip(VX.astype(int), 0, W - 1)]
    for i, j in enumerate(BONES, 1):
        (ax, ay), (bx, by) = rest[PARENT[j]], rest[j]
        vx, vy = bx - ax, by - ay
        t = np.clip(((VX - ax) * vx + (VY - ay) * vy) / max(1e-9, vx * vx + vy * vy), 0, 1)
        d2 = (VX - ax - t * vx) ** 2 + (VY - ay - t * vy) ** 2
        w = 1.0 / (d2 + 25.0) ** 2 * np.where(lab == i, 8.0, 1.0)
        M = mats[j]
        px = M[0, 0] * VX + M[0, 1] * VY + M[0, 2]
        py = M[1, 0] * VX + M[1, 1] * VY + M[1, 2]
        out[..., 0] += w * px
        out[..., 1] += w * py
        wsum += w
    out /= wsum[..., None]
    ids = Image.new("I", art.size, 0)
    d = ImageDraw.Draw(ids)
    alpha = art.getchannel("A")
    tris = []
    for r in range(len(gy) - 1):
        for q in range(len(gx) - 1):
            if not alpha.crop((int(gx[q]), int(gy[r]), int(gx[q + 1]), int(gy[r + 1]))).getbbox():
                continue
            a, b, cc, dd = (r, q), (r, q + 1), (r + 1, q), (r + 1, q + 1)
            for tri in ((a, b, cc), (b, dd, cc)):
                src = [(gx[k[1]], gy[k[0]]) for k in tri]
                dst = [tuple(out[k]) for k in tri]
                S = np.array([[p[0], p[1], 1.0] for p in dst])
                try:
                    coef = np.linalg.solve(S, np.array(src))   # dst -> src
                except np.linalg.LinAlgError:
                    continue
                tris.append(coef.T.reshape(-1))
                d.polygon(dst, fill=len(tris), outline=len(tris))
    if not tris:
        return Image.new("RGBA", art.size, (0, 0, 0, 0))
    T = np.array(tris)
    I = np.asarray(ids)
    ys, xs = np.nonzero(I)
    k = I[ys, xs] - 1
    sx = T[k, 0] * xs + T[k, 1] * ys + T[k, 2]
    sy = T[k, 3] * xs + T[k, 4] * ys + T[k, 5]
    A = np.asarray(art).astype(np.float32)
    sx = np.clip(sx, 0, W - 1.001)
    sy = np.clip(sy, 0, H - 1.001)
    ix, iy = sx.astype(int), sy.astype(int)
    fx, fy = (sx - ix)[:, None], (sy - iy)[:, None]
    px = (A[iy, ix] * (1 - fx) * (1 - fy) + A[iy, ix + 1] * fx * (1 - fy) + A[iy + 1, ix] * (1 - fx) * fy
          + A[iy + 1, ix + 1] * fx * fy)
    res = np.zeros(A.shape, np.float32)
    res[ys, xs] = px
    return Image.fromarray(np.clip(res, 0, 255).astype(np.uint8), "RGBA")


def bone_matrix(P, ab, s):
    """The 2x3 map from a bone's own frame (origin at its start, x along it) to the screen."""
    a = math.radians(ab[s["id"]])
    x, y = P[s["parent"] or ROOT]
    return [[math.cos(a), -math.sin(a), x], [math.sin(a), math.cos(a), y]]


def place_picture(canvas, pic, M):
    """Draw the picture onto the canvas through the 2x3 map M (picture pixels -> screen), only around its box."""
    import paint
    w, h = pic.size
    cs = [paint.apply(M, x, y) for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
    x0, y0 = math.floor(min(p[0] for p in cs)) - 1, math.floor(min(p[1] for p in cs)) - 1
    x1, y1 = math.ceil(max(p[0] for p in cs)) + 1, math.ceil(max(p[1] for p in cs)) + 1
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(canvas.width, x1), min(canvas.height, y1)
    if x1c <= x0c or y1c <= y0c:
        return
    out = paint.warp(pic, paint.compose([[1, 0, -x0c], [0, 1, -y0c]], M), (x1c - x0c, y1c - y0c))
    canvas.alpha_composite(out, (x0c, y0c))


def bone_shapes(c, s, P):
    """A figure bone's look as paint shapes (line, circle, box, ellipse; nothing for "none")."""
    import paint
    j, p = s["id"], s["parent"] or ROOT
    a, b = P[p], P[j]
    col = s.get("colour") or c["colour"]
    w = float(s.get("width", 6))
    kind = s.get("shape", "line")
    if kind == "line":
        return [paint.make_shape("line", [a, b], stroke=col, width=w)]
    if kind == "none":
        return []
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1e-6
    if kind == "circle":
        cx, cy, r = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, L / 2
        ux, uy, vx, vy = dx / 2, dy / 2, -dy / 2, dx / 2
    else:
        t = float(s.get("thick", 18)) / 2
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ux, uy, vx, vy = dx / 2, dy / 2, -dy / L * t, dx / L * t
    corners = [(cx - ux - vx, cy - uy - vy), (cx + ux - vx, cy + uy - vy), (cx + ux + vx, cy + uy + vy),
               (cx - ux + vx, cy - uy + vy)]
    fill = s.get("fill") if kind == "circle" else (s.get("fill") or col)
    shape = paint.make_shape("ellipse" if kind in ("circle", "ellipse") else "rect", corners, stroke=col,
                             width=w if kind == "circle" or s.get("outline") else 0, fill=fill)
    if not shape["width"]:
        shape["stroke"] = None
    return [shape]


def draw_figure(canvas, proj, c, pose):
    """A figure: each bone's shape and picture, lowest z first."""
    import paint
    P, ab = fk(c, pose)
    for s in sorted(c["figure"]["segs"], key=lambda s: s.get("z", 0)):
        if s["id"] not in P:
            continue
        for sh in bone_shapes(c, s, P):
            paint.draw_shape_into(canvas, sh)
        pic = s.get("pic")
        if pic and pic.get("id") in (proj.doc.get("pictures") or {}):
            im = proj.picture(pic["id"])
            if im is not None:
                place_picture(canvas, im, paint.compose(bone_matrix(P, ab, s), pic["m"]))


def render(proj, f, paper=True, onion=None, skip=(), replace=None):
    """Frame f of the whole scene as an RGBA picture. onion = layer id whose neighbouring drawings are shown faded
    (red before, green after). skip = track ids left out (e.g. the one being edited). replace = {layer id: picture}
    shown instead of that layer's drawing (the paint tools' live preview)."""
    replace = replace or {}
    W, H = proj.size
    img = Image.new("RGBA", (W, H), (243, 243, 243, 255) if paper else (0, 0, 0, 0))
    if onion:
        L = proj.layer(onion)
        cur = proj.cel_at(L, f)
        before, after = proj.doc["onion"]
        for d, col in [(-k, (227, 34, 43)) for k in range(before, 0, -1)] + [(k, (47, 179, 90))
                                                                             for k in range(1, after + 1)]:
            c = proj.cel_at(L, f + d)
            if c and c is not cur:
                a = proj.image(f"cel:{c['img']}").getchannel("A").point(lambda v, k=abs(d): v * 0.3 / k)
                g = Image.new("RGBA", (W, H), col + (0,))
                g.putalpha(a)
                img.alpha_composite(g)
    for tid in proj.doc["stack"]:
        if tid in skip or not proj.shown(tid):
            continue
        try:
            c = proj.char(tid)
        except AnimateError:
            L = proj.layer(tid)
            cel = proj.cel_at(L, f)
            if tid in replace or cel:
                im = replace[tid] if tid in replace else proj.cel_picture(cel)
                if L["opacity"] < 1:
                    im = im.copy()
                    im.putalpha(im.getchannel("A").point(lambda v: int(v * L["opacity"])))
                img.alpha_composite(im)
            continue
        if c["kind"] == "figure":
            draw_figure(img, proj, c, proj.world_pose(c, f))
        elif c["kind"] == "rig" and c.get("rig"):
            draw_rig(img, proj, c, proj.world_pose(c, f))
        else:
            draw_stick(img, c, proj.points_at(c, f))
    return img


# ---------------------------------------------------------------- TRACE import
def traced_moves(images):
    out = []
    try:
        names = sorted(os.listdir(images))
    except OSError:
        return out
    for n in names:
        d = os.path.join(images, n)
        if os.path.isdir(d) and trace_io.find_file(d, trace_io.TRACE):
            out.append(d)
    return out


def import_trace(proj, move, char_ids=None, fixed=False, exact=False):
    """Copy a TRACE move's characters into the project as skeleton characters (TRACE files are only read).
    Proportions are steadied: each bone gets its median length (exact=True keeps every key's traced length).
    Frame numbers are converted to the project's frame rate; the group is fitted into the canvas together, so
    the characters keep their distances. -> the new characters."""
    import characters as chars
    import trace_player as tp
    fps_src, _ = tp.find_fps(move)
    found = []
    for e in chars.list_characters(move):
        if char_ids and e["id"] not in char_ids:
            continue
        ks = chars.keys(move, e["id"], fixed=fixed and bool(trace_io.find_file(e["trace_dir"], trace_io.FIXED)))
        if ks:
            found.append((e, ks))
    if not found:
        raise AnimateError("That move has no finished traced frames to import.")
    W, H = proj.size
    xs = [P[n][0] for _, ks in found for _, P in ks for n in ORDER]
    ys = [P[n][1] for _, ks in found for _, P in ks for n in ORDER]
    s = min(0.8 * H / max(1.0, max(ys) - min(ys)), 0.9 * W / max(1.0, max(xs) - min(xs)))
    ox = W / 2 - s * (min(xs) + max(xs)) / 2
    oy = 0.92 * H - s * max(ys)
    f0 = min(f for _, ks in found for f, _ in ks)
    proj.snapshot("import a Trace move")
    made = []
    for e, ks in found:
        poses = []
        extras = [x for x in EXTRAS if all(x in P for _, P in ks)]   # optional joints traced on every key frame
        for f, P in ks:
            Q = {n: (ox + s * P[n][0], oy + s * P[n][1]) for n in ORDER + extras}
            pose, lens = pose_from_points(Q)
            poses.append((int(round((f - f0) * proj.doc["fps"] / fps_src)), pose, lens))
        med = {j: sorted(L[j] for _, _, L in poses)[len(poses) // 2] for j in poses[0][2]}
        n = len(proj.doc["characters"])
        c = {"id": new_id("ch_", proj.ids()), "name": clean_name(f"{os.path.basename(move)} {e['name']}"),
             "colour": PALETTE[n % len(PALETTE)], "visible": True, "locked": False, "kind": "stick",
             "facing": tp.Look(ks).facing, "lengths": med, "lock": not exact, "interp": "smooth", "keys": {},
             "rig": None, "extras": extras,
             "source": {"move": os.path.normpath(move), "character": e["id"], "fixed": bool(fixed), "fps": fps_src}}
        for fr, pose, lens in poses:
            if exact:
                pose["len"] = lens
            c["keys"][fr] = pose
        proj.doc["characters"].append(c)
        proj.doc["stack"].append(c["id"])
        made.append(c)
        proj.doc["length"] = max(proj.doc["length"], max(c["keys"]) + 1)
    return made


# ---------------------------------------------------------------- export
def export(proj, out_dir, kinds=("png", "gif"), transparent=False):
    """PNG frames, a looping GIF and / or an MP4 video into a NEW dated folder. -> that folder.
    The video always has the paper background (MP4 can't be see-through)."""
    name = proj.doc["name"]
    d = os.path.join(out_dir, f"{name} animate {time.strftime('%Y-%m-%d %H%M%S')}")
    k = 2
    while os.path.exists(d):
        d = f"{d} ({k})"
        k += 1
    os.makedirs(d)
    frames = [render(proj, f, paper=not transparent) for f in range(proj.doc["length"])]
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "animation"
    if "png" in kinds:
        for i, im in enumerate(frames, 1):
            im.save(os.path.join(d, f"{slug}_{i:04d}.png"))
    if "gif" in kinds:   # one palette for every frame (no flicker), exact timing
        import gifwrite
        gifwrite.write_gif(os.path.join(d, f"{slug}.gif"), frames, proj.doc["fps"], transparent=transparent)
    if "mp4" in kinds:
        video = frames if not transparent else [render(proj, f) for f in range(proj.doc["length"])]
        write_mp4(os.path.join(d, f"{slug}.mp4"), video, proj.doc["fps"])
    return d


def write_mp4(path, frames, fps):
    """An MP4 video (MPEG-4; H.264 only if that fails), read back to check every frame is there."""
    import cv2
    W, H = frames[0].size
    W2, H2 = W + W % 2, H + H % 2          # video sizes must be even
    for code in ("mp4v", "avc1"):
        if os.path.exists(path):
            os.remove(path)
        w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*code), float(fps), (W2, H2))
        if not w.isOpened():
            continue
        for im in frames:
            rgb = Image.new("RGB", (W2, H2), (243, 243, 243))
            rgb.paste(im.convert("RGB"), (0, 0))
            w.write(cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR))
        w.release()
        cap = cv2.VideoCapture(path)
        n = 0
        while cap.read()[0]:
            n += 1
        cap.release()
        if n == len(frames):
            return path
    if os.path.exists(path):
        os.remove(path)
    raise AnimateError("The MP4 video couldn't be written on this computer (no video encoder in OpenCV).")


def export_trace(proj, images, char_ids, name=None):
    """A NEW move in Images, usable by 02 TRACE, 03 PLAY / FIX and Game Settings: the scene as f00.png …, every
    frame a finished key frame of trace.json (the first character), the others as traced characters, timing.json.
    Nothing that exists is overwritten. -> the move folder."""
    import characters as chars
    char_ids = [i for i in char_ids if proj.char(i)["kind"] != "figure"]   # v3.2: a figure has no 12 joints
    if not char_ids:
        raise AnimateError("Pick at least one stickman or rigged character to export as a move (figures have their "
                           "own bones, not the 12 joints).")
    base = clean_name(name or proj.doc["name"])
    move, k = os.path.join(images, base), 2
    while os.path.exists(move):
        move, k = os.path.join(images, f"{base} {k}"), k + 1
    os.makedirs(move)
    n = proj.doc["length"]
    for f in range(n):
        render(proj, f).convert("RGB").save(os.path.join(move, f"f{f:02d}.png"))
    with open(os.path.join(move, "timing.json"), "w") as fh:
        json.dump({"fps": proj.doc["fps"]}, fh)

    def write(cid, path):
        c = proj.char(cid)
        pts = [{j: list(v) for j, v in proj.points_at(c, f).items()} for f in range(n)]
        trace_io.write_trace(path, list(range(n)), pts, [[] for _ in range(n)])

    write(char_ids[0], os.path.join(move, trace_io.TRACE))
    if len(char_ids) > 1:
        cs = chars.CharacterSet.open(move)
        cs.rename(chars.PRIMARY, proj.char(char_ids[0])["name"])
        for cid in char_ids[1:]:
            new = cs.create(proj.char(cid)["name"])
            write(cid, os.path.join(cs.trace_dir(new), trace_io.TRACE))
    return move
