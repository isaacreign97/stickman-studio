"""Ribbon UI (v3.3), shared by every Stickman Studio screen, Game Settings and the Paint window:

    TitleBar   the window's top strip, like Paint's: app mark, quick-access icons (Save, Undo, Redo, a menu),
               the document title, and a Help menu on the right.
    Ribbon     a File menu button and tabs (Home, View, …). Each tab holds captioned groups of controls; everyday
               controls go on Home, advanced ones on the other tabs. Double-click a tab to collapse the ribbon.
    tooltip()  a hover tip (keyboard shortcuts and explanations live here instead of on the buttons).

    rb = Ribbon(parent, file_items=[("Open…", open_fn, "Ctrl+O"), None, ("Export…", export_fn)])
    g = rb.tab("Home").group("Clipboard")
    g.button("Copy", copy_fn, tip="Copy the selection (Ctrl+C)")
    g.check("Loop", loop_var, tip="Play again from the start")
"""
import tkinter as tk

import hud

TAB_FONT = (hud.F, 10)
BTN_FONT = (hud.F, 9)
CAP_FONT = (hud.F_COND, 8)


# ================================================================ tooltips
class _Tip:
    def __init__(self, widget, text):
        self.w, self.text, self.win, self.after = widget, text, None, None
        widget.bind("<Enter>", self.enter, add="+")
        widget.bind("<Leave>", self.leave, add="+")
        widget.bind("<ButtonPress>", self.leave, add="+")

    def enter(self, e=None):
        self.cancel()
        self.after = self.w.after(450, self.show)

    def cancel(self):
        if self.after:
            try:
                self.w.after_cancel(self.after)
            except tk.TclError:
                pass
            self.after = None

    def show(self):
        self.after = None
        text = self.text() if callable(self.text) else self.text
        if not text or not self.w.winfo_exists():
            return
        self.win = tk.Toplevel(self.w)
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(self.win, text=text, bg=hud.PANEL2, fg=hud.TEXT, font=BTN_FONT, justify="left", wraplength=360,
                 padx=8, pady=5, highlightthickness=1, highlightbackground=hud.LINE2).pack()
        x = self.w.winfo_rootx() + 4
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.win.geometry(f"+{x}+{y}")

    def leave(self, e=None):
        self.cancel()
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None


def tooltip(widget, text):
    """Show text (or text() when it's a function) under the widget after a short hover."""
    if text:
        widget._tip = _Tip(widget, text)
    return widget


# ================================================================ drawn icons (no image files)
def _icon(c, kind, col):
    c.delete("all")
    if kind == "save":     # a floppy disk
        c.create_rectangle(4, 4, 17, 17, outline=col, width=1.5)
        c.create_rectangle(7, 4, 14, 9, outline=col, width=1)
        c.create_rectangle(7, 12, 14, 17, fill=col, outline=col)
    elif kind in ("undo", "redo"):
        s = 1 if kind == "redo" else -1
        cx = 10.5
        c.create_arc(cx - 6, 6, cx + 6, 18, start=0 if s > 0 else 180, extent=180 * s, style="arc", outline=col,
                     width=2)
        tip_x = cx + 6 * s
        c.create_polygon(tip_x - 4, 9, tip_x + 4, 9, tip_x, 14, fill=col, outline=col)
    elif kind == "menu":   # Paint's "customise" arrow: a bar over a small triangle
        c.create_line(6, 8, 15, 8, fill=col, width=1)
        c.create_polygon(6, 11, 15, 11, 10.5, 16, fill=col, outline=col)
    elif kind == "help":
        c.create_oval(3, 3, 18, 18, outline=col, width=1.5)
        c.create_text(10.5, 10.5, text="?", fill=col, font=(hud.F_SEMI, 9))
    elif kind == "logo":   # the studio's mark: a red plate with a tiny stickman
        c.create_rectangle(2, 2, 19, 19, fill=hud.RED, outline=hud.RED)
        w = "#ffffff"
        c.create_oval(8, 4, 13, 9, outline=w, width=1.5)
        c.create_line(10.5, 9, 10.5, 14, fill=w, width=1.5)
        c.create_line(6, 11, 15, 11, fill=w, width=1.5)
        c.create_line(10.5, 14, 7, 18, fill=w, width=1.5)
        c.create_line(10.5, 14, 14, 18, fill=w, width=1.5)


class IconButton(tk.Canvas):
    def __init__(self, master, kind, command=None, tip=None, bg=hud.BG):
        super().__init__(master, width=22, height=22, bg=bg, highlightthickness=0, cursor="hand2")
        self.kind, self.command, self.base, self.enabled = kind, command, bg, True
        _icon(self, kind, hud.TEXT)
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=hud.PANEL2))
        self.bind("<Leave>", lambda e: self.configure(bg=self.base))
        self.bind("<ButtonRelease-1>", self.click)
        tooltip(self, tip)

    def click(self, e):
        if self.enabled and self.command and 0 <= e.x < 22 and 0 <= e.y < 22:
            self.command()

    def set_enabled(self, on):
        self.enabled = bool(on)
        _icon(self, self.kind, hud.TEXT if on else hud.FAINT)
        self.configure(cursor="hand2" if on else "")


def dark_menu(master):
    return tk.Menu(master, tearoff=False, bg=hud.PANEL2, fg=hud.TEXT, activebackground=hud.RED,
                   activeforeground="#ffffff", font=BTN_FONT, bd=0, relief="flat")


def fill_menu(menu, items):
    """items: (label, command[, accelerator]) or None for a separator, or (label, [sub-items]) for a submenu."""
    menu.delete(0, "end")
    for it in items:
        if it is None:
            menu.add_separator()
        elif isinstance(it[1], (list, tuple)):
            sub = dark_menu(menu)
            fill_menu(sub, it[1])
            menu.add_cascade(label=it[0], menu=sub)
        else:
            menu.add_command(label=it[0], command=it[1], accelerator=it[2] if len(it) > 2 else "")
    return menu


def post_menu(widget, items):
    m = fill_menu(dark_menu(widget), items() if callable(items) else items)
    m.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
    return m


# ================================================================ title bar
class TitleBar(tk.Frame):
    """[mark] [Save] [Undo] [Redo] [▾]   Title — Stickman Studio                          [Help ▾]"""

    def __init__(self, master, app="Stickman Studio", save=None, undo=None, redo=None, menu_items=None,
                 help_items=None, bg=hud.BG):
        super().__init__(master, bg=bg)
        self.app = app
        mark = tk.Canvas(self, width=22, height=22, bg=bg, highlightthickness=0)
        _icon(mark, "logo", hud.TEXT)
        mark.pack(side="left", padx=(0, 6))
        self.icons = {}
        for kind, fn, tip in (("save", save, "Save (Ctrl+S)"), ("undo", undo, "Undo (Ctrl+Z)"),
                              ("redo", redo, "Redo (Ctrl+Y)")):
            b = IconButton(self, kind, fn, tip, bg)
            b.pack(side="left", padx=1)
            self.icons[kind] = b
        if menu_items is not None:
            m = IconButton(self, "menu", None, "More commands", bg)
            m.command = lambda: post_menu(m, menu_items)
            m.pack(side="left", padx=(1, 0))
        tk.Frame(self, bg=hud.LINE, width=1, height=16).pack(side="left", padx=10)
        self.title = tk.Label(self, text=app, bg=bg, fg=hud.TEXT, font=(hud.F, 10))
        self.title.pack(side="left")
        if help_items is not None:
            h = tk.Label(self, text="Help  ▾", bg=bg, fg=hud.DIM, font=BTN_FONT, cursor="hand2", padx=8, pady=2)
            h.pack(side="right")
            h.bind("<Button-1>", lambda e: post_menu(h, help_items))
            h.bind("<Enter>", lambda e: h.configure(fg=hud.TEXT))
            h.bind("<Leave>", lambda e: h.configure(fg=hud.DIM))
            self.help = h

    def set_title(self, doc=None):
        self.title.configure(text=f"{doc}  —  {self.app}" if doc else self.app)

    def set_enabled(self, **states):
        for k, on in states.items():
            if k in self.icons:
                self.icons[k].set_enabled(on)


# ================================================================ ribbon
class RibbonGroup(tk.Frame):
    """A captioned group of controls. Controls go on the current row; row() starts a new row under it."""

    def __init__(self, tab, caption):
        super().__init__(tab, bg=hud.PANEL)
        self.body = tk.Frame(self, bg=hud.PANEL)
        self.body.pack(side="top", fill="both", expand=True, padx=6, pady=(5, 0))
        self.cap = tk.Label(self, text=caption, bg=hud.PANEL, fg=hud.FAINT, font=CAP_FONT)
        self.cap.pack(side="bottom", pady=(1, 2))
        self._row = None

    def row(self):
        self._row = tk.Frame(self.body, bg=hud.PANEL)
        self._row.pack(side="top", anchor="w", pady=1)
        return self._row

    def cur(self):
        return self._row or self.row()

    def button(self, text, command, tip=None, kind="normal", padx=8):
        b = hud.Button(self.cur(), text, command, kind=kind, font=hud.BOLD if kind == "red" else BTN_FONT,
                       padx=padx, pady=2)
        b.pack(side="left", padx=(0, 3))
        tooltip(b, tip)
        return b

    def check(self, text, var, command=None, tip=None):
        c = tk.Checkbutton(self.cur(), text=text, variable=var, command=command, bg=hud.PANEL, fg=hud.TEXT,
                           selectcolor=hud.FIELD, activebackground=hud.PANEL, activeforeground=hud.TEXT,
                           font=BTN_FONT, highlightthickness=0, bd=0)
        c.pack(side="left", padx=(0, 6))
        tooltip(c, tip)
        return c

    def label(self, text, fg=hud.DIM, **kw):
        lb = tk.Label(self.cur(), text=text, bg=hud.PANEL, fg=fg, font=BTN_FONT, **kw)
        lb.pack(side="left", padx=(0, 4))
        return lb

    def place(self, widget, padx=(0, 3)):
        """Pack a widget made with self.cur() as its parent."""
        widget.pack(side="left", padx=padx)
        return widget


class RibbonTab(tk.Frame):
    def __init__(self, ribbon, name):
        super().__init__(ribbon.body, bg=hud.PANEL)
        self.ribbon, self.name = ribbon, name
        self.groups = []

    def group(self, caption):
        if self.groups:
            tk.Frame(self, bg=hud.LINE, width=1).pack(side="left", fill="y", pady=6)
        g = RibbonGroup(self, caption)
        g.pack(side="left", fill="y")
        self.groups.append(g)
        return g


class Ribbon(tk.Frame):
    def __init__(self, master, file_items=None, file_label="File", bg=hud.BG):
        super().__init__(master, bg=bg)
        self.strip = tk.Frame(self, bg=bg)
        self.strip.pack(fill="x")
        self.file_items = file_items or []
        self.file_btn = tk.Label(self.strip, text=file_label, bg=hud.RED, fg="#ffffff", font=TAB_FONT, padx=16,
                                 pady=3, cursor="hand2")
        self.file_btn.pack(side="left", padx=(0, 4))
        self.file_btn.bind("<Button-1>", lambda e: post_menu(self.file_btn, self.file_items))
        self.file_btn.bind("<Enter>", lambda e: self.file_btn.configure(bg=hud.RED_HI))
        self.file_btn.bind("<Leave>", lambda e: self.file_btn.configure(bg=hud.RED))
        self.body = tk.Frame(self, bg=hud.PANEL, highlightthickness=1, highlightbackground=hud.LINE,
                             highlightcolor=hud.LINE, height=74)
        self.body.pack(fill="x")
        self.body.pack_propagate(False)
        self.tabs, self.labels = {}, {}
        self.current = None
        self.collapsed = False

    def tab(self, name, tip=None):
        if name in self.tabs:
            return self.tabs[name]
        t = RibbonTab(self, name)
        self.tabs[name] = t
        lb = tk.Label(self.strip, text=name, bg=self["bg"], fg=hud.DIM, font=TAB_FONT, padx=14, pady=3,
                      cursor="hand2")
        lb.pack(side="left")
        lb.bind("<Button-1>", lambda e: self.select(name))
        lb.bind("<Double-Button-1>", lambda e: self.toggle_collapse())
        tooltip(lb, tip)
        self.labels[name] = lb
        if self.current is None:
            self.select(name)
        return t

    def select(self, name):
        if self.collapsed:
            self.toggle_collapse()
        if self.current and self.current in self.tabs:
            self.tabs[self.current].place_forget()
            self.labels[self.current].configure(bg=self["bg"], fg=hud.DIM)
        self.current = name
        self.tabs[name].place(x=0, y=0, relheight=1)
        self.labels[name].configure(bg=hud.PANEL, fg=hud.TEXT)

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body.pack_forget()
        else:
            self.body.pack(fill="x")

    def set_file_items(self, items):
        self.file_items = items


def tool_buttons(buttons, current):
    """Show which tool is on: red for the current one."""
    for k, b in buttons.items():
        b.set_kind("red" if k == current else "normal")
