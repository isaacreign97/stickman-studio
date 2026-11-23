"""Old console launcher for trace_clicker.py. Not used any more: Stickman Studio (studio.py) does this.

Drop onto the .bat:
  - a GIF                        -> splits it into frames (in frames\\<GIF name> next to the GIF, or Images\\<GIF name>
                                    for a GIF in the Images folder), shows all.png,
                                    asks which key frames, then opens the tracer
  - frame images (f01.png, ...)  -> traces exactly those frames (select them with Ctrl+click, drag them together)
  - a frames folder              -> reopens its trace.json, or asks which key frames
                                    (type P instead to play the trace as a stickman animation)
  - trace.json (or any other file in a frames folder) -> same as dropping its folder
When every frame is done and you close the tracer, trace_check.png opens.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FRAME = re.compile(r"^f(\d+)\.png$", re.IGNORECASE)


def frame_numbers(folder):
    nums = []
    for n in os.listdir(folder):
        m = FRAME.match(n)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def saved_trace(folder):
    for n in os.listdir(folder):
        if n.lower() == "trace.json":
            return os.path.join(folder, n)
    return None


def open_file(path):
    try:
        os.startfile(path)
    except (OSError, AttributeError):
        pass


def show_sheet(folder):
    sheet = os.path.join(folder, "all.png")
    if os.path.exists(sheet):
        open_file(sheet)
        print("all.png shows every frame with its number in yellow.")


def ask_frames(folder):
    have = frame_numbers(folder)
    if not have:
        print("There are no frame images (f00.png, f01.png, ...) in", folder)
        return None
    trace = saved_trace(folder)
    if trace:
        try:
            with open(trace) as fh:
                saved = json.load(fh)["frames"]
            print("This folder already has a trace of frames", ", ".join(map(str, saved)) + ".")
        except (OSError, ValueError, KeyError, TypeError):
            print("This folder already has a trace.json.")
    prompt = f"Which key frames? Numbers from {have[0]} to {have[-1]}, e.g. 1 4 7"
    if trace:
        print("Press Enter to reopen the saved trace, or type P to play it as a stickman animation.")
        prompt += " (Enter = reopen, P = play): "
    else:
        prompt += ": "
    while True:
        s = input(prompt).strip()
        if not s and trace:
            return []
        if s.lower() in ("p", "play") and trace:
            return "play"
        try:
            nums = list(dict.fromkeys(int(x) for x in s.replace(",", " ").split()))
        except ValueError:
            print("Type the numbers only, with spaces between them, like: 1 4 7")
            continue
        if not nums:
            continue
        bad = [n for n in nums if n not in have]
        if bad:
            print("There's no frame", ", ".join(map(str, bad)), "in this folder. Try again.")
            continue
        return nums


def choose(paths):
    """Work out the frames folder and the frame numbers ([] = reopen the saved trace) from what was dropped."""
    first = paths[0]
    if first.lower().endswith(".gif"):
        if len(paths) > 1:
            print("Drop one GIF at a time.")
            return None, None
        name = os.path.splitext(os.path.basename(first))[0]
        where = os.path.dirname(first)
        if os.path.basename(where).lower() == "images":   # Images\ keeps one folder per move: Images\<name>
            folder = os.path.join(where, name)
        else:
            folder = os.path.join(where, "frames", name)
        if os.path.isdir(folder) and frame_numbers(folder):
            print("Using the frames already split in", folder)
        else:
            print("Splitting the GIF into", folder)
            r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "extract_frames.py"), first, folder])
            if r.returncode:
                return None, None
        open_file(os.path.join(folder, "all.png"))
        print("all.png shows every frame with its number in yellow.")
        return folder, ask_frames(folder)
    if os.path.isdir(first):
        show_sheet(first)
        return first, ask_frames(first)
    folder = os.path.dirname(first)
    if all(FRAME.match(os.path.basename(p)) for p in paths):
        if any(os.path.dirname(p) != folder for p in paths):
            print("Drop frames from one folder at a time.")
            return None, None
        return folder, sorted(int(FRAME.match(os.path.basename(p)).group(1)) for p in paths)
    if frame_numbers(folder):   # trace.json, all.png, ... inside a frames folder
        show_sheet(folder)
        return folder, ask_frames(folder)
    print("I don't know what to do with", os.path.basename(first))
    print("Drop a GIF, frame images (f01.png ...), a frames folder or a trace.json.")
    return None, None


def main(args):
    paths = [os.path.abspath(a.strip().strip('"')) for a in args if a.strip()]
    if not paths:
        print(__doc__)
        print("Use Stickman Studio.bat instead.")
        return 1
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print("Can't find:", *missing, sep="\n  ")
        return 1
    folder, frames = choose(paths)
    if folder is None or frames is None:
        return 1
    if frames == "play":
        print("Playing the trace in", folder)
        return subprocess.run([sys.executable, "-I", os.path.join(HERE, "trace_player.py"), folder]).returncode
    print("Opening the tracer for", folder, "- frames", ", ".join(map(str, frames)) if frames else "from the saved trace")
    start = time.time()
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "trace_clicker.py"), folder] + [str(n) for n in frames])
    check = os.path.join(folder, "trace_check.png")
    if r.returncode == 0 and os.path.exists(check) and os.path.getmtime(check) >= start - 1:
        open_file(check)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
