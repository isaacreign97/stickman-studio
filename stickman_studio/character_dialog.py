"""The MANAGE… window for traced characters (Stickman Studio Multi-Character Support, Phase 11).

Lists a move's characters with their colour, key frames, shown / hidden and locked, and does:
RENAME…, COLOUR…, UP / DOWN (drawing order), SHOW / HIDE, LOCK / UNLOCK,
DELETE… (after a confirmation; the character's folder is ARCHIVED in characters\\_deleted\\, never erased;
         character 1 can't be deleted, and a locked character must be unlocked first),
RESTORE DELETED…, IMPORT FROM ANOTHER MOVE… (only when the frames are the same pictures, or, if you agree, at least
the same size). All the data work is done by characters.py.
"""
import os
import tkinter as tk
from tkinter import colorchooser, messagebox

import characters as ch
import hud
import project
import trace_io


def pick(win, title, text, items):
    """A small list to choose one item from. -> its index, or None when cancelled."""
    d = tk.Toplevel(win, bg=hud.PANEL, padx=16, pady=12)
    d.title(title)
    d.transient(win)
    d.resizable(False, False)
    res = {"i": None}
    hud.label(d, text, bg=hud.PANEL, justify="left", anchor="w", wraplength=460).pack(fill="x")
    lb = tk.Listbox(d, bg=hud.FIELD, fg=hud.TEXT, selectbackground=hud.RED, font=hud.SMALL, height=min(12, max(3, len(items))),
                    width=60, activestyle="none", highlightthickness=0, bd=0, exportselection=False)
    lb.pack(fill="both", pady=8)
    for it in items:
        lb.insert("end", "  " + it)
    if items:
        lb.selection_set(0)

    def ok():
        s = lb.curselection()
        res["i"] = s[0] if s else None
        d.destroy()

    row = tk.Frame(d, bg=hud.PANEL)
    row.pack(anchor="e")
    hud.Button(row, "Cancel", d.destroy).pack(side="right", padx=(4, 0))
    hud.Button(row, "OK", ok, kind="red").pack(side="right")
    lb.bind("<Double-Button-1>", lambda e: ok())
    d.bind("<Return>", lambda e: ok())
    d.bind("<Escape>", lambda e: d.destroy())
    d.grab_set()
    d.wait_window()
    return res["i"]


class CharacterDialog:
    def __init__(self, root, move, on_change=None):
        self.root, self.move, self.on_change = root, os.path.normpath(move), on_change
        self.cs = ch.CharacterSet.open(self.move)
        self.rows = []
        self.win = w = tk.Toplevel(root, bg=hud.BG)
        w.title(f"Characters: {os.path.basename(self.move)}")
        w.geometry("900x520")
        w.minsize(760, 440)
        w.transient(root)
        w.bind("<Escape>", lambda e: w.destroy())
        head = tk.Frame(w, bg=hud.BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        hud.Header(head, "Traced characters of " + os.path.basename(self.move),
                   "Every character shares this move's frames and has its own 12-joint trace. Character 1 is your "
                   "original trace.json. Deleting a character keeps its files in characters\\_deleted\\, so it can "
                   "be restored.").pack(fill="x")
        body = tk.Frame(w, bg=hud.BG)
        body.pack(fill="both", expand=True, padx=12)
        lw = hud.panel(body)
        lw.pack(side="left", fill="both", expand=True)
        self.list = tk.Listbox(lw, bg=hud.PANEL, fg=hud.TEXT, selectbackground=hud.RED_BG, selectforeground=hud.TEXT,
                               font=hud.SMALL, activestyle="none", highlightthickness=0, bd=0, exportselection=False)
        self.list.pack(fill="both", expand=True, padx=6, pady=6)
        self.list.bind("<Double-Button-1>", lambda e: self.rename())
        side = tk.Frame(body, bg=hud.BG)
        side.pack(side="left", fill="y", padx=(10, 0))
        for text, cmd in (("Rename…", self.rename), ("Colour…", self.colour), ("Up", lambda: self.order(-1)),
                          ("Down", lambda: self.order(1)), ("Show / Hide", self.toggle_visible),
                          ("Lock / Unlock", self.toggle_lock), ("Delete…", self.delete)):
            hud.Button(side, text, cmd, padx=8, font=hud.SMALL).pack(fill="x", pady=2)
        hud.rule(side, pady=8)
        for text, cmd in (("Restore Deleted…", self.restore), ("Import from Another Move…", self.import_)):
            hud.Button(side, text, cmd, padx=8, font=hud.SMALL).pack(fill="x", pady=2)
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        hud.Button(bar, "Close", w.destroy).pack(side="right")
        self.msg = hud.label(w, "", fg=hud.DIM, font=hud.SMALL, anchor="w")
        self.msg.pack(fill="x", padx=12, pady=(4, 8))
        self.refresh()
        w.focus_set()

    # ---- the list
    def refresh(self, select=None):
        keep = select or (self.selected_id() if self.rows else self.cs.active)
        self.cs = ch.CharacterSet.open(self.move)
        self.rows = self.cs.summary()
        lb = self.list
        lb.delete(0, "end")
        for c in self.rows:
            where = "character 1: trace.json" if c["primary"] else f"characters\\{c['id']}"
            flags = ("" if c["visible"] else "  ·  Hidden") + ("  ·  Locked" if c["locked"] else "")
            lb.insert("end", f"  ■  {c['name']}   ·   {c['done']} of {c['frames']} key frames finished   ·   "
                             f"{where}{flags}{'   ◀ active' if c['active'] else ''}")
            lb.itemconfigure("end", fg=c["colour"])
        ids = [c["id"] for c in self.rows]
        lb.selection_set(ids.index(keep) if keep in ids else 0)

    def selected_id(self):
        s = self.list.curselection()
        return self.rows[s[0]]["id"] if s and s[0] < len(self.rows) else None

    def say(self, text, colour=None):
        self.msg.configure(text=text, fg=colour or hud.DIM)

    def done(self, text, select=None):
        self.refresh(select)
        self.say(text, hud.GREEN)
        if self.on_change:
            self.on_change()

    def guard(self, fn, *a):
        """Run a characters.py action. -> (True, its result), or (False, None) after showing why it failed."""
        try:
            return True, fn(*a)
        except (ch.CharacterError, OSError) as e:
            self.say(f"Nothing was changed: {e}", hud.RED_HI)
            return False, None

    # ---- actions
    def rename(self):
        cid = self.selected_id()
        if not cid:
            return
        name = hud.ask_text(self.win, "Rename character", "New name:", self.cs.get(cid)["name"])
        if name is not None and self.guard(self.cs.rename, cid, name)[0]:
            self.done(f"Renamed to “{self.cs.get(cid)['name']}”.", cid)

    def colour(self):
        cid = self.selected_id()
        if not cid:
            return
        got = colorchooser.askcolor(self.cs.get(cid)["colour"], parent=self.win, title="Character colour")
        if got and got[1]:
            if self.guard(self.cs.set_colour, cid, got[1].lower())[0]:
                self.done("Colour changed.", cid)

    def order(self, delta):
        cid = self.selected_id()
        if cid and self.guard(self.cs.move_order, cid, delta)[0]:
            self.done("Order changed (later characters are drawn on top).", cid)

    def toggle_visible(self):
        cid = self.selected_id()
        if cid:
            on = not self.cs.get(cid)["visible"]
            if self.guard(self.cs.set_visible, cid, on)[0]:
                self.done("Shown." if on else "Hidden: it isn't drawn and group edits leave it alone.", cid)

    def toggle_lock(self):
        cid = self.selected_id()
        if cid:
            on = not self.cs.get(cid)["locked"]
            if self.guard(self.cs.set_locked, cid, on)[0]:
                self.done("Locked: it can't be edited until you unlock it." if on else "Unlocked.", cid)

    def delete(self):
        cid = self.selected_id()
        if not cid:
            return
        c = self.cs.get(cid)
        if cid == ch.PRIMARY:
            self.say("Character 1 is your original trace.json, so it can't be deleted. Rename, hide or lock it "
                     "instead.", hud.AMBER)
            return
        if c["locked"]:
            self.say(f"“{c['name']}” is locked: unlock it first to delete it.", hud.AMBER)
            return
        done, total = self.cs.progress(cid)
        if not messagebox.askyesno(
                "Delete character", f"Delete “{c['name']}” ({done} of {total} key frames finished)?\n\n"
                                    "Its folder is moved to characters\\_deleted\\ (nothing is erased), and Restore "
                                    "Deleted… can bring it back.", parent=self.win):
            return
        ok, dest = self.guard(self.cs.archive, cid)
        if ok:
            self.done(f"Deleted “{c['name']}”: kept in characters\\_deleted\\{os.path.basename(dest)}.")

    def restore(self):
        gone = self.cs.deleted()
        if not gone:
            self.say("There are no deleted characters in this move.")
            return
        i = pick(self.win, "Restore deleted character", "Which one?",
                 [f"{g['name']}   ·   {g['frames']} key frames   ·   deleted {g['archived']}" for g in gone])
        if i is None:
            return
        ok, cid = self.guard(self.cs.restore, gone[i]["path"])
        if ok:
            self.done(f"Restored “{self.cs.get(cid)['name']}”.", cid)

    def import_(self):
        others = [d for d in project.moves(os.path.dirname(self.move))
                  if os.path.normcase(d) != os.path.normcase(self.move)]
        options = []
        for d in others:
            for c in ch.list_characters(d):
                if trace_ok(c["trace_dir"]):
                    options.append((d, c["id"], f"{os.path.basename(d)}  ›  {c['name']}"))
        if not options:
            self.say("No other move has a traced character to import.")
            return
        i = pick(self.win, "Import a character", "Copy which traced character in as a new character of "
                 f"{os.path.basename(self.move)}? It must have been traced on the same frames (for example in a "
                 "duplicate of this move). The other move is only read.", [o[2] for o in options])
        if i is None:
            return
        d, oid, label = options[i]
        try:
            info = ch.import_check(d, oid, self.move)
        except ch.CharacterError as e:
            self.say(f"Nothing was imported: {e}", hud.RED_HI)
            return
        allow = False
        if info["missing"]:
            self.say("Nothing was imported: this move has no frame "
                     + ", ".join(f"f{f:02d}.png" for f in info["missing"]) + ".", hud.RED_HI)
            return
        if info["different"]:
            fs = ", ".join(f"f{f:02d}" for f in info["different"][:6])
            if info["other_size"]:
                self.say(f"Nothing was imported: the pictures of {fs} aren't the same, not even the same size, so "
                         "the points wouldn't line up.", hud.RED_HI)
                return
            if not messagebox.askyesno(
                    "Import a character", f"The pictures of {fs} aren't exactly the same in both moves (same size, "
                                          "different pixels). The points may not line up.\n\nImport anyway?",
                    parent=self.win):
                return
            allow = True
        name = hud.ask_text(self.win, "Import a character", "Name of the imported character:", info["name"])
        if name is None:
            return
        ok, cid = self.guard(self.cs.import_from, d, oid, name, allow)
        if ok:
            self.done(f"Imported “{self.cs.get(cid)['name']}” from {label}.", cid)


def trace_ok(trace_dir):
    return bool(trace_io.find_file(trace_dir, trace_io.TRACE))
