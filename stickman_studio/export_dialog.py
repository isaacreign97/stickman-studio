"""The EXPORT window (Stickman Studio upgrade, Phase 10): batch export of several moves with export settings,
a check before (CHECK FIRST) and after (every file read back), and a summary. The work is done by export.py.

Opened from 04 GAME SETTINGS (EXPORT…, the moves of the open project ticked) and from 02 TRACE (EXPORT MOVES…).
The settings are kept in the studio's prefs file (Game Settings\\studio.json, key "export").

usage: python -I export_dialog.py <Images folder>      (on its own)
"""
import os
import sys
import tkinter as tk
from tkinter import filedialog, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I leaves the script's folder out
import export  # noqa: E402
import hud  # noqa: E402
import project  # noqa: E402
import trace_io  # noqa: E402

HEIGHTS = [240, 360, 480, 720, 1080]
VERSION_LABELS = [("auto", "Fixed trace if there is one, else yours"), ("trace", "Your trace"),
                  ("fixed", "Fixed trace only")]


def status_line(d):
    try:
        st = project.status(d)
    except Exception:   # a list label only
        return "can't be checked", hud.AMBER
    if not st["keys"]:
        return f"{st['frames']} frames  ·  not traced", hud.FAINT
    text = f"traced {st['done']}/{st['keys']}"
    if st["fixed"] == "ok":
        text += "  ·  fixed"
    elif st["fixed"] == "stale":
        text += "  ·  Fixed Out of Date"
    n = st["counts"]["error"]
    return text + (f"  ·  {n} broken" if n else ""), (hud.AMBER if st["fixed"] == "stale" or n
                                                     else hud.GREEN if st["done"] == st["keys"] else hud.DIM)


class ExportDialog:
    def __init__(self, root, images, prefs_path, preselect=None, note=""):
        self.root, self.images, self.prefs_path = root, os.path.normpath(images), prefs_path
        self.s = export.load_settings(prefs_path, self.images)
        self.result = None
        self.win = w = tk.Toplevel(root, bg=hud.BG)
        w.title("Export moves")
        w.geometry("1180x780")
        w.minsize(980, 640)
        w.transient(root)
        w.bind("<Escape>", lambda e: w.destroy())

        head = tk.Frame(w, bg=hud.BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        hud.Header(head, "Batch export", "Export several moves at once into a new dated folder (nothing is ever "
                   "overwritten). Each move gets a folder with your trace files exactly as they are, plus the files "
                   "you tick, named the same way for every move. Every move is checked first and every file is read "
                   "back after." + (f"  {note}" if note else "")).pack(fill="x")

        body = tk.Frame(w, bg=hud.BG)
        body.pack(fill="both", expand=True, padx=12)
        left = hud.panel(body, width=400)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        hud.label(left, "MOVES", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY, anchor="w").pack(fill="x", padx=10,
                                                                                          pady=(8, 2))
        lw = tk.Frame(left, bg=hud.PANEL)
        lw.pack(fill="both", expand=True, padx=(8, 2))
        self.lc = tk.Canvas(lw, bg=hud.PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(lw, orient="vertical", command=self.lc.yview)
        self.inner = tk.Frame(self.lc, bg=hud.PANEL)
        self.lc.create_window(0, 0, window=self.inner, anchor="nw")
        self.lc.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.lc.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.lc.configure(scrollregion=self.lc.bbox("all")))
        self.folders = project.moves(self.images)
        if preselect:
            for d in preselect:   # a linked move outside Images still shows
                if os.path.isdir(d) and os.path.normcase(os.path.normpath(d)) not in {
                        os.path.normcase(x) for x in self.folders}:
                    self.folders.append(os.path.normpath(d))
        want = {os.path.normcase(os.path.normpath(d)) for d in preselect} if preselect else None
        self.vars = {}
        for d in self.folders:
            traced = bool(trace_io.find_file(d, trace_io.TRACE) or trace_io.find_file(d, trace_io.FIXED))
            v = tk.BooleanVar(w, value=(os.path.normcase(d) in want) if want is not None else traced)
            self.vars[d] = v
            row = tk.Frame(self.inner, bg=hud.PANEL)
            row.pack(fill="x", pady=1)
            tk.Checkbutton(row, text=os.path.basename(d), variable=v, command=self.update_names, bg=hud.PANEL,
                           fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.PANEL, activeforeground=hud.TEXT,
                           font=hud.BOLD, anchor="w").pack(fill="x")
            text, col = status_line(d)
            hud.label(row, "      " + text, bg=hud.PANEL, fg=col, font=hud.TINY, anchor="w").pack(fill="x")
        if not self.folders:
            hud.label(self.inner, "No moves in the Images folder yet.", bg=hud.PANEL, fg=hud.DIM).pack(fill="x")
        lb = tk.Frame(left, bg=hud.PANEL)
        lb.pack(fill="x", padx=10, pady=8)
        hud.Button(lb, "All Traced", self.tick_traced, padx=6, font=hud.SMALL).pack(side="left", expand=True,
                                                                                    fill="x", padx=(0, 4))
        hud.Button(lb, "None", self.tick_none, padx=6, font=hud.SMALL).pack(side="left", expand=True, fill="x")

        right = tk.Frame(body, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        opts = hud.panel(right)
        opts.pack(fill="x")
        g = tk.Frame(opts, bg=hud.PANEL)
        g.pack(fill="x", padx=10, pady=8)

        def head_lbl(r, text):
            hud.label(g, text, bg=hud.PANEL, fg=hud.DIM, font=hud.TINY, anchor="nw").grid(row=r, column=0,
                                                                                         sticky="nw", pady=(4, 0))

        head_lbl(0, "Export to")
        orow = tk.Frame(g, bg=hud.PANEL)
        orow.grid(row=0, column=1, sticky="we", pady=2)
        self.out = tk.StringVar(w, value=self.s["out"])
        tk.Entry(orow, textvariable=self.out, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT, font=hud.SMALL,
                 relief="flat", highlightthickness=1, highlightbackground=hud.LINE).pack(side="left", fill="x",
                                                                                       expand=True, ipady=2)
        hud.Button(orow, "Browse…", self.browse, padx=6, font=hud.SMALL).pack(side="left", padx=(4, 0))
        self.version = tk.StringVar(w, value=self.s["version"])
        self.data = tk.StringVar(w, value=self.s["data"])
        for r, (title, var, choices) in enumerate((("Version", self.version, VERSION_LABELS),
                                                   ("Data", self.data, export.DATA)), 1):
            head_lbl(r, title)
            fr = tk.Frame(g, bg=hud.PANEL)
            fr.grid(row=r, column=1, sticky="w", pady=2)
            for key, text in choices:
                tk.Radiobutton(fr, text=text, variable=var, value=key, command=self.update_names, bg=hud.PANEL,
                               fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.PANEL,
                               activeforeground=hud.TEXT, font=hud.SMALL).pack(side="left", padx=(0, 10))
        head_lbl(3, "FILES")
        ff = tk.Frame(g, bg=hud.PANEL)
        ff.grid(row=3, column=1, sticky="w", pady=2)
        self.flags = {}
        for k, text in (("copy_traces", "Trace files as they are (trace.json, trace_fixed.json, timing.json)"),
                        ("poses_json", "Pose data per frame: <move>_poses.json (pixels, hip-relative, angles)"),
                        ("csv", "Frames table: <move>_frames.csv (as Analytics → Save CSV…)"),
                        ("stickman_png", "Stickman pictures: <move>_stickman\\<move>_stickman_0001.png …"),
                        ("overlay_png", "Your trace on the reference frames: <move>_overlay\\<move>_overlay_f05.png …"),
                        ("characters", "Every traced character of a multi-character move (in <move>\\characters\\)"),
                        ("scene_png", "Scene pictures: every character together, <move>_scene\\<move>_scene_0001.png …")):
            v = tk.BooleanVar(w, value=bool(self.s[k]))
            self.flags[k] = v
            tk.Checkbutton(ff, text=text, variable=v, command=self.update_names, bg=hud.PANEL, fg=hud.TEXT,
                           selectcolor=hud.FIELD, activebackground=hud.PANEL, activeforeground=hud.TEXT,
                           font=hud.SMALL, anchor="w").pack(fill="x")
            if k == "stickman_png":
                pr = tk.Frame(ff, bg=hud.PANEL)
                pr.pack(fill="x", padx=(24, 0))
                hud.label(pr, "height", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(side="left")
                self.height = tk.StringVar(w, value=str(self.s["png_height"]))
                ttk.Combobox(pr, textvariable=self.height, values=[str(h) for h in HEIGHTS], width=6,
                             state="readonly").pack(side="left", padx=4)
                hud.label(pr, "px", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(side="left")
                self.transparent = tk.BooleanVar(w, value=bool(self.s["transparent"]))
                tk.Checkbutton(pr, text="see-through background", variable=self.transparent, bg=hud.PANEL,
                               fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.PANEL,
                               activeforeground=hud.TEXT, font=hud.SMALL).pack(side="left", padx=(12, 0))
        head_lbl(4, "NAMES")
        self.names_lbl = hud.label(g, "", bg=hud.PANEL, fg=hud.AMBER, font=hud.SMALL, anchor="w", justify="left",
                                   wraplength=640)
        self.names_lbl.grid(row=4, column=1, sticky="we", pady=2)
        g.columnconfigure(1, weight=1)

        tw = hud.panel(right)
        tw.pack(fill="both", expand=True, pady=(8, 0))
        self.text = tk.Text(tw, bg=hud.PANEL, fg=hud.TEXT, font=hud.SMALL, wrap="word", bd=0, highlightthickness=0,
                            padx=8, pady=6, cursor="arrow", height=8)
        self.text.pack(fill="both", expand=True)
        for tag, col in (("ok", hud.GREEN), ("warn", hud.AMBER), ("bad", hud.RED_HI), ("dim", hud.DIM),
                         ("head", hud.TEXT)):
            self.text.tag_configure(tag, foreground=col)

        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        hud.Button(bar, "Close", w.destroy).pack(side="right", padx=(4, 0))
        self.export_btn = hud.Button(bar, "Export", self.do_export, kind="red", padx=20)
        self.export_btn.pack(side="right", padx=(4, 0))
        hud.Button(bar, "Check First", self.check).pack(side="right", padx=(4, 0))
        self.copy_btn = hud.Button(bar, "Copy Summary", self.copy)
        self.copy_btn.pack(side="right", padx=(4, 0))
        self.open_btn = hud.Button(bar, "Open Export Folder", self.open_out)
        self.open_btn.pack(side="right", padx=(4, 0))
        self.msg = hud.label(w, "", fg=hud.DIM, font=hud.SMALL, anchor="w")
        self.msg.pack(fill="x", padx=12, pady=(4, 8))
        self.update_names()
        self.show_lines([("Tick the moves, choose what to export, then Check First (nothing is written) or Export.",
                          "dim")])
        w.focus_set()

    # ---- settings
    def settings(self):
        s = dict(self.s)
        s["out"] = self.out.get().strip()
        s["version"], s["data"] = self.version.get(), self.data.get()
        for k, v in self.flags.items():
            s[k] = bool(v.get())
        try:
            s["png_height"] = int(self.height.get())
        except ValueError:
            s["png_height"] = export.DEFAULTS["png_height"]
        s["transparent"] = bool(self.transparent.get())
        return s

    def chosen(self):
        return [d for d in self.folders if self.vars[d].get()]

    def update_names(self):
        ds = self.chosen()
        s = self.settings()
        if not ds:
            self.names_lbl.configure(text="(tick a move to see its file names)")
            return
        d = ds[0]
        n = export.names(ds)[d]
        parts = [f"{os.path.basename(d)} → {n}\\"]
        if s["copy_traces"]:
            parts.append("trace.json")
        if s["poses_json"]:
            parts.append(f"{n}_poses.json")
        if s["csv"]:
            parts.append(f"{n}_frames.csv")
        if s["stickman_png"]:
            parts.append(f"{n}_stickman\\{n}_stickman_0001.png")
        if s["overlay_png"]:
            parts.append(f"{n}_overlay\\{n}_overlay_f01.png")
        self.names_lbl.configure(text="  ·  ".join(parts) + f"    ({project.plural(len(ds), 'move')} ticked)")

    def tick_traced(self):
        for d, v in self.vars.items():
            v.set(bool(trace_io.find_file(d, trace_io.TRACE) or trace_io.find_file(d, trace_io.FIXED)))
        self.update_names()

    def tick_none(self):
        for v in self.vars.values():
            v.set(False)
        self.update_names()

    def browse(self):
        d = filedialog.askdirectory(parent=self.win, title="Export into this folder",
                                    initialdir=self.out.get() if os.path.isdir(self.out.get()) else None)
        if d:
            self.out.set(os.path.normpath(d))

    # ---- showing
    def show_lines(self, lines):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for text, tag in lines:
            t.insert("end", text + "\n", (tag,))
        t.configure(state="disabled")

    def say(self, text, colour=None):
        self.msg.configure(text=text, fg=colour or hud.DIM)
        self.win.update_idletasks()

    # ---- actions
    def check(self):
        """Prepare every ticked move without writing anything, and list what would happen."""
        ds, s = self.chosen(), self.settings()
        if not ds:
            self.say("Tick at least one move.", hud.RED_HI)
            return None
        lines, ready = [(f"Check (nothing written yet)  ·  {export.describe_settings(s)}", "head")], 0
        for d in ds:
            m = export.prepare(d, s)
            if m["errors"]:
                lines.append((f"✖ {m['move']}: Skipped. " + " ".join(m["errors"]), "bad"))
                continue
            ready += 1
            fs = sorted(m["poses"])
            lines.append((f"✔ {m['move']}: {'fixed trace' if m['version'] == 'fixed' else 'your trace'}, "
                          f"{project.plural(len(m['key_frames']), 'key frame')}, {project.plural(len(fs), 'frame')}, "
                          f"{(fs[-1] - fs[0]) / m['fps']:.2f} s at {m['fps']:g} fps", "ok"))
            for x in m["warnings"]:
                lines.append(("      ▲ " + x, "warn"))
        lines.append((f"{ready} of {project.plural(len(ds), 'move')} can be exported.", "head"))
        self.show_lines(lines)
        self.say("Checked. Nothing was written.")
        return ready

    def do_export(self):
        ds, s = self.chosen(), self.settings()
        if not s["out"]:
            self.say("Pick a folder to export into.", hud.RED_HI)
            return None
        if not ds:
            self.say("Tick at least one move.", hud.RED_HI)
            return None
        try:
            export.save_settings(self.prefs_path, s)
        except OSError:
            pass   # the export itself doesn't depend on remembering the settings
        self.export_btn.configure(state="disabled")
        try:
            res = export.run(ds, s, progress=lambda text: self.say(text))
        except (OSError, ValueError) as e:
            self.say(f"Nothing was exported: {e}", hud.RED_HI)
            return None
        finally:
            self.export_btn.configure(state="normal")
        self.result = res
        lines = []
        for line in res["summary"].splitlines():
            tag = ("bad" if "SKIPPED" in line or "FAILED" in line else "warn" if line.strip().startswith("!")
                   else "ok" if "checked OK" in line or "read back OK" in line else "head")
            lines.append((line, tag))
        self.show_lines(lines)
        ok = not res["failed"]
        checked = ", all read back OK" if ok else f", {len(res['failed'])} Failed the check"
        self.say(f"Exported {project.plural(len(res['moves']), 'move')} ({project.plural(res['files'], 'file')}"
                 f"{checked}) into {res['dir']}", hud.GREEN if ok else hud.RED_HI)
        return res

    def copy(self):
        text = self.result["summary"] if self.result else self.text.get("1.0", "end")
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self.say("Copied.")

    def open_out(self):
        d = self.result["dir"] if self.result else self.out.get().strip()
        if d:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    images = os.path.abspath(sys.argv[1])
    root = tk.Tk()
    hud.setup(root)
    root.withdraw()
    prefs = os.path.join(os.path.dirname(images), "Game Settings", "studio.json")
    dlg = ExportDialog(root, images, prefs)
    dlg.win.bind("<Destroy>", lambda e: e.widget is dlg.win and root.destroy())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
