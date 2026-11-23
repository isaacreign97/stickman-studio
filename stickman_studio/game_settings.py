"""Game Settings: every character's Stickman Mover settings, outside Unity.

Change values and keys, add moves with their own key, write notes and feedback, then copy a ready-made
prompt for Claude, who makes the changes in Unity. After Claude has done them, press "Mark as done"
(or "Reload from Unity") so the next prompt only lists new changes.

usage: python -I game_settings.py [--home DIR] [--unity DIR] [project.json | Unity project folder]
Screen 04 of Stickman Studio (studio.py); also runs on its own. With no file it opens the project you had open last; the very first time it
reads the characters from the Unity project given by --unity.
Projects are saved as <home>/<name>.json after every change.
"""
import copy
import json
import os
import re
import sys
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                       "stickman-reference-animation",
                                           os.path.basename(os.path.dirname(os.path.abspath(__file__)))))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)   # hud.py (the shared look) and the stickman player live there
import hud  # noqa: E402

# ---------------------------------------------------------------- Unity's Key enum (Input System 1.x)
KEY_ORDER = (
    "Space Enter Tab Backquote Quote Semicolon Comma Period Slash Backslash LeftBracket RightBracket Minus Equals "
    "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z "
    "Digit1 Digit2 Digit3 Digit4 Digit5 Digit6 Digit7 Digit8 Digit9 Digit0 "
    "LeftShift RightShift LeftAlt RightAlt LeftCtrl RightCtrl LeftMeta RightMeta ContextMenu Escape "
    "LeftArrow RightArrow UpArrow DownArrow Backspace PageDown PageUp Home End Insert Delete CapsLock NumLock "
    "PrintScreen ScrollLock Pause NumpadEnter NumpadDivide NumpadMultiply NumpadPlus NumpadMinus NumpadPeriod "
    "NumpadEquals Numpad0 Numpad1 Numpad2 Numpad3 Numpad4 Numpad5 Numpad6 Numpad7 Numpad8 Numpad9 "
    "F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 OEM1 OEM2 OEM3 OEM4 OEM5 "
    "F13 F14 F15 F16 F17 F18 F19 F20 F21 F22 F23 F24").split()
KEY_BY_NUM = {i + 1: k for i, k in enumerate(KEY_ORDER)}          # Space = 1 ... F24 = 122
TK_KEYS = {
    "Left": "LeftArrow", "Right": "RightArrow", "Up": "UpArrow", "Down": "DownArrow", "space": "Space",
    "Return": "Enter", "Tab": "Tab", "grave": "Backquote", "apostrophe": "Quote", "semicolon": "Semicolon",
    "comma": "Comma", "period": "Period", "slash": "Slash", "backslash": "Backslash", "bracketleft": "LeftBracket",
    "bracketright": "RightBracket", "minus": "Minus", "equal": "Equals", "Shift_L": "LeftShift",
    "Shift_R": "RightShift", "Control_L": "LeftCtrl", "Control_R": "RightCtrl", "Alt_L": "LeftAlt",
    "Alt_R": "RightAlt", "Win_L": "LeftMeta", "Win_R": "RightMeta", "App": "ContextMenu",
    "BackSpace": "Backspace", "Prior": "PageUp", "Next": "PageDown", "Home": "Home", "End": "End",
    "Insert": "Insert", "Delete": "Delete", "Caps_Lock": "CapsLock", "Num_Lock": "NumLock", "Print": "PrintScreen",
    "Scroll_Lock": "ScrollLock", "Pause": "Pause", "KP_Enter": "NumpadEnter", "KP_Divide": "NumpadDivide",
    "KP_Multiply": "NumpadMultiply", "KP_Add": "NumpadPlus", "KP_Subtract": "NumpadMinus",
    "KP_Decimal": "NumpadPeriod", "KP_Delete": "NumpadPeriod", "KP_Insert": "Numpad0", "KP_End": "Numpad1",
    "KP_Down": "Numpad2", "KP_Next": "Numpad3", "KP_Left": "Numpad4", "KP_Begin": "Numpad5",
    "KP_Right": "Numpad6", "KP_Home": "Numpad7", "KP_Up": "Numpad8", "KP_Prior": "Numpad9",
}
ARROWS = {"LeftArrow": "← Left arrow", "RightArrow": "→ Right arrow", "UpArrow": "↑ Up arrow",
          "DownArrow": "↓ Down arrow"}


def key_from_event(e):
    ks = e.keysym
    if len(ks) == 1 and ks.isalpha():
        return ks.upper()
    if len(ks) == 1 and ks.isdigit():
        return "Digit" + ks
    if re.fullmatch(r"F\d+", ks) and 1 <= int(ks[1:]) <= 24:
        return ks
    if re.fullmatch(r"KP_\d", ks):
        return "Numpad" + ks[3:]
    return TK_KEYS.get(ks)


def key_label(k):
    if not k:
        return "(none)"
    if k in ARROWS:
        return ARROWS[k]
    if k.startswith("Digit"):
        return k[5:]
    if k.startswith("Numpad") and k[6:].isdigit():
        return "Numpad " + k[6:]
    return re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", k)


# ---------------------------------------------------------------- what can be set
KEYS = [
    ("walkKey", "Walk forward", "Double-tap and hold: run.  Triple-tap: front dash."),
    ("walkBackKey", "Walk back", "Double-tap: back dash.  Triple-tap: back teleport."),
    ("jumpKey", "Jump", "Alone: straight up.  With forward: forward flip.  With back: backflip."),
    ("crouchKey", "Crouch", "Hold to crouch.  With forward / back: crouch-walk."),
]
GROUPS = [
    ("safe", "Safe to change", hud.GREEN, "Change these freely."),
    ("small", "Small changes only", hud.AMBER, "Fine a little; big changes look odd."),
    ("claude", "Ask Claude: the clips are built for these", hud.RED_HI,
     "You can still ask for a new value here: Claude rebakes the clips that depend on it."),
    ("locked", "Locked: how the clips were made", hud.DIM,
     "Not settings. They describe the baked clips, so they only change when Claude rebakes them."),
]
# key, label, kind, unit, group, help
FIELDS = [
    ("jumpDistance", "Jump distance", "float", "units", "safe", "How far a jump travels forward or back."),
    ("frontDashDistance", "Front dash distance", "float", "units", "safe",
     "The teleport distance of both triple-tap dashes."),
    ("afterimageCount", "Afterimage count", "int", "", "safe", "Dash effect: how many afterimages."),
    ("afterimageTime", "Afterimage time", "float", "s", "safe", "Dash effect: how long they last."),
    ("afterimageColor", "Afterimage colour", "color", "", "safe", "Dash effect: colour and see-through."),
    ("crouchWalkSpeed", "Crouch-walk speed", "float", "u/s", "safe",
     "The crouch-walk animation plays faster or slower to match."),
    ("doubleTapWindow", "Double-tap window", "float", "s", "safe",
     "How fast the taps of a double or triple tap must be."),
    ("minDistance", "Min distance", "float", "units", "safe",
     "Closest the two characters get. About 1.6 stops the arms overlapping."),
    ("stageLimits", "Stage limits", "range", "x", "safe", "Left and right edges of the stage."),
    ("walkSpeed", "Walk speed", "float", "u/s", "small", "The walk animation plays faster or slower to match."),
    ("runSpeed", "Run speed", "float", "u/s", "claude", "The run, its skid stops and running jumps are built for it."),
    ("dashDistance", "Back dash distance", "float", "units", "claude", "More makes the traced hop glide on the floor."),
    ("dashDuration", "Back dash duration", "float", "s", "claude", "Must equal the back dash clip's length."),
    ("jumpDuration", "Jump duration", "float", "s", "claude", "Must equal the jump clip's length."),
    ("crouchDownDuration", "Crouch down duration", "float", "s", "claude", "Must equal the crouch down clip."),
    ("standUpDuration", "Stand up duration", "float", "s", "claude", "Must equal the stand up clip."),
    ("direction", "Faces", "dir", "", "locked", "Which way the character faces. All its clips are made for it."),
    ("walkClipSpeed", "Walk clip speed", "float", "u/s", "locked", "The speed the walk clip was made for."),
    ("crouchWalkClipSpeed", "Crouch-walk clip speed", "float", "u/s", "locked",
     "The speed the crouch-walk clip was made for."),
    ("runJumpLandSpeed", "Run jump land speed", "float", "u/s", "locked", "Running jump: the speed at landing."),
]
FIELD = {f[0]: f for f in FIELDS}
DEFAULT_KEYS = {"walkKey": "LeftArrow", "walkBackKey": "RightArrow", "jumpKey": "UpArrow", "crouchKey": "DownArrow"}
DEFAULT_VALUES = {   # the man's values in Stick fights animation, 2026-11-22
    "walkSpeed": 2.0, "runSpeed": 6.7133093, "dashDistance": 1.0, "dashDuration": 0.51, "frontDashDistance": 2.5,
    "afterimageCount": 5, "afterimageTime": 0.3, "afterimageColor": [1.0, 1.0, 1.0, 0.55], "jumpDistance": 2.0,
    "jumpDuration": 1.0, "walkClipSpeed": 2.0, "crouchWalkClipSpeed": 3.1875, "runJumpLandSpeed": 2.4,
    "crouchWalkSpeed": 1.5, "crouchDownDuration": 0.24, "standUpDuration": 0.24, "doubleTapWindow": 0.25,
    "minDistance": 1.3, "stageLimits": [-8.0, 8.0], "direction": -1,
}
CHECKS = [
    ("none", "No checking, I'll test it myself"),
    ("quick", "Quick check (numbers only, no renders)"),
    ("related", "Only test what changed"),
    ("gif", "Show me a GIF"),
    ("full", "Full check"),
]
BG = hud.BG
FONT = hud.FONT
BOLD = hud.BOLD
CHANGED = "#3b2a0b"    # a changed value: dark amber behind it
CARD = hud.PANEL2


def fmt(v):
    if isinstance(v, list):
        return ", ".join(fmt(x) for x in v)
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def value_text(name, v):
    kind = FIELD[name][2]
    if kind == "dir":
        return "left" if v < 0 else "right"
    if kind == "color":
        r, g, b, a = v
        hexc = "#%02x%02x%02x" % tuple(round(max(0, min(1, c)) * 255) for c in (r, g, b))
        return ("white" if hexc == "#ffffff" else "black" if hexc == "#000000" else hexc) + f", {round(a * 100)}% visible"
    if kind == "range":
        return f"{fmt(float(v[0]))} to {fmt(float(v[1]))}"
    return fmt(v)


def same(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-4 * max(1.0, abs(b))
    return a == b


# ---------------------------------------------------------------- reading a Unity project
def find_mover_guid(unity):
    for root, dirs, files in os.walk(os.path.join(unity, "Assets")):
        if "StickmanMover.cs.meta" in files:
            with open(os.path.join(root, "StickmanMover.cs.meta"), encoding="utf-8") as fh:
                m = re.search(r"^guid: (\w+)", fh.read(), re.M)
                return m.group(1) if m else None
    return None


def read_unity(unity):
    """-> (scene, [character]) from the first scene that uses StickmanMover."""
    guid = find_mover_guid(unity)
    if not guid:
        raise OSError("This Unity project has no StickmanMover script (yet).")
    scenes = []
    for root, dirs, files in os.walk(os.path.join(unity, "Assets")):
        scenes += [os.path.join(root, f) for f in files if f.endswith(".unity")]
    for scene in sorted(scenes):
        with open(scene, encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        if guid not in txt:
            continue
        blocks = {}
        for m in re.finditer(r"^--- !u!(\d+) &(-?\d+)[^\n]*\n(.*?)(?=^--- |\Z)", txt, re.S | re.M):
            blocks[m.group(2)] = m.group(3)
        chars = []
        for body in blocks.values():
            if "MonoBehaviour:" not in body or guid not in body:
                continue
            ch = new_character(f"Character {len(chars) + 1}")
            go = re.search(r"m_GameObject: \{fileID: (-?\d+)\}", body)
            ch["object"] = object_name(blocks, go.group(1)) if go else ""
            ch["label"] = ch["object"] or ch["label"]
            for k in DEFAULT_KEYS:
                m = re.search(rf"^\s+{k}: (\d+)\s*$", body, re.M)
                if m:
                    ch["keys"][k] = KEY_BY_NUM.get(int(m.group(1)), "")
            for name, *_ in FIELDS:
                m = re.search(rf"^\s+{name}: (.+)$", body, re.M)
                if not m:
                    continue
                raw = m.group(1).strip()
                kind = FIELD[name][2]
                nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", raw)]
                if kind == "color" and len(nums) == 4:
                    ch["values"][name] = nums
                elif kind == "range" and len(nums) == 2:
                    ch["values"][name] = nums
                elif kind == "int" and nums:
                    ch["values"][name] = int(nums[0])
                elif kind == "dir" and nums:
                    ch["values"][name] = -1 if nums[0] < 0 else 1
                elif nums:
                    ch["values"][name] = nums[0]
            ch["base"] = snapshot(ch)
            chars.append(ch)
        if chars:
            return os.path.relpath(scene, unity).replace("\\", "/"), chars
    raise OSError("No scene uses StickmanMover yet.")


def object_name(blocks, gid):
    body = blocks.get(gid, "")
    m = re.search(r"^\s+m_Name: (.+)$", body, re.M)
    if m:
        return m.group(1).strip()
    pi = re.search(r"m_PrefabInstance: \{fileID: (-?\d+)\}", body)
    if pi:
        m = re.search(r"propertyPath: m_Name\s*\n\s*value: (.+)", blocks.get(pi.group(1), ""))
        if m:
            return m.group(1).strip()
    return ""


# ---------------------------------------------------------------- project data
def new_character(label):
    return {"id": f"c{time.time_ns()}", "label": label, "object": "", "keys": {k: "" for k in DEFAULT_KEYS},
            "values": copy.deepcopy(DEFAULT_VALUES), "moves": [], "notes": "", "base": None}


def snapshot(ch):
    return {"label": ch["label"], "object": ch["object"], "keys": dict(ch["keys"]),
            "values": copy.deepcopy(ch["values"]), "moves": copy.deepcopy(ch["moves"])}


def new_project(name):
    return {"name": name, "unity": "", "scene": "", "characters": [], "removed": [], "notes": "", "feedback": "",
            "check": "quick", "brief": False, "everything": False}


def all_keys(project):
    """[(key, who)] for every key in use."""
    out = []
    for ch in project["characters"]:
        for k, label, _ in KEYS:
            if ch["keys"].get(k):
                out.append((ch["keys"][k], f"{ch['label']}: {label}"))
        for mv in ch["moves"]:
            if mv.get("key"):
                out.append((mv["key"], f"{ch['label']}: {mv.get('name') or 'new move'}"))
    return out


def conflicts(project):
    by = {}
    for k, who in all_keys(project):
        by.setdefault(k, []).append(who)
    return {k: v for k, v in by.items() if len(v) > 1}


# ---------------------------------------------------------------- traced animations (Images\<move>\trace.json)
TRACER_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                           "stickman-reference-animation",
                                           os.path.basename(os.path.dirname(os.path.abspath(__file__)))))
JOINTS = ["head", "neck", "waist", "hip", "backKnee", "backFoot", "frontKnee", "frontFoot",
          "frontElbow", "frontHand", "backElbow", "backHand"]
FRAME_FILE = re.compile(r"^f\d+\.png$", re.IGNORECASE)


def pretty(name):
    """A folder or file name as a move name: jumping -> Jumping, low_kick -> Low kick."""
    s = re.sub(r"[_]+", " ", name or "").strip()
    return s[:1].upper() + s[1:]


def character_of(path):
    """Phase 11 (Multi-Character Support): (move folder, character id, character name) when path is a traced
    character's folder / trace inside <move>\\characters\\, else (None, None, None)."""
    if not path:
        return None, None, None
    try:
        import characters
        move, cid = characters.locate(path if os.path.isdir(path) else os.path.dirname(path))
        if move and cid:
            return move, cid, characters.CharacterSet.open(move).get(cid)["name"]
    except Exception:   # the tracer tools missing or a broken list: treat it as a plain folder
        pass
    return None, None, None


def ref_name(ref):
    if not ref:
        return ""
    move, cid, cname = character_of(ref)
    if cid:   # a traced character of a multi-character move: "Jumping Ryu"
        return f"{os.path.basename(move)} {cname}"
    if os.path.isdir(ref):
        return os.path.basename(os.path.normpath(ref))
    base = os.path.basename(ref)
    if base.lower() == "trace.json" or FRAME_FILE.match(base):
        return os.path.basename(os.path.dirname(ref))
    return os.path.splitext(base)[0]


def trace_for(ref):
    """The trace.json that belongs to a reference (a traced folder, its trace.json or a frame in it,
    or a GIF / video whose frames folder has one), or None."""
    if not ref:
        return None
    if os.path.isdir(ref):
        p = os.path.join(ref, "trace.json")
        return p if os.path.exists(p) else None
    base = os.path.basename(ref)
    d = os.path.dirname(ref)
    if base.lower() == "trace.json":
        return ref if os.path.exists(ref) else None
    if FRAME_FILE.match(base):
        p = os.path.join(d, "trace.json")
        return p if os.path.exists(p) else None
    stem = os.path.splitext(base)[0]
    for p in (os.path.join(d, stem, "trace.json"), os.path.join(d, "frames", stem, "trace.json")):
        if os.path.exists(p):
            return p
    return None


def trace_status(path):
    """-> (finished key frames, key frames)."""
    try:
        with open(path, encoding="utf-8") as fh:
            J = json.load(fh)
        return sum(all(n in P for n in JOINTS) for P in J["pts"]), len(J["frames"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0, 0


def fixed_info(trace):
    """The summary of trace_fixed.json next to a trace (saved by the player's Fix panel), or ''."""
    p = os.path.join(os.path.dirname(trace), "trace_fixed.json")
    if not os.path.exists(p):
        return ""
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh).get("summary") or "fixed"
    except (OSError, ValueError):
        return ""


def animations(images):
    """Every traced animation in the Images folder: [(text for the list, folder)]."""
    out = []
    if not os.path.isdir(images):
        return out
    for name in sorted(os.listdir(images), key=str.lower):
        d = os.path.join(images, name)
        t = os.path.join(d, "trace.json")
        if os.path.isdir(d) and os.path.exists(t):
            done, total = trace_status(t)
            if total == 0:
                continue
            state = f"{done} key frames" if done == total else f"{done} of {total} key frames traced"
            if fixed_info(t):
                state += ", fixed"
            many = []
            try:   # Phase 11: every traced character of a multi-character move is an animation of its own
                import characters
                if characters.is_multi(d):
                    many = characters.list_characters(d)
            except Exception:
                many = []
            who = (' \u203a ' + many[0]['name']) if many else ''
            out.append((f"{name}{who}   ({state})", d))
            for c in many[1:]:
                ct = os.path.join(c["trace_dir"], "trace.json")
                if os.path.exists(ct):
                    cd, ctot = trace_status(ct)
                    if ctot:
                        st = f"{cd} key frames" if cd == ctot else f"{cd} of {ctot} key frames traced"
                        out.append((f"{name} \u203a {c['name']}   ({st}{', fixed' if fixed_info(ct) else ''})",
                                    c["trace_dir"]))
    return out


# ---------------------------------------------------------------- the prompt for Claude
def move_text(mv):
    parts = [f"key {mv['key']}" if mv.get("key") else "no key yet"]
    if mv.get("ref"):
        t = trace_for(mv["ref"])
        if t:
            done, total = trace_status(t)
            fx = fixed_info(t)
            if fx:
                parts.append(f"FIXED trace {os.path.join(os.path.dirname(t), 'trace_fixed.json')} ({fx}; "
                             f"bake from this one, the original is trace.json)")
            else:
                parts.append(f"trace {t} ({done} key frames" + (f" of {total} finished" if done < total else "")
                             + ")")
        else:
            parts.append(f"reference {mv['ref']} (not traced yet)")
        move, cid, cname = character_of(mv["ref"])
        if cid:   # Phase 11: one traced character of a move with several
            parts.append(f"traced character \u201c{cname}\u201d of the move {os.path.basename(move)} (its frames are "
                         f"that move's fNN.png; the other characters there are separate traces)")
    text = f"\"{mv.get('name') or 'unnamed'}\": " + ", ".join(parts)
    if mv.get("notes", "").strip():
        text += f". Notes: {mv['notes'].strip()}"
    return text


def character_lines(ch, everything):
    b = ch.get("base")
    lines = []
    v, keys = ch["values"], ch["keys"]
    if b is None:
        lines.append("- NEW character: please add it" + (f" (GameObject \"{ch['object']}\")" if ch["object"] else "")
                     + f", facing {value_text('direction', v['direction'])}.")
        for k, label, _ in KEYS:
            lines.append(f"- {label} key: {keys.get(k) or '(not set)'}")
        for name, label, kind, unit, group, _ in FIELDS:
            if group != "locked":
                lines.append(f"- {label}: {value_text(name, v[name])}{(' ' + unit) if unit and kind != 'range' else ''}")
        for mv in ch["moves"]:
            lines.append(f"- NEW move {move_text(mv)}")
    else:
        if ch["object"] != b["object"]:
            lines.append(f"- GameObject name: \"{b['object']}\" -> \"{ch['object']}\"")
        for k, label, _ in KEYS:
            if keys.get(k) != b["keys"].get(k):
                lines.append(f"- {label} key: {b['keys'].get(k) or '(none)'} -> {keys.get(k) or '(none)'}")
            elif everything:
                lines.append(f"- {label} key: {keys.get(k) or '(none)'}")
        for name, label, kind, unit, group, _ in FIELDS:
            u = f" {unit}" if unit and kind != "range" else ""
            if not same(v[name], b["values"].get(name)):
                tag = {"claude": "   [built into the clips: rebake what depends on it]",
                       "small": "   [small-change field]", "locked": "   [locked field]"}.get(group, "")
                lines.append(f"- {label} ({name}): {value_text(name, b['values'][name])} -> "
                             f"{value_text(name, v[name])}{u}{tag}")
            elif everything:
                lines.append(f"- {label} ({name}): {value_text(name, v[name])}{u}")
        old = {m["id"]: m for m in b["moves"]}
        for mv in ch["moves"]:
            o = old.get(mv["id"])
            if o is None:
                lines.append(f"- NEW move {move_text(mv)}")
            elif o != mv:
                lines.append(f"- CHANGED move (was {move_text(o)}): now {move_text(mv)}")
            elif everything:
                lines.append(f"- Move {move_text(mv)}")
        ids = {m["id"] for m in ch["moves"]}
        for o in b["moves"]:
            if o["id"] not in ids:
                lines.append(f"- REMOVE move {move_text(o)}")
    if ch["notes"].strip():
        lines.append(f"- Notes: {ch['notes'].strip()}")
    return lines


def make_prompt(p):
    everything = p.get("everything")
    out = [f"Game Settings for \"{p['name']}\" (from Stickman Studio, 04 Game Settings). Please make these changes in Unity."]
    if p.get("unity"):
        out.append(f"Unity project: {p['unity']}" + (f"   scene: {p['scene']}" if p.get("scene") else ""))
    else:
        out.append("Unity project: new (not made yet).")
    out.append("")
    any_change = False
    for ch in p["characters"]:
        lines = character_lines(ch, everything)
        head = ch["label"] + (f" (GameObject \"{ch['object']}\"" if ch["object"] else " (") + \
            f"{', ' if ch['object'] else ''}faces {value_text('direction', ch['values']['direction'])})"
        if lines:
            any_change = True
            out.append(head)
            out += lines
        else:
            out.append(head + ": no changes.")
        out.append("")
    for r in p.get("removed", []):
        any_change = True
        out.append(f"REMOVE character {r['label']}" + (f" (GameObject \"{r['object']}\")" if r.get("object") else ""))
        out.append("")
    clash = conflicts(p)
    if clash:
        out.append("Key conflicts (the same key twice):")
        for k, who in clash.items():
            out.append(f"- {k}: " + "; ".join(who))
        out.append("")
    if p.get("notes", "").strip():
        any_change = True
        out.append("Notes: " + p["notes"].strip())
        out.append("")
    if p.get("feedback", "").strip():
        any_change = True
        out.append("Feedback / problems: " + p["feedback"].strip())
        out.append("")
    if not any_change and not everything:
        out.insert(2, "Nothing has changed since the last time these were done in Unity.")
    out.append("Checking: " + dict(CHECKS).get(p.get("check", "quick"), "quick check") + "."
               + (" Be brief." if p.get("brief") else ""))
    return "\n".join(out).strip() + "\n"


# ---------------------------------------------------------------- UI pieces
class Scroll(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=BG)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))


def ask_key(root, title, current):
    """Small window: press a key (or pick one from the list). Returns the Unity key name, '' for none, or None."""
    d = tk.Toplevel(root)
    d.title("Choose a key")
    d.configure(bg=BG, padx=18, pady=14)
    d.transient(root)
    d.resizable(False, False)
    d.grab_set()
    result = {"key": None}
    tk.Label(d, text=title, bg=BG, font=hud.TITLE).pack(anchor="w")
    big = tk.Label(d, text="Press a key now…", bg=hud.FIELD, fg=hud.TEXT, font=(hud.F_LIGHT, 18), width=22,
                   pady=12, highlightthickness=1, highlightbackground=hud.RED)
    big.pack(pady=10, fill="x")
    tk.Label(d, text=f"Now: {key_label(current)}.  Esc = cancel.  Or pick one:", bg=BG, font=FONT).pack(anchor="w")
    box = ttk.Combobox(d, state="readonly", values=["(none)"] + [f"{key_label(k)}   [{k}]" for k in KEY_ORDER],
                       width=34)
    box.pack(anchor="w", pady=(4, 0))

    def done(k):
        result["key"] = k
        d.destroy()

    def on_key(e):
        if e.widget is box:
            return None
        if e.keysym == "Escape":
            d.destroy()
            return "break"
        k = key_from_event(e)
        if result.get("taken"):
            return "break"
        if k:
            result["taken"] = True
            big.configure(text=key_label(k))
            d.after(250, lambda: done(k))
        else:
            big.configure(text=f"Can't use {e.keysym}: pick from the list")
        return "break"

    def on_pick(e):
        i = box.current()
        done("" if i == 0 else KEY_ORDER[i - 1])

    d.bind("<KeyPress>", on_key)
    box.bind("<<ComboboxSelected>>", on_pick)
    d.focus_force()
    d.wait_window()
    return result["key"]


class CharTab:
    def __init__(self, app, ch):
        self.app, self.ch = app, ch
        self.frame = Scroll(app.book)
        self.rows = {}
        self.move_buttons = {}
        self.build()

    # --- build ---
    def section(self, text, colour=hud.RED, sub=None):
        f = self.frame.inner
        hud.Header(f, text, sub, color=colour).pack(fill="x", padx=14, pady=(18, 0))
        g = tk.Frame(f, bg=BG)
        g.pack(fill="x", padx=14, pady=(4, 0))
        return g

    def build(self):
        ch = self.ch
        g = self.section("Character")
        self.label_var = tk.StringVar(value=ch["label"])
        self.obj_var = tk.StringVar(value=ch["object"])
        tk.Label(g, text="Name here", bg=BG, font=FONT).grid(row=0, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.label_var, width=24).grid(row=0, column=1, sticky="w", padx=6, pady=2)
        tk.Label(g, text="Unity GameObject", bg=BG, font=FONT).grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Entry(g, textvariable=self.obj_var, width=20).grid(row=0, column=3, sticky="w", padx=6)
        self.label_var.trace_add("write", lambda *_: self.set_text("label", self.label_var.get()))
        self.obj_var.trace_add("write", lambda *_: self.set_text("object", self.obj_var.get()))
        bb = tk.Frame(g, bg=BG)
        bb.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        hud.Button(bb, "Undo Changes to This Character", self.reset).pack(side="left", padx=(0, 6))
        hud.Button(bb, "Remove Character", lambda: self.app.remove_character(self), kind="ghost").pack(
            side="left")

        g = self.section("Controls", sub="Click a key to change it.")
        for r, (k, label, hint) in enumerate(KEYS):
            tk.Label(g, text=label, bg=BG, font=FONT, width=18, anchor="w").grid(row=r, column=0, sticky="w")
            b = tk.Button(g, width=18, font=BOLD, relief="flat", bg=hud.PANEL2, fg=hud.TEXT, cursor="hand2",
                          activebackground=hud.RED_LO, activeforeground=hud.TEXT, highlightthickness=1,
                          highlightbackground=hud.LINE2, command=lambda k=k, l=label: self.pick_key(k, l))
            b.grid(row=r, column=1, sticky="w", pady=2)
            was = tk.Label(g, bg=BG, font=hud.SMALL, fg=hud.AMBER, anchor="w", width=22)
            was.grid(row=r, column=2, sticky="w", padx=6)
            tk.Label(g, text=hint, bg=BG, fg=hud.DIM, font=hud.SMALL, anchor="w").grid(row=r, column=3,
                                                                                         sticky="w")
            self.rows[("key", k)] = (b, was)

        self.moves_box = self.section("Moves with their own key",
                                      sub="New attacks or anything else on a key. Pick the animation you traced: "
                                          "the move is named after it, and ▶ Preview plays it as the stickman.")
        self.moves_frame = tk.Frame(self.moves_box, bg=BG)
        self.moves_frame.pack(fill="x")
        mb = tk.Frame(self.moves_box, bg=BG)
        mb.pack(anchor="w", pady=(4, 0))
        self.from_anim_btn = hud.Button(mb, "+  Add Move from Animation…", self.add_from_animation, kind="red")
        self.from_anim_btn.pack(side="left")
        hud.Button(mb, "+  Add Empty Move", self.add_move).pack(side="left", padx=6)
        self.build_moves()

        for gid, title, colour, sub in GROUPS:
            g = self.section(title, colour, sub)
            r = 0
            for name, label, kind, unit, group, hint in FIELDS:
                if group != gid:
                    continue
                self.value_row(g, r, name, label, kind, unit, group, hint)
                r += 1

        g = self.section("Notes for this character", sub="Anything else for Claude about this character.")
        self.notes = tk.Text(g, height=4, font=FONT, wrap="word", relief="flat", highlightthickness=1,
                             highlightbackground=hud.LINE2, highlightcolor=hud.RED, padx=6, pady=4)
        self.notes.pack(fill="x")
        self.notes.insert("1.0", ch["notes"])
        self.notes.edit_modified(False)
        self.notes.bind("<<Modified>>", self.notes_changed)
        tk.Frame(self.frame.inner, bg=BG, height=20).pack()
        self.refresh()

    def value_row(self, g, r, name, label, kind, unit, group, hint):
        v = self.ch["values"]
        tk.Label(g, text=label, bg=BG, font=FONT, width=22, anchor="w").grid(row=r, column=0, sticky="w")
        cell = tk.Frame(g, bg=BG)
        cell.grid(row=r, column=1, sticky="w", pady=2)
        locked = group == "locked" and not (kind == "dir" and self.ch.get("base") is None)
        widgets = []
        if kind == "color":
            sw = tk.Button(cell, width=4, relief="solid", bd=1, command=lambda: self.pick_colour(name))
            sw.pack(side="left")
            av = tk.StringVar(value=str(round(v[name][3] * 100)))
            e = ttk.Entry(cell, textvariable=av, width=5)
            e.pack(side="left", padx=(6, 2))
            tk.Label(cell, text="% visible", bg=BG, font=FONT).pack(side="left")
            av.trace_add("write", lambda *_: self.set_alpha(name, av, e))
            widgets = [sw]
        elif kind == "range":
            a = tk.StringVar(value=fmt(float(v[name][0])))
            b = tk.StringVar(value=fmt(float(v[name][1])))
            ea, eb = ttk.Entry(cell, textvariable=a, width=7), ttk.Entry(cell, textvariable=b, width=7)
            ea.pack(side="left")
            tk.Label(cell, text=" to ", bg=BG, font=FONT).pack(side="left")
            eb.pack(side="left")
            a.trace_add("write", lambda *_: self.set_range(name, a, b, ea, eb))
            b.trace_add("write", lambda *_: self.set_range(name, a, b, ea, eb))
        elif kind == "dir":
            box = ttk.Combobox(cell, state="disabled" if locked else "readonly", values=["left", "right"], width=8)
            box.set(value_text(name, v[name]))
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda e: self.set_value(name, -1 if box.get() == "left" else 1))
        else:
            sv = tk.StringVar(value=fmt(v[name]))
            e = ttk.Entry(cell, textvariable=sv, width=10, state="readonly" if locked else "normal")
            e.pack(side="left")
            sv.trace_add("write", lambda *_: self.set_number(name, kind, sv, e))
            if unit:
                tk.Label(cell, text=" " + unit, bg=BG, font=FONT).pack(side="left")
        was = tk.Label(g, bg=BG, font=hud.SMALL, fg=hud.AMBER, anchor="w", width=22)
        was.grid(row=r, column=2, sticky="w", padx=6)
        tk.Label(g, text=hint, bg=BG, fg=hud.DIM, font=hud.SMALL, anchor="w").grid(row=r, column=3, sticky="w")
        self.rows[("val", name)] = (cell, was, widgets)

    def build_moves(self):
        for w in self.moves_frame.winfo_children():
            w.destroy()
        if not self.ch["moves"]:
            tk.Label(self.moves_frame, text="No extra moves yet.", bg=BG, fg=hud.DIM, font=FONT).pack(anchor="w")
        for mv in self.ch["moves"]:
            card = tk.Frame(self.moves_frame, bg=CARD, highlightthickness=1, highlightbackground=hud.LINE2,
                            padx=10, pady=8)
            card.pack(fill="x", pady=3)
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x")
            nv, notes = tk.StringVar(value=mv.get("name", "")), tk.StringVar(value=mv.get("notes", ""))
            tk.Label(row, text="NAME", bg=CARD, fg=hud.DIM, font=hud.SMALL).pack(side="left")
            ttk.Entry(row, textvariable=nv, width=18).pack(side="left", padx=(4, 10))
            kb = tk.Button(row, text=key_label(mv.get("key")), width=12, font=BOLD, relief="flat", bg=hud.FIELD,
                           fg=hud.TEXT, activebackground=hud.RED_LO, activeforeground=hud.TEXT, cursor="hand2",
                           highlightthickness=1, highlightbackground=hud.LINE2,
                           command=lambda mv=mv: self.pick_move_key(mv))
            kb.pack(side="left")
            tk.Label(row, text="   ANIMATION", bg=CARD, fg=hud.DIM, font=hud.SMALL).pack(side="left")
            cb = ttk.Combobox(row, state="readonly", width=36)
            cb.pack(side="left", padx=4)
            cb.set(self.ref_text(mv.get("ref")))
            cb.configure(postcommand=lambda cb=cb: self.fill_animations(cb))
            cb.bind("<<ComboboxSelected>>", lambda e, mv=mv, cb=cb, nv=nv: self.pick_animation(mv, cb, nv))
            hud.Button(row, "Other File…", lambda mv=mv, cb=cb, nv=nv: self.browse_ref(mv, cb, nv)).pack(
                side="left")
            hud.Button(row, "▶  Preview", lambda mv=mv: self.app.preview(mv.get("ref"), mv.get("name") or "move"),
                       kind="red").pack(side="left", padx=(8, 0))
            hud.Button(row, "Analytics", lambda mv=mv: self.app.analytics(mv.get("ref"), mv.get("name") or "move")
                       ).pack(side="left", padx=(4, 0))
            hud.Button(row, "✕", lambda mv=mv: self.remove_move(mv), kind="ghost", padx=8).pack(side="right")
            row2 = tk.Frame(card, bg=CARD)
            row2.pack(fill="x", pady=(4, 0))
            tk.Label(row2, text="Notes", bg=CARD, fg=hud.DIM, font=hud.SMALL).pack(side="left")
            ttk.Entry(row2, textvariable=notes).pack(side="left", fill="x", expand=True, padx=(6, 0))
            for var, field in ((nv, "name"), (notes, "notes")):
                var.trace_add("write", lambda *_, mv=mv, var=var, field=field: self.set_move(mv, field, var.get()))
            self.move_buttons[mv["id"]] = kb

    def ref_text(self, ref):
        if not ref:
            return "(pick the animation you traced)"
        for text, folder in animations(self.app.images):
            if os.path.normcase(os.path.normpath(folder)) == os.path.normcase(os.path.normpath(ref)):
                return text
        return os.path.basename(os.path.normpath(ref)) + ("   (traced)" if trace_for(ref) else "   (not traced yet)")

    def fill_animations(self, cb):
        self.anims = animations(self.app.images)
        cb.configure(values=[t for t, _ in self.anims] or ["(no traced animations in Images yet)"])

    def pick_animation(self, mv, cb, nv):
        i = cb.current()
        if 0 <= i < len(getattr(self, "anims", [])):
            self.set_ref(mv, self.anims[i][1], cb, nv)
        else:
            cb.set(self.ref_text(mv.get("ref")))

    def set_ref(self, mv, ref, cb, nv):
        """Link the move to an animation; a move with no name (or the old animation's name) takes the new name."""
        old_auto = pretty(ref_name(mv.get("ref")))
        mv["ref"] = os.path.normpath(ref)
        if not nv.get().strip() or nv.get() == old_auto:
            nv.set(pretty(ref_name(ref)))
        cb.set(self.ref_text(mv["ref"]))
        self.app.changed()

    def add_from_animation(self):
        anims = animations(self.app.images)
        menu = tk.Menu(self.app.root, tearoff=0, font=FONT)
        if not anims:
            menu.add_command(label="No traced animations in Images yet", state="disabled")
        for text, folder in anims:
            menu.add_command(label=text, command=lambda f=folder: self.add_move(f))
        b = self.from_anim_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    # --- edits ---
    def set_text(self, field, text):
        self.ch[field] = text
        if field == "label":
            self.app.book.tab(self.frame, text=text or "(no name)")
        self.app.changed()

    def pick_key(self, k, label):
        new = ask_key(self.app.root, f"{self.ch['label']}: {label}", self.ch["keys"].get(k))
        if new is not None:
            self.ch["keys"][k] = new
            self.app.changed()
            self.refresh()

    def pick_move_key(self, mv):
        new = ask_key(self.app.root, f"{self.ch['label']}: {mv.get('name') or 'new move'}", mv.get("key"))
        if new is not None:
            mv["key"] = new
            self.move_buttons[mv["id"]].configure(text=key_label(new))
            self.app.changed()

    def add_move(self, ref=""):
        ref = os.path.normpath(ref) if ref else ""
        self.ch["moves"].append({"id": f"m{time.time_ns()}", "name": pretty(ref_name(ref)), "key": "",
                                 "ref": ref, "notes": ""})
        self.build_moves()
        self.app.changed()

    def remove_move(self, mv):
        self.ch["moves"] = [m for m in self.ch["moves"] if m is not mv]
        self.build_moves()
        self.app.changed()

    def set_move(self, mv, field, text):
        mv[field] = text
        self.app.changed()

    def browse_ref(self, mv, cb, nv):
        start = self.app.images
        p = filedialog.askopenfilename(parent=self.app.root, title="A trace.json, GIF or video for this move",
                                       initialdir=start if os.path.isdir(start) else None)
        if p:
            self.set_ref(mv, p, cb, nv)

    def set_number(self, name, kind, sv, entry):
        try:
            x = int(sv.get()) if kind == "int" else float(sv.get().replace(",", "."))
            if x < 0 or (x == 0 and FIELD[name][4] == "claude"):
                raise ValueError
        except ValueError:
            entry.configure(style="Bad.TEntry")
            return
        entry.configure(style="TEntry")
        self.set_value(name, x)

    def set_range(self, name, a, b, ea, eb):
        try:
            lo, hi = float(a.get()), float(b.get())
            if lo >= hi:
                raise ValueError
        except ValueError:
            ea.configure(style="Bad.TEntry")
            eb.configure(style="Bad.TEntry")
            return
        ea.configure(style="TEntry")
        eb.configure(style="TEntry")
        self.set_value(name, [lo, hi])

    def set_alpha(self, name, av, e):
        try:
            a = float(av.get())
            if not 0 <= a <= 100:
                raise ValueError
        except ValueError:
            e.configure(style="Bad.TEntry")
            return
        e.configure(style="TEntry")
        c = list(self.ch["values"][name])
        c[3] = round(a / 100, 3)
        self.set_value(name, c)

    def pick_colour(self, name):
        c = self.ch["values"][name]
        init = "#%02x%02x%02x" % tuple(round(x * 255) for x in c[:3])
        rgb, _ = colorchooser.askcolor(initialcolor=init, parent=self.app.root, title="Afterimage colour")
        if rgb:
            self.set_value(name, [round(x / 255, 3) for x in rgb] + [c[3]])

    def set_value(self, name, x):
        self.ch["values"][name] = x
        self.app.changed()
        self.refresh()

    def notes_changed(self, e):
        if self.notes.edit_modified():
            self.ch["notes"] = self.notes.get("1.0", "end-1c")
            self.notes.edit_modified(False)
            self.app.changed()

    def reset(self):
        b = self.ch.get("base")
        if b is None:
            messagebox.showinfo("Undo changes", "This character is new: there's nothing in Unity to go back to.",
                                parent=self.app.root)
            return
        if not messagebox.askyesno("Undo changes", f"Put {self.ch['label']} back to the values Unity has?",
                                   parent=self.app.root):
            return
        for k in ("label", "object", "keys", "values", "moves"):
            self.ch[k] = copy.deepcopy(b[k])
        self.app.rebuild_tab(self)

    # --- show what changed ---
    def refresh(self):
        b = self.ch.get("base")
        for k, label, _ in KEYS:
            btn, was = self.rows[("key", k)]
            cur = self.ch["keys"].get(k, "")
            btn.configure(text=key_label(cur))
            changed = b is not None and cur != b["keys"].get(k)
            btn.configure(bg=CHANGED if changed else hud.PANEL2,
                          highlightbackground=hud.AMBER if changed else hud.LINE2)
            was.configure(text=f"was {key_label(b['keys'].get(k))}" if changed else "")
        for name, label, kind, unit, group, _ in FIELDS:
            cell, was, widgets = self.rows[("val", name)]
            cur = self.ch["values"][name]
            changed = b is not None and not same(cur, b["values"].get(name))
            cell.configure(bg=CHANGED if changed else BG)
            was.configure(text=f"was {value_text(name, b['values'][name])}" if changed else "")
            if kind == "color":
                widgets[0].configure(bg="#%02x%02x%02x" % tuple(round(x * 255) for x in cur[:3]))
        clash = conflicts(self.app.project)
        for k, label, _ in KEYS:
            btn, _ = self.rows[("key", k)]
            btn.configure(fg=hud.RED_HI if self.ch["keys"].get(k) in clash else hud.TEXT)


# ---------------------------------------------------------------- the main window
class App:
    """The Game Settings window. On its own it fills the window; inside Stickman Studio it lives in a panel
    (parent=...), and Preview / untraced files go to the studio's screens through on_preview / on_open_source."""

    def __init__(self, root, home, unity_default, open_path, parent=None, on_preview=None, on_open_source=None,
                 images=None):
        self.root, self.home, self.unity_default = root, home, unity_default
        self.embedded = parent is not None
        self.on_preview, self.on_open_source = on_preview, on_open_source
        self.images = images or os.path.join(os.path.dirname(home), "Images")   # the Images folder beside it
        self.players = {}
        self.project = None
        self.path = None
        self.tabs = []
        self.save_id = None
        self.keymap = {}
        box = parent if parent is not None else root
        if not self.embedded:
            root.title("Game Settings")
            hud.setup(root)
            root.minsize(1200, 760)
            try:
                root.state("zoomed")
            except tk.TclError:
                root.geometry("1500x940")

        import ribbon   # Stickman Studio 3.3: a ribbon (File menu, Home, Export) like the other screens
        rb = self.ribbon = ribbon.Ribbon(box, [
            ("New Project…", self.new_dialog), ("Open Project…", self.open_dialog), ("Save", self.save, "Ctrl+S"), None,
            ("Reload from Unity…", self.reload_unity), None, ("Export Moves…", self.export_moves)])
        rb.pack(fill="x", padx=12, pady=(8, 0))
        g = rb.tab("Home").group("Project")
        g.label("Name")
        self.name_var = tk.StringVar()
        g.place(ttk.Entry(g.cur(), textvariable=self.name_var, width=26))
        self.name_var.trace_add("write", self.name_changed)
        g = rb.tab("Home").group("Characters")
        g.button("Add Character", self.add_character, "Another character with its own keys and moves")
        g = rb.tab("Home").group("Claude")
        self.copy_btn = g.button("Copy Prompt for Claude", self.copy_prompt,
                                 "One message with everything that changed, ready to paste into Claude", kind="red")
        self.done_btn = g.button("Mark as Done  ✓", self.mark_done,
                                 "Claude has built it: the next prompt lists only new changes")
        g = rb.tab("Export").group("Export")
        self.export_btn = g.button("Export Moves…", self.export_moves, "Export several moves at once")
        g = rb.tab("Export").group("Unity")
        g.button("Reload from Unity…", self.reload_unity, "Read the keys and values from the Unity project again")
        if not self.embedded:
            deco = tk.Canvas(box, height=10, bg=BG, highlightthickness=0)
            deco.pack(fill="x", padx=12, pady=(4, 0))
            deco.bind("<Configure>", lambda e: self.draw_deco(deco))
        self.status = tk.Label(box, bg=BG, font=hud.SMALL, fg=hud.DIM, anchor="w")
        self.status.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        self.book = ttk.Notebook(box)
        self.book.pack(fill="both", expand=True, padx=8, pady=6)
        self.book.bind("<<NotebookTabChanged>>", lambda e: self.update_prompt())
        if not self.embedded:
            root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<MouseWheel>", self.wheel, add="+")

        self.load_start(open_path)

    def analytics(self, ref, title):
        """Stickman Studio upgrade Phase 8: measurements of the move's traced animation (speeds, angles, timing)."""
        if not ref:
            messagebox.showinfo("Analytics", "Pick the animation for this move first.", parent=self.root)
            return None
        trace = trace_for(ref)
        if not trace:
            messagebox.showinfo("Analytics", f"{os.path.basename(ref)} isn't traced yet, so there's nothing to "
                                             "measure. Trace it first in the Trace screen.", parent=self.root)
            return None
        if TRACER_DIR not in sys.path:
            sys.path.insert(0, TRACER_DIR)
        try:
            from analytics_dialog import AnalyticsDialog
        except ImportError as err:
            messagebox.showerror("Analytics", f"The analytics tools aren't there:\n{err}", parent=self.root)
            return None
        move, cid, cname = character_of(trace)   # Phase 11: a character's frame rate is its move's
        return AnalyticsDialog(self.root, os.path.dirname(trace), title, frames_dir=move if cid else None)

    def linked_moves(self):
        """The traced folders the open project's moves point to (every character), without repeats."""
        out = []
        for ch in (self.project or {}).get("characters", []):
            for mv in ch.get("moves", []):
                t = trace_for(mv.get("ref"))
                d = (character_of(t)[0] or os.path.dirname(t)) if t else None   # a character: its move
                if d and d not in out:
                    out.append(d)
        return out

    def export_moves(self):
        """Stickman Studio upgrade Phase 10: batch export with export settings. The project's moves start ticked."""
        if TRACER_DIR not in sys.path:
            sys.path.insert(0, TRACER_DIR)
        try:
            from export_dialog import ExportDialog
        except ImportError as err:
            messagebox.showerror("Export", f"The export tools aren't there:\n{err}", parent=self.root)
            return None
        linked = self.linked_moves()
        return ExportDialog(self.root, self.images, os.path.join(self.home, "studio.json"), preselect=linked or None,
                            note="The moves of this project are ticked." if linked else "")

    def preview(self, ref, title):
        """Play the move's traced animation with the same stickman as Trace Clicker's player."""
        if not ref:
            messagebox.showinfo("Preview", "Pick the animation for this move first.", parent=self.root)
            return
        trace = trace_for(ref)
        if trace and self.on_preview:
            self.on_preview(os.path.dirname(trace))
            return
        if not trace and self.on_open_source and os.path.exists(ref):
            if messagebox.askyesno("Preview", f"{os.path.basename(ref)} isn't traced yet, so there's no stickman "
                                              "to play.\n\nOpen it in Source now?", parent=self.root):
                self.on_open_source(ref)
            return
        if not trace:
            if os.path.exists(ref) and messagebox.askyesno(
                    "Preview", f"{os.path.basename(ref)} isn't traced yet, so there's no stickman to play.\n\n"
                               "Open it in Stickman Studio now?", parent=self.root):
                import subprocess
                subprocess.Popen([sys.executable, "-I", os.path.join(TRACER_DIR, "studio.py"), "--images",
                                  self.images, ref], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            elif not os.path.exists(ref):
                messagebox.showerror("Preview", f"Can't find {ref}", parent=self.root)
            return
        old = self.players.get(trace)
        if old and old.alive:
            old.win.deiconify()
            old.win.lift()
            old.win.focus_force()
            return
        if TRACER_DIR not in sys.path:
            sys.path.insert(0, TRACER_DIR)
        try:
            import trace_player
        except ImportError as err:
            messagebox.showerror("Preview", f"The stickman player isn't there:\n{err}", parent=self.root)
            return
        self.players[trace] = trace_player.Player(tk.Toplevel(self.root), os.path.dirname(trace),
                                                  trace_player.file_keys(trace), title)

    def draw_deco(self, c):
        c.delete("all")
        w = c.winfo_width()
        c.create_line(0, 5, w, 5, fill=hud.LINE)
        for x in range(0, w, 12):
            c.create_line(x, 3, x, 7, fill=hud.LINE2 if x % 120 else hud.RED)
        c.create_rectangle(0, 3, 90, 7, fill=hud.RED, outline="")

    def wheel(self, e):
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        if w is None or isinstance(w, (tk.Text, ttk.Combobox)):
            return
        for t in self.tabs:
            if str(w).startswith(str(t.frame)):
                t.frame.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
                return

    # --- opening / saving ---
    def load_start(self, open_path):
        try:
            if open_path and os.path.isdir(open_path):
                self.import_unity(open_path)
                return
            if open_path:
                self.open_file(open_path)
                return
            last = os.path.join(self.home, "last.txt")
            if os.path.exists(last):
                with open(last, encoding="utf-8") as fh:
                    p = fh.read().strip()
                if os.path.exists(p):
                    self.open_file(p)
                    return
            if self.unity_default and os.path.isdir(self.unity_default):
                self.import_unity(self.unity_default)
                return
        except (OSError, ValueError, KeyError) as err:
            messagebox.showerror("Game Settings", str(err), parent=self.root)
        self.set_project(new_project("New game"), None)
        self.add_character()

    def project_file(self, name):
        safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "Game"
        return os.path.join(self.home, safe + ".json")

    def import_unity(self, unity):
        scene, chars = read_unity(unity)
        p = new_project(os.path.basename(os.path.normpath(unity)))
        p["unity"], p["scene"], p["characters"] = os.path.normpath(unity), scene, chars
        path = self.project_file(p["name"])
        if os.path.exists(path):
            if not messagebox.askyesno("Game Settings", f"There's already a project called {p['name']}.\n\n"
                                       "Replace it with what Unity has now? (No opens the saved one.)",
                                       parent=self.root):
                self.open_file(path)
                return
        self.set_project(p, path)
        self.save()

    def open_file(self, path):
        with open(path, encoding="utf-8") as fh:
            p = json.load(fh)
        for ch in p["characters"]:
            for k in DEFAULT_VALUES:
                ch["values"].setdefault(k, copy.deepcopy(DEFAULT_VALUES[k]))
            for k in DEFAULT_KEYS:
                ch["keys"].setdefault(k, "")
        for k, v in new_project("").items():
            p.setdefault(k, v)
        self.set_project(p, path)

    def set_project(self, p, path):
        self.project, self.path = p, path
        for w in self.book.tabs():
            self.book.forget(w)
            self.root.nametowidget(w).destroy()
        self.tabs = []
        self.name_var.set(p["name"])
        for ch in p["characters"]:
            self.add_tab(ch)
        self.build_notes_tab()
        self.build_prompt_tab()
        self.book.select(0)
        if not self.embedded:
            self.root.title(f"Game Settings - {p['name']}")
        if path:
            self.remember(path)
        self.update_prompt()

    def remember(self, path):
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, "last.txt"), "w", encoding="utf-8") as fh:
            fh.write(path)

    def changed(self):
        if self.save_id:
            self.root.after_cancel(self.save_id)
        self.save_id = self.root.after(600, self.save)
        for t in self.tabs:
            t.refresh()
        self.update_prompt()

    def save(self):
        self.save_id = None
        if not self.project:
            return
        if not self.path:
            self.path = self.project_file(self.project["name"])
            self.remember(self.path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = self.project
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self.path)
        self.status.configure(text=f"Saved {self.path}  ({time.strftime('%H:%M:%S')})")

    def name_changed(self, *_):
        if self.project:
            self.project["name"] = self.name_var.get()
            if not self.embedded:
                self.root.title(f"Game Settings - {self.project['name']}")
            self.changed()

    def new_dialog(self):
        name = simpledialog.askstring("New project", "Name of the new game:", parent=self.root)
        if not name:
            return
        if os.path.exists(self.project_file(name)):
            messagebox.showinfo("New project", f"There's already a project called {name}. Opening it.",
                                parent=self.root)
            self.open_file(self.project_file(name))
            return
        self.save()
        self.set_project(new_project(name), self.project_file(name))
        self.add_character()
        self.save()

    def open_dialog(self):
        p = filedialog.askopenfilename(parent=self.root, title="Open a Game Settings project",
                                       initialdir=self.home, filetypes=[("Game Settings", "*.json")])
        if p:
            self.save()
            self.open_file(p)

    def reload_unity(self):
        start = self.project.get("unity") or self.unity_default or ""
        unity = filedialog.askdirectory(parent=self.root, title="The Unity project folder",
                                        initialdir=start if os.path.isdir(start) else None)
        if not unity:
            return
        try:
            scene, chars = read_unity(unity)
        except OSError as err:
            messagebox.showerror("Reload from Unity", str(err), parent=self.root)
            return
        if not messagebox.askyesno(
                "Reload from Unity", f"Found {len(chars)} character(s) in {scene}.\n\nTake their keys and values "
                "from Unity? Changes here that aren't in Unity yet are replaced. Moves and notes are kept.",
                parent=self.root):
            return
        p = self.project
        p["unity"], p["scene"] = os.path.normpath(unity), scene
        by_obj = {c["object"]: c for c in p["characters"] if c["object"]}
        for u in chars:
            mine = by_obj.get(u["object"])
            if mine:
                mine["keys"], mine["values"] = u["keys"], u["values"]
                mine["base"] = snapshot(mine)
            else:
                p["characters"].append(u)
        p["removed"] = []
        self.set_project(p, self.path)
        self.save()

    # --- characters ---
    def add_tab(self, ch, at=None):
        t = CharTab(self, ch)
        if at is None:
            self.tabs.append(t)
            index = len(self.tabs) - 1
        else:
            self.tabs.insert(at, t)
            index = at
        if index >= len(self.book.tabs()):
            self.book.add(t.frame, text=ch["label"] or "(no name)")
        else:
            self.book.insert(index, t.frame, text=ch["label"] or "(no name)")
        return t

    def add_character(self):
        if not self.project:
            return
        label = f"Character {len(self.project['characters']) + 1}"
        ch = new_character(label)
        if self.project["characters"]:   # start from the values of the one on screen, keys empty
            cur = self.current_tab()
            src = cur.ch if cur else self.project["characters"][0]
            ch["values"] = copy.deepcopy(src["values"])
            ch["values"]["direction"] = -src["values"]["direction"]
        self.project["characters"].append(ch)
        t = self.add_tab(ch, at=len(self.tabs))
        self.book.select(t.frame)
        self.changed()

    def current_tab(self):
        sel = self.book.select()
        for t in self.tabs:
            if str(t.frame) == sel:
                return t
        return None

    def remove_character(self, tab):
        ch = tab.ch
        if not messagebox.askyesno("Remove character", f"Remove {ch['label']} from these settings?"
                                   + ("\n\nThe prompt will ask Claude to remove it from Unity too."
                                      if ch.get("base") else ""), parent=self.root):
            return
        if ch.get("base"):
            self.project["removed"].append({"label": ch["base"]["label"], "object": ch["base"]["object"]})
        self.project["characters"].remove(ch)
        self.book.forget(tab.frame)
        tab.frame.destroy()
        self.tabs.remove(tab)
        self.changed()

    def rebuild_tab(self, tab):
        i = self.tabs.index(tab)
        self.book.forget(tab.frame)
        tab.frame.destroy()
        self.tabs.pop(i)
        t = self.add_tab(tab.ch, at=i)
        self.book.select(t.frame)
        self.changed()

    # --- notes and prompt tabs ---
    def build_notes_tab(self):
        f = tk.Frame(self.book, bg=BG)
        self.book.add(f, text="Notes & feedback")
        p = self.project

        def box(title, sub, key):
            hud.Header(f, title).pack(fill="x", padx=14,
                                                                                         pady=(14, 0))
            tk.Label(f, text=sub, bg=BG, fg=hud.DIM, font=hud.SMALL, anchor="w").pack(fill="x", padx=14)
            t = tk.Text(f, height=7, font=FONT, wrap="word", relief="flat", highlightthickness=1,
                        highlightbackground=hud.LINE2, highlightcolor=hud.RED, padx=6, pady=4)
            t.pack(fill="x", padx=14, pady=(4, 0))
            t.insert("1.0", p.get(key, ""))
            t.edit_modified(False)

            def mod(e):
                if t.edit_modified():
                    p[key] = t.get("1.0", "end-1c")
                    t.edit_modified(False)
                    self.changed()
            t.bind("<<Modified>>", mod)

        box("Notes", "Anything else you want: ideas, new features, the stage, the camera...", "notes")
        box("Feedback / problems", "What looks or feels wrong, e.g. \"the lady's crouch-walk slides\". "
                                   "Name the move and the moment.", "feedback")
        hud.Header(f, "How much checking").pack(
            fill="x", padx=14, pady=(14, 0))
        tk.Label(f, text="Checking (play tests, renders, GIFs) costs the most tokens.", bg=BG, fg=hud.DIM,
                 font=hud.SMALL, anchor="w").pack(fill="x", padx=14)
        self.check_var = tk.StringVar(value=p.get("check", "quick"))
        for key, text in CHECKS:
            ttk.Radiobutton(f, text=text, value=key, variable=self.check_var,
                            command=lambda: self.set_flag("check", self.check_var.get())).pack(anchor="w", padx=20)
        self.brief_var = tk.BooleanVar(value=p.get("brief", False))
        ttk.Checkbutton(f, text="Ask for short replies (be brief)", variable=self.brief_var,
                        command=lambda: self.set_flag("brief", self.brief_var.get())).pack(anchor="w", padx=20,
                                                                                         pady=(8, 0))

    def build_prompt_tab(self):
        f = tk.Frame(self.book, bg=BG)
        self.book.add(f, text="Prompt for Claude")
        bar = tk.Frame(f, bg=BG)
        bar.pack(fill="x", padx=10, pady=8)
        hud.Button(bar, "Copy Prompt for Claude", self.copy_prompt, kind="red").pack(side="left")
        self.every_var = tk.BooleanVar(value=self.project.get("everything", False))
        ttk.Checkbutton(bar, text="Everything, not only the changes", variable=self.every_var,
                        command=lambda: self.set_flag("everything", self.every_var.get())).pack(side="left",
                                                                                                padx=14)
        tk.Label(bar, text="Paste it in your chat with Claude. When Claude has done it, click Mark as done ✓.",
                 bg=BG, fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=8)
        self.prompt_text = tk.Text(f, font=(hud.MONO, 10), wrap="word", relief="flat", bg=hud.FIELD, fg=hud.TEXT,
                                   highlightthickness=1, highlightbackground=hud.LINE2, padx=10, pady=8)
        self.prompt_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def set_flag(self, key, value):
        self.project[key] = value
        self.changed()

    def update_prompt(self):
        if not self.project or not hasattr(self, "prompt_text"):
            return
        try:
            if not self.prompt_text.winfo_exists():
                return
        except tk.TclError:
            return
        text = make_prompt(self.project)
        self.prompt_text.configure(state="normal")
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", text)
        self.prompt_text.configure(state="disabled")
        n = sum(len(character_lines(c, False)) for c in self.project["characters"])
        clash = conflicts(self.project)
        self.copy_btn.configure(text=f"Copy Prompt for Claude  ·  {n}")
        if clash:
            self.status.configure(text="Key conflict: " + "; ".join(f"{k} is used by {' and '.join(v)}"
                                                                   for k, v in clash.items()), fg=hud.RED_HI)
        elif self.status.cget("fg") == hud.RED_HI:
            self.status.configure(text="", fg=hud.DIM)

    def copy_prompt(self):
        self.save()
        text = make_prompt(self.project)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.status.configure(text="Copied the prompt. Paste it in your chat with Claude (Ctrl+V).", fg=hud.GREEN)

    def mark_done(self):
        if not messagebox.askyesno(
                "Mark as done", "Has Claude made all these changes in Unity?\n\nThe values here become the new "
                "starting point, so the next prompt only lists new changes.", parent=self.root):
            return
        clear = (self.project["notes"].strip() or self.project["feedback"].strip()
                 or any(c["notes"].strip() for c in self.project["characters"]))
        if clear and messagebox.askyesno("Mark as done", "Clear the notes and feedback as well?", parent=self.root):
            self.project["notes"] = self.project["feedback"] = ""
            for c in self.project["characters"]:
                c["notes"] = ""
        for c in self.project["characters"]:
            c["base"] = snapshot(c)
        self.project["removed"] = []
        self.set_project(self.project, self.path)
        self.save()

    def close(self):
        if self.save_id:
            self.root.after_cancel(self.save_id)
            self.save_id = None
        self.save()
        if not self.embedded:
            self.root.destroy()


def main(args):
    home = os.path.join(os.getcwd(), "Game Settings")
    unity = ""
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--home" and i + 1 < len(args):
            home, i = args[i + 1], i + 2
        elif args[i] == "--unity" and i + 1 < len(args):
            unity, i = args[i + 1], i + 2
        else:
            rest.append(args[i].strip().strip('"'))
            i += 1
    home = os.path.abspath(home)
    os.makedirs(home, exist_ok=True)
    target = os.path.abspath(rest[0]) if rest else None
    if target and not os.path.exists(target):
        print("Can't find:", target)
        return 1
    try:   # sharp (not blurry) window on scaled Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root, home, unity, target)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
