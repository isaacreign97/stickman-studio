"""Traced characters of a move (Stickman Studio Multi-Character Support, Phase 11). Plain file handling, no AI.

A move folder (Images\\<move>\\) can hold several traced stickman characters that share its frames (fNN.png):

    Images\\<move>\\trace.json            character "c1", the PRIMARY character: your existing trace, never moved,
                                         renamed or converted (with trace_fixed.json, trace_history.json,
                                         key_poses.json and backups\\ beside it, as always)
    Images\\<move>\\characters\\<id>\\      every other character, with the SAME files in the SAME formats:
                                         trace.json, trace_fixed.json, trace_history.json, key_poses.json, backups\\
    Images\\<move>\\characters.json       the list: id, name, colour, visible, locked, folder, and the active one

A move without characters.json is a single-character move: list_characters() still returns its one character (c1),
and nothing is written until you add a second character. Every character has the same 12 joints and 11 bones
(trace_io.ORDER / CHAINS) and its own coordinates, key frames, estimated (guessed) joints, undo, backups and fixed trace.

Deleting a character never erases anything: its folder moves to characters\\_deleted\\<id> <date time>\\ and can be
restored. Character c1 can't be deleted (its files are the move's original trace, which every older tool reads).

Read-only interface for other tools (and, later, ANIMATE):
    list_characters(move)                 -> [{"id", "name", "colour", "visible", "locked", "trace_dir"}]
    trace_path(move, char_id)             -> that character's trace.json path
    keys(move, char_id, fixed=False)      -> [(frame, {joint: (x, y)})] finished key frames
    scene(move, frame, every=True, hold=False) -> {char_id: {joint: (x, y)}} visible characters at that frame
    motion(move, char_id)                 -> trace_player.Motion of its in-betweens, or None
"""
import hashlib
import json
import math
import os
import re
import shutil
import time

import history
import trace_io

SCHEMA = "stickman-characters/1"
FILE = "characters.json"
DIR = "characters"
DELETED = "_deleted"
ARCHIVE_NOTE = "character_archive.json"
PRIMARY = "c1"
NAME_MAX = 40
PALETTE = ["#e3222b", "#1e6eff", "#1ec83c", "#ff8c00", "#b04fe0", "#00b5b8", "#e0c020", "#ff5fa8"]
ID_RE = re.compile(r"^(c1|ch_[0-9a-f]{8})$")
COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ABOUT = ("Stickman Studio traced characters of this move. Character c1 is trace.json in this folder; the others are "
         "in characters\\<id>\\ with the same files. Frames (fNN.png) are shared. Deleted characters are kept in "
         "characters\\_deleted\\.")


class CharacterError(ValueError):
    """A character action that can't be done; nothing was changed."""


# ---------------------------------------------------------------- paths and checks
def registry_path(move):
    return os.path.join(move, FILE)


def is_multi(move):
    return os.path.isfile(registry_path(move))


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def clean_name(name):
    """A character name you typed, checked. -> the name, or raises CharacterError."""
    name = " ".join(str(name or "").split())
    if not name:
        raise CharacterError("Type a name for the character.")
    if len(name) > NAME_MAX:
        raise CharacterError(f"That name is too long ({NAME_MAX} characters at most).")
    if any(ord(c) < 32 for c in name):
        raise CharacterError("A name can't contain control characters.")
    return name


def primary_entry():
    return {"id": PRIMARY, "name": "Character 1", "folder": ".", "colour": PALETTE[0], "visible": True,
            "locked": False, "created": now()}


def default_registry():
    return {"schema": SCHEMA, "about": ABOUT, "characters": [primary_entry()], "active": PRIMARY}


def inside(move, folder):
    """True when folder (relative, from the registry) stays inside the move folder."""
    if not isinstance(folder, str) or os.path.isabs(folder) or ":" in folder:
        return False
    full = os.path.realpath(os.path.join(move, folder))
    root = os.path.realpath(move)
    return full == root or full.startswith(root + os.sep)


def validate(move, J):
    """Problems that make a registry unsafe to use (then nothing is changed). -> list of messages."""
    out = []
    if not isinstance(J, dict) or not isinstance(J.get("characters"), list):
        return ["it has no list of characters"]
    if J.get("schema") != SCHEMA:
        out.append(f"unknown schema {J.get('schema')!r}")
    seen, folders = set(), set()
    for k, c in enumerate(J["characters"]):
        if not isinstance(c, dict):
            out.append(f"entry {k + 1} isn't a character")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            out.append(f"entry {k + 1} has a bad id {cid!r}")
        elif cid in seen:
            out.append(f"the id {cid} is listed twice")
        seen.add(cid)
        folder = c.get("folder")
        if not inside(move, folder):
            out.append(f"{cid}: its folder {folder!r} is outside the move")
        elif cid == PRIMARY and os.path.normpath(folder) != ".":
            out.append("c1 must be the move's own trace (folder \".\")")
        elif cid != PRIMARY and os.path.normpath(folder) == ".":
            out.append(f"{cid} can't use the move's own trace (that's c1)")
        else:
            nf = os.path.normcase(os.path.normpath(folder))
            if nf in folders:
                out.append(f"two characters share the folder {folder!r}")
            folders.add(nf)
        if not isinstance(c.get("name"), str) or not c.get("name", "").strip():
            out.append(f"{cid}: no name")
    if PRIMARY not in seen:
        out.append("character c1 (the move's own trace) is missing")
    return out


def load(move):
    """-> (registry, problem). A missing file gives the implicit single-character registry (nothing is written).
    problem is a message when the file exists but can't be used safely; then registry is None."""
    p = registry_path(move)
    if not os.path.exists(p):
        return default_registry(), None
    try:
        J = trace_io.read_json(p)
    except (OSError, ValueError) as e:
        return None, f"characters.json can't be read ({e})"
    bad = validate(move, J)
    if bad:
        return None, "characters.json isn't usable: " + "; ".join(bad)
    out = default_registry()
    out["characters"] = []
    for c in J["characters"]:
        e = {"id": c["id"], "name": " ".join(str(c["name"]).split())[:NAME_MAX], "folder": c["folder"].replace("\\", "/"),
             "colour": c.get("colour") if COLOUR_RE.match(str(c.get("colour", ""))) else PALETTE[0],
             "visible": c.get("visible", True) is not False, "locked": c.get("locked", False) is True,
             "created": str(c.get("created") or "")}
        out["characters"].append(e)
    ids = [c["id"] for c in out["characters"]]
    out["active"] = J.get("active") if J.get("active") in ids else PRIMARY
    return out, None


# ---------------------------------------------------------------- the set of characters of one move
class CharacterSet:
    """The characters of one move. Every change is written straight away (atomically) to characters.json; the first
    change of a single-character move creates it, after a checkpoint of trace.json. Nothing here deletes a file."""

    def __init__(self, move, data, saved):
        self.move, self.data, self.saved = os.path.normpath(move), data, saved

    @classmethod
    def open(cls, move):
        """Raises CharacterError when characters.json exists but can't be used (it's left as it is)."""
        data, problem = load(move)
        if problem:
            raise CharacterError(problem + ". It was left as it is; nothing was changed.")
        return cls(move, data, is_multi(move))

    # ---- reading
    @property
    def characters(self):
        return list(self.data["characters"])

    def ids(self):
        return [c["id"] for c in self.data["characters"]]

    def get(self, cid):
        for c in self.data["characters"]:
            if c["id"] == cid:
                return c
        raise CharacterError(f"There's no character {cid} in this move.")

    @property
    def active(self):
        return self.data["active"]

    def trace_dir(self, cid):
        return os.path.normpath(os.path.join(self.move, self.get(cid)["folder"]))

    def trace_path(self, cid):
        return trace_io.trace_path(self.trace_dir(cid))

    def fixed_path(self, cid):
        return trace_io.fixed_path(self.trace_dir(cid))

    def progress(self, cid):
        """-> (finished key frames, key frames) of the character's trace.json (0, 0 when it has none)."""
        t = trace_io.find_file(self.trace_dir(cid), trace_io.TRACE)
        if not t:
            return 0, 0
        try:
            s = trace_io.summary(t)
            return s["done"], s["frames"]
        except (OSError, ValueError, KeyError, TypeError):
            return 0, 0

    def name_taken(self, name, but=None):
        return any(c["name"].lower() == name.lower() and c["id"] != but for c in self.data["characters"])

    def ensure_editable(self, cid):
        c = self.get(cid)
        if c["locked"]:
            raise CharacterError(f"“{c['name']}” is locked: unlock it to change it.")
        return c

    # ---- writing
    def save(self):
        out = {"schema": SCHEMA, "about": ABOUT, "characters": self.data["characters"], "active": self.data["active"]}
        bad = validate(self.move, out)
        if bad:   # never write a registry that wouldn't load again
            raise CharacterError("Not saved: " + "; ".join(bad))
        if not self.saved and not os.path.exists(registry_path(self.move)) and \
                trace_io.find_file(self.move, trace_io.TRACE):
            # the move becomes a multi-character move, whatever the first change is (adding, or renaming
            # character 1): checkpoint its trace first. trace.json itself is never changed.
            trace_io.checkpoint(self.move, "before adding characters")
        trace_io.write_atomic(registry_path(self.move), json.dumps(out, indent=1, ensure_ascii=True) + "\n")
        self.saved = True

    def new_id(self):
        taken = set(self.ids())
        base = os.path.join(self.move, DIR)
        try:
            taken |= {n.lower() for n in os.listdir(base)}
            taken |= {n.split(" ")[0].lower() for n in os.listdir(os.path.join(base, DELETED))}
        except OSError:
            pass
        while True:
            cid = "ch_" + os.urandom(4).hex()
            if cid not in taken:
                return cid

    def create(self, name=None, colour=None):
        """Add a new (untraced) character. The first time, characters.json is created and trace.json gets a
        checkpoint "before adding characters" first; trace.json itself is never changed. -> its id."""
        n = len(self.data["characters"])
        name = clean_name(name or f"Character {n + 1}")
        if colour is not None and not COLOUR_RE.match(str(colour)):
            raise CharacterError(f"{colour!r} isn't a colour like #1e6eff.")
        first = not self.saved   # the checkpoint "before adding characters" is made by save() the first time
        cid = self.new_id()
        folder = f"{DIR}/{cid}"
        os.makedirs(os.path.join(self.move, DIR, cid))
        self.data["characters"].append({"id": cid, "name": name, "folder": folder,
                                        "colour": colour or PALETTE[n % len(PALETTE)], "visible": True,
                                        "locked": False, "created": now()})
        self.save()
        history.add_event(self.move, "character", f"Added the traced character “{name}”"
                          + (" (the move became a multi-character move)" if first else ""))
        return cid

    def rename(self, cid, name):
        c = self.get(cid)
        old, c["name"] = c["name"], clean_name(name)
        self.save()
        history.add_event(self.move, "character", f"Renamed the traced character “{old}” to “{c['name']}”")
        return c["name"]

    def set_flag(self, cid, flag, value):
        if flag not in ("visible", "locked"):
            raise CharacterError(f"Unknown setting {flag}.")
        self.get(cid)[flag] = bool(value)
        self.save()

    def set_visible(self, cid, on):
        self.set_flag(cid, "visible", on)

    def set_locked(self, cid, on):
        self.set_flag(cid, "locked", on)

    def set_colour(self, cid, colour):
        if not COLOUR_RE.match(str(colour)):
            raise CharacterError(f"{colour!r} isn't a colour like #1e6eff.")
        self.get(cid)["colour"] = colour
        self.save()

    def set_active(self, cid):
        self.get(cid)
        self.data["active"] = cid
        if self.saved:   # a single-character move stays without characters.json
            self.save()

    def move_order(self, cid, delta):
        """Move a character up (-1) or down (+1) in the list (= drawing order). -> its new position."""
        cs = self.data["characters"]
        i = self.ids().index(cid)
        j = max(0, min(len(cs) - 1, i + delta))
        cs.insert(j, cs.pop(i))
        self.save()
        return j

    # ---- deleting (archiving) and restoring
    def archive(self, cid):
        """"Delete" a character: its folder moves to characters\\_deleted\\<id> <date time>\\ (with a note of its
        name and settings) and it leaves the list. Nothing is erased. -> the archive folder."""
        c = self.get(cid)
        if cid == PRIMARY:
            raise CharacterError("Character 1 is the move's own trace.json, so it can't be deleted. You can rename, "
                                 "hide or lock it.")
        src = self.trace_dir(cid)
        base = os.path.join(self.move, DIR, DELETED)
        os.makedirs(base, exist_ok=True)
        first = os.path.join(base, f"{cid} {time.strftime('%Y-%m-%d %H%M%S')}")
        dest, k = first, 2
        while os.path.exists(dest):
            dest, k = f"{first}-{k}", k + 1
        if os.path.isdir(src):
            shutil.move(src, dest)
        else:
            os.makedirs(dest)
        with open(os.path.join(dest, ARCHIVE_NOTE), "w", encoding="utf-8") as fh:
            json.dump({"entry": c, "archived": now()}, fh, indent=1, ensure_ascii=True)
        self.data["characters"] = [x for x in self.data["characters"] if x["id"] != cid]
        if self.data["active"] == cid:
            self.data["active"] = PRIMARY
        self.save()
        history.add_event(self.move, "character", f"Deleted the traced character “{c['name']}” (kept in "
                                                  f"characters\\{DELETED}\\{os.path.basename(dest)})")
        return dest

    def deleted(self):
        """Archived characters, newest first: [{"path", "id", "name", "archived", "frames"}]."""
        base = os.path.join(self.move, DIR, DELETED)
        out = []
        try:
            names = os.listdir(base)
        except OSError:
            return out
        for n in names:
            d = os.path.join(base, n)
            try:
                note = trace_io.read_json(os.path.join(d, ARCHIVE_NOTE))
                e = note["entry"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            frames = 0
            t = trace_io.find_file(d, trace_io.TRACE)
            if t:
                try:
                    frames = trace_io.summary(t)["frames"]
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            out.append({"path": d, "id": e.get("id"), "name": e.get("name", "?"), "archived": note.get("archived", ""),
                        "frames": frames, "entry": e})
        return sorted(out, key=lambda x: x["archived"], reverse=True)

    def restore(self, archive_dir):
        """Bring a deleted character back (same id if it's free, otherwise a new one). -> its id."""
        try:
            e = trace_io.read_json(os.path.join(archive_dir, ARCHIVE_NOTE))["entry"]
        except (OSError, ValueError, KeyError, TypeError) as err:
            raise CharacterError(f"That isn't a deleted character ({err}).")
        cid = e.get("id") if isinstance(e.get("id"), str) and ID_RE.match(e.get("id", "")) else None
        if not cid or cid == PRIMARY or cid in self.ids() or os.path.exists(os.path.join(self.move, DIR, cid)):
            cid = self.new_id()
        os.makedirs(os.path.join(self.move, DIR), exist_ok=True)
        shutil.move(archive_dir, os.path.join(self.move, DIR, cid))
        n = len(self.data["characters"])
        self.data["characters"].append({
            "id": cid, "name": clean_name(e.get("name") or f"Character {n + 1}"), "folder": f"{DIR}/{cid}",
            "colour": e.get("colour") if COLOUR_RE.match(str(e.get("colour", ""))) else PALETTE[n % len(PALETTE)],
            "visible": True, "locked": e.get("locked", False) is True, "created": e.get("created") or now()})
        self.save()
        history.add_event(self.move, "character", f"Restored the deleted traced character “{e.get('name')}”")
        return cid

    # ---- importing a character traced in another move with the same frames
    def import_from(self, other_move, other_id=PRIMARY, name=None, allow_size_only=False):
        """Copy a character traced in another move (for example a duplicate of this move) in as a new character.
        Only when every frame it uses is the same picture here (SHA-1), or, with allow_size_only, at least the same
        size. The other move is only read. -> the new id."""
        other = CharacterSet.open(other_move)
        src = other.trace_dir(other_id)
        t = trace_io.find_file(src, trace_io.TRACE)
        if not t:
            raise CharacterError(f"“{other.get(other_id)['name']}” in {os.path.basename(other_move)} isn't traced.")
        try:
            frames = [int(f) for f in trace_io.read_json(t)["frames"]]
        except (OSError, ValueError, KeyError, TypeError) as err:
            raise CharacterError(f"Its trace can't be read ({err}).")
        problems = frame_match(other_move, self.move, frames)
        if problems["missing"]:
            raise CharacterError("This move has no frame " + ", ".join(f"f{f:02d}.png" for f in problems["missing"])
                                 + ", so that trace can't be placed here. Nothing was changed.")
        if problems["different"]:
            fs = ", ".join(f"f{f:02d}" for f in problems["different"][:6])
            if problems["other_size"] or not allow_size_only:
                raise CharacterError(f"The pictures of {fs} aren't the same in both moves"
                                     + (" (not even the same size)" if problems["other_size"] else "")
                                     + ", so the points wouldn't line up. Nothing was changed.")
        cid = self.create(name or other.get(other_id)["name"])
        dest = self.trace_dir(cid)
        for n in (trace_io.TRACE, trace_io.FIXED, "key_poses.json"):
            p = trace_io.find_file(src, n)
            if p:
                shutil.copyfile(p, os.path.join(dest, n))
        history.add_event(self.move, "character", f"Imported “{self.get(cid)['name']}” from "
                                                  f"{os.path.basename(os.path.normpath(other_move))}")
        return cid

    # ---- for lists
    def summary(self):
        """[{"id", "name", "colour", "visible", "locked", "done", "frames", "active", "primary"}] in order."""
        out = []
        for c in self.data["characters"]:
            done, total = self.progress(c["id"])
            out.append({**{k: c[k] for k in ("id", "name", "colour", "visible", "locked")}, "done": done,
                        "frames": total, "active": c["id"] == self.active, "primary": c["id"] == PRIMARY})
        return out


def sha1(path):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def frame_match(src_move, dst_move, frames):
    """Compare the pictures of the given frames in two moves.
    -> {"missing": [frames not in dst], "different": [frames whose picture differs], "other_size": bool}."""
    from PIL import Image
    import project
    out = {"missing": [], "different": [], "other_size": False}
    for f in frames:
        a, b = project.frame_file(src_move, f), project.frame_file(dst_move, f)
        if not b:
            out["missing"].append(f)
            continue
        if not a or sha1(a) != sha1(b):
            out["different"].append(f)
            try:
                with Image.open(a) as ia, Image.open(b) as ib:
                    if ia.size != ib.size:
                        out["other_size"] = True
            except (OSError, TypeError, AttributeError):
                out["other_size"] = True
    return out


def import_check(other_move, other_id=PRIMARY, move=None):
    """What importing that character into move would meet, without changing anything.
    -> {"name", "frames", "missing", "different", "other_size", "traced"}."""
    other = CharacterSet.open(other_move)
    c = other.get(other_id)
    t = trace_io.find_file(other.trace_dir(other_id), trace_io.TRACE)
    out = {"name": c["name"], "frames": [], "missing": [], "different": [], "other_size": False, "traced": bool(t)}
    if t:
        try:
            out["frames"] = [int(f) for f in trace_io.read_json(t)["frames"]]
        except (OSError, ValueError, KeyError, TypeError):
            out["traced"] = False
    if move and out["frames"]:
        out.update(frame_match(other_move, move, out["frames"]))
    return out


def locate(path):
    """A path inside a move's characters\\ folder -> (move folder, character id or None); otherwise (None, None).
    Used when a character's file is dropped on the studio."""
    import project
    p = os.path.normpath(os.path.abspath(path))
    parts = p.split(os.sep)
    for k in range(len(parts) - 1, 0, -1):
        if parts[k].lower() == DIR:
            move = os.sep.join(parts[:k])
            if project.frame_numbers(move):
                cid = parts[k + 1] if k + 1 < len(parts) else None
                if cid and cid.lower() != DELETED and os.path.isdir(os.path.join(move, DIR, cid)) \
                        and cid in {c["id"] for c in list_characters(move)}:
                    return move, cid
                return move, None
    return None, None


def problems(move):
    """Character problems for PROJECT → Check (read-only): [(level, text)]."""
    out = []
    if not is_multi(move):
        return out
    data, problem = load(move)
    if problem:
        return [("error", problem + ". Backups can't restore it; Level2 backups or the move's .zip backups can.")]
    listed = set()
    for c in data["characters"]:
        d = os.path.normpath(os.path.join(move, c["folder"]))
        listed.add(os.path.normcase(d))
        if c["id"] != PRIMARY and not os.path.isdir(d):
            out.append(("error", f"The folder of “{c['name']}” ({c['folder']}) is missing."))
    try:
        for n in os.listdir(os.path.join(move, DIR)):
            d = os.path.join(move, DIR, n)
            if n != DELETED and os.path.isdir(d) and os.path.normcase(os.path.normpath(d)) not in listed:
                out.append(("note", f"characters\\{n} isn't in the character list (an orphan folder); "
                                    "nothing uses it."))
    except OSError:
        pass
    names = [c["name"].lower() for c in data["characters"]]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        out.append(("note", "Two characters share the name " + ", ".join(f"“{n}”" for n in dup) + "."))
    out += same_poses(move, data)
    return out


SAME_POSE_PX = 0.5   # every joint closer than this to the other character's: the same pose


def same_poses(move, data=None):
    """The same pose on two characters on the same frame: usually an import or a carry that was never moved onto
    the second figure. -> [("warning", text)]. Read-only."""
    data = data or load(move)[0]
    traced = []
    for c in data["characters"]:
        d = os.path.normpath(os.path.join(move, c["folder"]))
        try:
            traced.append((c["name"], {f: P for f, P in keys_in(d)}))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    out = []
    for i in range(len(traced)):
        for j in range(i + 1, len(traced)):
            (na, A), (nb, B) = traced[i], traced[j]
            same = [f for f in sorted(set(A) & set(B))
                    if all(math.dist(A[f][n], B[f][n]) < SAME_POSE_PX for n in trace_io.ORDER)]
            if same:
                fs = ", ".join(map(str, same[:8])) + (" …" if len(same) > 8 else "")
                out.append(("warning", f"“{na}” and “{nb}” have exactly the same pose on frame"
                                       f"{'s' if len(same) > 1 else ''} {fs}: usually a copy (import or carry) "
                                       "that was never moved onto the second figure."))
    return out


def keys_in(trace_dir):
    """Finished key frames of the trace in a folder: [(frame, {joint: (x, y)})]; [] when there's no trace."""
    p = trace_io.find_file(trace_dir, trace_io.TRACE)
    if not p:
        return []
    J = trace_io.read_json(p)
    return [(int(f), {n: (float(P[n][0]), float(P[n][1])) for n in trace_io.ORDER})
            for f, P in zip(J["frames"], J["pts"]) if all(n in P for n in trace_io.ORDER)]


# ---------------------------------------------------------------- read-only interface (other tools, later ANIMATE)
def list_characters(move):
    """[{"id", "name", "colour", "visible", "locked", "trace_dir"}]; a single-character move gives its one character.
    A broken characters.json gives the primary character only (the move's own trace still works)."""
    data, problem = load(move)
    if problem:
        data = default_registry()
    return [{**{k: c[k] for k in ("id", "name", "colour", "visible", "locked")},
             "trace_dir": os.path.normpath(os.path.join(move, c["folder"]))} for c in data["characters"]]


def _entry(move, char_id):
    for c in list_characters(move):
        if c["id"] == char_id:
            return c
    raise CharacterError(f"There's no character {char_id} in {os.path.basename(os.path.normpath(move))}.")


def trace_path(move, char_id=PRIMARY):
    return trace_io.trace_path(_entry(move, char_id)["trace_dir"])


def keys(move, char_id=PRIMARY, fixed=False):
    """Finished key frames (all 12 joints) of a character, sorted: [(frame, {joint: (x, y)})]. [] when untraced."""
    d = _entry(move, char_id)["trace_dir"]
    p = trace_io.find_file(d, trace_io.FIXED if fixed else trace_io.TRACE)
    if not p:
        return []
    try:
        J = trace_io.read_json(p)
        out = [(int(f), {n: (float(P[n][0]), float(P[n][1])) for n in trace_io.ALL if n in P})   # + optional joints
               for f, P in zip(J["frames"], J["pts"]) if all(n in P for n in trace_io.ORDER)]
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return []
    return sorted(out)


def motion(move, char_id=PRIMARY, fixed=False):
    import trace_player
    ks = keys(move, char_id, fixed)
    return trace_player.Motion(ks) if ks else None


def scene(move, frame, every=True, hold=False, fixed=False):
    """Every VISIBLE character's pose at a frame: {char_id: {joint: (x, y)}}, in drawing order.
    every: the in-betweens PLAY draws (else only characters with a key on that frame).
    hold: outside a character's traced frames, keep its first / last pose (else it's left out)."""
    out = {}
    for c in list_characters(move):
        if not c["visible"]:
            continue
        ks = keys(move, c["id"], fixed)
        if not ks:
            continue
        first, last = ks[0][0], ks[-1][0]
        if frame < first or frame > last:
            if hold:
                out[c["id"]] = dict(ks[0][1] if frame < first else ks[-1][1])
            continue
        if not every:
            P = dict(ks).get(frame)
            if P is not None:
                out[c["id"]] = dict(P)
            continue
        if len(ks) == 1:
            out[c["id"]] = dict(ks[0][1])
            continue
        import trace_player
        P = trace_player.Motion(ks).pose(float(frame))
        out[c["id"]] = {n: (float(P[n][0]), float(P[n][1])) for n in trace_io.ORDER}
    return out
