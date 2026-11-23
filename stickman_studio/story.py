"""STORY (v3.2): branching stories in a 05 ANIMATE project. No AI.

The animation's timeline is split into scenes (named frame ranges; scenes may share frames). Each scene ends in one
of four ways:

    "next"    carry on with the next scene in the list (the last one then ends the story)
    "goto"    jump to another scene (a loop, or a shared ending)
    "choice"  stop and ask: up to 4 buttons, each going to a scene (choose-your-path)
    "end"     the story ends here (one of its endings)

Stored in animation.json as doc["story"] = {"first": scene id, "scenes": [{"id", "name", "start", "end", "then":
{"kind", "goto", "prompt", "options": [{"label", "goto"}]}}]}. Frames are 0-based; end is included.
"""
import json
import os
import re
import time

import animate as A

KINDS = ("next", "goto", "choice", "end")
MAX_OPTIONS = 4


class StoryError(Exception):
    pass


def get(proj):
    return proj.doc.get("story") or None


def scenes(proj):
    s = get(proj)
    return list(s["scenes"]) if s else []


def scene(proj, sid):
    for sc in scenes(proj):
        if sc["id"] == sid:
            return sc
    raise StoryError("That scene isn't in the story.")


def _check_range(proj, start, end):
    n = proj.doc["length"]
    start, end = int(start), int(end)
    if not (0 <= start <= end < n):
        raise StoryError(f"Frames must be from 1 to {n}, and the first can't be after the last.")
    return start, end


def add_scene(proj, name, start, end):
    """A new scene from frame start to end (0-based, end included). The first scene becomes the story's start."""
    start, end = _check_range(proj, start, end)
    proj.snapshot("add a scene")
    st = proj.doc.setdefault("story", {"first": None, "scenes": []})
    sid = A.new_id("sc_", {s["id"] for s in st["scenes"]})
    sc = {"id": sid, "name": A.clean_name(name), "start": start, "end": end, "then": {"kind": "next"}}
    st["scenes"].append(sc)
    if not st["first"]:
        st["first"] = sid
    return sc


def edit_scene(proj, sid, name=None, start=None, end=None):
    sc = scene(proj, sid)
    s, e = _check_range(proj, sc["start"] if start is None else start, sc["end"] if end is None else end)
    proj.snapshot("edit a scene")
    sc["start"], sc["end"] = s, e
    if name is not None:
        sc["name"] = A.clean_name(name)
    return sc


def set_then(proj, sid, kind, goto=None, prompt="", options=()):
    """How the scene ends: "next", "goto" (goto = scene id), "choice" (prompt + [(label, scene id)]) or "end"."""
    if kind not in KINDS:
        raise StoryError(f"Unknown ending {kind}.")
    sc = scene(proj, sid)
    ids = {s["id"] for s in scenes(proj)}
    then = {"kind": kind}
    if kind == "goto":
        if goto not in ids:
            raise StoryError("Pick the scene to go to.")
        then["goto"] = goto
    elif kind == "choice":
        opts = [(str(lab).strip(), g) for lab, g in options if str(lab).strip()]
        if not opts:
            raise StoryError("A choice needs at least one button with a label.")
        if len(opts) > MAX_OPTIONS:
            raise StoryError(f"A choice can have up to {MAX_OPTIONS} buttons.")
        for _, g in opts:
            if g not in ids:
                raise StoryError("Every button needs a scene to go to.")
        then.update(prompt=str(prompt).strip()[:200], options=[{"label": lab[:60], "goto": g} for lab, g in opts])
    proj.snapshot("scene ending")
    sc["then"] = then
    return sc


def remove_scene(proj, sid):
    """Delete a scene; endings that went to it become "next" (nothing else is deleted: frames stay)."""
    scene(proj, sid)
    proj.snapshot("delete a scene")
    st = proj.doc["story"]
    st["scenes"] = [s for s in st["scenes"] if s["id"] != sid]
    for s in st["scenes"]:
        t = s["then"]
        if t.get("goto") == sid:
            s["then"] = {"kind": "next"}
        if t["kind"] == "choice":
            t["options"] = [o for o in t["options"] if o["goto"] != sid]
            if not t["options"]:
                s["then"] = {"kind": "next"}
    if st["first"] == sid:
        st["first"] = st["scenes"][0]["id"] if st["scenes"] else None
    if not st["scenes"]:
        proj.doc.pop("story")


def move_scene(proj, sid, d):
    st = proj.doc["story"]
    i = next(k for k, s in enumerate(st["scenes"]) if s["id"] == sid)
    j = max(0, min(len(st["scenes"]) - 1, i + d))
    if i != j:
        proj.snapshot("scene order")
        st["scenes"].insert(j, st["scenes"].pop(i))


def set_first(proj, sid):
    scene(proj, sid)
    proj.snapshot("first scene")
    proj.doc["story"]["first"] = sid


def after(proj, sid, option=None):
    """The scene that follows scene sid (option = the button index for a choice), or None at an ending."""
    sc_list = scenes(proj)
    sc = scene(proj, sid)
    t = sc["then"]
    if t["kind"] == "end":
        return None
    if t["kind"] == "goto":
        return t["goto"]
    if t["kind"] == "choice":
        if option is None:
            raise StoryError("This scene ends with a choice: pick a button.")
        return t["options"][option]["goto"]
    i = next(k for k, s in enumerate(sc_list) if s["id"] == sid)
    return sc_list[i + 1]["id"] if i + 1 < len(sc_list) else None


def check(proj):
    """Problems a story has (an empty list = fine): scenes nobody reaches, a story that can never end, and a
    scene outside the animation's frames."""
    st = get(proj)
    if not st:
        return []
    out = []
    n = proj.doc["length"]
    ids = [s["id"] for s in st["scenes"]]
    for s in st["scenes"]:
        if s["end"] >= n or s["start"] > s["end"]:
            out.append(f"“{s['name']}” is outside the animation's {n} frames.")
    seen, todo = set(), [st["first"]] if st["first"] else []
    edges = {}
    for s in st["scenes"]:
        t = s["then"]
        nxt = []
        if t["kind"] == "goto":
            nxt = [t["goto"]]
        elif t["kind"] == "choice":
            nxt = [o["goto"] for o in t["options"]]
        elif t["kind"] == "next":
            i = ids.index(s["id"])
            nxt = [ids[i + 1]] if i + 1 < len(ids) else []
        edges[s["id"]] = nxt
    while todo:
        x = todo.pop()
        if x in seen or x not in edges:
            continue
        seen.add(x)
        todo += edges[x]
    for s in st["scenes"]:
        if s["id"] not in seen:
            out.append(f"Nobody reaches “{s['name']}” (no scene or choice goes to it).")
    ends = {s["id"] for s in st["scenes"] if not edges[s["id"]]}
    if seen and not (ends & seen):
        out.append("The story never ends: every path loops forever (that's fine for a looping game menu).")
    return out


def frames_used(proj):
    return sorted({f for s in scenes(proj) for f in range(s["start"], s["end"] + 1)})


# ---------------------------------------------------------------- export as a playable web page
PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
 body{margin:0;background:#1a1a1f;color:#eee;font:16px system-ui,sans-serif;display:flex;flex-direction:column;
      align-items:center;min-height:100vh}
 h1{font-size:18px;letter-spacing:.08em;margin:14px 0 8px}
 #stage{max-width:96vw;max-height:72vh;background:#f3f3f3;border-radius:6px}
 #ask{min-height:110px;margin:12px;text-align:center}
 #ask p{margin:6px 0 10px}
 button{background:#e3222b;color:#fff;border:0;border-radius:5px;padding:9px 16px;margin:4px;font:inherit;cursor:pointer}
 button.alt{background:#3a3a44}
</style></head><body>
<h1>__TITLE__</h1>
<img id="stage" alt="">
<div id="ask"></div>
<script>
const STORY = __STORY__;
const img = document.getElementById("stage"), ask = document.getElementById("ask");
const cache = {};
for (const f of STORY.frames) { const i = new Image(); i.src = "frames/" + STORY.names[f]; cache[f] = i; }
let timer = null;
function show(f){ img.src = "frames/" + STORY.names[f]; }
function play(id){
  const s = STORY.scenes[id]; ask.innerHTML = ""; let f = s.start; show(f);
  clearInterval(timer);
  timer = setInterval(() => {
    f += 1;
    if (f <= s.end) { show(f); return; }
    clearInterval(timer); next(id);
  }, 1000 / STORY.fps);
}
function button(text, fn, alt){ const b = document.createElement("button"); b.textContent = text;
  if (alt) b.className = "alt"; b.onclick = fn; ask.appendChild(b); }
function next(id){
  const s = STORY.scenes[id], t = s.then;
  if (t.kind === "goto") return play(t.goto);
  if (t.kind === "next" && s.next) return play(s.next);
  if (t.kind === "choice") {
    const p = document.createElement("p"); p.textContent = t.prompt || "What happens next?"; ask.appendChild(p);
    t.options.forEach(o => button(o.label, () => play(o.goto)));
    return;
  }
  const p = document.createElement("p"); p.textContent = "THE END"; ask.appendChild(p);
  button("Play again", () => play(STORY.first), true);
}
play(STORY.first);
</script></body></html>
"""


def export_html(proj, out_dir):
    """The story as a web page anyone can play in a browser: a NEW dated folder with index.html and the frames it
    uses. Nothing is downloaded or sent anywhere. -> the folder."""
    st = get(proj)
    if not st or not st["scenes"]:
        raise StoryError("Make at least one scene first.")
    problems = [p for p in check(proj) if "outside" in p]
    if problems:
        raise StoryError(problems[0])
    name = proj.doc["name"]
    d = os.path.join(out_dir, f"{name} story {time.strftime('%Y-%m-%d %H%M%S')}")
    k = 2
    while os.path.exists(d):
        d = f"{d} ({k})"
        k += 1
    os.makedirs(os.path.join(d, "frames"))
    used = frames_used(proj)
    names = {}
    for f in used:
        names[f] = f"f{f + 1:04d}.png"
        A.render(proj, f).convert("RGB").save(os.path.join(d, "frames", names[f]))
    sc_list = st["scenes"]
    data = {"fps": proj.doc["fps"], "first": st["first"], "frames": used, "names": {str(f): n for f, n in names.items()},
            "scenes": {}}
    for i, s in enumerate(sc_list):
        data["scenes"][s["id"]] = {"name": s["name"], "start": s["start"], "end": s["end"], "then": s["then"],
                                   "next": sc_list[i + 1]["id"] if i + 1 < len(sc_list) else None}
    title = re.sub(r"[<>&\"]", "", name)
    page = PAGE.replace("__TITLE__", title).replace("__STORY__", json.dumps(data).replace("</", "<\\/"))
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(d, "story.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    return d
