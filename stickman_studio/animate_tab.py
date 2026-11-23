"""05 ANIMATE: the hybrid animation screen (skeleton keys + frame-by-frame drawing + optional rigs) on one timeline.
v3.2 adds the creative tools: paint tools and PAINT…, figures (your own skeletons), attachments, motion paths, the
Animation Library and STORY (branching scenes). The data and maths are in animate.py, paint.py, story.py and
library.py; this file is the screen. No AI."""
import math
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageTk

import animate as A
import creative_dialogs as cd
import hud
import library
import paint
import paint_tools as pt
import story
import trace_io
import trace_player as tp

HEAD_W = 190      # timeline: the track names
ROW = 22
RULER = 20
TOOLS = [("pose", "Pose  Q"), ("build", "Build  J"), ("path", "Path  H"), ("rig", "Rig  R")]
DRAW = ("pen", "brush", "eraser")                       # the original drawing tools
PAINT = tuple(k for k, _, _ in pt.TOOLS if k not in DRAW)   # v3.2: handled by paint_tools
SCENE_COLOURS = ["#e3a23a", "#1e6eff", "#2fb35a", "#d0407c", "#16a5a5", "#9b59d0"]
BONE_COLOURS = ["#e3222b", "#e37a22", "#e3c022", "#8ad022", "#22d05a", "#22d0b4", "#22a0e3", "#2250e3", "#7a22e3",
                "#c822e3", "#e32290"]


class AnimateTab:
    def __init__(self, parent, studio):
        self.s, self.root, self.images = studio, studio.root, studio.images
        self.proj = None
        self.frame = 0
        self.tool = "pose"
        self.active = None            # the track being edited (a character or a layer id)
        self.selected = set()         # characters selected together (group editing)
        self.playing = False
        self.after_id = None
        self.drag = None
        self.cache = {}
        self.rig_sub = "joints"       # in RIG: "joints" (place them) or "bind" (paint which bone owns the drawing)
        self.pt = pt.PaintTools(self)  # v3.2: shapes, fill, gradient, pick, select... (and their colours / size)
        self.colour = "#111111"
        self.size = self.pt.size
        self.bone = None              # v3.2: the picked bone of a figure
        self.attach_mode = None       # v3.2: the track waiting for a click on the joint to attach it to
        self.side_ctx = None
        self.v_shape = tk.StringVar(value="line")
        self.v_pstart, self.v_pend = tk.StringVar(), tk.StringVar()
        self.v_pease, self.v_porient, self.v_pclosed = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        self.v_onion = tk.BooleanVar(value=True)
        self.v_loop = tk.BooleanVar(value=True)
        self.v_lock = tk.BooleanVar(value=True)
        self.v_interp = tk.StringVar(value="smooth")
        self.v_rigging = tk.BooleanVar(value=False)
        self.v_rigmode = tk.StringVar(value="rigid")
        self.v_bone = tk.StringVar(value="frontHand")
        self.v_extra = {g: tk.BooleanVar(value=False) for g in A.EXTRA_GROUPS}   # v3.0 optional joints
        self.v_fps = tk.StringVar(value="12")
        self.v_len = tk.StringVar(value="24")
        self.frame_ui = tk.Frame(parent, bg=hud.BG)
        self.build()
        self.keymap = {}
        for seq, fn in [("<space>", self.toggle_play), ("<Left>", lambda: self.step(-1)),
                        ("<Right>", lambda: self.step(1)), ("<Home>", lambda: self.go(0)),
                        ("<End>", lambda: self.go(self.length() - 1)), ("<k>", self.add_key), ("<K>", self.add_key),
                        ("<q>", lambda: self.set_tool("pose")), ("<p>", lambda: self.set_tool("pen")),
                        ("<b>", lambda: self.set_tool("brush")), ("<e>", lambda: self.set_tool("eraser")),
                        ("<r>", lambda: self.set_tool("rig")), ("<o>", self.toggle_onion), ("<a>", self.select_all),
                        ("<Control-z>", self.undo), ("<Control-y>", self.redo), ("<Control-s>", self.save),
                        ("<bracketleft>", lambda: self.size.set(max(1, self.size.get() - 1))),
                        ("<bracketright>", lambda: self.size.set(min(80, self.size.get() + 1))),
                        ("<Delete>", self.on_delete), ("<j>", lambda: self.set_tool("build")),
                        ("<h>", lambda: self.set_tool("path")), ("<l>", lambda: self.set_tool("line")),
                        ("<f>", lambda: self.set_tool("fill")), ("<g>", lambda: self.set_tool("gradient")),
                        ("<i>", lambda: self.set_tool("pick")), ("<s>", lambda: self.set_tool("select")),
                        ("<d>", lambda: self.set_tool("shapes")), ("<Escape>", self.on_escape),
                        ("<Return>", lambda: self.paint_key("Return")), ("<Control-c>", lambda: self.paint_key("copy")),
                        ("<Control-x>", lambda: self.paint_key("cut")),
                        ("<Control-v>", lambda: self.paint_key("paste"))]:
            self.keymap[seq] = lambda e, fn=fn: None if isinstance(e.widget, (tk.Entry, tk.Spinbox)) else fn()
        self.show_project()

    # ================================================================ layout
    def build(self):
        """v3.3: a ribbon. Home has what a beginner needs (tools, pen, colours, adding things, keys); Draw, Arrange,
        Timeline, View and Advanced hold the rest."""
        import ribbon
        f = self.frame_ui
        rb = self.ribbon = ribbon.Ribbon(f, [
            ("New Animation…", self.new_project), ("Open…", self.open_dialog), ("Save", self.save, "Ctrl+S"), None,
            ("Import Trace…", self.import_dialog), None,
            ("Export…", self.export_dialog), ("Sprite Sheet…", self.sprite_dialog),
            ("Story Web Page…", self.story_dialog), None, ("Library…", self.library_dialog)])
        rb.pack(fill="x", padx=12, pady=(8, 6))
        self.tool_btns = {}

        def tool(g, key, text, tip):
            self.tool_btns[key] = g.button(text, lambda: self.set_tool(key), tip)

        home = rb.tab("Home")
        g = home.group("Tools")
        tool(g, "pose", "Pose", "Drag joints to pose; drag the red root to move; right-drag to turn (Q)")
        tool(g, "build", "Build", "Reshape a figure and grow new bones with Ctrl+drag (J)")
        tool(g, "path", "Path", "Draw a path for the selected track to travel along (H)")
        g = home.group("Draw")
        tool(g, "pen", "Pen", "Draw on the selected drawing layer (P)")
        tool(g, "brush", "Brush", "Soft-edged strokes (B)")
        tool(g, "eraser", "Eraser", "Rub out (E)")
        g = home.group("Colour and size")
        g.label("Colour")
        self.swatch = tk.Label(g.cur(), text="    ", bg=self.colour, cursor="hand2", relief="flat", highlightthickness=1,
                               highlightbackground=hud.LINE2)
        g.place(self.swatch, padx=(0, 8))
        self.swatch.bind("<Button-1>", lambda e: self.pick_colour())
        ribbon.tooltip(self.swatch, "Line, pen and fill-bucket colour")
        g.label("Fill")
        self.fill_swatch = tk.Label(g.cur(), text=" ╳  ", bg=self.pt.fill, cursor="hand2", relief="flat",
                                    highlightthickness=1, highlightbackground=hud.LINE2)
        g.place(self.fill_swatch)
        self.fill_swatch.bind("<Button-1>", lambda e: self.pick_fill())
        ribbon.tooltip(self.fill_swatch, "Colour inside shapes, and the end colour of a gradient")
        g.row()
        g.label("Size")
        sc = tk.Scale(g.cur(), from_=1, to=80, orient="horizontal", variable=self.size, length=110)
        hud.style_scale(sc, bg=hud.PANEL)
        g.place(sc)
        ribbon.tooltip(sc, "Pen and line size ([ and ])")
        g = home.group("Add")
        g.button("Stickman", self.add_stickman, "Add a stickman")
        g.button("Figure", self.add_figure, "Add your own skeleton (bones branch from any joint)")
        g.row()
        g.button("Picture…", self.add_picture, "Add a prop or a background")
        g.button("Layer", self.add_layer, "Add a drawing layer")
        g = home.group("Keyframes")
        g.button("Set Key", self.add_key, "Key the selected characters on this frame (K)", kind="red")
        g.row()
        g.button("Delete Key", self.delete_key, "Remove the key on this frame")
        g = home.group("Create")
        g.button("Paint…", lambda: self.open_paint(), "Paint characters' parts, props and backgrounds")
        g.row()
        g.button("Library…", self.library_dialog, "Your saved characters, props and backgrounds")

        draw = rb.tab("Draw")
        g = draw.group("Shapes")
        for key, text, tip in (("line", "Line", "Shift: straight or 45° (L)"), ("rect", "Rectangle", "Shift: square"),
                               ("ellipse", "Ellipse", "Shift: circle")):
            tool(g, key, text, tip)
        g.row()
        tool(g, "polygon", "Polygon", "Click the corners; double-click or Enter finishes")
        tool(g, "curve", "Curve", "Click points the curve passes through; double-click or Enter finishes")
        g = draw.group("Colour")
        tool(g, "fill", "Fill", "Fill an area with the colour; it stops at lines (F)")
        tool(g, "gradient", "Gradient", "Drag across an area: Colour to Fill (G)")
        g.row()
        tool(g, "pick", "Pick Colour", "Take a colour from the stage; right-click takes it as Fill (I)")
        g = draw.group("Select")
        tool(g, "select", "Select", "Drag a box, then move, resize or turn it (S)")
        tool(g, "lasso", "Lasso", "Draw around what you want to select")
        g.row()
        tool(g, "shapes", "Edit Shapes", "Pick a shape to move it or drag its points (D)")
        g = draw.group("Selection")
        g.button("Flip ↔", lambda: self.paint_cmd("fliph"), "Flip horizontally")
        g.button("Flip ↕", lambda: self.paint_cmd("flipv"), "Flip vertically")
        g.button("Rotate 90°", lambda: self.paint_cmd("turn"))
        g.row()
        g.button("Copy", lambda: self.paint_key("copy"), "Ctrl+C")
        g.button("Cut", lambda: self.paint_key("cut"), "Ctrl+X")
        g.button("Paste", lambda: self.paint_key("paste"), "Ctrl+V")
        g.button("Delete", lambda: self.paint_key("Delete"), "Delete")
        g = draw.group("Options")
        g.check("No Fill", self.pt.no_fill, self.sync_paint_swatches, "Shapes are outlines only")
        g.row()
        g.check("Fill Sees All Layers", self.pt.look_all, None,
                "Fill finds its area in everything you see, e.g. lines drawn on another layer")

        arr = rb.tab("Arrange")
        g = arr.group("Track")
        g.button("Rename…", self.rename)
        g.button("Colour…", self.track_colour, "The character's colour")
        g.button("Delete…", self.delete_track)
        g.row()
        g.button("Bring Forward", lambda: self.restack(1))
        g.button("Send Backward", lambda: self.restack(-1))
        g.button("Flip", self.flip, "Face the other way")
        g = arr.group("Link")
        g.button("Attach To…", self.start_attach, "Follow a joint of another character (a sword in a hand)")
        g.row()
        g.button("Detach", self.detach)
        g = arr.group("Character")
        g.button("Draw on Character", self.owned_layer, "A drawing layer that shows, hides and locks with it")
        g.button("Turn into Figure", self.to_figure, "A copy of the stickman with bones you can add to")
        g.row()
        g.button("Save to Library…", self.save_to_library)
        g = arr.group("Optional joints")
        for grp, text in (("shoulders", "Shoulders"), ("handtips", "Hand Tips"), ("toes", "Toes")):
            g.check(text, self.v_extra[grp], lambda grp=grp: self.extras_changed(grp), "Never required")

        tlt = rb.tab("Timeline")
        g = tlt.group("Frames")
        g.button("Insert", lambda: self.frame_op("insert"), "Insert an empty frame here")
        g.button("Duplicate", lambda: self.frame_op("duplicate"), "Copy this frame after it")
        g.row()
        g.button("Delete", lambda: self.frame_op("delete"), "Delete this frame")
        g = tlt.group("Drawing")
        g.button("Hold −", lambda: self.hold(-1), "Show this drawing one frame less")
        g.button("Hold +", lambda: self.hold(1), "Show this drawing one frame more")
        g.row()
        g.button("Clear Drawing", self.clear_drawing)
        g = tlt.group("Playback")
        for text, var, cmd in (("Frame rate", self.v_fps, self.fps_changed), ("Frames", self.v_len, self.len_changed)):
            g.label(text)
            e = tk.Entry(g.cur(), textvariable=var, width=5, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT,
                         relief="flat", font=hud.SMALL)
            g.place(e, padx=(0, 8))
            e.bind("<Return>", lambda ev, c=cmd: c())
            e.bind("<FocusOut>", lambda ev, c=cmd: c())
        g.row()
        g.check("Loop", self.v_loop, None, "Play again from the start")
        g = tlt.group("In-betweens")
        om = tk.OptionMenu(g.cur(), self.v_interp, *A.INTERP, command=lambda v: self.interp_changed())
        om.configure(bg=hud.FIELD, fg=hud.TEXT, highlightthickness=0, relief="flat", font=hud.SMALL)
        g.place(om)
        ribbon.tooltip(om, "smooth: never overshoots · linear · hold: no in-betweens")
        g = tlt.group("Story")
        g.button("Story…", self.story_dialog, "Scenes, endings and choices (branching stories)")

        view = rb.tab("View")
        g = view.group("Show")
        g.check("Onion Skin", self.v_onion, self.redraw, "The drawings and keys before (red) and after (green) (O)")
        g = view.group("Select")
        g.button("Select All Characters", self.select_all, "A")

        adv = rb.tab("Advanced")
        g = adv.group("Proportions")
        g.check("Lock Proportions", self.v_lock, self.lock_changed, "Bones keep their length (untick, then Ctrl+drag "
                                                                     "to stretch one on purpose)")
        g.row()
        g.button("Reset Proportions", self.reset_props)
        g = adv.group("Drawing-to-skeleton rigging")
        g.check("Enable Rigging", self.v_rigging, self.rigging_changed, "Rig your own drawing to the 12-joint "
                                                                        "skeleton")
        g.row()
        tool(g, "rig", "Rig Tool", "Place joints, bind and edit the artwork of a rigged character (R)")
        g.button("New Rigged Character…", self.add_rigged)

        mid = tk.Frame(f, bg=hud.BG)
        mid.pack(fill="both", expand=True, padx=12)
        outer = hud.panel(mid)   # v3.2: the side panel scrolls (mouse wheel) when it's taller than the screen
        outer.pack(side="left", fill="y")
        self.side_cv = tk.Canvas(outer, bg=hud.PANEL, highlightthickness=0, width=206)
        self.side_cv.pack(side="left", fill="y")
        self.side = tk.Frame(self.side_cv, bg=hud.PANEL, padx=8, pady=8)
        self.side_cv.create_window(0, 0, window=self.side, anchor="nw")
        self.side.bind("<Configure>", lambda e: self.side_cv.configure(scrollregion=self.side_cv.bbox("all")))
        self.build_side()
        self.stage = tk.Canvas(mid, bg="#1a1a1f", highlightthickness=0, cursor="crosshair")
        self.stage.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.stage.bind("<Configure>", lambda e: self.redraw())
        self.stage.bind("<ButtonPress-1>", self.on_press)
        self.stage.bind("<B1-Motion>", self.on_motion)
        self.stage.bind("<ButtonRelease-1>", self.on_release)
        self.stage.bind("<ButtonPress-3>", lambda e: self.on_press(e, right=True))
        self.stage.bind("<Double-Button-1>", self.on_double)
        self.stage.bind("<B3-Motion>", self.on_motion)
        self.stage.bind("<ButtonRelease-3>", self.on_release)

        bar = tk.Frame(f, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=(6, 2))
        for text, cmd in (("|◀", lambda: self.go(0)), ("◀", lambda: self.step(-1))):
            hud.Button(bar, text, cmd, padx=8, pady=1, font=hud.SMALL).pack(side="left", padx=(0, 2))
        self.play_btn = hud.Button(bar, "▶  Play", self.toggle_play, kind="red", padx=12, pady=1, font=hud.SMALL)
        self.play_btn.pack(side="left", padx=2)
        for text, cmd in (("▶", lambda: self.step(1)), ("▶|", lambda: self.go(self.length() - 1))):
            hud.Button(bar, text, cmd, padx=8, pady=1, font=hud.SMALL).pack(side="left", padx=(0, 2))
        self.frame_lbl = hud.label(bar, "", fg=hud.TEXT, font=hud.BOLD)
        self.frame_lbl.pack(side="left", padx=10)
        self.title = hud.label(bar, "", fg=hud.DIM, font=hud.SMALL)   # the animation's name (also in the title bar)
        self.title.pack(side="left", padx=(4, 12))
        self.msg_lbl = hud.label(bar, "", fg=hud.AMBER, font=hud.SMALL, anchor="e")
        self.msg_lbl.pack(side="right", fill="x", expand=True)

        tl = tk.Frame(f, bg=hud.BG)
        tl.pack(fill="x", padx=12, pady=(2, 10))
        self.tl = tk.Canvas(tl, height=170, bg=hud.PANEL, highlightthickness=1, highlightbackground=hud.LINE)
        sb = tk.Scrollbar(tl, orient="vertical", command=self.tl.yview)
        self.tl.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tl.pack(side="left", fill="x", expand=True)
        self.tl.bind("<Configure>", lambda e: self.draw_timeline())
        self.tl.bind("<ButtonPress-1>", self.tl_press)
        self.tl.bind("<B1-Motion>", self.tl_drag)
        self.tl.bind("<Double-Button-1>", self.tl_double)
        self.tl.bind("<MouseWheel>", lambda e: self.tl.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    def btn_row(self, s, items, font=None, pady=1, kinds=()):
        row = tk.Frame(s, bg=hud.PANEL)
        row.pack(fill="x", pady=pady)
        for i, (text, cmd) in enumerate(items):
            hud.Button(row, text, cmd, padx=3, pady=1, font=font or hud.TINY,
                       kind=kinds[i] if i < len(kinds) else "normal").grid(row=0, column=i, sticky="we", padx=1)
            row.columnconfigure(i, weight=1, uniform="b")
        return row

    def context(self):
        c = self.active_char()
        return (self.active, (c or {}).get("kind"), self.bone if c and c["kind"] == "figure" else None,
                bool((c or {}).get("path")), self.tool == "path", self.v_rigging.get(),
                bool(c and self.bone and c["kind"] == "figure" and any(s["id"] == self.bone and s.get("pic")
                                                                     for s in c["figure"]["segs"])))

    def build_side(self):
        for w in self.side.winfo_children():
            w.destroy()
        s = self.side
        c = self.active_char()   # v3.3: the side panel shows the selected track's properties only
        hud.tag(s, "Properties", bg=hud.PANEL).pack(anchor="w")
        if c and self.tool == "path":   # PATH: its settings first
            self.path_section(s, c)
        if c and c["kind"] == "figure":
            self.figure_section(s, c)
        if c and c.get("path") and self.tool != "path":
            self.path_section(s, c)
        if self.v_rigging.get():
            hud.rule(s, pady=6)
            hud.tag(s, "Rig", bg=hud.PANEL).pack(anchor="w", pady=(0, 2))
            for v, t in (("rigid", "Rigid parts"), ("mesh", "Mesh (bends)")):
                tk.Radiobutton(s, text=t, value=v, variable=self.v_rigmode, command=self.rigmode_changed,
                               bg=hud.PANEL, fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.PANEL,
                               font=hud.SMALL).pack(anchor="w")
            for sub, t in (("joints", "Place Joints"), ("bind", "Bind Brush"), ("art", "Edit Artwork")):
                hud.Button(s, t, lambda k=sub: self.set_rig_sub(k), padx=6, pady=1, font=hud.TINY,
                           kind="red" if self.rig_sub == sub else "normal").pack(fill="x", pady=1)
            om = tk.OptionMenu(s, self.v_bone, *A.BONES)
            om.configure(bg=hud.FIELD, fg=hud.TEXT, highlightthickness=0, relief="flat", font=hud.TINY)
            om.pack(fill="x", pady=1)
            hud.Button(s, "Bind to Nearest Bone", self.rebind, padx=6, pady=1, font=hud.TINY).pack(fill="x", pady=1)
            hud.Button(s, "Reset Artwork", self.reset_art, padx=6, pady=1, font=hud.TINY).pack(fill="x", pady=1)
        self.info = hud.label(s, "", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY, justify="left", wraplength=186)
        self.info.pack(anchor="w", pady=(10, 0))
        self.side_ctx = self.context()
        self.wheel(s)

    # ================================================================ state
    def msg(self, text):
        self.msg_lbl.configure(text=text)

    def length(self):
        return self.proj.doc["length"] if self.proj else 1

    def changed(self):
        self.cache.clear()
        self.redraw()
        self.draw_timeline()

    def show_project(self):
        p = self.proj
        self.title.configure(text=(p.doc["name"] if p else "No animation open: File → New Animation… or Open…"))
        if hasattr(self.s, "refresh_titlebar"):
            self.s.refresh_titlebar()
        if p:
            self.v_fps.set(str(p.doc["fps"]))
            self.v_len.set(str(p.doc["length"]))
            self.v_loop.set(p.doc.get("loop", True))
            self.v_rigging.set(p.doc.get("rigging", False))
            if self.active not in p.ids():
                self.active = p.doc["stack"][-1] if p.doc["stack"] else None
        self.selected = {i for i in self.selected if p and i in p.ids()}
        self.frame = min(self.frame, self.length() - 1)
        self.build_side()
        self.sync_track_ui()
        self.set_tool(self.tool)

    def sync_track_ui(self):
        c = self.active_char()
        if c:
            self.v_lock.set(c["lock"])
            self.v_interp.set(c["interp"])
            if c.get("rig"):
                self.v_rigmode.set(c["rig"]["mode"])
        have = set((c or {}).get("extras") or ())
        for g, names in A.EXTRA_GROUPS.items():
            self.v_extra[g].set(bool(have & set(names)))
        if c and c.get("path"):
            p = c["path"]
            self.v_pstart.set(str(p["start"] + 1))
            self.v_pend.set(str(p["end"] + 1))
            self.v_pease.set(p.get("ease", "smooth") == "smooth")
            self.v_porient.set(bool(p.get("orient")))
            self.v_pclosed.set(bool(p.get("closed")))
        if c and c["kind"] == "figure":
            segs = {s["id"]: s for s in c["figure"]["segs"]}
            if self.bone not in segs:
                self.bone = c["figure"]["segs"][-1]["id"] if segs else None
            if self.bone:
                self.v_shape.set(segs[self.bone].get("shape", "line"))
        if self.context() != self.side_ctx:
            self.build_side()

    def extras_changed(self, g):
        """Tick / untick Shoulders, Hand tips or Toes for the picked stickman (or every selected one)."""
        on = self.v_extra[g].get()
        ids = [i for i in self.targets() if self.proj.char(i)["kind"] != "rig"] if self.proj else []
        if not ids:
            self.msg("Pick a stickman first (rigged drawings use the 12 joints).")
            self.sync_track_ui()
            return
        for cid in ids:
            self.proj.set_extras(self.proj.char(cid), g, on)
        self.changed()
        self.msg((f"Added {g} to " if on else f"Removed {g} from ") + ", ".join(self.proj.char(i)["name"] for i in ids)
                 + (": drag the new joints to pose them. Ctrl+Z undoes it." if on else ". Ctrl+Z undoes it."))

    def active_char(self):
        if not self.proj or not self.active:
            return None
        try:
            return self.proj.char(self.active)
        except A.AnimateError:
            return None

    def active_layer(self):
        if not self.proj or not self.active:
            return None
        try:
            return self.proj.layer(self.active)
        except A.AnimateError:
            return None

    def need(self):
        if not self.proj:
            self.msg("Make or open an animation first (New… / Open…).")
            return False
        return True

    # ================================================================ projects
    def new_project(self):
        name = hud.ask_text(self.root, "New animation", "Name of the new animation:", "My animation")
        if not name:
            return
        try:
            self.save_quietly()
            self.proj = A.Project.create(self.images, name)
            self.proj.add_character("Stickman")
            self.proj.undo_stack.clear()
            self.active = self.proj.doc["characters"][0]["id"]
            self.selected = {self.active}
        except (A.AnimateError, OSError) as e:
            messagebox.showinfo("Animate", str(e), parent=self.root)
            return
        self.frame = 0
        self.show_project()
        self.changed()
        self.msg(f"Made {self.proj.folder}")

    def open_dialog(self):
        names = A.list_projects(self.images)
        if not names:
            self.msg("No animations yet: New… makes one.")
            return
        d = self.dialog("Open an animation")
        lb = tk.Listbox(d, bg=hud.FIELD, fg=hud.TEXT, font=hud.FONT, height=min(14, len(names)), width=40,
                        relief="flat", selectbackground=hud.RED)
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True)

        def ok():
            if lb.curselection():
                self.open_project(os.path.join(A.projects_dir(self.images), names[lb.curselection()[0]]))
            d.destroy()

        lb.bind("<Double-Button-1>", lambda e: ok())
        hud.Button(d, "Open", ok, kind="red").pack(anchor="e", pady=(8, 0))

    def open_project(self, folder):
        try:
            p = A.Project.open(folder)
        except A.AnimateError as e:
            messagebox.showinfo("Animate", str(e), parent=self.root)
            return
        self.save_quietly()
        self.proj, self.frame, self.active = p, 0, None
        self.selected = set()
        self.show_project()
        self.changed()
        self.msg(f"Opened {folder}")

    def save(self):
        if not self.need():
            return
        try:
            self.proj.save()
            self.msg(f"Saved {self.proj.folder}")
        except OSError as e:
            messagebox.showinfo("Animate", f"Not Saved: {e}", parent=self.root)

    def save_quietly(self):
        if self.proj and self.proj.changed:
            try:
                self.proj.save()
            except OSError:
                pass

    def dialog(self, title):
        d = tk.Toplevel(self.root, bg=hud.PANEL, padx=16, pady=14)
        d.title(title)
        d.transient(self.root)
        return d

    # ================================================================ tracks
    def after_change(self, text=""):
        self.show_project() if text == "rebuild" else None
        self.changed()
        if text and text != "rebuild":
            self.msg(text)

    def add_stickman(self):
        if not self.need():
            return
        c = self.proj.add_character()
        for k in list(c["keys"]):
            c["keys"] = {self.frame: c["keys"][k]}
        self.active, self.selected = c["id"], {c["id"]}
        self.after_change("rebuild")

    def add_layer(self, owner=None):
        if not self.need():
            return None
        L = self.proj.add_layer(owner=owner)
        if owner:
            L["name"] = A.clean_name(f"{self.proj.char(owner)['name']} drawing")
        self.active = L["id"]
        self.after_change("rebuild")
        return L

    def owned_layer(self):
        c = self.active_char()
        if not c:
            self.msg("Pick a character first: its drawings show and hide and lock with it.")
            return
        self.add_layer(owner=c["id"])
        self.set_tool("pen")

    def add_rigged(self):
        if not self.need():
            return
        L = self.active_layer()
        opts = ["Import a picture…", "Use the drawing on this frame", "Cancel"]
        ch = tp.ask_choice(self.root, "Rigged character",
                           "Rig artwork to the 12-joint skeleton. Your artwork is kept as it is; a copy is bound.\n\n"
                           "Use a picture file, or the drawing of the picked layer on this frame?", opts, 0)
        if ch == 0:
            path = filedialog.askopenfilename(parent=self.root, filetypes=[("Pictures", "*.png *.jpg *.jpeg *.gif")])
            if not path:
                return
            try:
                with Image.open(path) as im:
                    src = im.convert("RGBA")
            except OSError as e:
                messagebox.showinfo("Animate", f"It couldn't be opened: {e}", parent=self.root)
                return
            W, H = self.proj.size
            k = min(0.7 * H / src.height, 0.5 * W / src.width)
            src = src.resize((max(1, int(src.width * k)), max(1, int(src.height * k))), Image.LANCZOS)
            art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            art.alpha_composite(src, ((W - src.width) // 2, int(0.85 * H) - src.height))
        elif ch == 1:
            cel = self.proj.cel_at(L, self.frame) if L else None
            if not cel:
                self.msg("Pick a drawing layer with a drawing on this frame first.")
                return
            art = self.proj.image(f"cel:{cel['img']}").copy()
        else:
            return
        try:
            c = self.proj.make_rig(art)
        except A.AnimateError as e:
            self.msg(str(e))
            return
        if ch == 1:
            L["visible"] = False      # the drawing is now the rig's: its layer is hidden, not deleted
        self.active, self.selected = c["id"], {c["id"]}
        self.rig_sub = "joints"
        self.after_change("rebuild")
        self.set_tool("rig")
        self.msg("Drag the 12 joints onto the drawing, then Bind to Nearest Bone.")

    def rename(self):
        t = self.track()
        if not t:
            return
        name = hud.ask_text(self.root, "Rename", "New name:", t["name"])
        if name:
            try:
                self.proj.snapshot("rename")
                t["name"] = A.clean_name(name)
            except A.AnimateError as e:
                self.msg(str(e))
            self.after_change("rebuild")

    def track(self):
        return self.active_char() or self.active_layer()

    def track_colour(self):
        c = self.active_char()
        if not c:
            self.msg("Colour is a character's colour; for drawing, click the colour box in the tools.")
            return
        col = colorchooser.askcolor(c["colour"], parent=self.root)[1]
        if col:
            self.proj.snapshot("colour")
            c["colour"] = col
            self.after_change()

    def restack(self, d):
        if self.need() and self.active:
            self.proj.restack(self.active, d)
            self.after_change()

    def flip(self):
        c = self.active_char()
        if c and c["kind"] == "figure":   # v3.2: mirrored around its root, pictures too
            self.proj.flip_figure(c)
            self.after_change()
        elif c:
            self.proj.snapshot("flip facing")
            c["facing"] = -c["facing"]
            self.after_change()

    def delete_track(self):
        t = self.track()
        if not t:
            return
        if messagebox.askyesno("Delete", f"Delete “{t['name']}” from this animation?\n\nCtrl+Z brings it back; "
                                         "saved versions stay in the animation's backups folder.", parent=self.root):
            self.proj.remove_track(t["id"])
            self.active = None
            self.after_change("rebuild")

    def toggle_flag(self, tid, flag):
        try:
            t = self.proj.char(tid)
        except A.AnimateError:
            t = self.proj.layer(tid)
        self.proj.snapshot(flag)
        t[flag] = not t[flag]
        self.changed()

    def select_all(self):
        if self.proj:
            self.selected = {c["id"] for c in self.proj.doc["characters"]}
            self.msg(f"{len(self.selected)} characters selected: drag a hip to move them together; K keys them all.")
            self.redraw()
            self.draw_timeline()

    def lock_changed(self):
        c = self.active_char()
        if c:
            self.proj.snapshot("lock proportions")
            c["lock"] = self.v_lock.get()
            self.msg("Proportions locked: bones keep their length." if c["lock"] else
                     "Proportions unlocked: Ctrl+drag a joint to stretch its bone on this key.")

    def interp_changed(self):
        for cid in self.targets():
            self.proj.char(cid)["interp"] = self.v_interp.get()
        self.changed()

    def reset_props(self):
        for cid in self.targets():
            self.proj.snapshot("reset proportions")
            self.proj.reset_proportions(self.proj.char(cid), self.frame)
        self.changed()

    def targets(self):
        """The characters an action applies to: the selection, or the active one."""
        if not self.proj:
            return []
        ids = [c["id"] for c in self.proj.doc["characters"] if c["id"] in self.selected]
        if not ids and self.active_char():
            ids = [self.active]
        return ids

    # ================================================================ keys and frames
    def go(self, f):
        if not self.proj:
            return
        self.settle()
        n = self.length()
        self.frame = (f % n) if self.v_loop.get() else max(0, min(n - 1, f))
        self.redraw()
        self.draw_timeline()

    def step(self, d):
        self.go(self.frame + d)

    def add_key(self):
        ids = [i for i in self.targets() if self.proj.editable(i)]
        if not ids:
            self.msg("Pick an unlocked character to key.")
            return
        self.proj.snapshot("key")
        for cid in ids:
            c = self.proj.char(cid)
            self.proj.set_key(c, self.frame, self.proj.pose_at(c, self.frame))
        self.changed()
        self.msg(f"Key on frame {self.frame + 1} for {len(ids)} character(s).")

    def delete_key(self):
        ids = [i for i in self.targets() if self.proj.editable(i) and self.frame in self.proj.char(i)["keys"]]
        ids = [i for i in ids if len(self.proj.char(i)["keys"]) > 1]
        if not ids:
            self.msg("No key to delete here (a character keeps at least one).")
            return
        self.proj.snapshot("delete key")
        for cid in ids:
            del self.proj.char(cid)["keys"][self.frame]
        self.changed()

    def frame_op(self, op):
        if not self.need():
            return
        if op == "insert":
            self.proj.insert_frames(self.frame)
        elif op == "delete":
            if not self.proj.delete_frame(self.frame):
                return
        else:
            self.proj.duplicate_frame(self.frame)
            self.frame += 1
        self.v_len.set(str(self.length()))
        self.frame = min(self.frame, self.length() - 1)
        self.changed()

    def hold(self, d):
        L = self.active_layer()
        if not L or not self.proj.exposure(L["id"], self.frame, d):
            self.msg("Pick a drawing layer with a drawing on this frame (Hold changes how long it's shown).")
            return
        self.v_len.set(str(self.length()))
        self.changed()

    def clear_drawing(self):
        L = self.active_layer()
        if L:
            self.proj.clear_cel(L["id"], self.frame)
            self.changed()

    def fps_changed(self):
        if not self.proj:
            return
        try:
            v = max(1, min(60, int(float(self.v_fps.get()))))
        except ValueError:
            v = self.proj.doc["fps"]
        if v != self.proj.doc["fps"]:
            self.proj.snapshot("frame rate")
            self.proj.doc["fps"] = v
        self.v_fps.set(str(v))

    def len_changed(self):
        if not self.proj:
            return
        try:
            v = max(1, min(5000, int(float(self.v_len.get()))))
        except ValueError:
            v = self.length()
        if v != self.length():
            self.proj.snapshot("length")
            self.proj.doc["length"] = v
            self.frame = min(self.frame, v - 1)
            self.changed()
        self.v_len.set(str(v))

    def undo(self):
        if self.proj:
            self.pt.cancel()
            label = self.proj.undo()
            self.after_change("rebuild")
            self.msg(f"Undone: {label}" if label else "Nothing to undo.")

    def redo(self):
        if self.proj:
            self.pt.cancel()
            label = self.proj.redo()
            self.after_change("rebuild")
            self.msg(f"Redone: {label}" if label else "Nothing to redo.")

    # ================================================================ playback
    def toggle_play(self):
        if not self.proj:
            return
        self.playing = not self.playing
        self.play_btn.configure(text="Pause  Space" if self.playing else "Play  Space")
        if self.playing:
            self.tick()
        elif self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
            self.redraw()

    def pause(self):
        if self.playing:
            self.toggle_play()

    def tick(self):
        if not self.playing or not self.proj:
            return
        n = self.length()
        if self.frame + 1 >= n and not self.v_loop.get():
            self.toggle_play()
            return
        self.frame = (self.frame + 1) % n
        self.redraw()
        self.draw_timeline()
        self.after_id = self.root.after(max(10, int(1000 / self.proj.doc["fps"])), self.tick)

    # ================================================================ the stage
    def view(self):
        W, H = self.proj.size
        cw, ch = max(10, self.stage.winfo_width()), max(10, self.stage.winfo_height())
        z = min((cw - 20) / W, (ch - 20) / H)
        return z, (cw - W * z) / 2, (ch - H * z) / 2

    def to_stage(self, x, y):
        z, ox, oy = self.view()
        return (x - ox) / z, (y - oy) / z

    def to_screen(self, x, y):
        z, ox, oy = self.view()
        return x * z + ox, y * z + oy

    def redraw(self):
        c = self.stage
        c.delete("all")
        if not self.proj:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, fill=hud.DIM, font=hud.TITLE, justify="center",
                          text="No animation open\n\nFile → New Animation… starts one, File → Open… opens one,\n"
                               "and File → Import Trace… brings in a traced move.")
            self.frame_lbl.configure(text="")
            return
        z, ox, oy = self.view()
        rig = self.tool == "rig" and self.active_char() and self.active_char().get("rig")
        live = self.pt.live() if self.tool in PAINT else None
        rep = {self.active: paint.flatten(*live)} if live and self.active_layer() else None
        key = (self.frame, round(z, 4), self.proj.version, self.v_onion.get(), self.active, bool(rig),
               self.pt.version if rep else None)
        if key not in self.cache:
            onion = self.active if (self.v_onion.get() and self.active_layer() and not self.playing) else None
            img = A.render(self.proj, self.frame, onion=onion, skip={self.active} if rig else (), replace=rep)
            W, H = self.proj.size
            if rig:
                ac = self.active_char()
                art = self.proj.image(f"art:{ac['id']}")
                img.alpha_composite(art)
                m = self.proj.image(f"map:{ac['id']}")
                if m is not None and ac["rig"].get("bound"):
                    tint = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    for i, col in enumerate(BONE_COLOURS, 1):
                        rgb = tuple(int(col[k:k + 2], 16) for k in (1, 3, 5))
                        tint.paste(rgb + (110,), (0, 0), m.point(lambda v, i=i: 255 if v == i else 0))
                    img.alpha_composite(tint)
            img = img.resize((max(1, int(W * z)), max(1, int(H * z))), Image.BILINEAR)
            if len(self.cache) > 300:
                self.cache.clear()
            self.cache[key] = ImageTk.PhotoImage(img)
        c.create_image(ox, oy, image=self.cache[key], anchor="nw")
        self.frame_lbl.configure(text=f"Frame {self.frame + 1} / {self.length()}")
        if self.playing:
            return
        if rig:
            self.draw_rig_handles()
        elif self.tool in ("pose", "build", "path"):
            self.draw_handles()
        ac = self.active_char()
        if ac and (ac.get("path") or self.tool == "path") and self.proj.shown(ac["id"]):
            self.draw_path(ac)
        if self.tool in PAINT:
            self.pt.overlay()
        self.update_info()

    def draw_handles(self):
        p = self.proj
        if self.v_onion.get() and self.active_char():   # skeleton onion: the keys before and after
            ac = self.active_char()
            ks = sorted(ac["keys"])
            for f, col in ((max([k for k in ks if k < self.frame], default=None), "#e3222b"),
                           (min([k for k in ks if k > self.frame], default=None), "#2fb35a")):
                if f is not None:
                    P = p.points_at(ac, f)
                    for a, b in A.limbs(ac, P):
                        self.stage.create_line(*self.to_screen(*P[a]), *self.to_screen(*P[b]), fill=col,
                                               dash=(3, 3))
        for ch in p.doc["characters"]:
            if not p.shown(ch["id"]):
                continue
            P = p.points_at(ch, self.frame)
            act = ch["id"] == self.active
            sel = ch["id"] in self.selected
            col = ch["colour"] if p.editable(ch["id"]) else hud.FAINT
            if sel or ch["kind"] == "figure":   # a figure's bones always show (some may be invisible "none")
                for a, b in A.limbs(ch, P):
                    pick = act and ch["kind"] == "figure" and b == self.bone
                    self.stage.create_line(*self.to_screen(*P[a]), *self.to_screen(*P[b]),
                                           fill=hud.AMBER if sel or pick else col, width=3 if pick else 1,
                                           dash=() if sel or pick else (2, 3))
            if ch.get("attach"):
                x, y = self.to_screen(*P["hip"])
                self.stage.create_text(x + 10, y + 10, text="⛓", fill=hud.AMBER, font=hud.SMALL)
            for n in P:   # the 12, and any optional joints (smaller squares)
                x, y = self.to_screen(*P[n])
                r = ((7 if n == "hip" else 5) if act else 3) - (1 if n in A.EXTRAS else 0)
                make = self.stage.create_rectangle if n in A.EXTRAS else self.stage.create_oval
                make(x - r, y - r, x + r, y + r, fill=hud.RED if n == "hip" else "white", outline=col, width=2)
            if self.frame in ch["keys"] and (act or sel):
                top = P["head"] if "head" in P else min(P.values(), key=lambda v: v[1])   # a figure: its top joint
                x, y = self.to_screen(*top)
                self.stage.create_text(x, y - 26, text="◆ Key", fill=hud.AMBER, font=hud.TINY)

    def draw_rig_handles(self):
        c = self.active_char()
        R = c["rig"]["rest"]
        for j in A.BONES:
            self.stage.create_line(*self.to_screen(*R[A.PARENT[j]]), *self.to_screen(*R[j]),
                                   fill=BONE_COLOURS[A.BONES.index(j)], width=3)
        for n in A.ORDER:
            x, y = self.to_screen(*R[n])
            self.stage.create_oval(x - 6, y - 6, x + 6, y + 6, fill="white", outline=hud.RED, width=2)
            self.stage.create_text(x + 9, y, text=n, anchor="w", fill=hud.TEXT, font=hud.TINY)

    def update_info(self):
        t = self.track()
        if not t:
            self.info.configure(text="")
            return
        c = self.active_char()
        if c:
            kind = (f"figure · {len(c['figure']['segs'])} bones" if c["kind"] == "figure" else
                    "rigged drawing" if c["kind"] == "rig" else "stickman")
            txt = (f"{c['name']}\n{kind} · {len(c['keys'])} keys\n"
                   f"proportions {'locked' if c['lock'] else 'UNLOCKED'} · {c['interp']}\n"
                   f"{len(self.selected)} selected\n")
            if c.get("attach"):
                try:
                    to = self.proj.char(c["attach"]["to"])["name"]
                except A.AnimateError:
                    to = "?"
                j = c["attach"]["joint"]
                txt += f"⛓ attached to {to} ({'root' if j == 'hip' else j})\n"
            if c.get("path"):
                txt += f"travels along its path, frames {c['path']['start'] + 1}–{c['path']['end'] + 1}\n"
            if self.tool == "build":
                txt += ("\nBuild: drag a joint to reshape (the bone keeps that length everywhere). Ctrl+drag from "
                        "any joint grows a new bone. Click a joint to pick its bone, then set its look below.")
            elif self.tool == "path":
                txt += ("\nPath: drag on the stage to draw the path. Then drag its points; Ctrl+click adds a "
                        "point, right-click removes one, Shift+drag draws a new one.")
            else:
                txt += ("\nDrag a joint to turn its bone; drag the red root to move; right-drag turns the whole "
                        "body. Ctrl+drag stretches (proportions unlocked).")
        else:
            cel = self.proj.cel_at(t, self.frame)
            txt = (f"{t['name']}\ndrawing layer · {len(t['cels'])} drawings\n"
                   + (f"this drawing: frames {cel['start'] + 1}–{cel['start'] + cel['len']}" if cel else
                      "no drawing on this frame") + "\n\nPen / Brush / Eraser draw here. Hold ± sets how long a "
                                                    "drawing stays. Onion shows the frames around it.")
        self.info.configure(text=txt)

    # ---- mouse on the stage
    def hit(self, x, y, chars):
        best, bd = None, 12.0
        for ch in chars:
            P = self.proj.points_at(ch, self.frame)
            for n in P:
                sx, sy = self.to_screen(*P[n])
                d = math.hypot(sx - x, sy - y) - (2 if ch["id"] == self.active else 0)
                if d < bd:
                    best, bd = (ch, n), d
        return best

    def on_press(self, e, right=False):
        if not self.proj or self.playing:
            return
        self.stage.focus_set()
        sx, sy = self.to_stage(e.x, e.y)
        ctrl = bool(e.state & 0x0004)
        if self.attach_mode:
            return self.finish_attach(e)
        if self.tool in PAINT:   # v3.2: the paint tools
            if right and self.tool != "pick":
                return
            if self.tool != "pick" and not self.paint_layer():
                return
            return self.pt.press(e, right)
        if self.tool == "build":
            return self.build_press(e, sx, sy, right, ctrl)
        if self.tool == "path":
            return self.path_press(e, sx, sy, right, ctrl)
        if self.tool == "rig":
            return self.rig_press(e, sx, sy)
        if self.tool in ("pen", "brush", "eraser"):
            L = self.drawing_layer()
            if not L:
                return
            if not self.proj.editable(L["id"]):
                self.msg("That layer (or its character) is locked.")
                return
            self.drag = {"kind": "draw", "layer": L["id"], "pts": [(sx, sy)], "last": (e.x, e.y)}
            return
        chars = [c for c in self.proj.doc["characters"] if self.proj.shown(c["id"])]
        h = self.hit(e.x, e.y, chars)
        if not h:
            if not ctrl:
                self.selected = {self.active} if self.active_char() else set()
            self.redraw()
            return
        ch, joint = h
        if ch["kind"] == "figure" and joint != A.ROOT:
            self.bone = joint
        if ctrl and not right:
            self.selected ^= {ch["id"]}
            self.active = ch["id"]
            self.sync_track_ui()
            self.redraw()
            self.draw_timeline()
            if ch["id"] not in self.selected:
                return
        elif ch["id"] not in self.selected:
            self.selected = {ch["id"]}
        self.active = ch["id"]
        self.sync_track_ui()
        if not self.proj.editable(ch["id"]):
            self.msg(f"{ch['name']} is locked.")
            return
        group = joint == "hip" and len(self.selected) > 1 and not right
        self.proj.snapshot("group move" if group else "pose")
        self.drag = {"kind": "turn" if right else ("group" if group else "pose"), "char": ch["id"], "joint": joint,
                     "start": (sx, sy), "last": (sx, sy), "stretch": ctrl and joint != "hip"}

    def on_motion(self, e):
        if self.tool in PAINT:
            return self.pt.motion(e)
        d = self.drag
        if not d:
            return
        sx, sy = self.to_stage(e.x, e.y)
        if d["kind"] in ("build", "grow", "pathpt", "pathdraw"):
            return self.creative_motion(e, d, sx, sy)
        if d["kind"] == "draw":
            d["pts"].append((sx, sy))
            z = self.view()[0]
            col = "#f3f3f3" if self.tool == "eraser" else self.colour
            self.stage.create_line(*d["last"], e.x, e.y, fill=col, width=max(1, self.size.get() * z),
                                   capstyle="round")
            d["last"] = (e.x, e.y)
            return
        if d["kind"] in ("rigjoint", "bind", "art"):
            return self.rig_motion(e, sx, sy)
        c = self.proj.char(d["char"])
        try:
            if d["kind"] == "turn":
                self.proj.turn_body(c, self.frame, sx, sy, *d["last"])
            elif d["kind"] == "group":
                ids = [i for i in self.selected if self.proj.editable(i)]
                self.proj.move_chars(ids, self.frame, sx - d["last"][0], sy - d["last"][1])
            else:
                self.proj.drag_joint(c, self.frame, d["joint"], sx, sy, stretch=d["stretch"])
        except A.AnimateError as err:
            self.msg(str(err))
            d["stretch"] = False
            return
        d["last"] = (sx, sy)
        self.proj.touch()
        self.redraw()

    def on_release(self, e):
        if self.tool in PAINT:
            return self.pt.release(e)
        d, self.drag = self.drag, None
        if not d:
            return
        if d["kind"] in ("build", "grow", "pathpt", "pathdraw"):
            self.creative_release(d)
        if d["kind"] == "draw":
            try:
                self.proj.stroke(d["layer"], self.frame, d["pts"], self.tool, self.colour, self.size.get())
            except A.AnimateError as err:
                self.msg(str(err))
        elif d["kind"] in ("rigjoint", "bind", "art"):
            self.rig_release(d)
        self.changed()

    def drawing_layer(self):
        """The layer the pen draws on: the picked layer, else the picked character's own layer (made if needed)."""
        L = self.active_layer()
        if L:
            return L
        c = self.active_char()
        if c:
            own = [x for x in self.proj.doc["layers"] if x["owner"] == c["id"]]
            if own:
                self.active = own[-1]["id"]
                return own[-1]
            return self.add_layer(owner=c["id"])
        if self.proj.doc["layers"]:
            self.active = self.proj.doc["layers"][-1]["id"]
            return self.proj.doc["layers"][-1]
        return self.add_layer()

    # ---- rigging
    def rig_press(self, e, sx, sy):
        c = self.active_char()
        if not c or not c.get("rig"):
            self.msg("Pick a rigged character (New Rigged Character… makes one).")
            return
        if self.rig_sub == "joints":
            R = c["rig"]["rest"]
            best = min(A.ORDER, key=lambda n: math.dist(self.to_screen(*R[n]), (e.x, e.y)))
            if math.dist(self.to_screen(*R[best]), (e.x, e.y)) > 14:
                return
            self.proj.snapshot("place a joint")
            self.drag = {"kind": "rigjoint", "joint": best}
        elif self.rig_sub == "bind":
            if not c["rig"].get("bound"):
                self.msg("Bind to Nearest Bone first, then touch it up with the bind brush.")
                return
            self.proj.snapshot("bind brush", [f"map:{c['id']}"])
            self.drag = {"kind": "bind", "pts": [(sx, sy)]}
        else:
            self.drag = {"kind": "art", "pts": [(sx, sy)], "last": (e.x, e.y)}

    def rig_motion(self, e, sx, sy):
        d, c = self.drag, self.active_char()
        if d["kind"] == "rigjoint":
            c["rig"]["rest"][d["joint"]] = [sx, sy]
            self.redraw()
        else:
            d["pts"].append((sx, sy))
            z = self.view()[0]
            col = BONE_COLOURS[A.BONES.index(self.v_bone.get())] if d["kind"] == "bind" else self.colour
            self.stage.create_line(*self.to_screen(*d["pts"][-2]), e.x, e.y, fill=col,
                                   width=max(1, self.size.get() * z), capstyle="round")

    def rig_release(self, d):
        c = self.active_char()
        if d["kind"] == "rigjoint":
            self.proj.set_rest(c, c["rig"]["rest"])
            if c["rig"].get("bound") and not c["rig"].get("painted"):
                self.proj.bind(c)
        elif d["kind"] == "bind":
            self.proj.paint_bind(c, self.v_bone.get(), d["pts"], self.size.get())
            c["rig"]["painted"] = True
        else:
            tool = self.tool_for_art()
            self.proj.stroke_art(c["id"], d["pts"], tool, self.colour, self.size.get())
            if c["rig"].get("bound") and not c["rig"].get("painted"):
                self.proj.bind(c)

    def tool_for_art(self):
        return "eraser" if self.prev_draw_tool == "eraser" else self.prev_draw_tool or "pen"

    def set_rig_sub(self, sub):
        self.rig_sub = sub
        self.build_side()
        self.set_tool("rig")
        self.msg({"joints": "Drag each joint onto the drawing.",
                  "bind": f"Paint the parts that belong to {self.v_bone.get()} (pick the bone below).",
                  "art": "Draw on the working artwork (pen; the last draw tool you used). The original is kept."}[sub])

    def rebind(self):
        c = self.active_char()
        if not c or not c.get("rig"):
            self.msg("Pick a rigged character.")
            return
        self.proj.snapshot("bind", [f"map:{c['id']}"])
        self.proj.bind(c)
        c["rig"]["painted"] = False
        self.changed()
        self.msg("Bound: every part follows its nearest bone. Pose (Q) to animate it.")

    def reset_art(self):
        c = self.active_char()
        if c and c.get("rig"):
            self.proj.snapshot("reset the artwork", [f"art:{c['id']}"])
            self.proj.set_image(f"art:{c['id']}", self.proj.image(f"orig:{c['id']}").copy())
            if c["rig"].get("bound"):
                self.proj.bind(c)
            self.changed()

    def rigmode_changed(self):
        c = self.active_char()
        if c and c.get("rig"):
            self.proj.snapshot("rig mode")
            c["rig"]["mode"] = self.v_rigmode.get()
            self.changed()

    def rigging_changed(self):
        if self.proj:
            self.proj.doc["rigging"] = self.v_rigging.get()
            self.proj.touch()
        if not self.v_rigging.get() and self.tool == "rig":
            self.tool = "pose"
        self.build_side()
        self.set_tool(self.tool)

    # ================================================================ tools
    prev_draw_tool = "pen"

    def set_tool(self, tool):
        if tool == "rig" and not self.v_rigging.get():
            self.msg("Turn on Enable Rigging (Advanced tab) to use the Rig tool.")
            tool = "pose"
        if tool != self.tool:
            self.settle()
        if tool in ("pen", "brush", "eraser"):
            self.prev_draw_tool = tool
        if tool in pt.NAMES:
            self.pt.set_tool(tool)
        elif tool == "build":
            self.msg("Build: drag a figure's joint to reshape it; Ctrl+drag from a joint grows a new bone.")
        elif tool == "path":
            self.msg("Path: drag on the stage to draw the path the picked track travels along.")
        self.tool = tool
        for k, b in self.tool_btns.items():
            b.set_kind("red" if k == tool else "normal")
            if k == "rig":
                b.configure(fg=hud.TEXT if self.v_rigging.get() else hud.FAINT)
        self.cache.clear()
        if self.proj and self.context() != self.side_ctx:
            self.build_side()
        self.redraw()

    def pick_colour(self):
        col = colorchooser.askcolor(self.colour, parent=self.root)[1]
        if col:
            self.colour = col
            self.swatch.configure(bg=col)
            if self.pt.shape_i is not None:
                self.pt.apply_colours()

    def pick_fill(self):
        col = colorchooser.askcolor(self.pt.fill, parent=self.root)[1]
        if col:
            self.pt.fill = col
            self.pt.no_fill.set(False)
            self.sync_paint_swatches()

    def sync_paint_swatches(self):
        self.swatch.configure(bg=self.colour)
        self.fill_swatch.configure(bg=self.pt.fill, text=" ╳  " if self.pt.no_fill.get() else "    ")

    def toggle_onion(self):
        self.v_onion.set(not self.v_onion.get())
        self.redraw()

    # ================================================================ timeline
    def rows(self):
        p = self.proj
        out = []
        if not p:
            return out
        owned = {}
        for L in p.doc["layers"]:
            if L["owner"]:
                owned.setdefault(L["owner"], []).append(L)
        for tid in reversed(p.doc["stack"]):
            try:
                c = p.char(tid)
            except A.AnimateError:
                L = p.layer(tid)
                if not L["owner"] or L["owner"] not in p.ids():
                    out.append(("layer", L, 0))
                continue
            out.append(("char", c, 0))
            for L in sorted(owned.get(tid, []), key=lambda x: -p.doc["stack"].index(x["id"])):
                out.append(("layer", L, 1))
        return out

    def cell(self):
        n = self.length()
        return max(4.0, min(22.0, (self.tl.winfo_width() - HEAD_W - 10) / max(1, n)))

    def draw_timeline(self):
        t = self.tl
        t.delete("all")
        if not self.proj:
            return
        w, cw, n = t.winfo_width(), self.cell(), self.length()
        rows = self.rows()
        H = RULER + ROW * max(1, len(rows)) + 4
        t.configure(scrollregion=(0, 0, w, H))
        step = 1 if cw >= 14 else 5 if cw >= 5 else 10
        for f in range(n):
            x = HEAD_W + f * cw
            if f % step == 0:
                t.create_text(x + 2, 10, text=str(f + 1), anchor="w", fill=hud.DIM, font=hud.TINY)
            t.create_line(x, RULER, x, H, fill=hud.LINE if f % 5 else hud.LINE2 if hasattr(hud, "LINE2") else hud.LINE)
        scs = story.scenes(self.proj)   # v3.2: the story's scenes as coloured bands under the frame numbers
        for i, s in enumerate(scs):
            col = SCENE_COLOURS[i % len(SCENE_COLOURS)]
            t.create_rectangle(HEAD_W + s["start"] * cw + 1, RULER - 5, HEAD_W + (s["end"] + 1) * cw - 1, RULER - 1,
                               fill=col, outline="")
        if scs:
            t.create_text(6, 10, text=f"Story · {len(scs)} scenes", anchor="w", fill=hud.AMBER, font=hud.TINY)
        for i, (kind, tr, indent) in enumerate(rows):
            y = RULER + i * ROW
            act = tr["id"] == self.active
            if act:
                t.create_rectangle(0, y, w, y + ROW, fill=hud.RED_BG, outline="")
            eye = "◉" if tr["visible"] else "○"
            lock = "🔒" if tr["locked"] else "·"
            t.create_text(8, y + ROW / 2, text=eye, fill=hud.TEXT, font=hud.SMALL, anchor="w", tags=("eye", tr["id"]))
            t.create_text(26, y + ROW / 2, text=lock, fill=hud.AMBER if tr["locked"] else hud.FAINT, font=hud.SMALL,
                          anchor="w", tags=("lock", tr["id"]))
            name = tr["name"] if kind == "layer" else f"{'✦' if tr['kind'] == 'figure' else '■'} {tr['name']}"
            sel = kind == "char" and tr["id"] in self.selected
            t.create_text(46 + indent * 14, y + ROW / 2, text=name[:22], anchor="w", font=hud.SMALL,
                          fill=(tr["colour"] if kind == "char" and tr["colour"].lower() not in ("#111111", "#000000")
                                else hud.TEXT) if not sel else hud.AMBER)
            if kind == "char":
                ks = sorted(tr["keys"])
                if len(ks) > 1:
                    t.create_line(HEAD_W + ks[0] * cw + cw / 2, y + ROW / 2, HEAD_W + ks[-1] * cw + cw / 2,
                                  y + ROW / 2, fill=hud.FAINT)
                for f in ks:
                    cx, cy, r = HEAD_W + f * cw + cw / 2, y + ROW / 2, min(6, cw / 2)
                    t.create_polygon(cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy, fill=hud.AMBER, outline="")
            else:
                for c in tr["cels"]:
                    x0 = HEAD_W + c["start"] * cw
                    t.create_rectangle(x0 + 1, y + 4, x0 + c["len"] * cw - 1, y + ROW - 4, fill="#3a6fd0",
                                       outline="#9fc0ff")
            t.create_line(0, y + ROW, w, y + ROW, fill=hud.LINE)
        x = HEAD_W + self.frame * cw
        t.create_rectangle(x, 0, x + cw, RULER, fill=hud.RED, outline="")
        t.create_line(x + cw / 2, RULER, x + cw / 2, H, fill=hud.RED, width=2)
        t.create_line(HEAD_W, 0, HEAD_W, H, fill=hud.LINE)

    def tl_at(self, e):
        y = self.tl.canvasy(e.y)
        i = int((y - RULER) // ROW)
        rows = self.rows()
        row = rows[i] if 0 <= i < len(rows) and y >= RULER else None
        f = int((e.x - HEAD_W) // self.cell()) if e.x >= HEAD_W else None
        return row, f

    def tl_press(self, e):
        if not self.proj:
            return
        self.settle()
        row, f = self.tl_at(e)
        if row and e.x < HEAD_W:
            kind, tr, _ = row
            if e.x < 22:
                return self.toggle_flag(tr["id"], "visible")
            if e.x < 42:
                return self.toggle_flag(tr["id"], "locked")
            if kind == "char" and e.state & 0x0004:
                self.selected ^= {tr["id"]}
            elif kind == "char":
                self.selected = {tr["id"]}
            self.active = tr["id"]
            self.sync_track_ui()
            self.redraw()
            self.draw_timeline()
            return
        if row:
            self.active = row[1]["id"]
            if row[0] == "char" and not (e.state & 0x0004):
                self.selected = {row[1]["id"]}
            self.sync_track_ui()
        if f is not None:
            self.go(max(0, min(self.length() - 1, f)))

    def tl_drag(self, e):
        if self.proj and e.x >= HEAD_W:
            self.go(max(0, min(self.length() - 1, int((e.x - HEAD_W) // self.cell()))))

    def tl_double(self, e):
        row, _ = self.tl_at(e)
        if row and 42 <= e.x < HEAD_W:
            self.active = row[1]["id"]
            self.rename()

    # ================================================================ TRACE import and export
    def import_dialog(self):
        if not self.need():
            return
        moves = A.traced_moves(self.images)
        if not moves:
            self.msg("No traced moves in Images yet.")
            return
        import characters as chars
        d = self.dialog("Import a Trace move")
        hud.label(d, "Pick a traced move. Its files are only read: the points are copied into this animation.",
                  bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(anchor="w")
        lb = tk.Listbox(d, bg=hud.FIELD, fg=hud.TEXT, font=hud.FONT, height=min(12, len(moves)), width=44,
                        relief="flat", selectbackground=hud.RED, exportselection=False)
        for m in moves:
            lb.insert("end", os.path.basename(m))
        lb.pack(fill="both", expand=True, pady=6)
        box = tk.Frame(d, bg=hud.PANEL)
        box.pack(fill="x")
        cvars = {}
        v_fixed, v_exact = tk.BooleanVar(value=False), tk.BooleanVar(value=False)

        def pick(_=None):
            for w in box.winfo_children():
                w.destroy()
            cvars.clear()
            if not lb.curselection():
                return
            for c in chars.list_characters(moves[lb.curselection()[0]]):
                v = tk.BooleanVar(value=True)
                cvars[c["id"]] = v
                tk.Checkbutton(box, text=c["name"], variable=v, bg=hud.PANEL, fg=hud.TEXT, selectcolor=hud.FIELD,
                               activebackground=hud.PANEL, font=hud.SMALL).pack(anchor="w")

        lb.bind("<<ListboxSelect>>", pick)
        for text, var in (("Use the fixed trace where there is one", v_fixed),
                          ("Keep every traced bone length (unticked: steady proportions, no wobble)", v_exact)):
            tk.Checkbutton(d, text=text, variable=var, bg=hud.PANEL, fg=hud.TEXT, selectcolor=hud.FIELD,
                           activebackground=hud.PANEL, font=hud.SMALL).pack(anchor="w")

        def ok():
            if not lb.curselection():
                return
            ids = [i for i, v in cvars.items() if v.get()]
            try:
                made = A.import_trace(self.proj, moves[lb.curselection()[0]], ids, v_fixed.get(), v_exact.get())
            except A.AnimateError as e:
                messagebox.showinfo("Import", str(e), parent=d)
                return
            d.destroy()
            self.selected = {c["id"] for c in made}
            self.active = made[0]["id"]
            self.after_change("rebuild")
            self.msg(f"Imported {len(made)} character(s): {', '.join(c['name'] for c in made)}.")

        hud.Button(d, "Import", ok, kind="red").pack(anchor="e", pady=(8, 0))

    def export_dialog(self):
        if not self.need():
            return
        d = self.dialog("Export the animation")
        flags = {k: tk.BooleanVar(value=v) for k, v in (("png", True), ("gif", True), ("mp4", True),
                                                         ("transparent", False), ("trace", False))}
        for k, text in (("png", "PNG frames"), ("gif", "Looping GIF"), ("mp4", "MP4 video"),
                        ("transparent", "See-through background (PNG and GIF; a video keeps the paper)"),
                        ("trace", "As a new move in Images (for Trace, Review and Game Settings)")):
            tk.Checkbutton(d, text=text, variable=flags[k], bg=hud.PANEL, fg=hud.TEXT, selectcolor=hud.FIELD,
                           activebackground=hud.PANEL, font=hud.SMALL).pack(anchor="w")
        hud.label(d, "Characters for the new move:", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL).pack(anchor="w",
                                                                                                 pady=(6, 0))
        cvars = {}
        for c in self.proj.doc["characters"]:
            if c["kind"] == "figure":   # v3.2: figures have their own bones, not the 12 joints
                continue
            cvars[c["id"]] = tk.BooleanVar(value=c["id"] in self.selected or not self.selected)
            tk.Checkbutton(d, text=c["name"], variable=cvars[c["id"]], bg=hud.PANEL, fg=hud.TEXT,
                           selectcolor=hud.FIELD, activebackground=hud.PANEL, font=hud.SMALL).pack(anchor="w")

        def ok():
            out = []
            try:
                self.proj.save()
                kinds = [k for k in ("png", "gif", "mp4") if flags[k].get()]
                if kinds:
                    out.append(A.export(self.proj, os.path.join(os.path.dirname(self.images), "Exports"), kinds,
                                        flags["transparent"].get()))
                if flags["trace"].get():
                    ids = [c["id"] for c in self.proj.doc["characters"] if c["id"] in cvars and cvars[c["id"]].get()]
                    out.append(A.export_trace(self.proj, self.images, ids))
                    self.s.home.refresh_list()
            except (A.AnimateError, OSError) as e:
                messagebox.showinfo("Export", str(e), parent=d)
                return
            d.destroy()
            if out:
                messagebox.showinfo("Export", "Saved:\n\n" + "\n".join(out), parent=self.root)

        hud.Button(d, "Export", ok, kind="red").pack(anchor="e", pady=(8, 0))

    def sprite_dialog(self):
        """SPRITE SHEET… (v3.0): this animation as sprite sheets (it's saved first, the window reads the saved file)."""
        from spritesheet_dialog import SpriteSheetDialog
        if self.proj:
            self.save()
        return SpriteSheetDialog(self.root, self.images, "animate", self.proj.folder if self.proj else None)

    # ================================================================ v3.2: creative tools
    @property
    def colour(self):
        return self.pt.colour

    @colour.setter
    def colour(self, v):
        self.pt.colour = v

    @property
    def canvas(self):
        return self.stage

    def to_model(self, x, y):
        return self.to_stage(x, y)

    def wheel(self, w):
        w.bind("<MouseWheel>", lambda e: self.side_cv.yview_scroll(-1 if e.delta > 0 else 1, "units"), add="+")
        for ch in w.winfo_children():
            self.wheel(ch)

    # ---- the paint tools draw on the picked drawing layer, on this frame
    def paint_layer(self):
        if not self.need():
            return None
        L = self.drawing_layer()
        if L and not self.proj.editable(L["id"]):
            self.msg("That layer (or its character) is locked.")
            return None
        return L

    def paint_target(self):
        L = self.paint_layer()
        if not L:
            return None
        cel = self.proj.cel_at(L, self.frame)
        if cel:
            return self.proj.image(f"cel:{cel['img']}"), list(cel.get("shapes") or [])
        return Image.new("RGBA", self.proj.size, (0, 0, 0, 0)), []

    def paint_commit(self, img, shapes, label):
        L = self.paint_layer()
        if not L:
            return
        try:
            self.proj.set_cel_content(L["id"], self.frame, img, shapes, label)
        except A.AnimateError as e:
            self.msg(str(e))
            return
        self.changed()

    def paint_look(self):
        return A.render(self.proj, self.frame, paper=False) if self.proj else None

    def paint_refresh(self):
        self.sync_paint_swatches()
        self.redraw()

    def settle(self):
        """Put down a lifted selection / finish a shape before the frame, track or tool changes."""
        if self.pt.busy():
            self.pt.finish()

    def paint_key(self, name):
        if self.tool in PAINT and self.pt.key(name):
            self.redraw()
            return True
        return False

    def on_escape(self):
        if self.attach_mode:
            self.attach_mode = None
            self.msg("Not attached.")
        elif self.drag and self.drag.get("kind") in ("grow", "pathdraw"):
            self.drag = None
        else:
            self.paint_key("Escape")
        self.redraw()

    def on_delete(self):
        if not self.paint_key("Delete"):
            self.delete_key()

    def paint_cmd(self, what):
        """Draw tab: flip / rotate the selection or the picked shape."""
        if self.tool in PAINT and self.pt.transform(what):
            self.redraw()
        elif self.tool not in PAINT:
            self.msg("Select something with Select or Lasso (Draw tab) first.")

    def on_double(self, e):
        if self.tool in PAINT:
            self.pt.double(e)

    # ---- figures: BUILD
    def add_figure(self):
        if not self.need():
            return
        c = self.proj.add_figure(f=self.frame)
        self.active, self.selected = c["id"], {c["id"]}
        self.bone = c["figure"]["segs"][0]["id"]
        self.after_change("rebuild")
        self.set_tool("build")
        self.msg("A new figure. Build (J): Ctrl+drag from a joint to grow bones (arms, a tail, wings, branches); "
                 "pick a bone to change its look in Properties.")

    def to_figure(self):
        c = self.active_char()
        if not c or c["kind"] != "stick":
            self.msg("Pick a stickman first.")
            return
        new = self.proj.to_figure(c, self.frame)
        self.active, self.selected = new["id"], {new["id"]}
        self.bone = "head"
        self.after_change("rebuild")
        self.set_tool("build")
        self.msg(f"Made “{new['name']}” (the stickman is hidden, not deleted). Ctrl+drag from any joint to give it "
                 "more: a tail, wings, a sword, a hat.")

    def build_press(self, e, sx, sy, right, ctrl):
        figs = [c for c in self.proj.doc["characters"] if self.proj.shown(c["id"]) and c["kind"] == "figure"]
        h = self.hit(e.x, e.y, figs)
        if not h:
            c = self.active_char()
            if c and c["kind"] != "figure":
                self.msg("Build works on figures: Turn into Figure (Arrange tab) gives this stickman bones you can "
                         "add to, or Add → Figure starts a new one.")
            elif c:   # a click on a bone (not a joint) picks it
                P = self.proj.points_at(c, self.frame)
                best, bd = None, 8.0
                for a, b in A.limbs(c, P):
                    d = paint.seg_dist((e.x, e.y), self.to_screen(*P[a]), self.to_screen(*P[b]))
                    if d < bd:
                        best, bd = b, d
                if best:
                    self.bone = best
                    self.sync_track_ui()
                    self.redraw()
            return
        ch, joint = h
        self.active, self.selected = ch["id"], {ch["id"]}
        if not self.proj.editable(ch["id"]):
            self.sync_track_ui()
            self.msg(f"{ch['name']} is locked.")
            return
        if right:
            self.proj.snapshot("pose")
            self.drag = {"kind": "turn", "char": ch["id"], "joint": joint, "start": (sx, sy), "last": (sx, sy),
                         "stretch": False}
            return
        if ctrl:
            self.drag = {"kind": "grow", "char": ch["id"], "joint": joint, "to": (sx, sy)}
            return
        if joint != A.ROOT:
            self.bone = joint
        self.sync_track_ui()
        self.proj.snapshot("reshape")
        self.drag = {"kind": "build", "char": ch["id"], "joint": joint}

    # ---- motion paths: PATH
    def path_press(self, e, sx, sy, right, ctrl):
        c = self.active_char()
        if not c:
            self.msg("Pick a character, figure or prop first: Path makes it travel along a line you draw.")
            return
        if not self.proj.editable(c["id"]):
            self.msg(f"{c['name']} is locked.")
            return
        shift = bool(e.state & 0x0001)
        if c.get("path") and not shift:
            pts = [self.to_screen(*p) for p in self.proj.path_points_on_screen(c, self.frame)]
            k = min(range(len(pts)), key=lambda i: math.dist(pts[i], (e.x, e.y)))
            near = math.dist(pts[k], (e.x, e.y)) < 10
            if right:
                if near and len(pts) > 2:
                    self.proj.snapshot("remove a path point")
                    del c["path"]["pts"][k]
                    self.changed()
                return
            if near:
                self.proj.snapshot("move a path point")
                self.drag = {"kind": "pathpt", "char": c["id"], "k": k}
                return
            if ctrl:
                i = min(range(len(pts) - 1), key=lambda i: paint.seg_dist((e.x, e.y), pts[i], pts[i + 1]))
                self.proj.snapshot("add a path point")
                c["path"]["pts"].insert(i + 1, self.proj.to_local(c, self.frame, sx, sy))
                self.changed()
                return
            self.msg("Drag a point of the path; Ctrl+click adds one, right-click removes one, Shift+drag draws a new "
                     "path.")
            return
        if right:
            return
        self.drag = {"kind": "pathdraw", "char": c["id"], "pts": [(sx, sy)], "last": (e.x, e.y)}

    def draw_path(self, c):
        pts = self.proj.path_points_on_screen(c, self.frame)
        if len(pts) < 2:
            return
        S = [self.to_screen(*p) for p in pts]
        curve = paint.curve_points(S, bool(c["path"].get("closed")) and len(S) > 2)
        self.stage.create_line(*[v for p in curve for v in p], fill=c["colour"], width=2, dash=(6, 4))
        p = c["path"]
        for f in range(p["start"], p["end"] + 1, max(1, (p["end"] - p["start"]) // 40 or 1)):
            x, y = self.to_screen(*self.proj.points_at(c, f)[A.ROOT])
            self.stage.create_oval(x - 2, y - 2, x + 2, y + 2, fill=c["colour"], outline="")
        for k, (x, y) in enumerate(S):
            self.stage.create_rectangle(x - 5, y - 5, x + 5, y + 5, fill="white", outline=c["colour"], width=2)
        self.stage.create_text(S[0][0], S[0][1] - 14, text=f"frame {p['start'] + 1}", fill=hud.AMBER, font=hud.TINY)
        self.stage.create_text(S[-1][0], S[-1][1] - 14, text=f"frame {p['end'] + 1}", fill=hud.AMBER, font=hud.TINY)

    def creative_motion(self, e, d, sx, sy):
        c = self.proj.char(d["char"])
        if d["kind"] == "build":
            self.proj.build_move(c, d["joint"], sx, sy, self.frame)
            self.proj.touch()
            self.redraw()
        elif d["kind"] == "grow":
            d["to"] = (sx, sy)
            self.redraw()
            a = self.to_screen(*self.proj.points_at(c, self.frame)[d["joint"]])
            self.stage.create_line(*a, e.x, e.y, fill=hud.AMBER, width=3)
        elif d["kind"] == "pathpt":
            c["path"]["pts"][d["k"]] = self.proj.to_local(c, self.frame, sx, sy)
            self.proj.touch()
            self.redraw()
        elif d["kind"] == "pathdraw":
            d["pts"].append((sx, sy))
            self.stage.create_line(*d["last"], e.x, e.y, fill=c["colour"], width=2)
            d["last"] = (e.x, e.y)

    def creative_release(self, d):
        c = self.proj.char(d["char"])
        if d["kind"] == "grow":
            a = self.proj.points_at(c, self.frame)[d["joint"]]
            if math.dist(a, d["to"]) * self.view()[0] < 6:
                self.msg("Drag further to grow a bone.")
                return
            s = self.proj.add_bone(c, d["joint"], *d["to"], self.frame)
            self.bone = s["id"]
            self.sync_track_ui()
            self.msg(f"Added {s['name']}. Set its look in Properties (line, circle, box, ellipse or a picture).")
        elif d["kind"] == "pathdraw":
            z = self.view()[0]
            pts = paint.simplify(d["pts"], 3.0 / max(z, 1e-6))
            if len(pts) < 2 or math.dist(pts[0], pts[-1]) < 4 / max(z, 1e-6) and len(pts) < 3:
                self.msg("Drag a longer line for the path.")
                return
            try:
                self.proj.set_path(c, pts[:60], self.frame)
            except A.AnimateError as err:
                self.msg(str(err))
                return
            self.sync_track_ui()
            self.msg(f"{c['name']} now travels along the path from frame {c['path']['start'] + 1} to "
                     f"{c['path']['end'] + 1}. Set the frames in Properties.")

    def path_section(self, s, c):
        hud.rule(s, pady=6)
        hud.tag(s, "Path", bg=hud.PANEL).pack(anchor="w")
        if not c.get("path"):
            hud.label(s, "Drag on the stage to draw the path it travels along.", bg=hud.PANEL, fg=hud.DIM,
                      font=hud.TINY, wraplength=186, justify="left").pack(anchor="w")
            return
        row = tk.Frame(s, bg=hud.PANEL)
        row.pack(fill="x", pady=2)
        for text, var in (("From", self.v_pstart), ("To", self.v_pend)):
            hud.label(row, text, bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(side="left", padx=(0, 2))
            en = tk.Entry(row, textvariable=var, width=5, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT,
                          relief="flat", font=hud.SMALL)
            en.pack(side="left", padx=(0, 6))
            en.bind("<Return>", lambda ev: self.path_changed())
            en.bind("<FocusOut>", lambda ev: self.path_changed())
        for text, var in (("Slow in and out", self.v_pease), ("Turn to follow it", self.v_porient),
                          ("Closed loop", self.v_pclosed)):
            tk.Checkbutton(s, text=text, variable=var, command=self.path_changed, bg=hud.PANEL, fg=hud.TEXT,
                           selectcolor=hud.FIELD, activebackground=hud.PANEL, font=hud.SMALL, anchor="w").pack(fill="x")
        self.btn_row(s, [("Clear Path", self.clear_path)])

    def path_changed(self):
        c = self.active_char()
        if not c or not c.get("path"):
            return
        p = c["path"]
        try:
            a, b = int(float(self.v_pstart.get())) - 1, int(float(self.v_pend.get())) - 1
        except ValueError:
            a, b = p["start"], p["end"]
        a = max(0, min(self.length() - 1, a))
        b = max(a + 1, b)
        new = {"start": a, "end": b, "ease": "smooth" if self.v_pease.get() else "linear",
               "orient": self.v_porient.get(), "closed": self.v_pclosed.get()}
        if any(p.get(k) != v for k, v in new.items()):
            self.proj.snapshot("path settings")
            p.update(new)
            self.changed()
        self.v_pstart.set(str(a + 1))
        self.v_pend.set(str(b + 1))

    def clear_path(self):
        c = self.active_char()
        if c and self.proj.clear_path(c):
            self.after_change("rebuild")
            self.msg("Path cleared: it stays where the path had it on each key.")

    # ---- attach
    def start_attach(self):
        c = self.active_char()
        if not c:
            self.msg("Pick the character, figure or prop to attach first.")
            return
        self.attach_mode = c["id"]
        self.msg(f"Now click the joint to attach {c['name']} to (a hand, a head, a cart's root…). Esc cancels.")

    def finish_attach(self, e):
        cid, self.attach_mode = self.attach_mode, None
        c = self.proj.char(cid)
        others = [x for x in self.proj.doc["characters"] if x["id"] != cid and self.proj.shown(x["id"])]
        h = self.hit(e.x, e.y, others)
        if not h:
            self.msg("No joint there: not attached. Attach To… to try again.")
            return
        ch, joint = h
        try:
            self.proj.attach(c, ch["id"], joint, self.frame)
        except A.AnimateError as err:
            self.msg(str(err))
            return
        self.active, self.selected = cid, {cid}
        self.after_change("rebuild")
        self.msg(f"{c['name']} now follows {ch['name']}'s {'root' if joint == 'hip' else joint} on every frame. "
                 "Its own keys still pose and turn it. Detach frees it.")

    def detach(self):
        c = self.active_char()
        if c and self.proj.detach(c, self.frame):
            self.after_change("rebuild")
            self.msg(f"{c['name']} is free again (it stays where it was).")
        else:
            self.msg("Pick an attached track (⛓) first.")

    # ---- pictures: PAINT…, props, backgrounds, pictures on bones
    def load_picture_file(self):
        path = filedialog.askopenfilename(parent=self.root,
                                          filetypes=[("Pictures", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")])
        if not path:
            return None
        try:
            with Image.open(path) as im:
                return im.convert("RGBA"), [], os.path.splitext(os.path.basename(path))[0]
        except OSError as e:
            messagebox.showinfo("Animate", f"It couldn't be opened: {e}", parent=self.root)
            return None

    def ask_role(self):
        ch = tp.ask_choice(self.root, "Picture", "Use it as:", ["A prop (in front, to move)", "A background (at the back)",
                                                                 "Cancel"], 0)
        return {0: "prop", 1: "background"}.get(ch)

    def add_picture(self):
        if not self.need():
            return
        src = cd.choose_picture_source(self, "Add → Picture")
        if src == "paint":
            self.open_paint()
        elif src == "library":
            cd.LibraryDialog(self, "Props")
        elif src in ("file", "existing"):
            if src == "file":
                got = self.load_picture_file()
                if not got:
                    return
            else:
                pid = cd.pick_existing_picture(self)
                if not pid:
                    return
            role = self.ask_role()
            if not role:
                return
            if src == "file":
                self.picture_as(role, *got)
            else:
                n = len(self.proj.undo_stack)
                c = self.proj.picture_track(pid, role, self.proj.doc["pictures"][pid].get("name"), self.frame)
                del self.proj.undo_stack[n + 1:]
                self.active, self.selected = c["id"], {c["id"]}
                self.after_change("rebuild")

    def open_paint(self, picture=None, name="My picture", pid=None):
        from paint_window import PaintWindow
        outs = [("Add as Prop", lambda img, sh, nm: self.picture_as("prop", img, sh, nm)),
                ("Add as Background", lambda img, sh, nm: self.picture_as("background", img, sh, nm)),
                ("Put on the Picked Bone", self.picture_on_bone)]
        if self.v_rigging.get():
            outs.append(("Rig as A Character", self.picture_rig))
        if pid:
            outs.insert(0, ("Save Changes", lambda img, sh, nm: self.save_picture_edit(pid, img, sh, nm)))
        size = (400, 400)
        if self.proj and picture is None:
            size = (min(400, self.proj.size[0]), min(400, self.proj.size[1]))
        return PaintWindow(self.root, self.images, picture, size, outs, "Paint" if not pid else f"Paint: {name}", name)

    def picture_as(self, role, img, shapes, name):
        if not self.proj:
            raise A.AnimateError("Make or open an animation first (New… / Open…).")
        n = len(self.proj.undo_stack)
        self.proj.snapshot(f"add a {role}")
        pid = self.proj.add_picture(img, shapes, name)
        c = self.proj.picture_track(pid, role, name, self.frame)
        del self.proj.undo_stack[n + 1:]   # one undo step
        self.active, self.selected = c["id"], {c["id"]}
        self.after_change("rebuild")
        self.set_tool("pose")
        self.msg(f"Added {c['name']} as a {role}: drag its red root to move it, right-drag to turn it, K to key it; "
                 "Attach To… makes it follow a hand; Path (H) makes it travel.")

    def picked_bone(self, quiet=False):
        c = self.active_char()
        if not c or c["kind"] != "figure" or not self.bone or self.bone not in {s["id"] for s in c["figure"]["segs"]}:
            if not quiet:
                self.msg("Pick a figure's bone first (click a joint of a figure).")
            return None, None
        return c, self.proj.seg(c, self.bone)

    def picture_on_bone(self, img, shapes, name):
        c, s = self.picked_bone(quiet=True)
        if not c:
            raise A.AnimateError("Pick a figure's bone first (close this, click a joint of a figure, then use it).")
        n = len(self.proj.undo_stack)
        self.proj.snapshot("picture on a bone")
        pid = self.proj.add_picture(img, shapes, name)
        self.proj.bone_picture(c, s["id"], pid, self.frame)
        if s.get("shape") == "line":
            s["shape"] = "none"   # the picture shows instead of the line (pick a shape again to have both)
        del self.proj.undo_stack[n + 1:]
        self.after_change("rebuild")
        self.msg(f"The picture is on {s['name']}: it turns and moves with it. Nudge it with the arrows in the side "
                 "panel.")

    def picture_rig(self, img, shapes, name):
        if not self.proj:
            raise A.AnimateError("Make or open an animation first.")
        W, H = self.proj.size
        src = paint.flatten(img, shapes)
        k = min(1.0, 0.7 * H / src.height, 0.5 * W / src.width)
        src = src.resize((max(1, int(src.width * k)), max(1, int(src.height * k))), Image.LANCZOS)
        art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        art.alpha_composite(src, ((W - src.width) // 2, max(0, int(0.85 * H) - src.height)))
        c = self.proj.make_rig(art, name)
        self.active, self.selected = c["id"], {c["id"]}
        self.rig_sub = "joints"
        self.after_change("rebuild")
        self.set_tool("rig")
        self.msg("Drag the 12 joints onto the drawing, then Bind to Nearest Bone.")

    def save_picture_edit(self, pid, img, shapes, name):
        self.proj.set_picture(pid, img, shapes)
        self.proj.doc["pictures"][pid]["name"] = name[:60]
        self.changed()
        self.msg("Picture saved in the animation (Ctrl+Z on the stage undoes it).")

    # ---- the picked bone's look
    def figure_section(self, s, c):
        hud.rule(s, pady=6)
        hud.tag(s, "Bone", bg=hud.PANEL).pack(anchor="w", pady=(0, 2))
        c_, sg = self.picked_bone(quiet=True)
        if not sg:
            hud.label(s, "No bones yet: choose Build, then Ctrl+drag from the red root to grow one.", bg=hud.PANEL,
                      fg=hud.DIM, font=hud.TINY, wraplength=186, justify="left").pack(anchor="w")
            return
        hud.label(s, f"{sg['name']}   (click a joint to select its bone)", bg=hud.PANEL, fg=hud.AMBER,
                  font=hud.TINY).pack(anchor="w")
        row = tk.Frame(s, bg=hud.PANEL)
        row.pack(fill="x", pady=2)
        hud.label(row, "Look", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(side="left")
        om = tk.OptionMenu(row, self.v_shape, *A.SEG_SHAPES, command=lambda v: self.bone_set(shape=v))
        om.configure(bg=hud.FIELD, fg=hud.TEXT, highlightthickness=0, relief="flat", font=hud.TINY)
        om.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.btn_row(s, [("Line −", lambda: self.bone_step("width", -1)), ("Line +", lambda: self.bone_step("width", 1)),
                         ("Width −", lambda: self.bone_step("thick", -3)), ("Width +", lambda: self.bone_step("thick", 3))])
        self.btn_row(s, [("Colour…", lambda: self.bone_colour("colour")), ("Fill…", lambda: self.bone_colour("fill")),
                         ("No Fill", lambda: self.bone_set(fill=None))])
        self.btn_row(s, [("Outline", lambda: self.bone_set(outline=not sg.get("outline"))),
                         ("Forward", lambda: self.bone_order(1)), ("Backward", lambda: self.bone_order(-1))])
        self.btn_row(s, [("Rename…", self.bone_rename), ("Delete Bone", self.bone_delete)])
        hud.label(s, "Picture on this bone", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(anchor="w", pady=(4, 0))
        if not sg.get("pic"):
            self.btn_row(s, [("Add Picture…", self.bone_pic)])
            return
        self.btn_row(s, [("Change…", self.bone_pic), ("Edit in Paint", self.bone_pic_edit),
                         ("Remove", lambda: self.bone_set(pic=None))])
        k = 4.0
        self.btn_row(s, [("◀", lambda: self.bone_nudge(dx=-k)), ("▶", lambda: self.bone_nudge(dx=k)),
                         ("▲", lambda: self.bone_nudge(dy=-k)), ("▼", lambda: self.bone_nudge(dy=k)),
                         ("Flip", lambda: self.bone_nudge(flip=True))])
        self.btn_row(s, [("⟲", lambda: self.bone_nudge(turn=-15)), ("⟳", lambda: self.bone_nudge(turn=15)),
                         ("−", lambda: self.bone_nudge(scale=1 / 1.1)), ("+", lambda: self.bone_nudge(scale=1.1))])

    def bone_set(self, **look):
        c, s = self.picked_bone()
        if c:
            self.proj.set_bone(c, s["id"], **look)
            self.after_change("rebuild")

    def bone_step(self, key, d):
        c, s = self.picked_bone()
        if c:
            self.bone_set(**{key: max(0.5 if key == "width" else 2.0, float(s.get(key, 6)) + d)})

    def bone_colour(self, key):
        c, s = self.picked_bone()
        if c:
            col = colorchooser.askcolor(s.get(key) or c["colour"], parent=self.root)[1]
            if col:
                self.bone_set(**{key: col})

    def bone_order(self, d):
        c, s = self.picked_bone()
        if c and self.proj.bone_order(c, s["id"], d):
            self.changed()

    def bone_rename(self):
        c, s = self.picked_bone()
        if c:
            name = hud.ask_text(self.root, "Rename bone", "New name:", s["name"])
            if name:
                self.bone_set(name=name.strip()[:40])

    def bone_delete(self):
        c, s = self.picked_bone()
        if not c:
            return
        kids = [x for x in c["figure"]["segs"] if x["parent"] == s["id"]]
        if messagebox.askyesno("Delete bone", f"Delete {s['name']}" + (" and the bones hanging from it" if kids else "")
                               + "?\n\nCtrl+Z brings it back.", parent=self.root):
            self.proj.remove_bone(c, s["id"])
            self.bone = None
            self.after_change("rebuild")

    def bone_pic(self):
        c, s = self.picked_bone()
        if not c:
            return
        src = cd.choose_picture_source(self, f"Picture on {s['name']}")
        if src == "paint":
            self.open_paint()
            self.msg("Paint it, then Put on the Picked Bone.")
            return
        if src == "file":
            got = self.load_picture_file()
        elif src == "library":
            got = cd.pick_library_picture(self)
        elif src == "existing":
            pid = cd.pick_existing_picture(self)
            if pid:
                self.proj.snapshot("picture on a bone")
                self.proj.bone_picture(c, s["id"], pid, self.frame)
                self.after_change("rebuild")
            return
        else:
            return
        if got:
            self.picture_on_bone(*got)

    def bone_pic_edit(self):
        c, s = self.picked_bone()
        if c and s.get("pic"):
            pid = s["pic"]["id"]
            self.open_paint(self.proj.picture_raw(pid), self.proj.doc["pictures"][pid].get("name", "Picture"), pid)

    def bone_nudge(self, **kw):
        c, s = self.picked_bone()
        if c:
            try:
                self.proj.nudge_picture(c, s["id"], self.frame, **kw)
            except A.AnimateError as e:
                self.msg(str(e))
            self.changed()

    # ---- library and story
    def save_to_library(self):
        c = self.active_char()
        if not c:
            self.msg("Pick a character, figure, prop or background to save.")
            return
        ch = tp.ask_choice(self.root, "Save to library", f"Save “{c['name']}” to the Animation Library with:",
                           ["All its keys (its animation)", "Only this frame's pose", "Cancel"], 0)
        if ch not in (0, 1):
            return
        name = hud.ask_text(self.root, "Save to library", "Name in the library:", c["name"])
        if not name:
            return
        try:
            d = library.save_track(self.images, self.proj, c["id"], name, with_keys=ch == 0, f=self.frame)
        except library.LibraryError as e:
            if "already" not in str(e) or not messagebox.askyesno(
                    "Library", f"{e}\n\nReplace it? (The old one is moved to the library's Deleted folder.)",
                    parent=self.root):
                return
            d = library.save_track(self.images, self.proj, c["id"], name, with_keys=ch == 0, f=self.frame,
                                   replace=True)
        except (OSError, A.AnimateError) as e:
            messagebox.showinfo("Library", f"Not saved: {e}", parent=self.root)
            return
        self.msg(f"Saved to {d}")

    def library_dialog(self):
        cd.LibraryDialog(self)

    def story_dialog(self):
        if self.need():
            cd.StoryDialog(self)

    # ================================================================ leaving
    def leave(self):
        self.pause()
        self.settle()
        self.save_quietly()
