"""Trace history (Stickman Studio upgrade, Phase 9): trace_history.json beside trace.json.

It holds two things, and never changes trace.json itself:
  undo / redo   the 02 TRACE editor's undo and redo steps, so Ctrl+Z / Ctrl+Y still work after the editor (or the
                whole studio) was closed. Each step keeps a label ("Moved frontHand"), when it was made, the key frame
                it happened on and how the frames it changed looked before it (or, for redo steps, after it).
                The steps are only brought back when trace.json is exactly the trace they were saved with (same
                text, same key frames): after a restore or an edit elsewhere, old steps could undo the wrong thing,
                so the editor starts with a fresh undo list instead (every earlier version is still in BACKUPS…).
  events        a short log of what happened to the move: editing sessions (how many changes, which frames),
                checkpoints, restores, protection, copies and project backups.

The file is registered in trace_io.SIDE_FILES and video_tool.TRACE_FILES, so it moves with the trace when frames
are re-saved, and the studio never opens it as a Game Settings project. A history file that can't be read is
copied into backups\\ before a new one is written.
"""
import hashlib
import json
import os
import shutil
import time

import trace_io

FILE = "trace_history.json"
VERSION = 1
MAX_STEPS = 300     # as many as the editor keeps in memory
MAX_EVENTS = 1000   # the log only keeps sessions and bigger operations, so this is years of work
ABOUT = ("Stickman Studio trace history: the Trace editor's undo / redo steps and a log of what happened to "
         "this move. trace.json is never changed by it. Safe to delete (you only lose the saved undo steps and the "
         "log).")


def path(folder):
    return os.path.join(folder, FILE)


def text_sha1(p):
    """A fingerprint of a text file's contents (line endings don't matter), or None when it can't be read."""
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return hashlib.sha1(fh.read().encode("utf-8")).hexdigest()
    except OSError:
        return None


def empty():
    return {"about": ABOUT, "version": VERSION, "trace_sha1": None, "frames": [], "undo": [], "redo": [],
            "events": []}


def load(folder):
    """-> (data, problem). data always has every key; problem is a message when the file exists but can't be used."""
    p = path(folder)
    if not os.path.exists(p):
        return empty(), None
    try:
        with open(p, encoding="utf-8") as fh:
            J = json.load(fh)
        if not isinstance(J, dict):
            raise ValueError("not a history file")
    except (OSError, ValueError) as e:
        return empty(), f"The saved trace history couldn't be read ({e}); a copy is kept in backups\\."
    data = empty()
    for k in ("trace_sha1", "frames", "undo", "redo", "events", "version", "traces", "frames_by"):
        if k in J:
            data[k] = J[k]
    for k in ("frames", "undo", "redo", "events"):
        if not isinstance(data[k], list):
            data[k] = []
    return data, None


def save(folder, data):
    """Write the history (atomically). A history file that can't be read is copied into backups\\ first."""
    p = path(folder)
    if os.path.exists(p) and load(folder)[1]:
        d = trace_io.backup_folder(folder)
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(p, os.path.join(d, time.strftime("trace_history_unreadable_%Y%m%d-%H%M%S.json")))
    data = dict(data)
    data["about"] = ABOUT
    data["version"] = 2 if data.get("version") == 2 else VERSION   # 2: a multi-character move (Phase 11)
    data["undo"] = list(data.get("undo") or [])[-MAX_STEPS:]
    data["redo"] = list(data.get("redo") or [])[-MAX_STEPS:]
    data["events"] = list(data.get("events") or [])[-MAX_EVENTS:]
    trace_io.write_atomic(p, json.dumps(data, separators=(",", ":"), ensure_ascii=True) + "\n")


# ---------------------------------------------------------------- undo steps
def r3(v):
    return round(float(v), 3)


def encode_state(st):
    """A frame's editor state (.pts {joint: [x, y]}, .ok set, .guess set) as plain JSON data."""
    return {"pts": {n: [r3(st.pts[n][0]), r3(st.pts[n][1])] for n in trace_io.ORDER if n in st.pts},
            "ok": [n for n in trace_io.ORDER if n in st.ok], "guess": [n for n in trace_io.ORDER if n in st.guess]}


def decode_state(d, make):
    """make(pts, ok, guess) builds the editor's frame state. Raises ValueError for anything that isn't a state."""
    if not isinstance(d, dict):
        raise ValueError("bad state")
    pts = {}
    for n, v in (d.get("pts") or {}).items():
        if n in trace_io.ORDER:
            pts[n] = [float(v[0]), float(v[1])]
    ok = {n for n in d.get("ok") or [] if n in pts}
    guess = {n for n in d.get("guess") or [] if n in pts}
    return make(pts, ok, guess)


def encode_step(step):
    """step = (key frame index, {frame: state}, label, time) -> JSON data.
    Phase 11: a multi-character step adds (owner character id, {other character id: {frame: state}})."""
    i, snap, label, t = step[:4]
    d = {"i": int(i), "label": str(label), "time": round(float(t), 2),
         "states": {str(f): encode_state(st) for f, st in snap.items()}}
    if len(step) > 4:
        d["owner"] = step[4]
        d["extra"] = {cid: {str(f): encode_state(st) for f, st in gs.items()} for cid, gs in (step[5] or {}).items()}
    return d


def decode_step(d, make, frames):
    """-> (index, {frame: state}, label, time). Raises ValueError for a step that doesn't fit these key frames."""
    i = int(d["i"])
    if not 0 <= i < len(frames):
        raise ValueError("bad frame index")
    snap = {}
    for f, st in (d.get("states") or {}).items():
        f = int(f)
        if f not in frames:
            raise ValueError(f"frame {f} isn't a key frame")
        snap[f] = decode_state(st, make)
    if not snap:
        raise ValueError("empty step")
    return i, snap, str(d.get("label") or "Change"), float(d.get("time") or 0.0)


def restore_steps(data, trace_file, frames, make):
    """The saved undo and redo steps, when they belong to this exact trace and these key frames.
    -> (undo, redo, note): note says why they weren't brought back (None when they were, or there were none)."""
    saved = len(data.get("undo") or []) + len(data.get("redo") or [])
    if not saved:
        return [], [], None
    if data.get("version") == 2:   # Phase 11: a move that had characters and is single-character again
        data = as_single(data)
        if data is None:
            return [], [], ("The saved undo steps were made while this move had several characters, so Ctrl+Z "
                            "starts fresh. Earlier versions are in Backups….")
    if data.get("trace_sha1") != text_sha1(trace_file) or [int(f) for f in data.get("frames") or []] != list(frames):
        return [], [], ("The saved undo steps belong to a different version of this trace (it was restored or "
                        "changed elsewhere, or other key frames were picked), so Ctrl+Z starts fresh. "
                        "Earlier versions are in Backups….")
    try:
        undo = [decode_step(d, make, frames) for d in data.get("undo") or []]
        redo = [decode_step(d, make, frames) for d in data.get("redo") or []]
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return [], [], f"The saved undo steps couldn't be read ({e}), so Ctrl+Z starts fresh."
    return undo, redo, None


def as_single(data):
    """Phase 11: a version-2 (multi-character) history as version 1, when every step in it is character 1's alone.
    -> the version-1 data, or None when some step belongs to (or also changed) another character."""
    traces, fb = data.get("traces") or {}, data.get("frames_by") or {}
    if "c1" not in traces:
        return None
    for d in list(data.get("undo") or []) + list(data.get("redo") or []):
        if not isinstance(d, dict) or (d.get("owner") or "c1") != "c1" or d.get("extra"):
            return None
    out = dict(data)
    out["version"], out["trace_sha1"], out["frames"] = VERSION, traces["c1"], list(fb.get("c1") or [])
    out["undo"] = [{k: v for k, v in d.items() if k not in ("owner", "extra")} for d in data.get("undo") or []]
    out["redo"] = [{k: v for k, v in d.items() if k not in ("owner", "extra")} for d in data.get("redo") or []]
    out.pop("traces", None)
    out.pop("frames_by", None)
    return out


def restore_steps_multi(data, files, make):
    """Phase 11: the saved undo / redo steps of a multi-character move (one list for every character, so a group
    edit is one step). files = {character id: (its trace.json path, its key frames)}. The steps come back only
    when every character they were saved with still has exactly that trace text and those key frames; the steps of
    a move from before it had characters (version 1) come back as character 1's.
    -> (undo, redo, note) like restore_steps; steps are (index, snap, label, time, owner, {id: {frame: state}})."""
    saved = len(data.get("undo") or []) + len(data.get("redo") or [])
    if not saved:
        return [], [], None
    if data.get("version") == 2:
        traces, fb = data.get("traces") or {}, data.get("frames_by") or {}
        ok = bool(traces) and all(cid in files and traces[cid] == text_sha1(files[cid][0])
                                  and [int(x) for x in fb.get(cid) or []] == list(files[cid][1]) for cid in traces)
    else:
        c1 = files.get("c1")
        ok = bool(c1) and data.get("trace_sha1") == text_sha1(c1[0]) and \
            [int(x) for x in data.get("frames") or []] == list(c1[1])
    if not ok:
        return [], [], ("The saved undo steps belong to a different version of these characters' traces (one was "
                        "restored or changed elsewhere, or other key frames were picked), so Ctrl+Z starts fresh. "
                        "Earlier versions are in Backups….")

    def one(d):
        owner = d.get("owner") or "c1"
        if owner not in files:
            raise ValueError(f"unknown character {owner}")
        i, snap, label, t = decode_step(d, make, files[owner][1])
        extra = {}
        for cid, gs in (d.get("extra") or {}).items():
            if cid not in files:
                raise ValueError(f"unknown character {cid}")
            extra[cid] = {}
            for f, st in gs.items():
                if int(f) not in files[cid][1]:
                    raise ValueError(f"frame {f} isn't a key frame of {cid}")
                extra[cid][int(f)] = decode_state(st, make)
        return i, snap, label, t, owner, extra
    try:
        undo = [one(d) for d in data.get("undo") or []]
        redo = [one(d) for d in data.get("redo") or []]
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return [], [], f"The saved undo steps couldn't be read ({e}), so Ctrl+Z starts fresh."
    return undo, redo, None


# ---------------------------------------------------------------- the log
def frames_text(frames):
    """[1, 2, 3, 5] -> "frames 1–3, 5"; [4] -> "frame 4"."""
    fs = sorted({int(f) for f in frames})
    if not fs:
        return ""
    runs, start = [], fs[0]
    for a, b in zip(fs, fs[1:] + [None]):
        if b != a + 1:
            runs.append(f"{start}" if start == a else f"{start}–{a}")
            start = b
    return ("frame " if len(fs) == 1 else "frames ") + ", ".join(runs)


def add_event(folder, what, text, frames=None, **extra):
    """Add one entry to the move's log (read, add, write: undo steps saved by the editor are kept).
    Never raises for a file problem: the log is a convenience. -> the event, or None when it couldn't be written."""
    ev = {"time": round(time.time(), 2), "what": what, "text": text}
    if frames:
        ev["frames"] = sorted({int(f) for f in frames})
    ev.update(extra)
    try:
        data, _ = load(folder)
        data["events"].append(ev)
        save(folder, data)
    except OSError:
        return None
    return ev


def events(folder):
    """The log, newest first."""
    data, _ = load(folder)
    return sorted((e for e in data["events"] if isinstance(e, dict)), key=lambda e: -float(e.get("time") or 0))


def when(t, now=None):
    """A short time for lists: "15:02:11" today, "23 Nov 15:02" on another day."""
    now = time.time() if now is None else now
    lt = time.localtime(t)
    if time.strftime("%Y%m%d", lt) == time.strftime("%Y%m%d", time.localtime(now)):
        return time.strftime("%H:%M:%S", lt)
    return time.strftime("%d %b %H:%M", lt)
