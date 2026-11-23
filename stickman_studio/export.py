"""Batch export (Stickman Studio upgrade, Phase 10). Plain file handling and drawing, no AI.

Exports several moves in one go into a NEW dated folder (nothing that exists is ever overwritten):

    <out>\\export YYYY-MM-DD HHMMSS\\
        export_summary.txt       what was exported, from which version, warnings, and the file check
        export_summary.json      the same for programs
        <move>\\                  one folder per move, named the consistent way (see slug())
            trace.json           your trace, copied byte for byte (as are trace_fixed.json and timing.json), so the
            trace_fixed.json     folder still works with everything that reads trace folders: the studio, Game
            timing.json          Settings, draw_trace.py and the Unity bake
            <move>_poses.json    pose data per frame: pixels, hip-relative in bone lengths, angles ("stickman-poses/1")
            <move>_frames.csv    the same rows as ANALYTICS → SAVE CSV… (one row per frame; Excel / Google Sheets)
            <move>_stickman\\     <move>_stickman_0001.png …  the stickman as PLAY draws it, one picture per frame
            <move>_overlay\\      <move>_overlay_f05.png …    your trace drawn on the reference frames (key frames)

Versions: "auto" = the fixed trace when the move has one, otherwise your trace; "trace"; "fixed" (moves without a
fixed trace are skipped). Data: "every" frame (the in-betweens PLAY draws, from the first to the last finished key
frame) or "keys" (the key frames only).

Every move is checked before (project.check: broken data skips the move; warnings are listed) and every file is
read back after it was written (copies compared byte for byte, JSON and CSV parsed and counted, pictures opened).

usage: python -I export.py <Images folder> <out folder> [move names ...]     (all traced moves when none are given)
"""
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I leaves the script's folder out
import analytics  # noqa: E402
import compare  # noqa: E402
import project  # noqa: E402
import trace_io  # noqa: E402

ORDER = trace_io.ORDER
SCHEMA = "stickman-poses/1"
DEFAULTS = {"out": "", "version": "auto", "data": "every", "copy_traces": True, "poses_json": True, "csv": True,
            "stickman_png": False, "png_height": 480, "transparent": True, "overlay_png": False,
            "characters": True, "scene_png": False}   # Phase 11: every traced character; all of them together
VERSIONS = [("auto", "Fixed trace if there is one, otherwise your trace"), ("trace", "Your trace (trace.json)"),
            ("fixed", "Fixed trace only (trace_fixed.json)")]
DATA = [("every", "Every frame (the in-betweens Play draws)"), ("keys", "Key frames only")]
SETTINGS_KEY = "export"
COPIES = (trace_io.TRACE, trace_io.FIXED, "timing.json")


# ---------------------------------------------------------------- names and settings
def slug(name):
    """The consistent file name of a move: lower case, letters / digits / underscores. "Low Kick 2" -> low_kick_2."""
    s = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return s or "move"


def names(folders):
    """{folder: slug}, made unique ("jump", "jump_2") because Windows doesn't tell Jump from jump."""
    out, used = {}, set()
    for d in folders:
        base = slug(os.path.basename(os.path.normpath(d)))
        s, k = base, 2
        while s in used:
            s, k = f"{base}_{k}", k + 1
        used.add(s)
        out[d] = s
    return out


def default_out(images):
    return os.path.join(os.path.dirname(os.path.normpath(images)), "Exports")


def load_settings(prefs_path, images=None):
    """The export settings saved in the studio's prefs file (Game Settings\\studio.json), filled with defaults."""
    s = dict(DEFAULTS)
    try:
        with open(prefs_path, encoding="utf-8") as fh:
            saved = json.load(fh).get(SETTINGS_KEY) or {}
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    if not s["out"] and images:
        s["out"] = default_out(images)
    return s


def save_settings(prefs_path, settings):
    """Keep the export settings in the prefs file; every other key in it stays as it is."""
    try:
        with open(prefs_path, encoding="utf-8") as fh:
            J = json.load(fh)
        if not isinstance(J, dict):
            J = {}
    except (OSError, ValueError):
        J = {}
    J[SETTINGS_KEY] = {k: settings[k] for k in DEFAULTS if k in settings}
    os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
    trace_io.write_atomic(prefs_path, json.dumps(J))


def describe_settings(s):
    files = [n for n, on in (("trace files", s["copy_traces"]), ("pose JSON", s["poses_json"]), ("CSV", s["csv"]),
                             (f"stickman PNGs {s['png_height']} px" + (" see-through" if s["transparent"] else ""),
                              s["stickman_png"]), ("overlay PNGs", s["overlay_png"]),
                             ("scene PNGs", s.get("scene_png"))) if on]
    if s.get("characters", True):
        files.append("every traced character")
    return (f"{dict(VERSIONS)[s['version']]}  ·  {dict(DATA)[s['data']].split(' (')[0].lower()}  ·  "
            + (", ".join(files) or "no files"))


# ---------------------------------------------------------------- what each move gives
def complete(P):
    return all(n in P for n in ORDER)


def fixed_ground(keys, J):
    """(ground y, reach) the player uses to keep the fixed trace's in-betweens on the ground, or None."""
    fix = J.get("fix") if isinstance(J.get("fix"), dict) else {}
    if not fix.get("ground", True) or "ground_y" not in J or not keys:
        return None
    legs = sorted((math.dist(P["hip"], P["backKnee"]) + math.dist(P["backKnee"], P["backFoot"])
                   + math.dist(P["hip"], P["frontKnee"]) + math.dist(P["frontKnee"], P["frontFoot"])) / 2
                  for _, P in keys)
    m = len(legs)
    med = legs[m // 2] if m % 2 else (legs[m // 2 - 1] + legs[m // 2]) / 2
    return float(J["ground_y"]), 0.2 * med


def prepare(folder, settings, trace_dir=None, label=None):
    """Everything needed to export one move, or why it can't be. Read-only.
    Phase 11: trace_dir / label = one traced character of a multi-character move (its own trace, the move's frames).
    -> {"folder", "tdir", "move", "version", "source", "fps", "fps_from", "keys", "poses" {frame: pose},
        "key_frames", "estimated" {frame: set}, "errors" [], "warnings" [], "fixed_meta" {}}"""
    import characters as chars
    import trace_player as tp
    move = label or os.path.basename(os.path.normpath(folder))
    td = trace_dir or folder
    m = {"folder": folder, "tdir": td, "move": move, "errors": [], "warnings": [], "poses": {}, "keys": [],
         "key_frames": [], "estimated": {}, "fixed_meta": {}, "version": None, "source": None}
    # a multi-character move: this character's own checks (another character's problem doesn't stop it)
    issues = project.check_one(folder, td) if (trace_dir or chars.is_multi(folder)) else project.check(folder)
    for i in issues:
        if i["level"] == "error":
            m["errors"].append(i["text"])
    t = trace_io.find_file(td, trace_io.TRACE)
    fx = trace_io.find_file(td, trace_io.FIXED)
    want = settings["version"]
    if want == "fixed" and not fx:
        m["errors"].append("It has no fixed trace (save one in Review), and only fixed traces were asked for.")
    if not t and not fx:
        m["errors"].append("It isn't traced yet.")
    if m["errors"]:
        return m
    use_fixed = bool(fx) and want in ("auto", "fixed")
    m["version"] = "fixed" if use_fixed else "trace"
    m["source"] = fx if use_fixed else t
    m["fps"], m["fps_from"] = tp.find_fps(folder)
    try:
        if use_fixed:
            J = trace_io.read_json(fx)
            keys = sorted((int(f), {n: (float(P[n][0]), float(P[n][1])) for n in ORDER})
                          for f, P in zip(J["frames"], J["pts"]))
            if J.get("fps"):
                m["fps"], m["fps_from"] = float(J["fps"]), "the fixed trace"
            m["fixed_meta"] = {k: J[k] for k in ("summary", "in_place", "travel_px", "travel_px_per_s", "ground_y")
                               if k in J}
            state, detail = project.fixed_state(td)
            if state == "stale":
                m["warnings"].append("The fixed trace is Out of Date (" + detail + "); it's exported as saved. "
                                     "Save it again in Review for your latest trace.")
            partial = {f: P for f, P in keys}
            ground = fixed_ground(keys, J)
            est = {int(f): set(E) for f, E in zip(J["frames"], J.get("estimated") or [])}
        else:
            keys, unfinished = tp.read_trace(t)
            partial = {f: dict(P) for f, P in compare.load_poses(t).items()}
            ground = None
            J = trace_io.read_json(t)
            est = {int(f): set(E) for f, E in zip(J["frames"], J.get("estimated") or [])}
            if unfinished:
                m["warnings"].append(f"Key frame{'s' if len(unfinished) > 1 else ''} "
                                     f"{', '.join(map(str, unfinished))} {'aren' if len(unfinished) > 1 else 'isn'}'t "
                                     "finished, so " + ("they're" if len(unfinished) > 1 else "it's")
                                     + (" left out of the in-betweens and pictures." if settings["data"] == "every"
                                        else " exported with the points it has."))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        m["errors"].append(f"{os.path.basename(m['source'])} can't be read ({e}).")
        return m
    m["keys"], m["key_frames"], m["estimated"] = keys, sorted(partial), est
    if settings["data"] == "every":
        if not keys:
            m["errors"].append("No key frame has all 12 points, so there are no in-betweens to export.")
            return m
        if len(keys) == 1:
            m["poses"] = {keys[0][0]: dict(keys[0][1])}
        else:
            motion = tp.Motion(keys)
            for f in range(keys[0][0], keys[-1][0] + 1):
                P = motion.pose(float(f))
                if ground:
                    P = tp.on_ground(P, ground[0], ground[1])[0]
                m["poses"][f] = {n: (float(P[n][0]), float(P[n][1])) for n in ORDER}
    else:
        m["poses"] = {f: P for f, P in sorted(partial.items()) if P}
        if not m["poses"]:
            m["errors"].append("No key frame has any points yet.")
            return m
    if settings["stickman_png"] and not keys:
        m["warnings"].append("No finished key frame, so there are no stickman pictures.")
    if m["fps_from"] == "a guess":
        m["warnings"].append(f"The frame rate ({m['fps']:g} fps) is a guess: times in the files use it.")
    for i in issues:
        if i["level"] == "warning" and "fixed trace is out of date" not in i["text"]:
            m["warnings"].append(i["text"])
    return m


# ---------------------------------------------------------------- writing
def sha1(path):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def poses_doc(m):
    """The pose-data JSON of a prepared move."""
    fs = sorted(m["poses"])
    frames = []
    for f in fs:
        P = m["poses"][f]
        s = analytics.body_scale(P)
        hx, hy = P.get("hip", (0.0, 0.0))
        row = {"frame": f, "time_s": round((f - fs[0]) / m["fps"], 4), "key": f in m["key_frames"],
               "px": {n: [round(P[n][0], 2), round(P[n][1], 2)] for n in ORDER if n in P},
               "rel": {n: [round((P[n][0] - hx) / s, 4), round((P[n][1] - hy) / s, 4)] for n in ORDER if n in P},
               "angles_deg": {}}
        for a, (p, q, r) in analytics.ANGLES.items():
            if all(n in P for n in (p, q, r)):
                v = analytics.angle_at(P, p, q, r)
                if v is not None:
                    row["angles_deg"][a.replace(" ", "_")] = round(v, 2)
        if f in m["estimated"] and m["estimated"][f]:
            row["estimated"] = [n for n in ORDER if n in m["estimated"][f]]
        frames.append(row)
    return {"schema": SCHEMA, "move": m["move"], "version": m["version"],
            "source": os.path.basename(m["source"]), "fps": round(m["fps"], 4), "fps_from": m["fps_from"],
            "data": "every frame" if len(fs) > len(m["key_frames"]) or not m["key_frames"] else "key frames",
            "key_frames": m["key_frames"], "joints": ORDER,
            "bones": [[a, b] for ch in trace_io.CHAINS for a, b in zip(ch, ch[1:])],
            "units": {"px": "reference-frame pixels, x right, y down",
                      "rel": "relative to the hip, in bone lengths (the frame's median bone length), y down",
                      "time_s": "seconds from the first frame", "angles_deg": "degrees at the middle joint"},
            "fixed": m["fixed_meta"], "frames": frames}


def render_stickman(P, look, box, height, transparent):
    """One picture of the stickman (black, like PLAY / the game) in a fixed box, so a sequence keeps its motion."""
    import trace_player as tp
    from PIL import Image, ImageChops, ImageDraw
    x0, y0, x1, y1 = box
    margin = max(4, height // 30)
    k = (height - 2 * margin) / max(1e-6, (y1 - y0))
    W = max(8, int(round((x1 - x0) * k)) + 2 * margin)
    ox, oy = margin - x0 * k, margin - y0 * k
    ss = tp.SS
    back, front = Image.new("L", (W * ss, height * ss), 0), Image.new("L", (W * ss, height * ss), 0)
    tp.draw_stickman(P, look, lambda x, y: ((x * k + ox) * ss, (y * k + oy) * ss), ImageDraw.Draw(back),
                     ImageDraw.Draw(front), k * ss)
    mask = ImageChops.lighter(back.reduce(ss), front.reduce(ss))
    if transparent:
        img = Image.new("RGBA", (W, height), (0, 0, 0, 0))
        img.paste(Image.new("RGBA", (W, height), tp.INK + (255,)), (0, 0), mask)
    else:
        img = Image.new("RGB", (W, height), tp.PAPER)
        ImageDraw.Draw(img).line((0, look.ground * k + oy, W, look.ground * k + oy), fill=(200, 200, 200), width=2)
        img.paste(tp.INK, (0, 0), mask)
    return img


def render_overlay(folder, f, P, est):
    """Your trace drawn on the reference frame f (as the BACKUPS window and trace_check.png draw it), or None."""
    from PIL import Image, ImageDraw
    from restore_dialog import chain_colour
    p = project.frame_file(folder, f)
    if not p:
        return None
    with Image.open(p) as im:
        img = im.convert("RGB")
    d = ImageDraw.Draw(img)
    w = max(2, img.width // 160)
    for ch in trace_io.CHAINS:
        for a, b in zip(ch, ch[1:]):
            if a in P and b in P:
                d.line([P[a], P[b]], fill=chain_colour(ch), width=w)
    r = max(3, img.width // 110)
    for n, (x, y) in P.items():
        if n in est:
            d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 0), width=2)
        else:
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255), outline=(0, 0, 0))
    return img


def new_batch_dir(out):
    os.makedirs(out, exist_ok=True)
    base = os.path.join(out, time.strftime("export %Y-%m-%d %H%M%S"))
    d, k = base, 2
    while os.path.exists(d):
        d, k = f"{base}-{k}", k + 1
    os.makedirs(d)
    return d


def export_move(m, s, dest, settings, progress=None):
    """Write one prepared move into dest (a new folder). -> [{"path", "kind", "expect"}] of the files written."""
    import trace_player as tp
    os.makedirs(dest)
    out = []
    if settings["copy_traces"]:
        for n in COPIES:
            src = trace_io.find_file(m["folder"] if n == "timing.json" else m.get("tdir", m["folder"]), n)
            if src:
                p = os.path.join(dest, n)
                shutil.copyfile(src, p)
                out.append({"path": p, "kind": "copy", "expect": {"sha1": sha1(src), "name": n}})
    if settings["poses_json"]:
        p = os.path.join(dest, f"{s}_poses.json")
        doc = poses_doc(m)
        trace_io.write_atomic(p, json.dumps(doc, indent=1))
        out.append({"path": p, "kind": "poses", "expect": {"frames": len(doc["frames"])}})
    if settings["csv"]:
        p = os.path.join(dest, f"{s}_frames.csv")
        n = analytics.write_csv(p, m["poses"], m["fps"])
        out.append({"path": p, "kind": "csv", "expect": {"rows": n}})
    if settings["stickman_png"] and m["keys"]:
        full = {f: P for f, P in m["poses"].items() if complete(P)}
        if full:
            look = tp.Look(sorted(full.items()))
            box = look.box
            sub = os.path.join(dest, f"{s}_stickman")
            os.makedirs(sub)
            for k, f in enumerate(sorted(full), 1):
                img = render_stickman(full[f], look, box, int(settings["png_height"]), settings["transparent"])
                p = os.path.join(sub, f"{s}_stickman_{k:04d}.png")
                img.save(p)
                out.append({"path": p, "kind": "png", "expect": {"size": img.size, "frame": f}})
                if progress:
                    progress(f"{m['move']}: stickman picture {k} of {len(full)}")
    if settings["overlay_png"]:
        t = trace_io.find_file(m.get("tdir", m["folder"]), trace_io.TRACE)
        if t:
            mine = compare.load_poses(t)
            J = trace_io.read_json(t)
            est = {int(f): set(E) for f, E in zip(J["frames"], J.get("estimated") or [])}
            sub = os.path.join(dest, f"{s}_overlay")
            made = False
            for f in sorted(mine):
                if not mine[f]:
                    continue
                img = render_overlay(m["folder"], f, mine[f], est.get(f, set()))
                if img is None:
                    continue
                if not made:
                    os.makedirs(sub)
                    made = True
                p = os.path.join(sub, f"{s}_overlay_f{f:02d}.png")
                img.save(p)
                out.append({"path": p, "kind": "png", "expect": {"size": img.size, "frame": f}})
    return out


def render_scene(figs, box, height, transparent):
    """Several characters in one picture (Phase 11): figs = [(pose, look, colour rgb)] drawn in order, in one fixed
    box so a sequence keeps their movements and the distances between them."""
    import trace_player as tp
    from PIL import Image, ImageChops, ImageDraw
    x0, y0, x1, y1 = box
    margin = max(4, height // 30)
    k = (height - 2 * margin) / max(1e-6, (y1 - y0))
    W = max(8, int(round((x1 - x0) * k)) + 2 * margin)
    ox, oy = margin - x0 * k, margin - y0 * k
    ss = tp.SS
    img = Image.new("RGBA", (W, height), (0, 0, 0, 0)) if transparent else Image.new("RGB", (W, height), tp.PAPER)
    for P, look, rgb in figs:
        back, front = Image.new("L", (W * ss, height * ss), 0), Image.new("L", (W * ss, height * ss), 0)
        tp.draw_stickman(P, look, lambda x, y: ((x * k + ox) * ss, (y * k + oy) * ss), ImageDraw.Draw(back),
                         ImageDraw.Draw(front), k * ss)
        mask = ImageChops.lighter(back.reduce(ss), front.reduce(ss))
        ink = Image.new(img.mode, (W, height), tuple(rgb) + ((255,) if transparent else ()))
        img.paste(ink, (0, 0), mask)
    return img


def scene_frames(move):
    """[(char entry, keys, motion or None, look)] of the visible traced characters, and their union frame range."""
    import characters as chars
    import trace_player as tp
    out = []
    for c in chars.list_characters(move):
        ks = chars.keys(move, c["id"])
        if c["visible"] and ks:
            out.append((c, ks, tp.Motion(ks) if len(ks) > 1 else None, tp.Look(ks)))
    if not out:
        return out, []
    first = min(ks[0][0] for _, ks, _, _ in out)
    last = max(ks[-1][0] for _, ks, _, _ in out)
    return out, list(range(first, last + 1))


def export_scene(move, s, dest, settings, progress=None):
    """<move>_scene\\<move>_scene_0001.png …: every visible character together, as traced (character 1 black, the
    others in their colours), one picture per frame; a character is left out outside its traced frames."""
    import trace_player as tp
    data, frames = scene_frames(move)
    if len(data) < 2:
        return []
    boxes = [lk.box for _, _, _, lk in data]
    box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    sub = os.path.join(dest, f"{s}_scene")
    os.makedirs(sub)
    out = []
    for n, f in enumerate(frames, 1):
        figs = []
        for c, ks, m, lk in data:
            if ks[0][0] <= f <= ks[-1][0]:
                P = m.pose(float(f)) if m else dict(ks[0][1])
                figs.append((P, lk, tp.INK if c["id"] == "c1" else tp.hex_rgb(c["colour"])))
        img = render_scene(figs, box, int(settings["png_height"]), settings["transparent"])
        p = os.path.join(sub, f"{s}_scene_{n:04d}.png")
        img.save(p)
        out.append({"path": p, "kind": "png", "expect": {"size": img.size, "frame": f}})
        if progress:
            progress(f"{os.path.basename(move)}: scene picture {n} of {len(frames)}")
    return out


# ---------------------------------------------------------------- checking what was written
def verify(f):
    """Read one written file back. -> (ok, note)."""
    from PIL import Image
    p, kind, ex = f["path"], f["kind"], f["expect"]
    try:
        if kind == "copy":
            if sha1(p) != ex["sha1"]:
                return False, "differs from the original"
            if ex["name"] == trace_io.TRACE:
                import trace_player as tp
                tp.read_trace(p)
            elif ex["name"] == trace_io.FIXED:
                trace_io.summary(p)
            return True, "same bytes as the original"
        if kind == "poses":
            J = trace_io.read_json(p)
            if J.get("schema") != SCHEMA or len(J["frames"]) != ex["frames"]:
                return False, "wrong schema or frame count"
            for row in J["frames"]:
                for x, y in row["px"].values():
                    if not (math.isfinite(x) and math.isfinite(y)):
                        return False, f"a coordinate on frame {row['frame']} isn't a number"
            return True, f"{ex['frames']} frames"
        if kind == "csv":
            with open(p, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            want_cols = 2 + 5 * len(ORDER) + len(analytics.ANGLES)
            if len(rows) - 1 != ex["rows"] or any(len(r) != want_cols for r in rows):
                return False, "wrong number of rows or columns"
            return True, f"{ex['rows']} rows"
        if kind == "png":
            with Image.open(p) as im:
                im.load()
                if im.size != tuple(ex["size"]):
                    return False, "wrong size"
            return True, "opens"
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        return False, f"can't be read back ({e})"
    return False, "unknown file kind"


# ---------------------------------------------------------------- the whole batch
def run(folders, settings, out=None, progress=None):
    """Export the moves in folders. -> result {"dir", "settings", "moves": [...], "skipped": [...], "files": n,
    "checked_ok": n, "failed": [(path, note)], "summary": text}. Moves that can't be exported are skipped, never
    half-written: a move's folder is only made once its data is ready."""
    out = out or settings.get("out")
    if not out:
        raise ValueError("Pick a folder to export into.")
    folders = [os.path.normpath(d) for d in folders]
    if not folders:
        raise ValueError("Pick at least one move.")
    batch = new_batch_dir(out)
    res = {"dir": batch, "settings": dict(settings), "moves": [], "skipped": [], "files": 0, "checked_ok": 0,
           "failed": [], "made": time.strftime("%Y-%m-%d %H:%M:%S")}
    import characters as chars
    slugs = names(folders)
    jobs = []   # (move folder, trace folder or None, label, slug, destination relative to the batch)
    for d in folders:
        jobs.append((d, None, None, slugs[d], slugs[d]))
        if settings.get("characters", True) and chars.is_multi(d):   # Phase 11: the other traced characters
            listed = chars.list_characters(d)
            cnames = names([os.path.join(d, c["name"]) for c in listed[1:]])
            for c in listed[1:]:
                if trace_io.find_file(c["trace_dir"], trace_io.TRACE):
                    cs = cnames[os.path.join(d, c["name"])]
                    jobs.append((d, c["trace_dir"], f"{os.path.basename(d)} \u203a {c['name']}",
                                 f"{slugs[d]}_{cs}", os.path.join(slugs[d], "characters", cs)))
    made_dirs = set()
    for d, td, label, s, rel in jobs:
        if progress:
            progress(f"Preparing {label or os.path.basename(d)}…")
        m = prepare(d, settings, td, label)
        if m["errors"]:
            res["skipped"].append({"move": m["move"], "folder": d, "why": m["errors"]})
            continue
        dest = os.path.join(batch, rel)
        if os.path.isdir(dest):   # character 1 skipped but its folder name is taken by a character: keep apart
            dest = os.path.join(batch, rel + "_2")
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            written = export_move(m, s, dest, settings, progress)
            if td is None and settings.get("scene_png") and chars.is_multi(d) and d not in made_dirs:
                written += export_scene(d, slugs[d], dest, settings, progress)
            made_dirs.add(d)
        except (OSError, ValueError) as e:
            res["skipped"].append({"move": m["move"], "folder": d, "why": [f"Writing failed: {e}"]})
            continue
        checks = []
        for f in written:
            ok, note = verify(f)
            checks.append({"file": os.path.relpath(f["path"], batch), "ok": ok, "note": note})
            if ok:
                res["checked_ok"] += 1
            else:
                res["failed"].append((os.path.relpath(f["path"], batch), note))
        res["files"] += len(written)
        fs = sorted(m["poses"])
        res["moves"].append({
            "move": m["move"], "folder": d, "name": rel.replace(os.sep, "/"), "version": m["version"],
            "source": os.path.basename(m["source"]), "character": td is not None,
            "key_frames": len(m["key_frames"]), "frames": len(fs),
            "duration_s": round((fs[-1] - fs[0]) / m["fps"], 3) if fs else 0.0, "fps": round(m["fps"], 3),
            "fps_from": m["fps_from"], "warnings": m["warnings"], "files": len(written),
            "checks": checks, "fixed": m["fixed_meta"]})
    res["summary"] = summary_text(res)
    trace_io.write_atomic(os.path.join(batch, "export_summary.txt"), res["summary"])
    trace_io.write_atomic(os.path.join(batch, "export_summary.json"),
                          json.dumps({k: v for k, v in res.items() if k != "summary"}, indent=1))
    return res


def summary_text(res):
    s = res["settings"]
    lines = [f"Stickman Studio export  ·  {res['made']}", f"Folder: {res['dir']}",
             f"Settings: {describe_settings(s)}", "",
             f"{project.plural(len(res['moves']), 'move')} exported"
             + (f", {len(res['skipped'])} skipped" if res["skipped"] else "") + ":"]
    for mv in res["moves"]:
        ver = "fixed trace" if mv["version"] == "fixed" else "your trace"
        bad = sum(1 for c in mv["checks"] if not c["ok"])
        lines.append(f"  {mv['name']}  ({mv['move']}): {ver}, {project.plural(mv['key_frames'], 'key frame')}, "
                     f"{project.plural(mv['frames'], 'frame')}, {mv['duration_s']:g} s at {mv['fps']:g} fps"
                     f"{' (a guess)' if mv['fps_from'] == 'a guess' else ''}, {project.plural(mv['files'], 'file')} "
                     + ("checked OK" if not bad else f"({bad} Failed the check)"))
        for w in mv["warnings"]:
            lines.append(f"      ! {w}")
    for sk in res["skipped"]:
        lines.append(f"  Skipped {sk['move']}: " + " ".join(sk["why"]))
    lines += ["", f"Check: {res['checked_ok']} of {project.plural(res['files'], 'file')} read back OK."
              + ("" if not res["failed"] else "  Failed: " + "; ".join(f"{p} ({n})" for p, n in res["failed"]))]
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    images, out = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    want = {a.lower() for a in argv[2:]}
    folders = [d for d in project.moves(images) if not want or os.path.basename(d).lower() in want]
    if not want:
        folders = [d for d in folders if trace_io.find_file(d, trace_io.TRACE)]
    res = run(folders, dict(DEFAULTS), out)
    print(res["summary"])
    return 0 if not res["failed"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
