"""Project management for a move folder (Stickman Studio upgrade, Phase 9). Plain file handling, no AI.

  check(folder)            finds missing or inconsistent trace data: unreadable files, key frames without pictures,
                           frames and points that don't line up, missing joints, odd numbers, points far outside the
                           picture, copied poses, a fixed trace made from an older trace, and more. Read-only.
  fixed_state(folder)      whether trace_fixed.json still matches trace.json (recomputed with PLAY / FIX's own maths)
  status(folder)           counts and dates for the move list and the PROJECT… window
  protect / unprotect      the trace.json read-only lock (trace_io.set_protected), logged in the history
  duplicate                a copy of the move under a new name (frames, trace, fixed trace, side files); the
                           original is only read; the copy is never read-only and starts a clean history
  backup_zip / backup_all  the whole move folder (frames, traces, backups, side files, earlier frames) as one .zip in
                           "Project backups" beside the Images folder
  restore_zip_as_copy      unpacks a project backup into a NEW folder; nothing existing is ever overwritten

Nothing here deletes anything.
"""
import json
import math
import os
import re
import shutil
import stat
import time
import zipfile

import history
import trace_io

FRAME = re.compile(r"^f(\d+)\.png$", re.IGNORECASE)
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
HOME_NAME = "Project backups"
ZIP_NAME = re.compile(r"^(.+)_(\d{8}-\d{6})(?:-(\d+))?\.zip$", re.IGNORECASE)
MANIFEST = "_stickman_project_backup.json"
OUTSIDE = 150      # px: how far outside the picture the editor can show a point (trace_clicker.PAD)
LEVELS = ("error", "warning", "note")


# ---------------------------------------------------------------- small helpers
def frame_numbers(folder):
    try:
        return sorted(int(m.group(1)) for m in (FRAME.match(n) for n in os.listdir(folder)) if m)
    except OSError:
        return []


def frame_file(folder, f):
    for n in (f"f{int(f):02d}.png", f"f{int(f)}.png"):
        p = trace_io.find_file(folder, n)
        if p:
            return p
    return None


def moves(images):
    """Move folders in images (folders with fNN.png frames), sorted by name."""
    try:
        names = sorted(os.listdir(images), key=str.lower)
    except OSError:
        return []
    return [os.path.join(images, n) for n in names
            if os.path.isdir(os.path.join(images, n)) and frame_numbers(os.path.join(images, n))]


def backups_home(images):
    """Where whole-move backups go: "Project backups" beside the Images folder."""
    return os.path.join(os.path.dirname(os.path.normpath(images)), HOME_NAME)


def plural(n, word):
    if n != 1 and len(word) > 1 and word[-1] == "y" and word[-2] not in "aeiou":
        return f"{n} {word[:-1]}ies"   # "log entry" -> "log entries" (was "entrys" in v2.0 / 2.1)
    return f"{n} {word}{'' if n == 1 else 's'}"


def clean_name(name):
    """A folder name you typed, checked. -> the name, or raises ValueError with the reason."""
    name = " ".join(str(name or "").split()).strip(" .")
    if not name:
        raise ValueError("Type a name for the copy.")
    if BAD_NAME.search(name):
        raise ValueError('A folder name can\'t contain < > : " / \\ | ? *')
    if len(name) > 80:
        raise ValueError("That name is too long (80 characters at most).")
    return name


def free_name(parent, base):
    """base, or "base 2", "base 3" ... whichever doesn't exist in parent yet."""
    name, k = base, 2
    while os.path.exists(os.path.join(parent, name)):
        name, k = f"{base} {k}", k + 1
    return name


def make_writable(root):
    """Clear the read-only attribute on every file under root (copies of a protected trace stay editable)."""
    for d, _, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            try:
                if not os.stat(p).st_mode & stat.S_IWRITE:
                    os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass


def folder_size(folder):
    total = files = 0
    for d, _, names in os.walk(folder):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(d, n))
                files += 1
            except OSError:
                pass
    return total, files


def size_text(b):
    for unit in ("bytes", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit == "bytes" else f"{b:.1f} {unit}"
        b /= 1024.0


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---------------------------------------------------------------- the fixed trace against the trace
def fixed_state(folder):
    """Is trace_fixed.json still what PLAY / FIX would make from today's trace.json with its saved settings?
    -> (state, detail): "none" (no fixed trace), "ok", "stale", "no trace", "unreadable" (detail says why)."""
    import trace_player as tp   # PLAY / FIX's own maths, so "up to date" means exactly what it would save
    fx = trace_io.find_file(folder, trace_io.FIXED)
    if not fx:
        return "none", ""
    try:
        J = trace_io.read_json(fx)
        frames = [int(f) for f in J["frames"]]
        pts = J["pts"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return "unreadable", f"trace_fixed.json can't be read ({e})"
    t = trace_io.find_file(folder, trace_io.TRACE)
    if not t:
        return "no trace", "there's a fixed trace but no trace.json it could be made from"
    try:
        keys, _ = tp.read_trace(t)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return "unreadable", f"trace.json can't be read ({e})"
    if [f for f, _ in keys] != frames:
        return "stale", (f"it was made from key frames {', '.join(map(str, frames)) or 'none'}, and your finished "
                         f"key frames are now {', '.join(str(f) for f, _ in keys) or 'none'}")
    fix = {**tp.FIX_DEFAULT, **(J.get("fix") if isinstance(J.get("fix"), dict) else {})}
    try:
        out, _ = tp.apply_fix(keys, fix)
    except (ValueError, ZeroDivisionError, KeyError, TypeError) as e:
        return "unreadable", f"the fix couldn't be recomputed ({e})"
    worst = (0.0, None, None)
    for (f, P), Q in zip(out, pts):
        for n in trace_io.ORDER:
            try:
                d = max(abs(P[n][0] - float(Q[n][0])), abs(P[n][1] - float(Q[n][1])))
            except (KeyError, TypeError, ValueError, IndexError):
                d = float("inf")
            if d > worst[0]:
                worst = (d, f, n)
    if worst[0] > 0.11:   # the file keeps 0.1 px
        far = "" if worst[0] == float("inf") else f" by {worst[0]:.1f} px"
        return "stale", (f"it was made from an older version of your trace (frame {worst[1]}, {worst[2]} differs{far} "
                         f"from what Review makes now)")
    return "ok", ""


# ---------------------------------------------------------------- checking
def check(folder):
    """Missing or inconsistent trace data in a move folder. Read-only.
    -> [{"level": "error" | "warning" | "note", "text": str, "frames": [frame numbers]}], errors first.
    Phase 11: in a multi-character move every character is checked against the shared frames (its issues start with
    its name and carry "character": id), and the character list itself is checked (characters.problems)."""
    import characters as chars
    order = {lv: k for k, lv in enumerate(LEVELS)}
    out = check_one(folder, folder)
    if chars.is_multi(folder):
        listed = chars.list_characters(folder)
        for i in out:
            if not i.get("move_level"):
                i["text"] = f"{listed[0]['name']}: {i['text']}"
                i["character"] = chars.PRIMARY
        for level, text in chars.problems(folder):
            out.append({"level": level, "text": text, "frames": [], "move_level": True})
        for c in listed:
            if c["id"] == chars.PRIMARY or not os.path.isdir(c["trace_dir"]):
                continue
            for i in check_one(folder, c["trace_dir"]):
                i["text"], i["character"] = f"{c['name']}: {i['text']}", c["id"]
                out.append(i)
    for i in out:
        i.pop("move_level", None)
    return sorted(out, key=lambda i: order[i["level"]])


def check_one(folder, trace_dir):
    """The checks of one trace (a character's folder) against the move's frames. trace_dir == folder for the
    move's own trace (character 1); then the move-level checks (frames, timing.json) are done too."""
    out = []
    own = os.path.normcase(os.path.normpath(trace_dir)) == os.path.normcase(os.path.normpath(folder))

    def add(level, text, frames=None, move_level=False):
        out.append({"level": level, "text": text, "frames": sorted({int(f) for f in frames or []}),
                    "move_level": move_level})

    nums = frame_numbers(folder)
    if not nums and own:
        add("error", "There are no frames (f01.png, f02.png …) in this folder, so nothing can be traced or played.",
            move_level=True)
    t = trace_io.find_file(trace_dir, trace_io.TRACE)
    fx = trace_io.find_file(trace_dir, trace_io.FIXED)
    J = None
    if t:
        try:
            J = trace_io.read_json(t)
        except (OSError, ValueError) as e:
            add("error", f"trace.json can't be read ({e}). Backups… can put an earlier version back.")
        if J is not None and not (isinstance(J, dict) and isinstance(J.get("frames"), list)
                                  and isinstance(J.get("pts"), list)):
            add("error", "trace.json has no list of key frames and points, so no tool can use it. "
                         "Backups… can put an earlier version back.")
            J = None
    if J is not None:
        check_trace(folder, J, nums, add, trace_dir)
    elif not t and nums:
        add("note", "Not traced yet." if not fx else "There's a fixed trace but no trace.json, so the move can't "
                                                     "be re-traced or fixed again. Backups… may have it.")
    if fx:
        state, detail = fixed_state(trace_dir)
        if state == "unreadable":
            add("error", detail[0].upper() + detail[1:] + ".")
        elif state == "stale":
            add("warning", f"The fixed trace is out of date: {detail}. Open Review and save it again "
                           "(that never changes trace.json).")
    check_side_files(folder, J, nums, add, trace_dir)
    order = {lv: k for k, lv in enumerate(LEVELS)}
    return sorted(out, key=lambda i: order[i["level"]])


def check_trace(folder, J, nums, add, trace_dir=None):
    trace_dir = trace_dir or folder
    frames, pts = J["frames"], J["pts"]
    est = J.get("estimated")
    if trace_io.is_fixed_data(J):
        add("error", "trace.json holds a Fixed trace (it has Review settings in it). Your own trace and the fixed "
                     "trace belong in separate files: put your trace back from Backups….")
    bad = [f for f in frames if not (isinstance(f, int) and not isinstance(f, bool))]
    if bad:
        add("error", f"Some key frame numbers aren't whole numbers ({', '.join(map(str, bad[:5]))}).")
        frames = [f for f in frames if f not in bad]
    if len(J["frames"]) != len(pts):
        add("error", f"trace.json lists {plural(len(J['frames']), 'key frame')} but "
                     f"{plural(len(pts), 'set')} of points: every tool pairs them up in order and ignores the "
                     "extra ones, so some points may sit on the wrong frame.")
    dup = sorted({f for f in frames if frames.count(f) > 1})
    if dup:
        add("error", f"Key frame{'s' if len(dup) > 1 else ''} {', '.join(map(str, dup))} "
                     f"{'are' if len(dup) > 1 else 'is'} listed twice.", dup)
    nopic = [f for f in frames if f not in nums]
    if nopic and nums:
        add("error", "The picture of key frame" + ("s " if len(nopic) > 1 else " ")
            + ", ".join(f"f{f:02d}.png" for f in nopic) + " is missing, so the trace can't be shown on it.", nopic)
    if not frames:
        add("note", "trace.json has no key frames yet.")
    sizes = {}

    def size(f):
        if f not in sizes:
            p = frame_file(folder, f)
            try:
                from PIL import Image
                with Image.open(p) as im:
                    sizes[f] = im.size
            except (OSError, AttributeError, TypeError, ValueError):
                sizes[f] = None
        return sizes[f]

    unknown, badnum, unfinished, far = {}, [], [], []
    good = {}
    for f, P in zip(frames, pts):
        if not isinstance(P, dict):
            badnum.append(f)
            continue
        for k in P:
            if k not in trace_io.ALL:   # v3.0: the 6 optional joints are known too (and never required)
                unknown.setdefault(k, []).append(f)
        ok = {}
        for n in trace_io.ALL:
            if n in P:
                v = P[n]
                if isinstance(v, (list, tuple)) and len(v) == 2 and all(is_number(c) for c in v):
                    ok[n] = (float(v[0]), float(v[1]))
                else:
                    badnum.append(f)
        good[f] = ok
        miss = [n for n in trace_io.ORDER if n not in ok]
        if miss:
            unfinished.append((f, miss))
        wh = size(f) if ok else None
        if wh:
            w, h = wh
            out_pts = [n for n, (x, y) in ok.items() if x < -OUTSIDE or y < -OUTSIDE or x > w + OUTSIDE
                       or y > h + OUTSIDE]
            if out_pts:
                far.append((f, out_pts))
    if badnum:
        add("error", "Some points aren't two plain numbers (x, y), so they're skipped: "
            + history.frames_text(set(badnum)) + ".", set(badnum))
    for k, fs in unknown.items():
        add("warning", f"“{k}” isn't one of the 12 joints or the 6 optional ones (shoulders, hand tips, toes); "
                       f"every tool ignores it ({history.frames_text(fs)}).", fs)
    if unfinished:
        parts = [f"frame {f} ({len(m)}: {', '.join(m[:3])}{' …' if len(m) > 3 else ''})" for f, m in unfinished[:6]]
        add("warning", f"{plural(len(unfinished), 'key frame')} {'is' if len(unfinished) == 1 else 'are'} missing "
                       f"points, so Review leaves {'it' if len(unfinished) == 1 else 'them'} out: "
                       + "; ".join(parts) + (" …" if len(unfinished) > 6 else "") + ". N in the editor jumps there.",
            [f for f, _ in unfinished])
    for f, ns in far:
        add("warning", f"Frame {f}: {', '.join(ns)} {'is' if len(ns) == 1 else 'are'} more than {OUTSIDE} px outside "
                       "the picture, beyond where the editor can show or drag it.", [f])
    if est is not None:
        if not isinstance(est, list) or len(est) != len(J["frames"]):
            add("warning", "The list of guessed points (\"estimated\") doesn't line up with the key frames; the editor "
                           "will rebuild it the next time it saves.")
        else:
            odd = [f for f, E, P in zip(frames, est, pts)
                   if not isinstance(E, list) or any(n not in trace_io.ALL or not isinstance(P, dict) or n not in P
                                                     for n in E)]
            if odd:
                add("warning", "Some guessed-point marks name joints that aren't placed on that frame ("
                    + history.frames_text(odd) + "); they're ignored.", odd)
    # the same pose on two key frames: usually faded points kept with Enter (or carried as traced) and not moved
    full = [(f, P) for f, P in good.items() if len(P) >= 6]
    same = []
    for a in range(len(full)):
        for b in range(a + 1, len(full)):
            (fa, Pa), (fb, Pb) = full[a], full[b]
            if set(Pa) == set(Pb) and all(math.dist(Pa[n], Pb[n]) < 0.05 for n in Pa):
                same.append((fa, fb))
    for fa, fb in same[:5]:
        add("warning", f"Frames {fa} and {fb} have exactly the same pose: often points that were kept or carried "
                       "forward without being moved onto the picture.", [fa, fb])
    if frames != sorted(frames):
        add("note", "The key frames aren't in order in trace.json. Every tool sorts them, so this is only a note.")
    try:   # the editor's own bone-length hint (2x / 0.5x the usual length for that body size)
        import trace_clicker as tc
        _, states = tc.load_trace(trace_io.trace_path(trace_dir))
        flagged = [(f, k) for f in states for k in tc.bone_flags(states, list(states), f)]
        if flagged:
            fs = sorted({f for f, _ in flagged})
            add("note", f"Unusual bone lengths on {history.frames_text(fs)} (over twice or under half the usual "
                        "length). A turn can explain it; K in the editor shows them.", fs)
    except (OSError, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError):
        pass


def check_side_files(folder, J, nums, add, trace_dir=None):
    import trace_player as tp
    trace_dir = trace_dir or folder
    own = os.path.normcase(os.path.normpath(trace_dir)) == os.path.normcase(os.path.normpath(folder))
    tj = trace_io.find_file(folder, "timing.json")
    if not own:
        pass   # the frame rate belongs to the move: checked once, with character 1
    elif tj:
        try:
            fps = float(trace_io.read_json(tj)["fps"])
            if not fps > 0:
                raise ValueError("not a positive number")
        except (OSError, ValueError, KeyError, TypeError) as e:
            add("warning", f"timing.json can't be read ({e}); the frame rate is a guess.", move_level=True)
    elif nums:
        rate, where = tp.find_fps(folder)
        add("note", f"No timing.json: the frame rate ({rate:g} fps) is {where}.", move_level=True)
    folder = trace_dir   # everything below (key poses, history, backups) belongs to this character's own folder
    kp = trace_io.find_file(folder, "key_poses.json")
    if kp:
        try:
            K = trace_io.read_json(kp)
            kf = sorted({int(q["frame"]) for q in K.get("poses", []) if isinstance(q, dict) and "frame" in q})
            if J is not None and nums:
                lost = [f for f in kf if f not in nums]
                if lost:
                    add("note", f"key_poses.json marks {history.frames_text(lost)}, which "
                                f"{'isn' if len(lost) == 1 else 'aren'}'t in this folder any more.", lost)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            add("warning", f"key_poses.json can't be read ({e}); the Key Poses window will start empty.")
    _, problem = history.load(folder)
    if problem:
        add("note", problem)
    broken = []
    for b in trace_io.list_backups(folder):
        try:
            trace_io.summary(b["path"])
        except (OSError, ValueError, KeyError, TypeError):
            broken.append(b["name"])
    if broken:
        add("note", f"{plural(len(broken), 'backup')} can't be read ({', '.join(broken[:3])}"
                    f"{' …' if len(broken) > 3 else ''}); they're kept but can't be restored.")
    try:
        loose = [n for n in os.listdir(folder) if trace_io.BACKUP_NAME.match(n)]
    except OSError:
        loose = []
    if loose:
        add("note", f"{plural(len(loose), 'backup file')} sit{'s' if len(loose) == 1 else ''} next to the frames "
                    f"instead of in backups\\ ({', '.join(loose[:2])}{' …' if len(loose) > 2 else ''}), so Backups… "
                    "doesn't list them. Move them into a backups folder to restore them from there.")


def counts(issues):
    return {lv: sum(1 for i in issues if i["level"] == lv) for lv in LEVELS}


# ---------------------------------------------------------------- status (move list and PROJECT… window)
_cache = {}


def signature(folder):
    import characters as chars
    sig = []
    dirs = [folder]
    if chars.is_multi(folder):   # every character's files count (Phase 11)
        dirs += [c["trace_dir"] for c in chars.list_characters(folder)[1:]]
    for k, d in enumerate(dirs):
        for n in (trace_io.TRACE, trace_io.FIXED, "timing.json", "key_poses.json", history.FILE, chars.FILE):
            p = trace_io.find_file(d, n)
            if p:
                try:
                    s = os.stat(p)
                    sig.append((k, n, s.st_mtime_ns, s.st_size, s.st_mode))
                except OSError:
                    pass
    return tuple(sig), len(frame_numbers(folder))


def status(folder):
    """-> {"frames", "keys", "done", "fixed" (fixed_state), "fixed_detail", "protected", "backups", "checkpoints",
    "edited" (trace.json time or None), "issues" (check list), "counts", "old" (earlier-frames folders)}.
    Cached until one of the move's trace files changes."""
    sig = signature(folder)
    hit = _cache.get(os.path.normcase(folder))
    if hit and hit[0] == sig:
        return hit[1]
    nums = frame_numbers(folder)
    t = trace_io.find_file(folder, trace_io.TRACE)
    keys = done = 0
    if t:
        try:
            s = trace_io.summary(t)
            keys, done = s["frames"], s["done"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    fs, detail = fixed_state(folder)
    bks = trace_io.list_backups(folder)
    issues = check(folder)
    try:
        old = sorted(n for n in os.listdir(folder) if n.lower().startswith("old ")
                     and os.path.isdir(os.path.join(folder, n)))
    except OSError:
        old = []
    st = {"frames": len(nums), "keys": keys, "done": done, "fixed": fs, "fixed_detail": detail,
          "protected": bool(t) and trace_io.is_protected(t), "backups": len(bks),
          "checkpoints": sum(1 for b in bks if b.get("label")), "edited": os.path.getmtime(t) if t else None,
          "issues": issues, "counts": counts(issues), "old": old, "characters": None}
    import characters as chars
    if chars.is_multi(folder):   # Phase 11: [{"id", "name", "colour", "visible", "locked", "done", "frames", ...}]
        try:
            st["characters"] = chars.CharacterSet.open(folder).summary()
        except chars.CharacterError:
            st["characters"] = []
    _cache[os.path.normcase(folder)] = (sig, st)
    return st


def last_edited(folder):
    """The newest change to the move's own data (trace, fixed trace, key poses), or the frames' time."""
    import characters as chars
    times = []
    dirs = [c["trace_dir"] for c in chars.list_characters(folder)] if chars.is_multi(folder) else [folder]
    for d in dirs:
        for n in (trace_io.TRACE, trace_io.FIXED, "key_poses.json"):
            p = trace_io.find_file(d, n)
            if p:
                times.append(os.path.getmtime(p))
    if not times:
        try:
            times = [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder) if FRAME.match(n)]
        except OSError:
            pass
    return max(times) if times else 0.0


def sort_moves(folders, by="name"):
    if by == "recent":
        return sorted(folders, key=lambda d: -last_edited(d))
    return sorted(folders, key=lambda d: os.path.basename(d).lower())


# ---------------------------------------------------------------- protection
def protect(folder):
    """Make trace.json read-only (a backup is made first). The fixed trace stays writable, so PLAY / FIX can still
    save a new one: your traced original is what's protected. -> trace.json path."""
    p = trace_io.set_protected(folder, True)
    history.add_event(folder, "protect", "Protected: trace.json made read-only")
    return p


def unprotect(folder):
    p = trace_io.set_protected(folder, False)
    history.add_event(folder, "unprotect", "Unprotected: trace.json can be edited again")
    return p


# ---------------------------------------------------------------- duplicating
def duplicate(folder, new_name, with_backups=False, with_old=False):
    """Copy the move into a new folder next to it: frames, trace.json, trace_fixed.json, timing.json, key poses and
    every other file at the top of the folder (not trace_history.json: the copy starts a clean history, with a note
    of where it came from). backups\\ and the "old …" folders of earlier frames only when asked. The copy is never
    read-only. The original is only read. -> the new folder. Raises ValueError for a bad or taken name."""
    folder = os.path.normpath(folder)
    name = clean_name(new_name)
    dest = os.path.join(os.path.dirname(folder), name)
    if os.path.exists(dest):
        raise ValueError(f"There's already a folder called “{name}”. Pick another name.")
    if os.path.normcase(dest) == os.path.normcase(folder):
        raise ValueError("Pick a different name from the original.")
    os.makedirs(dest)
    copied = 0
    for n in sorted(os.listdir(folder)):
        src = os.path.join(folder, n)
        if os.path.isfile(src):
            if n.lower().endswith(".tmp") or n.lower() == history.FILE:
                continue
            shutil.copy2(src, os.path.join(dest, n))
            copied += 1
        elif os.path.isdir(src) and ((with_backups and n.lower() == trace_io.BACKUP_DIR)
                                     or (with_old and n.lower().startswith("old "))):
            shutil.copytree(src, os.path.join(dest, n))
            copied += folder_size(src)[1]
        elif os.path.isdir(src) and n.lower() == "characters":
            # Phase 11: every traced character comes along (each one's backups and the deleted ones only with
            # with_backups; no undo history, as for character 1)
            def skip(d, names, top=src):
                out = {x for x in names if x.lower() == history.FILE or x.lower().endswith(".tmp")}
                if not with_backups:
                    out |= {x for x in names if x.lower() == trace_io.BACKUP_DIR}
                    if os.path.normcase(d) == os.path.normcase(top):
                        out |= {x for x in names if x.lower() == "_deleted"}
                return out
            shutil.copytree(src, os.path.join(dest, n), ignore=skip)
            copied += folder_size(os.path.join(dest, n))[1]
    make_writable(dest)
    history.add_event(dest, "copy", f"Made as a copy of “{os.path.basename(folder)}” ({plural(copied, 'file')})")
    return dest


def copy_name(folder):
    parent, base = os.path.dirname(os.path.normpath(folder)), os.path.basename(os.path.normpath(folder))
    return free_name(parent, f"{base} copy")


# ---------------------------------------------------------------- whole-move backups (.zip)
def backup_zip(folder, home):
    """Pack the whole move folder (every file and subfolder) into <home>\\<move>_YYYYMMDD-HHMMSS.zip.
    -> (zip path, files packed)."""
    folder = os.path.normpath(folder)
    move = os.path.basename(folder)
    os.makedirs(home, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path, k = os.path.join(home, f"{move}_{stamp}.zip"), 2
    while os.path.exists(path):
        path, k = os.path.join(home, f"{move}_{stamp}-{k}.zip"), k + 1
    tmp = path + ".tmp"
    n, total = 0, 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for d, dirs, files in os.walk(folder):
                dirs.sort()
                if not files and not dirs and os.path.normpath(d) != folder:
                    # an empty folder (Phase 11: a character that isn't traced yet) is kept as a folder entry
                    z.writestr(os.path.join(move, os.path.relpath(d, folder)).replace(os.sep, "/") + "/", "")
                for name in sorted(files):
                    if name.lower().endswith(".tmp"):
                        continue
                    full = os.path.join(d, name)
                    z.write(full, os.path.join(move, os.path.relpath(full, folder)).replace(os.sep, "/"))
                    n += 1
                    total += os.path.getsize(full)
            z.writestr(MANIFEST, json.dumps({"what": "Stickman Studio project backup", "move": move,
                                             "made": time.strftime("%Y-%m-%d %H:%M:%S"), "files": n, "bytes": total,
                                             "from": folder}, indent=1))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)   # only our own half-written file
    history.add_event(folder, "project backup", f"Whole move backed up ({plural(n, 'file')}) to "
                                                f"{HOME_NAME}\\{os.path.basename(path)}")
    return path, n


def backup_all(images, home):
    """backup_zip for every move in images. -> [(zip path, files)]."""
    return [backup_zip(d, home) for d in moves(images)]


def list_zip_backups(home, move=None):
    """Project backups in home, newest first: [{"path", "name", "move", "time", "size"}] (only for move if given)."""
    out = []
    try:
        names = os.listdir(home)
    except OSError:
        return out
    for n in names:
        m = ZIP_NAME.match(n)
        if not m:
            continue
        if move and m.group(1).lower() != move.lower():
            continue
        try:
            t = time.mktime(time.strptime(m.group(2), "%Y%m%d-%H%M%S"))
            size = os.path.getsize(os.path.join(home, n))
        except (ValueError, OSError):
            continue
        out.append({"path": os.path.join(home, n), "name": n, "move": m.group(1), "time": t,
                    "seq": int(m.group(3) or 0), "size": size})
    out.sort(key=lambda b: (b["time"], b["seq"]), reverse=True)
    return out


def zip_info(path):
    """-> {"move", "made", "files", "bytes"} from the backup's manifest (or from its file list)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n != MANIFEST and not n.endswith("/")]
        try:
            info = json.loads(z.read(MANIFEST).decode("utf-8"))
        except (KeyError, ValueError):
            info = {}
        info.setdefault("move", names[0].split("/")[0] if names else "")
        info.setdefault("files", len(names))
        info.setdefault("bytes", sum(z.getinfo(n).file_size for n in names))
        info["frames"] = sum(1 for n in names if n.count("/") == 1 and FRAME.match(n.split("/")[1]))
        info["traced"] = any(n.count("/") == 1 and n.split("/")[1].lower() == trace_io.TRACE for n in names)
        return info


def restore_character_folders(dest):
    """Phase 11: a character listed in characters.json whose folder is missing after unpacking (a zip made before
    empty folders were kept, and the character wasn't traced yet) gets its empty folder back. Only folders the list
    names, inside the move; nothing else is created."""
    try:
        import characters as chars
        if not chars.is_multi(dest):
            return
        root = os.path.realpath(dest)
        for c in chars.list_characters(dest):
            d = os.path.realpath(c["trace_dir"])
            if d.startswith(root + os.sep) and not os.path.exists(d):
                os.makedirs(d)
    except Exception:   # a broken list: leave it as it is; the check reports it
        pass


def restore_zip_as_copy(path, images, new_name=None):
    """Unpack a project backup into a NEW folder in images: "<move> (backup YYYY-MM-DD HHMM)" unless new_name is
    given. Nothing that exists is overwritten. -> the new folder. Raises ValueError for a bad zip or name."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ValueError(f"That backup can't be opened ({e}).")
    with z:
        names = [n for n in z.namelist() if n != MANIFEST]
        tops = {n.split("/")[0] for n in names if n.strip("/")}
        if len(tops) != 1:
            raise ValueError("That isn't a Stickman Studio project backup (it should hold one move folder).")
        top = tops.pop()
        if new_name:
            name = clean_name(new_name)
        else:
            m = ZIP_NAME.match(os.path.basename(path))
            when = time.strftime("%Y-%m-%d %H%M", time.strptime(m.group(2), "%Y%m%d-%H%M%S")) if m else "copy"
            name = free_name(images, f"{top} (backup {when})")
        dest = os.path.join(images, name)
        if os.path.exists(dest):
            raise ValueError(f"There's already a folder called “{name}”. Pick another name.")
        root = os.path.realpath(dest)
        jobs, empty_dirs = [], []
        for n in names:
            rel = n[len(top) + 1:].strip("/")
            if not rel:
                continue
            target = os.path.realpath(os.path.join(dest, *rel.split("/")))
            if not target.startswith(root + os.sep):
                raise ValueError(f"That backup has a file outside its folder ({n}); nothing was unpacked.")
            if n.endswith("/"):
                empty_dirs.append(target)   # an empty folder kept in the backup (an untraced character's)
            else:
                jobs.append((n, target))
        os.makedirs(dest)
        for target in empty_dirs:
            os.makedirs(target, exist_ok=True)
        for n, target in jobs:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    restore_character_folders(dest)
    make_writable(dest)
    history.add_event(dest, "restored copy", f"Unpacked as a copy from the project backup {os.path.basename(path)}")
    return dest
