"""The HUD look shared by Stickman Studio, the stickman player and Game Settings:
near-black panels, thin grey lines, red accents, Bahnschrift (DIN-style) type and ring gauges.

    import hud
    hud.setup(root)                     # dark ttk theme + colours for the whole window
    hud.Button(parent, "Save", cmd, kind="red").pack()
    hud.Header(parent, "Controls", "Click a key to change it.").pack(fill="x")
    g = hud.Gauge(parent, size=96, label="FRAME"); g.set(12, 40)
"""
import math
import tkinter as tk
from tkinter import ttk

BG = "#0a0a0c"        # window
PANEL = "#111114"     # panels
PANEL2 = "#18181d"    # raised parts, buttons
FIELD = "#1d1d23"     # text boxes
LINE = "#2e2e36"      # thin lines and borders
LINE2 = "#4a4a55"
TEXT = "#ebebee"
DIM = "#8d8d98"
FAINT = "#5a5a64"
RED = "#e3222b"
RED_HI = "#ff434b"
RED_LO = "#4b0f14"
RED_BG = "#26090c"
AMBER = "#e3a23a"
GREEN = "#46c66f"
PAPER = "#f3f3f3"     # the stickman stage stays light: the stickman is black

F = "Bahnschrift"
F_SEMI = "Bahnschrift SemiBold"
F_LIGHT = "Bahnschrift Light"
F_COND = "Bahnschrift SemiCondensed"
MONO = "Consolas"
FONT = (F, 10)
SMALL = (F, 9)
TINY = (F_COND, 8)
BOLD = (F_SEMI, 10)
TITLE = (F_SEMI, 13)
HUGE = (F_LIGHT, 22)


def setup(root):
    """Dark theme for every ttk widget in this window, plus defaults for plain tk widgets."""
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=LINE, lightcolor=PANEL2,
                darkcolor=PANEL2, troughcolor=PANEL, focuscolor=RED, font=FONT, selectbackground=RED_LO,
                selectforeground=TEXT, insertcolor=RED, arrowcolor=DIM)
    s.configure("TButton", background=PANEL2, foreground=TEXT, bordercolor=LINE2, lightcolor=PANEL2,
                darkcolor=PANEL2, padding=(10, 4), font=FONT)
    s.map("TButton", background=[("pressed", RED), ("active", RED_LO)], bordercolor=[("active", RED)],
          foreground=[("disabled", FAINT)])
    s.configure("Red.TButton", background=RED, foreground="#ffffff", bordercolor=RED, font=BOLD)
    s.map("Red.TButton", background=[("pressed", RED_LO), ("active", RED_HI)], foreground=[("disabled", FAINT)])
    s.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=RED, bordercolor=LINE2,
                lightcolor=FIELD, darkcolor=FIELD, padding=3)
    s.map("TEntry", bordercolor=[("focus", RED)], fieldbackground=[("readonly", PANEL)],
          foreground=[("readonly", DIM), ("disabled", FAINT)])
    s.configure("Bad.TEntry", fieldbackground=RED_BG, foreground=RED_HI, bordercolor=RED)
    s.configure("TCombobox", fieldbackground=FIELD, background=PANEL2, foreground=TEXT, arrowcolor=RED,
                bordercolor=LINE2, lightcolor=FIELD, darkcolor=FIELD, padding=3, selectbackground=FIELD,
                selectforeground=TEXT)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", PANEL)],
          foreground=[("disabled", FAINT), ("readonly", TEXT)], bordercolor=[("focus", RED), ("hover", RED)],
          arrowcolor=[("disabled", FAINT)], background=[("active", RED_LO)])
    root.option_add("*TCombobox*Listbox.background", PANEL2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", RED)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    for kind in ("TCheckbutton", "TRadiobutton"):
        s.configure(kind, background=BG, foreground=TEXT, indicatorbackground=FIELD, indicatorforeground="#ffffff",
                    upperbordercolor=LINE2, lowerbordercolor=LINE2, font=FONT, focuscolor=BG)
        s.map(kind, background=[("active", BG)], indicatorbackground=[("selected", RED), ("active", RED_LO)],
              foreground=[("disabled", FAINT)])
    s.configure("Panel.TCheckbutton", background=PANEL)
    s.map("Panel.TCheckbutton", background=[("active", PANEL)])
    s.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG, bordercolor=BG, arrowcolor=DIM,
                lightcolor=PANEL2, darkcolor=PANEL2, gripcount=0)
    s.map("Vertical.TScrollbar", background=[("active", RED_LO)], arrowcolor=[("active", RED)])
    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background=PANEL, foreground=DIM, padding=(18, 7), bordercolor=LINE,
                lightcolor=PANEL, darkcolor=PANEL, font=BOLD)
    s.map("TNotebook.Tab", background=[("selected", RED_BG)], foreground=[("selected", TEXT)],
          lightcolor=[("selected", RED)], bordercolor=[("selected", RED)])
    s.configure("Horizontal.TProgressbar", background=RED, troughcolor=PANEL2, bordercolor=LINE,
                lightcolor=RED, darkcolor=RED)
    root.option_add("*Label.foreground", TEXT)      # plain labels: light text unless they say otherwise
    root.option_add("*Label.background", BG)
    root.option_add("*Frame.background", BG)
    root.option_add("*Text.background", FIELD)
    root.option_add("*Text.foreground", TEXT)
    root.option_add("*Text.insertBackground", RED)
    root.option_add("*Text.selectBackground", RED_LO)
    root.option_add("*Menu.background", PANEL2)
    root.option_add("*Menu.foreground", TEXT)
    root.option_add("*Menu.activeBackground", RED)
    root.option_add("*Menu.activeForeground", "#ffffff")
    root.option_add("*Menu.font", FONT)
    return s


class Button(tk.Label):
    """A flat HUD button: thin border that turns red on hover. kind = "normal", "red" (main action) or "ghost"."""
    KINDS = {
        "normal": (PANEL2, TEXT, LINE2, RED_LO, RED),
        "red": (RED, "#ffffff", RED, RED_HI, RED_HI),
        "ghost": (BG, DIM, LINE, PANEL2, RED),
    }

    def __init__(self, master, text, command=None, kind="normal", font=None, padx=12, pady=4, **kw):
        bg, fg, border, hover, hover_border = self.KINDS[kind]
        super().__init__(master, text=text, bg=bg, fg=fg, font=font or (BOLD if kind == "red" else FONT),
                         padx=padx, pady=pady, cursor="hand2", highlightthickness=1, highlightbackground=border,
                         highlightcolor=border, disabledforeground=FAINT, **kw)
        self.kind, self.command = kind, command
        self.colors = (bg, fg, border, hover, hover_border)
        self.bind("<Enter>", lambda e: self.hover(True))
        self.bind("<Leave>", lambda e: self.hover(False))
        self.bind("<ButtonRelease-1>", self.click)

    def hover(self, on):
        bg, fg, border, hover, hover_border = self.colors
        if str(self.cget("state")) == "disabled":
            on = False
        super().configure(bg=hover if on else bg, highlightbackground=hover_border if on else border)

    def click(self, e):
        if str(self.cget("state")) == "disabled" or not self.command:
            return
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            self.command()

    def set_kind(self, kind):
        self.kind = kind
        self.colors = self.KINDS[kind]
        self.restyle()

    def restyle(self):
        bg, fg, border, hover, hover_border = self.colors
        if str(self.cget("state")) == "disabled":   # disabled: grey, whatever the kind
            super().configure(bg=PANEL2, highlightbackground=LINE, cursor="")
        else:
            super().configure(bg=bg, fg=fg, highlightbackground=border, cursor="hand2")

    def configure(self, cnf=None, **kw):
        out = super().configure(cnf, **kw)
        if "state" in kw:
            self.restyle()
        return out

    config = configure


def tag(master, text, color=RED, bg=BG, font=None):
    """A red outlined label, like a HUD title plate."""
    return tk.Label(master, text=text, fg=color, bg=bg, font=font or (F_SEMI, 9), padx=8, pady=1,
                    highlightthickness=1, highlightbackground=color, highlightcolor=color)


class Header(tk.Frame):
    """Section title: a red plate, a thin line to the right, and an optional grey line of help under it."""

    def __init__(self, master, text, sub=None, color=RED, bg=BG, **kw):
        super().__init__(master, bg=bg, **kw)
        top = tk.Frame(self, bg=bg)
        top.pack(fill="x")
        tag(top, text, color, bg).pack(side="left")
        tk.Frame(top, bg=LINE, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0))
        if sub:
            s = tk.Label(self, text=sub, bg=bg, fg=DIM, font=SMALL, anchor="w", justify="left")
            s.pack(fill="x", pady=(3, 0))
            wrap_to_width(s)


def wrap_to_width(lbl, margin=4):
    """Let a label's text wrap at whatever width the label gets."""
    lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(50, e.width - margin)), add="+")
    return lbl


def ask_text(win, title, text, initial=""):
    """A small window asking for one line of text (Phase 9: checkpoint and copy names).
    -> the text (stripped), or None when cancelled."""
    d = tk.Toplevel(win, bg=PANEL, padx=18, pady=14)
    d.title(title)
    d.transient(win)
    d.resizable(False, False)
    result = {"v": None}
    tk.Label(d, text=text, bg=PANEL, fg=TEXT, font=FONT, justify="left", wraplength=420).pack(anchor="w")
    var = tk.StringVar(d, value=initial)
    e = tk.Entry(d, textvariable=var, width=48, bg=FIELD, fg=TEXT, insertbackground=TEXT, font=FONT, relief="flat",
                 highlightthickness=1, highlightbackground=LINE, highlightcolor=RED)
    e.pack(fill="x", pady=(10, 0), ipady=3)
    e.select_range(0, "end")
    e.focus_set()
    row = tk.Frame(d, bg=PANEL)
    row.pack(anchor="e", pady=(12, 0))

    def ok():
        result["v"] = var.get().strip()
        d.destroy()

    Button(row, "CANCEL", d.destroy).pack(side="right", padx=(4, 0))
    Button(row, "OK", ok, kind="red").pack(side="right")
    d.bind("<Return>", lambda ev: ok())
    d.bind("<Escape>", lambda ev: d.destroy())
    d.grab_set()
    d.wait_window()
    return result["v"]


def rule(master, bg=LINE, pady=0):
    f = tk.Frame(master, bg=bg, height=1)
    f.pack(fill="x", pady=pady)
    return f


def panel(master, bg=PANEL, border=LINE, **kw):
    return tk.Frame(master, bg=bg, highlightthickness=1, highlightbackground=border, highlightcolor=border, **kw)


def label(master, text="", bg=BG, fg=TEXT, font=None, **kw):
    return tk.Label(master, text=text, bg=bg, fg=fg, font=font or FONT, **kw)


def style_scale(scale, bg=BG):
    """A slim slider: red handle on a dark track (show the value in a label of your own)."""
    scale.configure(bg=RED, troughcolor=PANEL2, activebackground=RED_HI, highlightthickness=0,
                    sliderrelief="flat", bd=0, showvalue=0, sliderlength=16, width=12)
    return scale


class Gauge(tk.Canvas):
    """A ring gauge like the reference: tick marks, a red arc for value / maximum, a big number in the middle."""

    def __init__(self, master, size=92, label="", bg=BG, **kw):
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, **kw)
        self.size, self.label = size, label
        self.value, self.maximum, self.text = 0, 1, "0"
        self.draw()

    def set(self, value, maximum, text=None, label=None):
        self.value, self.maximum = value, max(maximum, 1e-9)
        self.text = str(text if text is not None else value)
        if label is not None:
            self.label = label
        self.draw()

    def draw(self):
        self.delete("all")
        s = self.size
        c = s / 2
        r1, r2 = s / 2 - 3, s / 2 - 9
        for i in range(60):
            a = math.radians(i * 6 - 90)
            long = i % 5 == 0
            ri = r2 - (4 if long else 1)
            self.create_line(c + ri * math.cos(a), c + ri * math.sin(a), c + r2 * math.cos(a), c + r2 * math.sin(a),
                             fill=LINE2 if long else LINE)
        self.create_oval(c - r1, c - r1, c + r1, c + r1, outline=LINE, width=1)
        frac = max(0.0, min(1.0, self.value / self.maximum))
        if frac > 0:
            self.create_arc(c - r1, c - r1, c + r1, c + r1, start=90, extent=-359.9 * frac, style="arc",
                            outline=RED, width=3)
        self.create_text(c, c - (3 if self.label else 0), text=self.text, fill=TEXT,
                         font=(F_LIGHT, max(10, int(s / 4.2))))
        if self.label:
            self.create_text(c, c + s / 5.2, text=self.label.upper(), fill=DIM, font=(F_COND, max(7, int(s / 13))))


def bars(canvas, x0, y0, x1, y1, n=48, color=LINE, accent=RED, seed=7):
    """Decorative equaliser bars along the bottom of a panel (the reference's data strips)."""
    import random
    rnd = random.Random(seed)
    w = (x1 - x0) / n
    for i in range(n):
        h = (y1 - y0) * (0.15 + 0.85 * rnd.random() ** 2)
        canvas.create_rectangle(x0 + i * w + 1, y1 - h, x0 + (i + 1) * w - 1, y1,
                                fill=accent if rnd.random() < 0.08 else color, outline="")
