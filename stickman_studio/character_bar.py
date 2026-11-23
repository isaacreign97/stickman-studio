"""The character bar (Stickman Studio Multi-Character Support, Phase 11): one slim row of character chips.

    CHARACTERS  [■ Ken 8/8  ◉ LOCK] [■ Ryu 6/8  ◉ LOCK] [■ Ref 0/0  ○ LOCK]   + CHARACTER   MANAGE…

Click a chip        make it the ACTIVE character (filled chip, red edge); the selection becomes just that one
Ctrl+click          add it to / take it out of the SELECTION (red outline) for group editing
Shift+click         select the range from the active character to this one
Double-click        rename it
◉ / ○               shown / hidden          LOCK (amber when locked)   locked characters can't be edited
+ CHARACTER         add a character (the first time it asks, explains what is created, and checkpoints trace.json)
MANAGE…             rename, colour, order, delete (archived, restorable), restore deleted, import (character_dialog.py)

A single-character move shows only "One character (your trace)" and + CHARACTER, so nothing else changes for it.
The data work is done by characters.py; this file only shows it and asks.
"""
import os
import tkinter as tk
from tkinter import messagebox

import characters as ch
import hud

CTRL, SHIFT = 0x0004, 0x0001


class CharacterBar(tk.Frame):
    """on_change(bar) is called after anything changed (active, selection, list, flags)."""

    def __init__(self, parent, root, on_change=None, bg=hud.BG):
        super().__init__(parent, bg=bg)
        self.root, self.on_change, self.bgc = root, on_change, bg
        self.move, self.cs, self.problem = None, None, None
        self.selected = set()
        self.chips = {}

    # ---- data
    def load(self, move, active=None):
        """Show the characters of a move (active: make that character active, e.g. a dropped character file)."""
        self.move = os.path.normpath(move) if move else None
        self.cs, self.problem = None, None
        if self.move:
            try:
                self.cs = ch.CharacterSet.open(self.move)
                if active and active in self.cs.ids() and active != self.cs.active:
                    self.cs.set_active(active)
            except ch.CharacterError as e:
                self.problem = str(e)
        ids = set(self.cs.ids()) if self.cs else set()
        self.selected = (self.selected & ids) or ({self.cs.active} if self.cs else set())
        self.render()

    @property
    def active(self):
        return self.cs.active if self.cs else ch.PRIMARY

    @property
    def multi(self):
        return bool(self.cs and self.cs.saved)

    def active_entry(self):
        return self.cs.get(self.active) if self.cs else ch.primary_entry()

    def changed(self):
        if self.move:
            self.load(self.move)   # re-reads the list; keeps the selection that still exists
        if self.on_change:
            self.on_change(self)

    # ---- drawing
    def render(self):
        for w in self.winfo_children():
            w.destroy()
        self.chips = {}
        if not self.move:
            return
        hud.label(self, "Characters", bg=self.bgc, fg=hud.FAINT, font=hud.TINY).pack(side="left", padx=(0, 8))
        if self.problem:
            hud.label(self, "characters.json can't be used (left as it is): see Project…", bg=self.bgc,
                      fg=hud.RED_HI, font=hud.SMALL).pack(side="left")
            return
        if not self.multi:
            hud.label(self, "One character (your trace)", bg=self.bgc, fg=hud.DIM, font=hud.SMALL).pack(
                side="left", padx=(0, 10))
        else:
            for c in self.cs.summary():
                self.chips[c["id"]] = self.chip(c)
        hud.Button(self, "+ Character", self.add, padx=6, pady=1, font=hud.TINY).pack(side="left", padx=(6, 4))
        if self.multi:
            hud.Button(self, "Manage…", self.manage, padx=6, pady=1, font=hud.TINY).pack(side="left")

    def chip(self, c):
        cid = c["id"]
        active, sel = c["active"], cid in self.selected
        bg = hud.RED_BG if active else hud.PANEL2
        f = tk.Frame(self, bg=bg, highlightthickness=2 if (active or sel) else 1, cursor="hand2",
                     highlightbackground=hud.RED if (active or sel) else hud.LINE)
        f.pack(side="left", padx=(0, 4))
        sw = tk.Frame(f, bg=c["colour"], width=10, height=10)
        sw.pack(side="left", padx=(6, 4))
        name = tk.Label(f, text=c["name"], bg=bg, font=hud.BOLD if active else hud.SMALL,
                        fg=hud.FAINT if not c["visible"] else hud.TEXT)
        name.pack(side="left")
        prog = tk.Label(f, text=f"{c['done']}/{c['frames']}", bg=bg, font=hud.TINY,
                        fg=hud.GREEN if c["frames"] and c["done"] == c["frames"] else hud.DIM)
        prog.pack(side="left", padx=(4, 6))
        eye = tk.Label(f, text="◉" if c["visible"] else "○", bg=bg, font=hud.SMALL, cursor="hand2",
                       fg=hud.TEXT if c["visible"] else hud.FAINT)
        eye.pack(side="left", padx=(0, 4))
        lock = tk.Label(f, text="Locked" if c["locked"] else "Lock", bg=bg, font=hud.TINY, cursor="hand2",
                        fg=hud.AMBER if c["locked"] else hud.FAINT)
        lock.pack(side="left", padx=(0, 6))
        for w in (f, sw, name, prog):
            w.bind("<Button-1>", lambda e, cid=cid: self.click(cid, e.state))
            w.bind("<Double-Button-1>", lambda e, cid=cid: self.rename(cid))
        eye.bind("<Button-1>", lambda e, cid=cid: self.toggle_visible(cid))
        lock.bind("<Button-1>", lambda e, cid=cid: self.toggle_lock(cid))
        f.parts = {"name": name, "progress": prog, "eye": eye, "lock": lock}
        return f

    # ---- actions
    def error(self, e):
        messagebox.showerror("Characters", f"{e}", parent=self.root)

    def click(self, cid, state=0):
        """Plain: make active. Ctrl: toggle in the selection. Shift: select the range from the active one."""
        if not self.cs:
            return
        if state & CTRL:
            if cid in self.selected and len(self.selected) > 1:
                self.selected.discard(cid)
            else:
                self.selected.add(cid)
        elif state & SHIFT:
            ids = self.cs.ids()
            a, b = sorted((ids.index(self.active), ids.index(cid)))
            self.selected = set(ids[a:b + 1])
        else:
            try:
                self.cs.set_active(cid)
            except ch.CharacterError as e:
                return self.error(e)
            self.selected = {cid}
        self.render()
        if self.on_change:
            self.on_change(self)

    def select_none(self):
        self.selected = {self.active}
        self.render()

    def add(self):
        if not self.cs:
            return None
        if not self.cs.saved and not messagebox.askyesno(
                "Add a character",
                f"Add a second traced character to {os.path.basename(self.move)}?\n\n"
                "Your trace stays exactly as it is (it becomes character 1). Created: characters.json (the list of "
                "characters) and a folder characters\\<id>\\ for the new one, which shares this move's frames. "
                "A checkpoint of your trace is saved first.", parent=self.root):
            return None
        name = hud.ask_text(self.root, "Add a character", "Name of the new traced character (for example Ryu):",
                            f"Character {len(self.cs.ids()) + 1}")
        if name is None:
            return None
        try:
            cid = self.cs.create(name)
            self.cs.set_active(cid)
        except (ch.CharacterError, OSError) as e:
            return self.error(e)
        self.selected = {cid}
        self.changed()
        return cid

    def rename(self, cid):
        name = hud.ask_text(self.root, "Rename character", "New name:", self.cs.get(cid)["name"])
        if name is None:
            return
        try:
            self.cs.rename(cid, name)
        except (ch.CharacterError, OSError) as e:
            return self.error(e)
        self.changed()

    def toggle_visible(self, cid):
        try:
            self.cs.set_visible(cid, not self.cs.get(cid)["visible"])
        except (ch.CharacterError, OSError) as e:
            return self.error(e)
        self.changed()

    def toggle_lock(self, cid):
        try:
            self.cs.set_locked(cid, not self.cs.get(cid)["locked"])
        except (ch.CharacterError, OSError) as e:
            return self.error(e)
        self.changed()

    def manage(self):
        from character_dialog import CharacterDialog
        return CharacterDialog(self.root, self.move, on_change=lambda: self.changed())
