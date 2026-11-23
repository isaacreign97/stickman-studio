"""05 ANIMATE's creative windows (v3.2): the LIBRARY, the STORY editor and the story player. No AI."""
import os
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageTk

import animate as A
import hud
import library
import story
import trace_player as tp


def dialog(root, title, w=None, h=None):
    d = tk.Toplevel(root, bg=hud.PANEL, padx=14, pady=12)
    d.title(title)
    d.transient(root)
    if w:
        d.geometry(f"{w}x{h}")
    return d


# ================================================================ LIBRARY
class LibraryDialog:
    """Browse the Animation Library: insert an item into the animation, paint a picture item further, or delete
    (moved to the library's Deleted folder)."""

    def __init__(self, tab, kind="Characters"):
        self.t = tab
        self.d = d = dialog(tab.root, "Animation Library", 760, 560)
        self.kind = tk.StringVar(value=kind)
        self.thumbs = []
        top = tk.Frame(d, bg=hud.PANEL)
        top.pack(fill="x")
        for k in library.KINDS:
            tk.Radiobutton(top, text=k, value=k, variable=self.kind, command=self.fill, indicatoron=False, bg=hud.FIELD,
                           fg=hud.TEXT, selectcolor=hud.RED, activebackground=hud.PANEL, font=hud.SMALL, padx=10,
                           pady=3, relief="flat").pack(side="left", padx=(0, 4))
        hud.label(top, library.root(tab.images), bg=hud.PANEL, fg=hud.FAINT, font=hud.TINY).pack(side="right")
        body = tk.Frame(d, bg=hud.PANEL)
        body.pack(fill="both", expand=True, pady=8)
        self.cv = tk.Canvas(body, bg=hud.FIELD, highlightthickness=0)
        sb = tk.Scrollbar(body, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.cv.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Button-1>", self.click)
        self.cv.bind("<Double-Button-1>", lambda e: self.insert())
        bot = tk.Frame(d, bg=hud.PANEL)
        bot.pack(fill="x")
        for text, cmd, kind in (("Insert", self.insert, "red"), ("Insert as Background", lambda: self.insert("background"),
                                                                  "normal"),
                                ("Paint It…", self.edit, "normal"), ("Delete…", self.delete, "normal")):
            hud.Button(bot, text, cmd, kind=kind, padx=10, pady=3, font=hud.SMALL).pack(side="left", padx=(0, 4))
        hud.Button(bot, "Close", d.destroy, padx=10, pady=3, font=hud.SMALL).pack(side="right")
        self.info = hud.label(d, "", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL)
        self.info.pack(anchor="w", pady=(6, 0))
        self.items, self.pick = [], None
        d.after(30, self.fill)

    def fill(self):
        c = self.cv
        c.delete("all")
        self.thumbs.clear()
        self.items = library.list_items(self.t.images, self.kind.get())
        self.pick = None
        W = max(300, c.winfo_width())
        cols = max(1, W // 178)
        for i, (k, name, folder) in enumerate(self.items):
            x, y = 10 + (i % cols) * 178, 10 + (i // cols) * 160
            c.create_rectangle(x, y, x + 168, y + 150, outline=hud.LINE, fill=hud.PANEL, tags=("cell", f"i{i}"))
            th = os.path.join(folder, "thumb.png")
            if os.path.exists(th):
                try:
                    with Image.open(th) as im:
                        bg = Image.new("RGBA", (160, 120), (243, 243, 243, 255))
                        im = im.convert("RGBA")
                        bg.alpha_composite(im, ((160 - im.width) // 2, (120 - im.height) // 2))
                    ph = ImageTk.PhotoImage(bg)
                    self.thumbs.append(ph)
                    c.create_image(x + 4, y + 4, image=ph, anchor="nw")
                except OSError:
                    pass
            c.create_text(x + 84, y + 136, text=name[:24], fill=hud.TEXT, font=hud.SMALL)
        c.configure(scrollregion=(0, 0, W, 20 + ((len(self.items) + cols - 1) // cols) * 160))
        self.info.configure(text=f"{len(self.items)} in {self.kind.get()}. Click one, then Insert (it goes in on "
                                 f"frame {self.t.frame + 1}). Save things here with Save to Library… (Arrange tab or "
                                 "PAINT)." if self.items else
                            f"No {self.kind.get().lower()} yet: Save to Library… (Arrange tab) or in Paint puts "
                            "things here.")

    def click(self, e):
        y = self.cv.canvasy(e.y)
        W = max(300, self.cv.winfo_width())
        cols = max(1, W // 178)
        col, row = int((e.x - 10) // 178), int((y - 10) // 160)
        i = row * cols + col
        self.cv.delete("sel")
        if 0 <= col < cols and 0 <= i < len(self.items):
            self.pick = i
            x, yy = 10 + col * 178, 10 + row * 160
            self.cv.create_rectangle(x, yy, x + 168, yy + 150, outline=hud.RED, width=3, tags="sel")
            J = library.read(self.items[i][2])
            self.info.configure(text=f"{J['name']} · {J['kind']} · saved {J.get('made', '?')}")
        else:
            self.pick = None

    def chosen(self):
        if self.pick is None:
            messagebox.showinfo("Library", "Click an item first.", parent=self.d)
            return None
        return self.items[self.pick]

    def insert(self, role=None):
        it = self.chosen()
        if not it or not self.t.need():
            return
        try:
            c = library.insert(self.t.proj, it[2], self.t.frame, role)
        except (library.LibraryError, OSError, KeyError) as e:
            messagebox.showinfo("Library", f"It couldn't be inserted: {e}", parent=self.d)
            return
        self.t.active, self.t.selected = c["id"], {c["id"]}
        self.t.after_change("rebuild")
        self.t.msg(f"Inserted {c['name']}. Ctrl+Z takes it out again.")

    def edit(self):
        it = self.chosen()
        if not it:
            return
        J = library.read(it[2])
        if J["track"] is not None:
            messagebox.showinfo("Library", "Paint works on picture items (Pictures, and props or backgrounds saved "
                                           "from Paint). Insert this one and edit its bones' pictures instead.",
                                parent=self.d)
            return
        img, shapes = library.picture_of(it[2])
        self.t.open_paint(picture=(img, shapes), name=J["name"])

    def delete(self):
        it = self.chosen()
        if not it:
            return
        if messagebox.askyesno("Library", f"Delete “{it[1]}” from the library?\n\nIt's moved to the library's Deleted "
                                          "folder, so it can be put back by hand.", parent=self.d):
            dst = library.delete(self.t.images, it[2])
            self.fill()
            self.info.configure(text=f"Moved to {dst}")


# ================================================================ STORY
class StoryDialog:
    """Scenes (frame ranges) and how each one ends: carry on, jump, ask a choice, or end the story."""

    def __init__(self, tab):
        self.t = tab
        self.d = d = dialog(tab.root, "Story: branching paths", 700, 520)
        hud.label(d, "Split the animation into scenes. Each scene ends by carrying on, jumping to another scene, "
                     "asking a choice (up to 4 buttons) or ending the story.", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL,
                  wraplength=660, justify="left").pack(anchor="w")
        self.lb = tk.Listbox(d, bg=hud.FIELD, fg=hud.TEXT, font=hud.FONT, height=12, relief="flat",
                             selectbackground=hud.RED, exportselection=False, activestyle="none")
        self.lb.pack(fill="both", expand=True, pady=8)
        self.lb.bind("<Double-Button-1>", lambda e: self.ending())
        g = tk.Frame(d, bg=hud.PANEL)
        g.pack(fill="x")
        for text, cmd in (("+ Scene…", self.add), ("Edit…", self.edit), ("Ending…", self.ending),
                          ("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)), ("Start Here", self.first),
                          ("Delete", self.delete)):
            hud.Button(g, text, cmd, padx=8, pady=2, font=hud.SMALL).pack(side="left", padx=(0, 4))
        g2 = tk.Frame(d, bg=hud.PANEL)
        g2.pack(fill="x", pady=(8, 0))
        hud.Button(g2, "▶ Play the Story", self.play, kind="red", padx=10, pady=3, font=hud.SMALL).pack(side="left")
        hud.Button(g2, "Export as A Web Page…", self.export, padx=10, pady=3, font=hud.SMALL).pack(side="left", padx=6)
        hud.Button(g2, "Close", d.destroy, padx=10, pady=3, font=hud.SMALL).pack(side="right")
        self.problems = hud.label(d, "", bg=hud.PANEL, fg=hud.AMBER, font=hud.SMALL, wraplength=660, justify="left")
        self.problems.pack(anchor="w", pady=(8, 0))
        self.fill()

    def fill(self, keep=None):
        p = self.t.proj
        self.lb.delete(0, "end")
        sc = story.scenes(p) if p else []
        names = {s["id"]: s["name"] for s in sc}
        first = (story.get(p) or {}).get("first") if p else None
        for i, s in enumerate(sc, 1):
            t = s["then"]
            end = {"next": "→ next scene", "end": "■ The End", "goto": f"→ go to “{names.get(t.get('goto'), '?')}”",
                   "choice": "? " + " / ".join(f"{o['label']} → {names.get(o['goto'], '?')}"
                                               for o in t.get("options", []))}[t["kind"]]
            self.lb.insert("end", f"{'▶ ' if s['id'] == first else '   '}{i}. {s['name']}   frames {s['start'] + 1}–"
                                  f"{s['end'] + 1}   {end}")
        if keep is not None and 0 <= keep < len(sc):
            self.lb.selection_set(keep)
        pr = story.check(p) if p else []
        self.problems.configure(text="\n".join("⚠ " + x for x in pr) if pr else
                                ("Story OK." if sc else "No scenes yet: + Scene… makes the first one."))
        self.t.draw_timeline()

    def picked(self):
        sel = self.lb.curselection()
        if not sel:
            messagebox.showinfo("Story", "Click a scene first.", parent=self.d)
            return None
        return story.scenes(self.t.proj)[sel[0]], sel[0]

    def ask_range(self, title, name, a, b):
        txt = hud.ask_text(self.d, title, "Name, first frame and last frame, e.g.  Fight, 10, 24", f"{name}, {a}, {b}")
        if not txt:
            return None
        parts = [x.strip() for x in txt.rsplit(",", 2)]
        try:
            return parts[0], int(parts[1]) - 1, int(parts[2]) - 1
        except (IndexError, ValueError):
            messagebox.showinfo("Story", "Type it as: name, first frame, last frame.", parent=self.d)
            return None

    def add(self):
        if not self.t.need():
            return
        sc = story.scenes(self.t.proj)
        a = (max(s["end"] for s in sc) + 2) if sc else self.t.frame + 1
        a = min(a, self.t.length())
        got = self.ask_range("New scene", f"Scene {len(sc) + 1}", a, self.t.length())
        if got:
            try:
                story.add_scene(self.t.proj, *got)
            except (story.StoryError, A.AnimateError) as e:
                messagebox.showinfo("Story", str(e), parent=self.d)
            self.fill(len(sc))

    def edit(self):
        got = self.picked()
        if not got:
            return
        s, i = got
        r = self.ask_range("Edit scene", s["name"], s["start"] + 1, s["end"] + 1)
        if r:
            try:
                story.edit_scene(self.t.proj, s["id"], *r)
            except (story.StoryError, A.AnimateError) as e:
                messagebox.showinfo("Story", str(e), parent=self.d)
            self.fill(i)

    def move(self, d):
        got = self.picked()
        if got:
            story.move_scene(self.t.proj, got[0]["id"], d)
            self.fill(max(0, got[1] + d))

    def first(self):
        got = self.picked()
        if got:
            story.set_first(self.t.proj, got[0]["id"])
            self.fill(got[1])

    def delete(self):
        got = self.picked()
        if got and messagebox.askyesno("Story", f"Delete the scene “{got[0]['name']}”? Its frames stay in the "
                                                "animation; Ctrl+Z brings the scene back.", parent=self.d):
            story.remove_scene(self.t.proj, got[0]["id"])
            self.fill()

    def ending(self):
        got = self.picked()
        if not got:
            return
        s, i = got
        EndingDialog(self, s, i)

    def play(self):
        if not story.scenes(self.t.proj):
            messagebox.showinfo("Story", "Make a scene first.", parent=self.d)
            return
        StoryPlayer(self.t)

    def export(self):
        try:
            self.t.proj.save()
            out = story.export_html(self.t.proj, os.path.join(os.path.dirname(self.t.images), "Exports"))
        except (story.StoryError, OSError) as e:
            messagebox.showinfo("Story", str(e), parent=self.d)
            return
        messagebox.showinfo("Story", f"Saved:\n\n{out}\n\nOpen index.html in any web browser to play it. Nothing is "
                                     "sent anywhere.", parent=self.d)


class EndingDialog:
    def __init__(self, owner, s, index):
        self.o, self.s, self.i = owner, s, index
        p = owner.t.proj
        self.sc = story.scenes(p)
        self.names = [x["name"] for x in self.sc]
        d = self.d = dialog(owner.d, f"How “{s['name']}” ends")
        t = s["then"]
        self.kind = tk.StringVar(value=t["kind"])
        for k, text in (("next", "Carry on with the next scene"), ("goto", "Go to a scene"),
                        ("choice", "Ask a choice"), ("end", "The end")):
            tk.Radiobutton(d, text=text, value=k, variable=self.kind, bg=hud.PANEL, fg=hud.TEXT, selectcolor=hud.FIELD,
                           activebackground=hud.PANEL, font=hud.SMALL).pack(anchor="w")
        ids = [x["id"] for x in self.sc]
        self.goto = tk.StringVar(value=self.names[ids.index(t["goto"])] if t.get("goto") in ids else self.names[0])
        row = tk.Frame(d, bg=hud.PANEL)
        row.pack(fill="x", pady=(4, 8))
        hud.label(row, "go to:", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(side="left")
        self.menu(row, self.goto).pack(side="left", padx=4)
        hud.label(d, "Choice question:", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(anchor="w")
        self.prompt = tk.StringVar(value=t.get("prompt", "What happens next?"))
        tk.Entry(d, textvariable=self.prompt, width=50, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT,
                 relief="flat", font=hud.SMALL).pack(fill="x", pady=(0, 6))
        self.opts = []
        old = t.get("options", [])
        for k in range(story.MAX_OPTIONS):
            r = tk.Frame(d, bg=hud.PANEL)
            r.pack(fill="x", pady=1)
            lab = tk.StringVar(value=old[k]["label"] if k < len(old) else "")
            tgt = tk.StringVar(value=self.names[ids.index(old[k]["goto"])] if k < len(old) and old[k]["goto"] in ids
                               else self.names[0])
            hud.label(r, f"button {k + 1}", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(side="left")
            tk.Entry(r, textvariable=lab, width=22, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT, relief="flat",
                     font=hud.SMALL).pack(side="left", padx=4)
            hud.label(r, "→", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(side="left")
            self.menu(r, tgt).pack(side="left", padx=4)
            self.opts.append((lab, tgt))
        hud.Button(d, "OK", self.ok, kind="red", padx=14, pady=3).pack(anchor="e", pady=(10, 0))

    def menu(self, parent, var):
        om = tk.OptionMenu(parent, var, *self.names)
        om.configure(bg=hud.FIELD, fg=hud.TEXT, highlightthickness=0, relief="flat", font=hud.SMALL)
        return om

    def sid(self, name):
        return self.sc[self.names.index(name)]["id"]

    def ok(self):
        k = self.kind.get()
        try:
            story.set_then(self.o.t.proj, self.s["id"], k, goto=self.sid(self.goto.get()) if k == "goto" else None,
                           prompt=self.prompt.get(),
                           options=[(lab.get(), self.sid(tgt.get())) for lab, tgt in self.opts if lab.get().strip()])
        except story.StoryError as e:
            messagebox.showinfo("Story", str(e), parent=self.d)
            return
        self.d.destroy()
        self.o.fill(self.i)


class StoryPlayer:
    """Plays the story like a viewer would: scene by scene, stopping at each choice."""

    def __init__(self, tab):
        self.t, self.p = tab, tab.proj
        self.d = d = dialog(tab.root, f"{self.p.doc['name']}: story", 900, 640)
        self.cv = tk.Canvas(d, bg="#1a1a1f", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.ask = tk.Frame(d, bg=hud.PANEL)
        self.ask.pack(fill="x", pady=(8, 0))
        self.photo, self.cache, self.after = None, {}, None
        d.protocol("WM_DELETE_WINDOW", self.close)
        d.after(60, lambda: self.play((story.get(self.p) or {}).get("first")))

    def frame(self, f):
        if f not in self.cache:
            if len(self.cache) > 200:
                self.cache.clear()
            self.cache[f] = A.render(self.p, f)
        img = self.cache[f]
        cw, ch = max(10, self.cv.winfo_width()), max(10, self.cv.winfo_height())
        z = min(cw / img.width, ch / img.height)
        self.photo = ImageTk.PhotoImage(img.resize((max(1, int(img.width * z)), max(1, int(img.height * z)))))
        self.cv.delete("all")
        self.cv.create_image(cw / 2, ch / 2, image=self.photo)

    def clear_ask(self):
        for w in self.ask.winfo_children():
            w.destroy()

    def play(self, sid):
        self.clear_ask()
        if not sid:
            return self.the_end()
        s = story.scene(self.p, sid)
        hud.label(self.ask, s["name"].upper(), bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(side="left")
        self.run(s, s["start"])

    def run(self, s, f):
        if not self.d.winfo_exists():
            return
        if f > s["end"]:
            return self.next(s)
        self.frame(f)
        self.after = self.d.after(max(10, int(1000 / self.p.doc["fps"])), lambda: self.run(s, f + 1))

    def next(self, s):
        t = s["then"]
        if t["kind"] == "choice":
            self.clear_ask()
            hud.label(self.ask, t.get("prompt") or "What happens next?", bg=hud.PANEL, fg=hud.TEXT,
                      font=hud.BOLD).pack(side="left", padx=(0, 10))
            for k, o in enumerate(t["options"]):
                hud.Button(self.ask, o["label"], lambda k=k: self.play(story.after(self.p, s["id"], k)), kind="red",
                           padx=12, pady=3).pack(side="left", padx=3)
            return
        self.play(story.after(self.p, s["id"]))

    def the_end(self):
        self.clear_ask()
        hud.label(self.ask, "The End", bg=hud.PANEL, fg=hud.TEXT, font=hud.BOLD).pack(side="left", padx=(0, 10))
        hud.Button(self.ask, "Play Again", lambda: self.play((story.get(self.p) or {}).get("first")), padx=12,
                   pady=3).pack(side="left")

    def close(self):
        if self.after:
            try:
                self.d.after_cancel(self.after)
            except tk.TclError:
                pass
        self.d.destroy()


def choose_picture_source(tab, title, can_existing=True):
    """-> "paint", "file", "library", "existing" or None."""
    opts = ["Paint a new one…", "From a picture file…", "From the library…"] + \
        (["A picture already in this animation…"] if can_existing and tab.proj and tab.proj.doc.get("pictures") else []) \
        + ["Cancel"]
    ch = tp.ask_choice(tab.root, title, "Where does the picture come from?", opts, 0)
    if ch is None or opts[ch] == "Cancel":
        return None
    return ["paint", "file", "library", "existing"][ch]


def pick_library_picture(tab):
    """A list of the library's picture items (Pictures, and props / backgrounds painted in PAINT).
    -> (pixels, shapes, name) or None."""
    items = [(k, n, f) for k, n, f in library.list_items(tab.images) if library.read(f)["track"] is None]
    if not items:
        messagebox.showinfo("Library", "No pictures in the library yet: Paint… → Save to Library… puts them there.",
                            parent=tab.root)
        return None
    d = dialog(tab.root, "Pick a library picture")
    lb = tk.Listbox(d, bg=hud.FIELD, fg=hud.TEXT, font=hud.FONT, height=min(14, len(items)), width=40, relief="flat",
                    selectbackground=hud.RED)
    for k, n, _ in items:
        lb.insert("end", f"{n}   ({k[:-1].lower()})")
    lb.pack(fill="both", expand=True)
    out = {}

    def ok():
        if lb.curselection():
            k, n, f = items[lb.curselection()[0]]
            img, shapes = library.picture_of(f)
            out["v"] = (img, shapes, n)
        d.destroy()
    lb.bind("<Double-Button-1>", lambda e: ok())
    hud.Button(d, "Use It", ok, kind="red").pack(anchor="e", pady=(8, 0))
    d.grab_set()
    d.wait_window()
    return out.get("v")


def pick_existing_picture(tab):
    """A small list of the animation's pictures. -> picture id or None."""
    pics = tab.proj.doc.get("pictures") or {}
    ids = list(pics)
    d = dialog(tab.root, "Pick a picture")
    lb = tk.Listbox(d, bg=hud.FIELD, fg=hud.TEXT, font=hud.FONT, height=min(12, len(ids)), width=36, relief="flat",
                    selectbackground=hud.RED)
    for i in ids:
        lb.insert("end", pics[i].get("name") or i)
    lb.pack(fill="both", expand=True)
    out = {}

    def ok():
        if lb.curselection():
            out["id"] = ids[lb.curselection()[0]]
        d.destroy()
    lb.bind("<Double-Button-1>", lambda e: ok())
    hud.Button(d, "Use It", ok, kind="red").pack(anchor="e", pady=(8, 0))
    d.grab_set()
    d.wait_window()
    return out.get("id")
