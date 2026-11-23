"""PAINT… (v3.2): a paint window for making your own pictures (characters' parts, props, backgrounds, anything).
Painted pixels plus shapes you can still edit; the picture then goes into the animation or the library. No AI.

    PaintWindow(root, images, picture=None, size=(400, 400), outputs=[(label, fn(img, shapes, name))], title=...)
"""
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageTk

import hud
import library
import paint
import paint_tools as pt

MAX_UNDO = 60


class PaintWindow:
    def __init__(self, root, images, picture=None, size=(400, 400), outputs=(), title="Paint", name="My picture",
                 on_close=None):
        self.root, self.images = root, images
        self.outputs = list(outputs)
        self.on_close = on_close
        if picture is not None:
            img, shapes = picture
            self.img, self.shapes = img.convert("RGBA").copy(), [dict(s) for s in shapes or []]
        else:
            self.img, self.shapes = Image.new("RGBA", tuple(int(v) for v in size), (0, 0, 0, 0)), []
        self.undo_stack, self.redo_stack = [], []
        self.zoom = None              # None = fit the window
        self.photo = None
        self.saved_version = 0
        self.version = 0
        w = self.win = tk.Toplevel(root, bg=hud.BG)
        w.title(title)
        w.geometry("1220x820")
        w.minsize(980, 640)
        w.transient(root)
        w.protocol("WM_DELETE_WINDOW", self.close)
        self.v_name = tk.StringVar(value=name)
        self.tools = pt.PaintTools(self)
        self.tools.tool = "pen"
        self.build()
        for seq, fn in [("<Control-z>", self.undo), ("<Control-y>", self.redo), ("<Escape>", lambda: self.key("Escape")),
                        ("<Return>", lambda: self.key("Return")), ("<Delete>", lambda: self.key("Delete")),
                        ("<Control-c>", lambda: self.key("copy")), ("<Control-x>", lambda: self.key("cut")),
                        ("<Control-v>", lambda: self.key("paste"))]:
            w.bind(seq, lambda e, fn=fn: None if isinstance(e.widget, tk.Entry) else fn())
        for k, _, short in pt.TOOLS:
            if short:
                w.bind(f"<{short.lower()}>", lambda e, k=k: None if isinstance(e.widget, tk.Entry) else self.set_tool(k))
        self.set_tool("pen")
        w.after(50, self.redraw)

    # ================================================================ layout
    def build(self):
        """v3.3: laid out like Microsoft Paint: a title bar (Save to library, Undo, Redo) and a ribbon. Home holds
        Clipboard, Image, Tools, Shapes, Size and Colours; Options holds opacity, fill tolerance and the rest."""
        import ribbon
        w = self.win
        tb = ribbon.TitleBar(w, "Paint", self.to_library, self.undo, self.redo, None, None)
        tb.icons["save"]._tip.text = "Save to the Animation Library"
        tb.pack(fill="x", padx=10, pady=(6, 0))
        self.titlebar = tb
        tb.set_title(self.v_name.get())
        self.v_name.trace_add("write", lambda *_: tb.set_title(self.v_name.get()))
        rb = self.ribbon = ribbon.Ribbon(w, [("Resize Picture…", self.new_size), ("Import Picture…", self.import_file),
                                             None, ("Save to Library…", self.to_library), None,
                                             ("Close", self.close)])
        rb.pack(fill="x", padx=10, pady=(6, 0))
        self.tool_btns = {}

        def tool(g, key, text, tip):
            self.tool_btns[key] = g.button(text, lambda: self.set_tool(key), tip)

        home = rb.tab("Home")
        g = home.group("Clipboard")
        g.button("Paste", lambda: self.key("paste"), "Ctrl+V")
        g.row()
        g.button("Cut", lambda: self.key("cut"), "Ctrl+X")
        g.button("Copy", lambda: self.key("copy"), "Ctrl+C")
        g = home.group("Image")
        tool(g, "select", "Select", "Drag a box, then move, resize or turn it (S)")
        tool(g, "lasso", "Lasso", "Draw around what you want to select")
        g.button("Rotate", lambda: self.tools.transform("turn"), "Rotate the selection 90°")
        g.row()
        g.button("Flip ↔", lambda: self.tools.transform("fliph"), "Flip horizontally")
        g.button("Flip ↕", lambda: self.tools.transform("flipv"), "Flip vertically")
        g.button("Resize…", self.new_size, "Change the picture's size")
        g = home.group("Tools")
        tool(g, "pen", "Pen", "P")
        tool(g, "brush", "Brush", "B")
        tool(g, "eraser", "Eraser", "E")
        g.row()
        tool(g, "fill", "Fill", "Fill an area; it stops at lines (F)")
        tool(g, "pick", "Pick", "Take a colour; right-click takes it as Fill (I)")
        tool(g, "gradient", "Gradient", "Drag across an area: Colour to Fill (G)")
        g = home.group("Shapes")
        tool(g, "line", "Line", "Shift: straight or 45° (L)")
        tool(g, "rect", "Rectangle", "Shift: square")
        tool(g, "ellipse", "Ellipse", "Shift: circle")
        g.row()
        tool(g, "polygon", "Polygon", "Click the corners; double-click or Enter finishes")
        tool(g, "curve", "Curve", "Click points it passes through; double-click or Enter finishes")
        tool(g, "shapes", "Edit", "Pick a shape to move it or drag its points (D)")
        g = home.group("Size")
        sc = tk.Scale(g.cur(), from_=1, to=80, resolution=1, orient="horizontal", variable=self.tools.size, length=96)
        hud.style_scale(sc, bg=hud.PANEL)
        g.place(sc)
        g = home.group("Colours")
        col = tk.Frame(g.cur(), bg=hud.PANEL)
        g.place(col, padx=(0, 8))
        for k, (text, which) in enumerate((("Colour", "colour"), ("Fill", "fill"))):
            sw = tk.Label(col, text="      ", bg=self.tools.colour if which == "colour" else self.tools.fill,
                          cursor="hand2", relief="flat", highlightthickness=1, highlightbackground=hud.LINE2)
            sw.grid(row=0, column=k, padx=2)
            sw.bind("<Button-1>", lambda e, w_=which: self.choose(w_))
            tk.Label(col, text=text, bg=hud.PANEL, fg=hud.DIM, font=ribbon.CAP_FONT).grid(row=1, column=k)
            setattr(self, "sw_colour" if which == "colour" else "sw_fill", sw)
            ribbon.tooltip(sw, "Line, pen and fill colour" if which == "colour" else "Inside shapes; gradient end")
        pal = tk.Frame(g.cur(), bg=hud.PANEL)
        g.place(pal)
        self.pal = pal
        self.fill_palette()
        g.button("Edit Colours…", lambda: self.choose("colour"), "Choose any colour")

        opt = rb.tab("Options")
        g = opt.group("Paint")
        for text, var, a, b, res in (("Opacity", self.tools.opacity, 0.05, 1, 0.05),
                                     ("Fill tolerance", self.tools.tolerance, 0, 200, 1)):
            g.label(text)
            s_ = tk.Scale(g.cur(), from_=a, to=b, resolution=res, orient="horizontal", variable=var, length=110)
            hud.style_scale(s_, bg=hud.PANEL)
            g.place(s_, padx=(0, 10))
        g.row()
        g.check("No Fill Inside Shapes", self.tools.no_fill, self.sync_swatches)
        g = opt.group("Shapes and selection")
        g.button("Apply Colours", self.tools.apply_colours, "Give the picked shape the current colours and size")
        g.button("Put Down", lambda: self.key("Return"), "Place the selection (Enter)")
        g.row()
        g.button("Delete", lambda: self.key("Delete"), "Delete the selection or the picked shape")
        g.button("Clear Picture", self.clear)
        g = opt.group("Colours")
        g.button("Save This Colour", self.save_colour, "Add the current colour to your palette")
        view = rb.tab("View")
        g = view.group("Zoom")
        g.button("Zoom In", lambda: self.set_zoom(1.25), "Mouse wheel")
        g.button("Zoom Out", lambda: self.set_zoom(0.8))
        g.button("Fit", lambda: self.set_zoom(None))
        g = view.group("Picture")
        g.label("Name")
        g.place(tk.Entry(g.cur(), textvariable=self.v_name, width=22, bg=hud.FIELD, fg=hud.TEXT,
                         insertbackground=hud.TEXT, relief="flat", font=hud.SMALL))

        mid = tk.Frame(w, bg=hud.BG)
        mid.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        self.canvas = tk.Canvas(mid, bg="#2a2a31", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side="left", fill="both", expand=True)
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<ButtonPress-1>", lambda e: self.tools.press(e))
        c.bind("<B1-Motion>", lambda e: self.tools.motion(e))
        c.bind("<ButtonRelease-1>", lambda e: self.tools.release(e))
        c.bind("<Double-Button-1>", lambda e: self.tools.double(e))
        c.bind("<ButtonPress-3>", lambda e: self.tools.press(e, right=True))
        c.bind("<MouseWheel>", lambda e: self.set_zoom(1.15 if e.delta > 0 else 1 / 1.15))

        status = tk.Frame(w, bg=hud.BG)
        status.pack(fill="x", padx=10, pady=(4, 0))
        self.msg_lbl = hud.label(status, "", fg=hud.AMBER, font=hud.SMALL, anchor="w")
        self.msg_lbl.pack(side="left", fill="x", expand=True)
        self.size_lbl = hud.label(status, "", fg=hud.DIM, font=hud.SMALL)
        self.size_lbl.pack(side="right")

        bot = tk.Frame(w, bg=hud.BG)
        bot.pack(fill="x", padx=10, pady=8)
        hud.label(bot, "Use the picture:", fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=(0, 6))
        for label, fn in self.outputs:
            hud.Button(bot, label, lambda fn=fn: self.output(fn), kind="red", padx=10, pady=3,
                       font=hud.SMALL).pack(side="left", padx=(0, 4))
        hud.Button(bot, "Save to Library…", self.to_library, padx=10, pady=3, font=hud.SMALL).pack(side="left", padx=4)
        hud.Button(bot, "Close", self.close, padx=10, pady=3, font=hud.SMALL).pack(side="right")

    def fill_palette(self):
        for wd in self.pal.winfo_children():
            wd.destroy()
        cols = paint.PALETTE + [c for c in library.swatches(self.images) if c not in paint.PALETTE]
        for i, col in enumerate(cols[:32]):   # two rows, like Paint's colour grid
            b = tk.Label(self.pal, text="  ", bg=col, cursor="hand2", relief="flat", highlightthickness=1,
                         highlightbackground=hud.LINE2, font=("Segoe UI", 6))
            b.grid(row=i % 2, column=i // 2, padx=1, pady=1)
            b.bind("<Button-1>", lambda e, c=col: self.set_colour("colour", c))
            b.bind("<Button-3>", lambda e, c=col: self.set_colour("fill", c))

    # ================================================================ host interface for the paint tools
    def to_screen(self, x, y):
        z, ox, oy = self.view()
        return ox + x * z, oy + y * z

    def to_model(self, x, y):
        z, ox, oy = self.view()
        return (x - ox) / z, (y - oy) / z

    def view(self):
        cw, ch = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        W, H = self.img.size
        z = self.zoom or min((cw - 30) / W, (ch - 30) / H)
        return z, (cw - W * z) / 2, (ch - H * z) / 2

    def paint_target(self):
        return self.img, self.shapes

    def paint_look(self):
        return paint.flatten(self.img, self.shapes)

    def paint_commit(self, img, shapes, label):
        self.undo_stack.append((self.img, self.shapes))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()
        self.img, self.shapes = img, [dict(s) for s in shapes]
        self.version += 1
        self.redraw()

    def paint_refresh(self):
        self.sync_swatches()
        self.redraw()

    def msg(self, text):
        self.msg_lbl.configure(text=text)

    # ================================================================ drawing
    def redraw(self):
        c = self.canvas
        if not c.winfo_exists():
            return
        c.delete("all")
        live = self.tools.live()
        img, shapes = live if live else (self.img, self.shapes)
        flat = paint.flatten(img, shapes)
        z, ox, oy = self.view()
        W, H = flat.size
        sw, sh = max(1, int(W * z)), max(1, int(H * z))
        shown = paint.checker((W, H), max(4, int(8 / max(z, 0.05))))
        shown.alpha_composite(flat)
        shown = shown.resize((sw, sh), Image.NEAREST if z >= 2 else Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(shown)
        c.create_image(ox, oy, image=self.photo, anchor="nw")
        c.create_rectangle(ox - 1, oy - 1, ox + sw, oy + sh, outline=hud.LINE)
        self.tools.overlay()
        self.size_lbl.configure(text=f"{W} × {H} px · {len(shapes)} shapes · zoom {z * 100:.0f}%")

    def set_zoom(self, k):
        if k is None:
            self.zoom = None
        else:
            self.zoom = max(0.05, min(16.0, self.view()[0] * k))
        self.redraw()

    def set_tool(self, t):
        self.tools.set_tool(t)
        for k, b in self.tool_btns.items():
            b.set_kind("red" if k == t else "normal")
        self.redraw()

    def key(self, name):
        if self.tools.key(name):
            self.redraw()

    # ================================================================ colours
    def choose(self, which):
        cur = self.tools.colour if which == "colour" else self.tools.fill
        col = colorchooser.askcolor(cur, parent=self.win)[1]
        if col:
            self.set_colour(which, col)

    def set_colour(self, which, col):
        if which == "colour":
            self.tools.colour = col
        else:
            self.tools.fill = col
            self.tools.no_fill.set(False)
        self.sync_swatches()

    def sync_swatches(self):
        self.sw_colour.configure(bg=self.tools.colour)
        self.sw_fill.configure(bg=self.tools.fill, text="  ╳   " if self.tools.no_fill.get() else "      ")

    def save_colour(self):
        cols = library.swatches(self.images)
        library.save_swatches(self.images, cols + [self.tools.colour])
        self.fill_palette()
        self.msg(f"Saved {self.tools.colour} with your colours (in the Animation Library folder).")

    # ================================================================ picture commands
    def undo(self):
        self.tools.cancel()
        if self.undo_stack:
            self.redo_stack.append((self.img, self.shapes))
            self.img, self.shapes = self.undo_stack.pop()
            self.version += 1
        self.redraw()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append((self.img, self.shapes))
            self.img, self.shapes = self.redo_stack.pop()
            self.version += 1
        self.redraw()

    def clear(self):
        if messagebox.askyesno("Paint", "Clear the whole picture? (Undo brings it back.)", parent=self.win):
            self.tools.cancel()
            self.paint_commit(Image.new("RGBA", self.img.size, (0, 0, 0, 0)), [], "clear")

    def new_size(self):
        txt = hud.ask_text(self.win, "Picture size", "Width × height in pixels (e.g. 400x300). The picture is kept "
                           "in the top-left corner:", f"{self.img.width}x{self.img.height}")
        if not txt:
            return
        try:
            w, h = (int(float(v)) for v in txt.lower().replace("×", "x").split("x"))
            if not (8 <= w <= 4096 and 8 <= h <= 4096):
                raise ValueError
        except ValueError:
            self.msg("Type it like 400x300 (8 to 4096 pixels).")
            return
        self.tools.finish()
        new = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        new.alpha_composite(self.img.crop((0, 0, min(w, self.img.width), min(h, self.img.height))))
        self.paint_commit(new, self.shapes, "size")

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.win, filetypes=[("Pictures", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")])
        if not path:
            return
        try:
            with Image.open(path) as im:
                src = im.convert("RGBA")
        except OSError as e:
            messagebox.showinfo("Paint", f"It couldn't be opened: {e}", parent=self.win)
            return
        self.tools.import_picture(src)
        self.set_tool("select")

    def result(self):
        """The picture as it is now (anything still lifted is put down first)."""
        self.tools.finish()
        return self.img, [dict(s) for s in self.shapes]

    def empty(self):
        img, shapes = self.result()
        return not shapes and not img.getchannel("A").getbbox()

    def output(self, fn):
        if self.empty():
            self.msg("The picture is empty: draw something first.")
            return
        img, shapes = self.result()
        try:
            done = fn(img, shapes, self.v_name.get().strip() or "Picture")
        except Exception as e:   # the animation side says what went wrong
            messagebox.showinfo("Paint", str(e), parent=self.win)
            return
        self.saved_version = self.version
        if done is not False:
            self.msg("Done. Keep painting, or Close.")

    def to_library(self):
        if self.empty():
            self.msg("The picture is empty: draw something first.")
            return
        import trace_player as tp
        shelf = tp.ask_choice(self.win, "Save to library", "Which shelf of the Animation Library?",
                              ["Pictures", "Props", "Backgrounds", "Cancel"], 0)
        if shelf in (None, 3):
            return
        kind = ["Pictures", "Props", "Backgrounds"][shelf]
        img, shapes = self.result()
        name = self.v_name.get().strip() or "Picture"
        try:
            d = library.save_picture(self.images, img, shapes, name, kind)
        except library.LibraryError as e:
            if "already" in str(e) and messagebox.askyesno("Library", f"{e}\n\nReplace it? (The old one is moved to "
                                                                       "the library's Deleted folder.)", parent=self.win):
                d = library.save_picture(self.images, img, shapes, name, kind, replace=True)
            else:
                return
        self.saved_version = self.version
        self.msg(f"Saved to {d}")

    def close(self):
        if self.version != self.saved_version and not self.empty():
            if not messagebox.askyesno("Paint", "Close without using or saving this picture?", parent=self.win):
                return
        self.win.destroy()
        if self.on_close:
            self.on_close()
