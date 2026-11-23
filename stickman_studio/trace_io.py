"""Reading, writing and backing up trace files (Stickman Studio upgrade, Phase 1; precision in Phase 2).

trace.json and trace_fixed.json keep the format they had in v1.1: format_trace() writes trace.json the way
trace_clicker.save_trace always has (that function now calls it), byte for byte for whole-pixel coordinates. Since
Phase 2 a point placed between pixels (zoomed in) keeps one decimal place instead of being rounded to a whole pixel;
every reader already parses the numbers as floats. Anything new the upgrade needs is kept in separate side files
(SIDE_FILES / SIDE_DIRS), never inside trace.json, because the trace editor rewrites trace.json from
frames / pts / estimated only and would drop any other field.

Versioned backups live in <move folder>\\backups\\:
    trace_YYYYMMDD-HHMMSS_<reason>.json         copies of trace.json
    trace_fixed_YYYYMMDD-HHMMSS_<reason>.json   copies of trace_fixed.json
A backup is skipped when it would be identical to the newest one of its kind. Backups are only ever copied, never
moved, and nothing here deletes them. The old single trace_backup.json works as before.

Phase 9 adds:
    checkpoints        a backup you name yourself (reason "checkpoint"); the names are kept in
                       backups\\checkpoints.json, beside the backups they belong to
    restore_frames     put back only some key frames of a trace backup (the rest of trace.json stays as it is)
    protection         a protected trace.json has the Windows read-only attribute: nothing here overwrites it
    kinds kept apart   a trace backup only ever goes back to trace.json and a fixed one only to trace_fixed.json;
                       a file that holds a fixed trace is never put back as trace.json

usage (from a console):
    python -I trace_io.py backup     <move folder> [reason]
    python -I trace_io.py checkpoint <move folder> <name>
    python -I trace_io.py list       <move folder>
"""
import json
import os
import re
import shutil
import stat
import sys
import time

ORDER = ["head", "neck", "waist", "hip", "backKnee", "backFoot", "frontKnee", "frontFoot",
         "frontElbow", "frontHand", "backElbow", "backHand"]
CHAINS = [("hip", "backKnee", "backFoot"), ("hip", "frontKnee", "frontFoot"), ("hip", "waist", "neck", "head"),
          ("neck", "frontElbow", "frontHand"), ("neck", "backElbow", "backHand")]
# v3.0: six OPTIONAL joints (never required: a frame is finished with the 12 above). With them a limb reads
#   neck > shoulder > elbow > hand > hand tip   and   hip > knee > foot > toe.
# Each is kept relative to its reference bone, so it follows the limb in every in-between.
EXTRAS = ["frontShoulder", "backShoulder", "frontHandTip", "backHandTip", "frontToe", "backToe"]
EXTRA_PARENT = {"frontShoulder": "neck", "backShoulder": "neck", "frontHandTip": "frontHand",
                "backHandTip": "backHand", "frontToe": "frontFoot", "backToe": "backFoot"}
EXTRA_REF = {"frontShoulder": ("waist", "neck"), "backShoulder": ("waist", "neck"),
             "frontHandTip": ("frontElbow", "frontHand"), "backHandTip": ("backElbow", "backHand"),
             "frontToe": ("frontKnee", "frontFoot"), "backToe": ("backKnee", "backFoot")}
ALL = ORDER + EXTRAS


def chains(P):
    """The limb chains of pose P, with the optional joints it has put in their places."""
    out = []
    for ch in CHAINS:
        c = list(ch)
        if c[0] == "neck" and c[1].replace("Elbow", "Shoulder") in P:
            c.insert(1, c[1].replace("Elbow", "Shoulder"))
        tip = {"Foot": "Toe", "Hand": "HandTip"}
        for end, add in tip.items():
            if c[-1].endswith(end) and c[-1].replace(end, add) in P:
                c.append(c[-1].replace(end, add))
        out.append(tuple(c))
    return out

TRACE = "trace.json"
FIXED = "trace_fixed.json"
BACKUP_DIR = "backups"
SIDE_FILES = ("trace_history.json", "key_poses.json", "characters.json")   # upgrade side files beside trace.json
#   key_poses.json: Phase 6 key poses (keyposes.py); trace_history.json: Phase 9;
#   characters.json: Phase 11 traced characters (characters.py)
SIDE_DIRS = (BACKUP_DIR, "characters")   # characters\: the other traced characters' own trace folders (Phase 11)
CHECKPOINTS = "checkpoints.json"   # Phase 9: checkpoint names, kept inside backups\ (so it moves with them)
# .json files in a move folder that belong to the trace (not Game Settings projects)
TRACE_JSON = {TRACE, FIXED, "trace_backup.json", "timing.json", *SIDE_FILES}
REASONS = {"open": "trace opened", "restore": "before a restore", "manual": "made by hand",
           "batch": "before a batch change", "fix": "before a new fixed trace was saved",
           "smooth": "before smoothing", "checkpoint": "checkpoint", "group": "before a group edit",
           "outside": "changed outside the editor", "protect": "when it was protected"}
BACKUP_NAME = re.compile(r"^(trace|trace_fixed)_(\d{8}-\d{6})(?:-(\d+))?(?:_([a-z]+))?\.json$", re.IGNORECASE)


# ---------------------------------------------------------------- finding and reading
def find_file(folder, name):
    """The file called name in folder, matched without regard to case (Images\\jump has Trace.json), or None."""
    try:
        for n in os.listdir(folder):
            if n.lower() == name.lower():
                return os.path.join(folder, n)
    except OSError:
        pass
    return None


def trace_path(folder):
    """The folder's trace.json (whatever its case), or where a new one goes."""
    return find_file(folder, TRACE) or os.path.join(folder, TRACE)


def fixed_path(folder):
    return find_file(folder, FIXED) or os.path.join(folder, FIXED)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def summary(path):
    """-> {"frames": n, "done": frames with all 12 joints, "points": joints placed, "estimated": joints guessed}.
    Raises OSError / ValueError for a missing or broken file."""
    J = read_json(path)
    frames, pts = list(J["frames"]), list(J["pts"])
    est = J.get("estimated") or [[] for _ in frames]
    return {"frames": len(frames),
            "done": sum(1 for P in pts if all(n in P for n in ORDER)),
            "points": sum(sum(1 for n in P if n in ORDER) for P in pts),
            "estimated": sum(len(E) for E in est)}


# ---------------------------------------------------------------- writing
def num(v):
    """A coordinate as text: a whole pixel as an integer (as v1.1 wrote it), otherwise one decimal place."""
    r = round(float(v), 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def format_trace(frames, pts, est):
    """trace.json text. frames = [frame numbers], pts = [{joint: [x, y]}], est = [[joint names]], all in frame order.
    Layout as v1.1: joints in ORDER, four joints per line; coordinates to 0.1 px (whole pixels as integers).
    v3.0: the optional joints (EXTRAS) come after the 12, only when placed, so files without them are unchanged."""
    blocks = []
    for P in pts:
        items = [f'"{n}": [{num(P[n][0])}, {num(P[n][1])}]' for n in ALL if n in P]
        rows = [", ".join(items[i:i + 4]) for i in range(0, len(items), 4)]
        blocks.append("  {" + ",\n   ".join(rows) + "}")
    est_txt = ", ".join("[" + ", ".join(f'"{n}"' for n in ALL if n in E and n in P) + "]"
                        for P, E in zip(pts, est))
    return ('{"frames": [' + ", ".join(str(f) for f in frames) + "],\n \"pts\": [\n" + ",\n".join(blocks)
            + "\n ],\n \"estimated\": [" + est_txt + "]}\n")


def write_atomic(path, text):
    """Write text so a crash leaves the old file or the new one, never half of one."""
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:   # no encoding / newline arguments: the same bytes v1.1 wrote
        fh.write(text)
    os.replace(tmp, path)


def write_trace(path, frames, pts, est):
    write_atomic(path, format_trace(frames, pts, est))


def copy_atomic(src, dst):
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


# ---------------------------------------------------------------- versioned backups
def backup_folder(folder):
    return os.path.join(folder, BACKUP_DIR)


def list_backups(folder):
    """-> newest first: [{"path", "name", "kind" ("trace" | "fixed"), "time" (epoch s), "stamp", "reason",
    "label" (the checkpoint's name, or "")}]."""
    d = backup_folder(folder)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    labels = checkpoint_names(folder) if CHECKPOINTS in {n.lower() for n in names} else {}
    for n in names:
        m = BACKUP_NAME.match(n)
        if not m:
            continue
        try:
            t = time.mktime(time.strptime(m.group(2), "%Y%m%d-%H%M%S"))
        except ValueError:
            continue
        out.append({"path": os.path.join(d, n), "name": n, "kind": "fixed" if m.group(1).lower() == "trace_fixed"
                    else "trace", "time": t, "seq": int(m.group(3) or 0), "stamp": m.group(2),
                    "reason": (m.group(4) or "").lower(), "label": labels.get(n.lower(), {}).get("name", "")})
    out.sort(key=lambda b: (b["time"], b["seq"], b["kind"] == "trace"), reverse=True)   # same second: trace first
    return out


def same_bytes(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def backup_file(folder, src, kind, reason="manual", force=False):
    """Copy src into backups\\ as the newest backup of its kind. -> the new path, or None when src is missing or is
    identical to the newest backup of that kind (unless force)."""
    if not src or not os.path.isfile(src):
        return None
    if not force:
        newest = next((b for b in list_backups(folder) if b["kind"] == kind), None)
        if newest and same_bytes(newest["path"], src):
            return None
    d = backup_folder(folder)
    os.makedirs(d, exist_ok=True)
    stem = "trace_fixed" if kind == "fixed" else "trace"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = re.sub(r"[^a-z]", "", reason.lower()) or "manual"
    # two backups of a kind in the same second (any reason): the later one gets a higher number, so the list
    # always shows them in the order they were made
    same = [b["seq"] for b in list_backups(folder) if b["kind"] == kind and b["stamp"] == stamp]
    if same:
        path = os.path.join(d, f"{stem}_{stamp}-{max(max(same), 1) + 1}_{tag}.json")
    else:
        path = os.path.join(d, f"{stem}_{stamp}_{tag}.json")
    while os.path.exists(path):   # belt and braces
        m = BACKUP_NAME.match(os.path.basename(path))
        path = os.path.join(d, f"{stem}_{stamp}-{int(m.group(3) or 1) + 1}_{tag}.json")
    copy_atomic(src, path)
    return path


def backup(folder, reason="manual", force=False):
    """Back up the folder's trace.json and trace_fixed.json (those that exist). -> list of new backup paths."""
    made = []
    for kind, src in (("trace", find_file(folder, TRACE)), ("fixed", find_file(folder, FIXED))):
        p = backup_file(folder, src, kind, reason, force)
        if p:
            made.append(p)
    return made


def is_fixed_data(J):
    """True for the contents of a fixed trace (PLAY / FIX writes its settings under "fix"; trace.json never has it)."""
    return isinstance(J, dict) and "fix" in J


def check_writable(path, what=None):
    """Raise ValueError when path exists and is protected (read-only), before anything is changed."""
    if is_protected(path):
        raise ValueError(f"{what or os.path.basename(path)} is protected (read-only), so it wasn't changed. "
                         "Unprotect it first (Trace → Project…).")


def restore(folder, backup_path):
    """Put a backup back. The file it replaces is backed up first (reason "restore").
    -> (restored file, safety backup or None). Raises ValueError for a file that isn't a readable trace, for a fixed
    trace that would land in trace.json, and for a protected (read-only) target; nothing is changed then."""
    m = BACKUP_NAME.match(os.path.basename(backup_path))
    if not m:
        raise ValueError(f"{os.path.basename(backup_path)} isn't a trace backup.")
    summary(backup_path)   # refuses a broken backup before anything is touched
    fixed = m.group(1).lower() == "trace_fixed"
    if not fixed and is_fixed_data(read_json(backup_path)):
        raise ValueError(f"{os.path.basename(backup_path)} holds a fixed trace, so it can't go back as trace.json: "
                         "your trace and the fixed trace are kept apart.")
    target = fixed_path(folder) if fixed else trace_path(folder)
    check_writable(target)
    safety = backup_file(folder, target, "fixed" if fixed else "trace", "restore") if os.path.exists(target) else None
    copy_atomic(backup_path, target)
    return target, safety


# ---------------------------------------------------------------- Phase 9: single frames, checkpoints, protection
def read_frames(path):
    """-> {frame: (pts {joint: [x, y]}, estimated set)} of a trace file, plus its frame order as a list."""
    J = read_json(path)
    frames = [int(f) for f in J["frames"]]
    est = J.get("estimated") or [[] for _ in frames]
    out = {}
    for f, P, E in zip(frames, J["pts"], est):
        out[f] = ({n: [float(P[n][0]), float(P[n][1])] for n in ORDER if n in P}, set(E or []) & set(P))
    return out, frames


def same_pose(a, b):
    """Two (pts, estimated) entries are the same to 0.05 px (what the file keeps) with the same guesses."""
    (pa, ea), (pb, eb) = a, b
    return (set(pa) == set(pb) and ea == eb
            and all(abs(pa[n][0] - pb[n][0]) < 0.05 and abs(pa[n][1] - pb[n][1]) < 0.05 for n in pa))


def differing_frames(current_path, backup_path):
    """Key frames of a trace backup that differ from the current trace (or that the current trace doesn't have).
    -> sorted list; every frame of the backup when there is no readable current trace."""
    theirs, _ = read_frames(backup_path)
    try:
        mine, _ = read_frames(current_path)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return sorted(theirs)
    return sorted(f for f in theirs if f not in mine or not same_pose(mine[f], theirs[f]))


def restore_frames(folder, backup_path, frames):
    """Put back only the chosen key frames of a TRACE backup (their points and guesses); every other key frame of
    trace.json stays as it is. A frame trace.json doesn't have is added in frame order. trace.json is backed up first
    (reason "restore"). -> (trace.json path, safety backup or None, frames put back).
    Raises ValueError for a fixed backup, a broken file, a frame the backup doesn't have or a protected trace."""
    m = BACKUP_NAME.match(os.path.basename(backup_path))
    if not m or m.group(1).lower() != "trace":
        raise ValueError("Only key frames of a trace backup can be put back one by one "
                         "(a fixed trace is made as a whole in Review).")
    if is_fixed_data(read_json(backup_path)):
        raise ValueError(f"{os.path.basename(backup_path)} holds a fixed trace, so it can't go into trace.json.")
    theirs, _ = read_frames(backup_path)
    frames = sorted({int(f) for f in frames})
    if not frames:
        raise ValueError("Pick at least one key frame to put back.")
    missing = [f for f in frames if f not in theirs]
    if missing:
        raise ValueError(f"The backup has no frame {', '.join(map(str, missing))}.")
    target = trace_path(folder)
    check_writable(target)
    mine, order = ({}, [])
    if os.path.exists(target):
        mine, order = read_frames(target)   # a broken current trace raises here, before anything is changed
    for f in frames:
        mine[f] = theirs[f]
        if f not in order:
            order = sorted(order + [f]) if order == sorted(order) else order + [f]
    safety = backup_file(folder, target, "trace", "restore") if os.path.exists(target) else None
    write_trace(target, order, [mine[f][0] for f in order], [sorted(mine[f][1]) for f in order])
    return target, safety, frames


def checkpoints_path(folder):
    return os.path.join(backup_folder(folder), CHECKPOINTS)


def checkpoint_names(folder):
    """-> {backup file name (lower case): {"name", "made"}}; {} when there are none or the file can't be read."""
    try:
        J = read_json(checkpoints_path(folder))
        return {str(k).lower(): v for k, v in J.items() if isinstance(v, dict)} if isinstance(J, dict) else {}
    except (OSError, ValueError):
        return {}


def checkpoint(folder, name, kinds=("trace", "fixed")):
    """Save a named checkpoint: a backup (always made, even when identical to the newest one) of trace.json and of
    trace_fixed.json if there is one, with the name kept in backups\\checkpoints.json. -> list of new backup paths."""
    name = " ".join(str(name).split())[:80] or time.strftime("checkpoint %d %b %H:%M")
    made = []
    for kind, src in (("trace", find_file(folder, TRACE)), ("fixed", find_file(folder, FIXED))):
        if kind in kinds and src:
            p = backup_file(folder, src, kind, "checkpoint", force=True)
            if p:
                made.append(p)
    if made:
        names = {}
        try:
            J = read_json(checkpoints_path(folder))
            if isinstance(J, dict):
                names = J
        except (OSError, ValueError):
            pass
        for p in made:
            names[os.path.basename(p)] = {"name": name, "made": time.strftime("%Y-%m-%d %H:%M:%S")}
        write_atomic(checkpoints_path(folder), json.dumps(names, indent=1, ensure_ascii=True) + "\n")
    return made


def is_protected(path):
    """True when the file exists and has the read-only attribute (how a trace is protected)."""
    try:
        return not (os.stat(path).st_mode & stat.S_IWRITE)
    except OSError:
        return False


def protected(folder):
    t = find_file(folder, TRACE)
    return bool(t) and is_protected(t)


def set_protected(folder, on):
    """Protect (read-only) or unprotect the folder's trace.json. Protecting makes a backup first (reason "protect").
    -> the trace.json path. Raises ValueError when there is no trace.json."""
    t = find_file(folder, TRACE)
    if not t:
        raise ValueError("There's no trace.json to protect yet.")
    if on:
        backup_file(folder, t, "trace", "protect")
        os.chmod(t, stat.S_IREAD)
    else:
        os.chmod(t, stat.S_IREAD | stat.S_IWRITE)
    return t


def describe(b):
    """One line for a backup, for lists."""
    when = time.strftime("%d %b %Y  %H:%M:%S", time.localtime(b["time"]))
    what = REASONS.get(b["reason"], b["reason"])
    if b.get("label"):
        what = f"checkpoint “{b['label']}”"
    return f"{when}  ·  {'fixed trace' if b['kind'] == 'fixed' else 'trace'}  ·  {what}"


def main(argv):
    if len(argv) < 2 or argv[0] not in ("backup", "list", "checkpoint") or (argv[0] == "checkpoint" and len(argv) < 3):
        print(__doc__)
        return 1
    folder = os.path.abspath(argv[1])
    if argv[0] == "backup":
        made = backup(folder, argv[2] if len(argv) > 2 else "manual")
        print("\n".join(made) if made else "Nothing new to back up.")
    elif argv[0] == "checkpoint":
        made = checkpoint(folder, " ".join(argv[2:]))
        print("\n".join(made) if made else "There's no trace to save a checkpoint of.")
    else:
        for b in list_backups(folder):
            try:
                s = summary(b["path"])
                info = f"{s['frames']} key frames, {s['done']} finished, {s['points']} points"
            except (OSError, ValueError, KeyError, TypeError) as e:
                info = f"unreadable ({e})"
            print(f"{describe(b)}  ·  {info}\n    {b['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
