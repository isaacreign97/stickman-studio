"""LIBRARY (v3.2): your own characters, props, backgrounds and pictures, saved once and used in any animation.

Folder: "Animation Library" beside Animations (NOT "Library": that's Unity's own folder in the project).

    Animation Library\\<Kind>\\<name>\\item.json      what it is (format "stickman-library/1")
                                     \\pictures\\*.png  its pictures (painted pixels; shapes are in item.json)
                                     \\rigs\\*.png      a rigged drawing's artwork / original / binding
                                     \\thumb.png       a small preview
    Animation Library\\swatches.json                 your saved colours
    Animation Library\\Deleted\\...                   deleted items go here (nothing is ever erased)

Kinds: Characters (stickmen, figures, rigged drawings), Props, Backgrounds, Pictures. Inserting an item copies it
into the animation with new ids, so the library copy never changes. No AI.
"""
import copy
import json
import os
import shutil
import time

from PIL import Image

import animate as A
import trace_io

FORMAT = "stickman-library/1"
KINDS = ("Characters", "Props", "Backgrounds", "Pictures")


class LibraryError(Exception):
    pass


def root(images):
    return os.path.join(os.path.dirname(os.path.normpath(images)), "Animation Library")


def kind_for(track):
    """The library shelf a track goes on."""
    if track["kind"] == "figure":
        role = track["figure"].get("role")
        return "Backgrounds" if role == "background" else "Props" if role == "prop" else "Characters"
    return "Characters"


def list_items(images, kind=None):
    """[(kind, name, folder)] sorted by kind then name."""
    out = []
    for k in KINDS if kind is None else [kind]:
        d = os.path.join(root(images), k)
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except OSError:
            continue
        for n in names:
            if os.path.isfile(os.path.join(d, n, "item.json")):
                out.append((k, n, os.path.join(d, n)))
    return out


def read(folder):
    try:
        J = trace_io.read_json(os.path.join(folder, "item.json"))
    except (OSError, ValueError) as e:
        raise LibraryError(f"It couldn't be read: {e}") from e
    if J.get("format") != FORMAT:
        raise LibraryError("That isn't a library item.")
    return J


def _folder_for(images, kind, name, replace=False):
    if kind not in KINDS:
        raise LibraryError(f"Unknown kind {kind}.")
    name = A.clean_name(name)
    d = os.path.join(root(images), kind, name)
    if os.path.exists(d):
        if not replace:
            raise LibraryError(f"There's already a {kind[:-1].lower()} called {name} in the library.")
        delete(images, d)   # moved to Deleted, never erased
    return name, d


def save_track(images, proj, cid, name=None, kind=None, with_keys=True, f=0, replace=False):
    """Save a character / figure / prop / background (with its pictures) to the library. with_keys=False keeps only
    its pose on frame f. Attachments and paths aren't saved (they belong to the animation). -> the item folder."""
    orig = proj.char(cid)
    c = copy.deepcopy(orig)
    kind = kind or kind_for(c)
    name, d = _folder_for(images, kind, name or c["name"], replace)
    frames = sorted(c["keys"]) if with_keys else [f]
    keys = {}
    for k in frames:   # each key as seen on screen (what it was attached to, and its path, aren't saved)
        pose = copy.deepcopy(proj.pose_at(orig, k))
        if c.get("attach") or c.get("path"):
            w = proj.world_pose(orig, k)
            pose["root"], pose["rot"] = list(w["root"]), w["rot"]
        keys[k - frames[0]] = pose
    c["keys"] = keys
    c.pop("attach", None)
    c.pop("path", None)
    c.pop("source", None)
    os.makedirs(os.path.join(d, "pictures"))
    pics = {}
    for s in (c.get("figure") or {}).get("segs", []):
        pid = (s.get("pic") or {}).get("id")
        if pid and pid not in pics and pid in (proj.doc.get("pictures") or {}):
            raw, shapes = proj.picture_raw(pid)
            raw.save(os.path.join(d, "pictures", pid + ".png"))
            pics[pid] = {"name": proj.doc["pictures"][pid].get("name", "Picture"), "shapes": shapes}
    if c["kind"] == "rig":
        os.makedirs(os.path.join(d, "rigs"))
        for kk in ("art", "orig", "map"):
            im = proj.image(f"{kk}:{cid}")
            if im is not None:
                im.save(os.path.join(d, "rigs", kk + ".png"))
    item = {"format": FORMAT, "kind": kind, "name": name, "made": time.strftime("%Y-%m-%d %H:%M:%S"),
            "track": dict(c, keys={str(k): v for k, v in c["keys"].items()}), "pictures": pics}
    _write(d, item)
    _thumb(proj, cid, f, d)
    return d


def save_picture(images, img, shapes, name, kind="Pictures", replace=False):
    """Save a painted picture to the library (Pictures, Props or Backgrounds shelf). -> the item folder."""
    name, d = _folder_for(images, kind, name, replace)
    os.makedirs(os.path.join(d, "pictures"))
    img.convert("RGBA").save(os.path.join(d, "pictures", "pic.png"))
    item = {"format": FORMAT, "kind": kind, "name": name, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "track": None,
            "pictures": {"pic": {"name": name, "shapes": copy.deepcopy(shapes or [])}}}
    _write(d, item)
    import paint
    t = paint.flatten(img.convert("RGBA"), shapes)
    t.thumbnail((160, 120))
    t.save(os.path.join(d, "thumb.png"))
    return d


def _write(d, item):
    trace_io.write_atomic(os.path.join(d, "item.json"), json.dumps(item, indent=1))


def _thumb(proj, cid, f, d):
    try:
        img = A.render(proj, f, paper=False, skip=set(proj.doc["stack"]) - {cid})
        box = img.getchannel("A").getbbox()
        if box:
            img = img.crop(box)
        img.thumbnail((160, 120))
        img.save(os.path.join(d, "thumb.png"))
    except Exception:   # a preview is only nice to have
        pass


def picture_of(folder):
    """(painted pixels, shapes) of a picture item."""
    J = read(folder)
    if not J["pictures"]:
        raise LibraryError("It has no picture.")
    pid, meta = next(iter(J["pictures"].items()))
    with Image.open(os.path.join(folder, "pictures", pid + ".png")) as im:
        return im.convert("RGBA"), copy.deepcopy(meta.get("shapes") or [])


def insert(proj, folder, f=0, role=None):
    """Copy a library item into the animation (new ids; the library copy is never changed). A picture item becomes
    a prop, or a background with role="background". Its keys start on frame f. -> the new track."""
    J = read(folder)
    proj.snapshot(f"insert {J['name']}")
    new_pids = {}
    for pid, meta in J["pictures"].items():
        with Image.open(os.path.join(folder, "pictures", pid + ".png")) as im:
            new_pids[pid] = proj.add_picture(im, meta.get("shapes"), meta.get("name", J["name"]))
    if J["track"] is None:
        pid = next(iter(new_pids.values()))
        role = role or ("background" if J["kind"] == "Backgrounds" else "prop")
        undo = len(proj.undo_stack)
        c = proj.picture_track(pid, role, J["name"], f)
        del proj.undo_stack[undo:]   # one undo step for the whole insert
        return c
    c = copy.deepcopy(J["track"])
    c["id"] = A.new_id({"figure": "fg_", "rig": "ch_", "stick": "ch_"}[c["kind"]], proj.ids())
    c["keys"] = {int(k) + f: v for k, v in c["keys"].items()}
    c["name"] = A.clean_name(c["name"])
    for s in (c.get("figure") or {}).get("segs", []):
        if s.get("pic"):
            s["pic"]["id"] = new_pids.get(s["pic"]["id"], s["pic"]["id"])
    if c["kind"] == "rig":
        for kk in ("art", "orig", "map"):
            p = os.path.join(folder, "rigs", kk + ".png")
            if os.path.exists(p):
                with Image.open(p) as im:
                    proj.set_image(f"{kk}:{c['id']}", im.convert("L" if kk == "map" else "RGBA"))
    proj.doc["characters"].append(c)
    if (c.get("figure") or {}).get("role") == "background":
        proj.doc["stack"].insert(0, c["id"])
    else:
        proj.doc["stack"].append(c["id"])
    proj.doc["length"] = max(proj.doc["length"], max(c["keys"]) + 1)
    return c


def delete(images, folder):
    """Move an item to Animation Library\\Deleted (it can be moved back by hand). -> where it went."""
    base = os.path.join(root(images), "Deleted")
    os.makedirs(base, exist_ok=True)
    dst = os.path.join(base, f"{time.strftime('%Y%m%d-%H%M%S')} {os.path.basename(folder)}")
    k = 2
    while os.path.exists(dst):
        dst, k = f"{dst} ({k})", k + 1
    shutil.move(folder, dst)
    return dst


def swatches(images):
    try:
        J = trace_io.read_json(os.path.join(root(images), "swatches.json"))
        return [c for c in J.get("colours", []) if isinstance(c, str)][:32]
    except (OSError, ValueError):
        return []


def save_swatches(images, colours):
    os.makedirs(root(images), exist_ok=True)
    trace_io.write_atomic(os.path.join(root(images), "swatches.json"),
                          json.dumps({"colours": list(dict.fromkeys(colours))[:32]}, indent=1))
