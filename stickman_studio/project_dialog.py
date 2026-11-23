"""The PROJECT… window of 02 TRACE (Stickman Studio upgrade, Phase 9).

One move at a time: its status (frames, trace, fixed trace up to date or not, protection, backups, checkpoints,
history, earlier frames, size), a check for missing or inconsistent data, and the project tools: protect / unprotect
the traced original, duplicate the move, whole-move backups (.zip in "Project backups") and unpacking one as a copy.
Nothing here deletes anything, and nothing existing is overwritten.

usage: python -I project_dialog.py <move folder>      (on its own; inside the studio: PROJECT… in 02 TRACE)
"""
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I leaves the script's folder out
import history  # noqa: E402
import hud  # noqa: E402
import project  # noqa: E402
import trace_io  # noqa: E402

MARK = {"error": ("✖", hud.RED_HI), "warning": ("▲", hud.AMBER), "note": ("•", hud.DIM)}
FIXED_TEXT = {"none": ("none yet (Review → Save Fixed)", hud.DIM), "ok": ("up to date with your trace", hud.GREEN),
              "stale": ("Out of Date: save it again in Review", hud.AMBER),
              "no trace": ("there's no trace.json it could come from", hud.AMBER),
              "unreadable": ("can't be read", hud.RED_HI)}


class ProjectDialog:
    """images = the Images folder (for copies and the Project backups folder beside it).
    on_changed(folder): something about the move changed (the studio refreshes its list).
    on_open(folder): show another move (a new copy) in 02 TRACE. on_backups(folder): open the BACKUPS… window."""

    def __init__(self, root, folder, images, on_changed=None, on_open=None, on_backups=None):
        self.root, self.folder, self.images = root, os.path.normpath(folder), os.path.normpath(images)
        self.home = project.backups_home(self.images)
        self.on_changed, self.on_open, self.on_backups = on_changed, on_open, on_backups
        self.zips = []
        self.win = w = tk.Toplevel(root, bg=hud.BG)
        w.title(f"Project: {os.path.basename(self.folder)}")
        w.geometry("1120x770")   # Phase 11: one more status row (Characters)
        w.minsize(900, 620)
        w.transient(root)
        w.bind("<Escape>", lambda e: w.destroy())

        head = tk.Frame(w, bg=hud.BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        hud.Header(head, "Project: " + os.path.basename(self.folder),
                   "Status, a check for missing or inconsistent data, protection, copies and whole-move backups. "
                   "Nothing here deletes anything or overwrites an existing file or folder.").pack(fill="x")

        body = tk.Frame(w, bg=hud.BG)
        body.pack(fill="both", expand=True, padx=12)
        left = hud.panel(body, width=430)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        hud.label(left, "STATUS", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY, anchor="w").pack(fill="x", padx=10,
                                                                                           pady=(8, 2))
        self.grid = tk.Frame(left, bg=hud.PANEL)
        self.grid.pack(fill="x", padx=10)
        self.cells = {}
        for r, key in enumerate(("Frames", "Characters", "Your trace", "Fixed trace", "Protection", "Backups",
                                 "History", "Earlier frames", "On disk")):
            hud.label(self.grid, key, bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL, anchor="nw").grid(
                row=r, column=0, sticky="nw", pady=2)
            v = hud.label(self.grid, "", bg=hud.PANEL, font=hud.SMALL, anchor="nw", justify="left", wraplength=290)
            v.grid(row=r, column=1, sticky="nw", padx=(10, 0), pady=2)
            self.cells[key] = v
        self.grid.columnconfigure(1, weight=1)
        hud.rule(left, pady=10)
        acts = tk.Frame(left, bg=hud.PANEL)
        acts.pack(fill="x", padx=10)
        self.protect_btn = hud.Button(acts, "Protect the Trace", self.toggle_protect)
        self.protect_btn.pack(fill="x", pady=2)
        hud.label(acts, "Protected = trace.json is read-only: the editor asks before touching it, restores refuse it. "
                        "The fixed trace stays separate and can still be saved.", bg=hud.PANEL, fg=hud.FAINT,
                  font=hud.TINY, anchor="w", justify="left", wraplength=400).pack(fill="x")
        hud.Button(acts, "Duplicate…", self.duplicate).pack(fill="x", pady=(8, 2))
        hud.label(acts, "A new move folder with the frames, both traces and settings (not its backups); the original "
                        "is only read.", bg=hud.PANEL, fg=hud.FAINT, font=hud.TINY, anchor="w", justify="left",
                  wraplength=400).pack(fill="x")
        row = tk.Frame(acts, bg=hud.PANEL)
        row.pack(fill="x", pady=(8, 2))
        hud.Button(row, "Backups & Checkpoints…", self.open_backups).pack(side="left", expand=True, fill="x",
                                                                         padx=(0, 4))
        hud.Button(row, "Open Folder", lambda: os.startfile(self.folder)).pack(side="left", expand=True, fill="x")

        right = tk.Frame(body, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        top = tk.Frame(right, bg=hud.BG)
        top.pack(fill="x")
        hud.Header(top, "Check", "Missing or inconsistent trace data. ✖ broken  ▲ worth a look  • a note.").pack(
            side="left", fill="x", expand=True)
        hud.Button(top, "Check Again", self.refresh, padx=8).pack(side="right", anchor="n")
        tw = hud.panel(right)
        tw.pack(fill="both", expand=True, pady=(6, 10))
        self.text = tk.Text(tw, bg=hud.PANEL, fg=hud.TEXT, font=hud.SMALL, wrap="word", height=10, bd=0,
                            highlightthickness=0, padx=8, pady=6, cursor="arrow")
        self.text.pack(fill="both", expand=True)
        for lv, (_, col) in MARK.items():
            self.text.tag_configure(lv, foreground=col)
        self.text.tag_configure("ok", foreground=hud.GREEN)
        self.text.tag_configure("body", lmargin1=0, lmargin2=18, spacing1=3)

        hud.Header(right, "Whole-move backups",
                   f"Every file of the move (frames, traces, backups, earlier frames) in one .zip in "
                   f"“{project.HOME_NAME}” beside the Images folder. Unpacking makes a New folder.").pack(fill="x")
        zw = hud.panel(right)
        zw.pack(fill="x", pady=(6, 0))
        self.zlist = tk.Listbox(zw, bg=hud.PANEL, fg=hud.TEXT, selectbackground=hud.RED, selectforeground="#ffffff",
                                font=hud.SMALL, height=5, activestyle="none", highlightthickness=0, bd=0,
                                exportselection=False)
        self.zlist.pack(fill="x", padx=6, pady=6)
        zb = tk.Frame(right, bg=hud.BG)
        zb.pack(fill="x", pady=(6, 0))
        for text, cmd, kind in (("Back Up This Move", self.backup_zip, "red"), ("Back Up All Moves", self.backup_all,
                                                                                "normal"),
                                ("Unpack as A Copy…", self.unzip, "normal"), ("Open Folder", self.open_home, "normal")):
            b = hud.Button(zb, text, cmd, kind=kind, padx=4, font=hud.SMALL if kind == "normal" else None)
            b.pack(side="left", expand=True, fill="x", padx=(0, 4))
            if cmd == self.unzip:
                self.unzip_btn = b

        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=10)
        hud.Button(bar, "Close", w.destroy).pack(side="right")   # packed first, so a long message can't hide it
        self.msg = hud.label(bar, "", fg=hud.DIM, font=hud.SMALL, anchor="w")
        self.msg.pack(side="left", fill="x", expand=True)
        self.refresh()
        w.focus_set()

    # ---- showing
    def say(self, text, colour=None):
        self.msg.configure(text=text, fg=colour or hud.DIM)

    def refresh(self):
        project._cache.pop(os.path.normcase(self.folder), None)
        st = self.st = project.status(self.folder)
        nums = project.frame_numbers(self.folder)
        c = self.cells
        c["Frames"].configure(text=f"{st['frames']}" + (f"  (f{nums[0]:02d} to f{nums[-1]:02d})" if nums else ""),
                              fg=hud.TEXT)
        if st["keys"]:
            c["Your trace"].configure(
                text=f"{st['done']} of {project.plural(st['keys'], 'key frame')} finished  ·  last changed "
                     f"{time.strftime('%d %b %Y %H:%M', time.localtime(st['edited']))}",
                fg=hud.GREEN if st["done"] == st["keys"] else hud.TEXT)
        else:
            c["Your trace"].configure(text="not traced yet" if not st["edited"] else "no key frames yet", fg=hud.DIM)
        txt, col = FIXED_TEXT.get(st["fixed"], (st["fixed"], hud.TEXT))
        c["Fixed trace"].configure(text=txt, fg=col)
        chars = st.get("characters")   # Phase 11: the traced characters of a multi-character move
        if chars:
            parts = [f"{x['name']} {x['done']}/{x['frames']}" + (" (hidden)" if not x["visible"] else "")
                     + (" (locked)" if x["locked"] else "") for x in chars]
            c["Characters"].configure(text=f"{len(chars)}: " + ", ".join(parts)
                                      + ".  “Your trace” and “Fixed trace” are character 1's.", fg=hud.TEXT)
        else:
            c["Characters"].configure(text="one (your trace). + Character on the Trace move page adds more.",
                                      fg=hud.DIM)
        c["Protection"].configure(text="Protected: trace.json is read-only" if st["protected"]
                                  else "not protected", fg=hud.AMBER if st["protected"] else hud.DIM)
        c["Backups"].configure(text=f"{st['backups']}" + (f"  ({project.plural(st['checkpoints'], 'checkpoint')})"
                                                          if st["checkpoints"] else ""), fg=hud.TEXT)
        data, problem = history.load(self.folder)
        c["History"].configure(text=problem or (f"{project.plural(len(data['undo']), 'undo step')} saved  ·  "
                                                f"{project.plural(len(data['events']), 'log entry')}"
                                                if os.path.exists(history.path(self.folder)) else "nothing yet"),
                               fg=hud.AMBER if problem else hud.TEXT)
        c["Earlier frames"].configure(text=", ".join(st["old"]) if st["old"] else "none (re-saving frames in 01 "
                                      "Source keeps the old ones in an “old …” folder)", fg=hud.TEXT if st["old"]
                                      else hud.DIM)
        size, files = project.folder_size(self.folder)
        c["On disk"].configure(text=f"{project.size_text(size)} in {project.plural(files, 'file')}", fg=hud.TEXT)
        self.protect_btn.configure(text="Unprotect the Trace" if st["protected"] else "Protect the Trace",
                                   state="normal" if st["edited"] else "disabled")
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        n = project.counts(st["issues"])
        if not n["error"] and not n["warning"]:
            t.insert("end", "✔ No problems found." + (" Notes:" if n["note"] else "") + "\n", ("ok", "body"))
        for i in st["issues"]:
            mark, _ = MARK[i["level"]]
            t.insert("end", f"{mark}  ", (i["level"], "body"))
            t.insert("end", i["text"] + "\n", ("body",))
        t.configure(state="disabled")
        self.load_zips()

    def load_zips(self, select=None):
        self.zips = project.list_zip_backups(self.home, os.path.basename(self.folder))
        lb = self.zlist
        lb.delete(0, "end")
        for z in self.zips:
            lb.insert("end", f"  {time.strftime('%d %b %Y  %H:%M:%S', time.localtime(z['time']))}   ·   "
                             f"{project.size_text(z['size'])}   ·   {z['name']}")
        if not self.zips:
            lb.insert("end", "  No whole-move backups of this move yet.")
        else:
            lb.selection_set(select or 0)
        self.unzip_btn.configure(state="normal" if self.zips else "disabled")

    def changed(self):
        self.refresh()
        if self.on_changed:
            self.on_changed(self.folder)

    # ---- actions
    def toggle_protect(self):
        try:
            if self.st["protected"]:
                project.unprotect(self.folder)
                self.say("Unprotected: trace.json can be edited again.", hud.GREEN)
            else:
                project.protect(self.folder)
                self.say("Protected: trace.json is now read-only (a backup was made first). The editor will ask "
                         "before you change it.", hud.GREEN)
        except (OSError, ValueError) as e:
            self.say(f"Nothing was changed: {e}", hud.RED_HI)
            return
        self.changed()

    def duplicate(self):
        name = hud.ask_text(self.win, "Duplicate move",
                            f"Name of the copy of “{os.path.basename(self.folder)}”. It's made next to it in "
                            f"{os.path.basename(os.path.dirname(self.folder))}, with the frames, your trace, the fixed "
                            "trace and the move's settings. The original isn't changed.", project.copy_name(self.folder))
        if name is None:
            return
        try:
            dest = project.duplicate(self.folder, name)
        except (OSError, ValueError) as e:
            self.say(f"No copy was made: {e}", hud.RED_HI)
            return
        self.say(f"Made “{os.path.basename(dest)}”. It's now picked in Trace.", hud.GREEN)
        if self.on_open:
            self.on_open(dest)
        self.win.lift()

    def open_backups(self):
        if self.on_backups:
            self.on_backups(self.folder)
        else:
            from restore_dialog import RestoreDialog
            RestoreDialog(self.root, self.folder, on_restored=lambda f: self.refresh())

    def backup_zip(self):
        self.say("Packing the move…")
        self.win.update_idletasks()
        try:
            path, n = project.backup_zip(self.folder, self.home)
        except OSError as e:
            self.say(f"Couldn't make the backup: {e}", hud.RED_HI)
            return
        self.load_zips()
        self.say(f"Backed up {project.plural(n, 'file')} to {project.HOME_NAME}\\{os.path.basename(path)}  "
                 "(Open Folder shows it).", hud.GREEN)

    def backup_all(self):
        folders = project.moves(self.images)
        if not folders:
            self.say("There are no moves in the Images folder.", hud.RED_HI)
            return
        if not messagebox.askyesno("Back up all moves", f"Pack each of the {len(folders)} moves in "
                                   f"{self.images} into its own .zip in\n{self.home}?\n\nNothing is changed or deleted.",
                                   parent=self.win):
            return
        made = []
        for d in folders:
            self.say(f"Packing {os.path.basename(d)}…")
            self.win.update_idletasks()
            try:
                made.append(project.backup_zip(d, self.home))
            except OSError as e:
                self.say(f"Stopped at {os.path.basename(d)}: {e}. The ones before it are saved.", hud.RED_HI)
                self.load_zips()
                return
        self.load_zips()
        self.say(f"Backed up {project.plural(len(made), 'move')} into {project.HOME_NAME} (Open Folder shows them).",
                 hud.GREEN)

    def unzip(self):
        sel = self.zlist.curselection()
        if not sel or sel[0] >= len(self.zips):
            return
        z = self.zips[sel[0]]
        try:
            info = project.zip_info(z["path"])
        except (OSError, ValueError, project.zipfile.BadZipFile) as e:
            self.say(f"That backup can't be read: {e}", hud.RED_HI)
            return
        m = project.ZIP_NAME.match(z["name"])
        stamp = time.strftime("%Y-%m-%d %H%M", time.strptime(m.group(2), "%Y%m%d-%H%M%S")) if m else "copy"
        name = hud.ask_text(self.win, "Unpack as a copy",
                            f"{z['name']}: {project.plural(info['files'], 'file')}, {info['frames']} frames"
                            f"{', traced' if info['traced'] else ''}.\n\nIt's unpacked into a New move folder "
                            f"in {os.path.basename(self.images)}; nothing that exists is changed. Name:",
                            project.free_name(self.images, f"{info['move']} (backup {stamp})"))
        if name is None:
            return
        try:
            dest = project.restore_zip_as_copy(z["path"], self.images, name)
        except (OSError, ValueError) as e:
            self.say(f"Nothing was unpacked: {e}", hud.RED_HI)
            return
        self.say(f"Unpacked into “{os.path.basename(dest)}”. It's now picked in Trace.", hud.GREEN)
        if self.on_open:
            self.on_open(dest)
        self.win.lift()

    def open_home(self):
        os.makedirs(self.home, exist_ok=True)
        os.startfile(self.home)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    folder = os.path.abspath(sys.argv[1])
    root = tk.Tk()
    hud.setup(root)
    root.withdraw()
    dlg = ProjectDialog(root, folder, os.path.dirname(folder))
    dlg.win.protocol("WM_DELETE_WINDOW", root.destroy)
    dlg.win.bind("<Destroy>", lambda e: e.widget is dlg.win and root.destroy())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
