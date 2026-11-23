"""The guided tour of Stickman Studio: it switches screens, draws a red frame around the part it explains,
and shows a step card next to it, ending with how to send the final prompt to Claude.

    Tour(studio).start()        # the "? TOUR" button, F1, and the first time the studio opens
"""
import tkinter as tk

import hud

PAD = 6        # space between the red frame and the widget
BAR = 3        # thickness of the red frame


class Tour:
    def __init__(self, studio):
        self.s = studio
        self.root = studio.root
        self.i = 0
        self.bars = []
        self.card = None
        self.move_id = None
        self.steps = [st for st in self.make_steps()    # no Game Settings stops while that tab is hidden
                      if st.get("screen") != "settings" or getattr(studio, "game_tab", True)]

    # ---------------------------------------------------------------- the steps
    def make_steps(self):
        s = self.s

        def source():
            return s.source

        def home():
            return s.home

        def gs():
            return s.settings

        def first_tab():
            return s.settings.tabs[0] if s.settings and s.settings.tabs else None

        def notes_tab():
            if s.settings:
                s.settings.book.select(len(s.settings.tabs))

        def char_tab():
            if s.settings and s.settings.tabs:
                s.settings.book.select(0)
                s.settings.tabs[0].frame.canvas.yview_moveto(0.0)

        game = getattr(s, "game_tab", True)   # the Unity game workflow (4 Game Settings) is on
        return [
            dict(title="Welcome to Stickman Studio",
                 text=("This turns a video into a new stickman move for your game.\n\n"
                       "You go through four screens, left to right:\n"
                       "Source  →  Trace  →  Review  →  Game Settings\n"
                       "and finish by pasting one prompt to Claude, who builds the move in Unity.\n\n" if game else
                       "Trace stickman animations from a video, or animate them yourself.\n\n"
                       "Source  →  Trace  →  Review: open a video, click the 12 joints on its key frames, "
                       "watch and fix the result.\nAnimate: pose stickmen, draw frame by frame, rig your own "
                       "drawings.\nThen export GIF, MP4, PNG frames or sprite sheets for your game.\n\n")
                 + "Click Next (or press →) to start. You can leave the tour any time."),
            dict(screen="source", target=lambda: list(s.nav.values()),
                 title="The five screens",
                 text="Switch screens with these tabs, or Ctrl+1 to Ctrl+5. Animate is a separate animation "
                      "studio (its stop is at the end of this tour). Everything is saved as you go, "
                      "so you can jump back and forth. Help → Guided Tour (or F1) brings this tour back."),
            dict(screen="source", target=lambda: [s.titlebar, source().ribbon],
                 title="Title bar and ribbon",
                 text="Save, Undo and Redo are always at the top left, as in Paint, and act on the screen you're on. "
                      "Help (top right) has the tour, the tutorial and every keyboard shortcut.\n\n"
                      "Each screen has a ribbon: File (red) opens, saves and exports; Home holds the everyday "
                      "commands; the other tabs hold the advanced ones. Hover over any button to see what it does and "
                      "its shortcut. Double-click a tab to hide the ribbon for more room."),
            dict(screen="source", target=lambda: [source().view, source().open_btn],
                 title="Source: open your reference",
                 text="Drag a video, a GIF or photos onto Stickman Studio.bat, or click Open File….\n\n"
                      "Step through it like VLC: ← → one frame (back works too), Shift+← → ten frames, "
                      "Space plays, [ ] changes the speed."),
            dict(screen="source", target=lambda: [source().range_lbl, source().range_row],
                 title="Mark the move",
                 text="Go to where the move starts (include the wind-up) and press I. Go to where it ends "
                      "(include the landing or the return to guard) and press O. That part turns red on the timeline."),
            dict(screen="source", target=lambda: source().save_btn,
                 title="Save the frames",
                 text="Press F, type the move's name (for example uppercut) and click Save Frames.\n\n"
                      "The frames go to Images\\uppercut\\f01.png, f02.png … and the studio jumps to Trace.\n"
                      "(G makes a GIF; S saves just the frame on screen" + (", for showing Claude a problem.)"
                                                                            if game else ".)")),
            dict(screen="trace", target=lambda: home().list_canvas,
                 title="Trace: pick the move",
                 text="Every move you've saved is listed here, with how much of it is traced. Click one."),
            dict(screen="trace", target=lambda: home().grid,
                 title="Click the key frames",
                 text="Click the frames where the motion changes: the start, the lowest point of the wind-up, the hit "
                      "or peak, the landing and the end. Usually 4 to 8. Each gets a red number; click again to "
                      "remove it. You don't trace every frame: the in-betweens are made for you."),
            dict(screen="trace", target=lambda: home().start_btn,
                 title="Trace the 12 joints",
                 text="Click Start Tracing. Then click the joints in the order the panel on the right asks: "
                      "head, neck, waist, hip, legs, arms.\n\n"
                      "Enter = next frame (it starts with a faded copy of the last one: click the head and the rest "
                      "follows)  ·  Space = keep a faded point  ·  right-click = a guess for a hidden joint  ·  "
                      "wheel = zoom.\n\nTo fix a point: Tab or Ctrl+click selects it, Alt+arrows nudge it (finer when "
                      "zoomed in), Delete removes it, Ctrl+Z / Ctrl+Y undo and redo (kept after a restart; U lists "
                      "every step and goes back to any of them; Ctrl+S saves a named checkpoint). N jumps to the next "
                      "unfinished "
                      "frame. C (Carry Forward) copies chosen joints to other key frames, e.g. a foot that stays "
                      "planted; R refreshes the faded copy. S (Smooth) takes the jitter out of joint paths, with a "
                      "preview, and keeps fast moves. T shows motion trails.\n\n"
                      "In the editor's ribbon, Home has Keep, Guess, Delete, Next Frame, Play and Finish; Tools has "
                      "Carry Forward, Smooth and History; View has zoom, joint names and trails. Click Finish when "
                      "every frame is done."),
            dict(screen="trace", target=lambda: home().start_btn,
                 title="Optional joints: shoulders, hand tips, toes",
                 text="Under the 12 joints the panel lists 6 optional ones: frontShoulder, backShoulder, "
                      "frontHandTip, backHandTip, frontToe, backToe. They are never asked for and never required: a "
                      "frame is finished with the 12, so a one-handed character, or any part you can't see, is fine.\n\n"
                      "To add one, click its name, then click the spot. The arm then goes neck → shoulder → "
                      "elbow → hand → hand tip, and the leg ends hip → knee → foot → toe. Tab reaches "
                      "them after the 12; Delete removes one. Add one on a single frame and the in-betweens keep it "
                      "following its limb.\n\nIn Animate, tick Shoulders, Hand tips or Toes for the picked "
                      "stickman." + (" The Unity bake still uses the 12." if game else "")),
            dict(screen="trace", target=lambda: home().charbar,
                 title="Multi-character moves",
                 text="Two or more fighters in the same video? + Character adds one to the picked move. Your first "
                      "trace stays where it is; each new character gets its own trace in the move's characters "
                      "folder. Click a name (or press 1 to 9 in the editor) to choose whose joints you're clicking; "
                      "the others show faded. ◉ hides one, Lock stops it being changed, double-click renames it.\n\n"
                      "In the editor A selects every character: Shift+Alt+arrows move them together, M opens Group… "
                      "and one Ctrl+Z undoes it for all of them. Manage… renames, recolours, reorders, deletes "
                      "(it can be restored) and imports a character from another move.\n\n"
                      "One fighter only? Ignore this bar: nothing changes for single-character moves."),
            dict(screen="trace", target=lambda: home().backups_btn,
                 title="Your work is backed up",
                 text="Every time a trace is opened, a dated copy goes into the move's backups folder (only when "
                      "something changed). Saving a new fixed trace backs up the old one too.\n\n"
                      "Backups… lists them, shows one next to the current trace and puts it back. Restoring backs up "
                      "the current file first, so nothing is ever lost. Checkpoints are the ones you named (Ctrl+S in "
                      "the editor, or Save Checkpoint… there). Restore Frames… puts back only the key frames you tick. "
                      "Your trace and the fixed trace are kept apart: each backup only goes back to its own file."),
            dict(screen="trace", target=lambda: home().project_btn,
                 title="Project: check, protect, copy",
                 text="Project… shows the picked move's status and checks it for missing or inconsistent data: "
                      "frames without points, a key frame with no picture, two frames with exactly the same pose, a "
                      "fixed trace that's older than your trace, and more.\n\n"
                      "Protect the Trace makes trace.json read-only: the editor then offers to trace a copy instead. "
                      "Duplicate… copies the move. Back Up This Move packs every file into a .zip in Project backups; "
                      "Unpack as a Copy… brings one back as a new folder. Nothing there deletes or overwrites "
                      "anything.\n\nAmber lines in the move list flag protected moves and things to check; Sort puts "
                      "the latest change on top."),
            dict(screen="play", target=lambda: s.player.stage if s.player else None,
                 title="Review: check it",
                 text="Your trace plays as the game's stickman at the real speed. Look for a joint that jumps for one "
                      "frame, a limb that suddenly gets longer or shorter, or front and back swapping (B greys the "
                      "back limbs). T draws motion trails of the hands, feet and head; K opens Key Poses (frames found by "
                      "simple rules, to accept or reject, or mark your own); C compares two frames, or your trace with the "
                      "fixed one or a backup; A opens Analytics (speeds, angles, timing): they're on the Home tab, and "
                      "the display options on the View tab. If something's wrong, go back to Trace and drag the "
                      "point.\n\n"
                      "(Nothing here yet? Trace a move first; this screen plays the move selected in Trace.)"),
            dict(screen="play", target=lambda: [s.player.fix_box, s.player.save_btn] if s.player else None,
                 title="Fix it, if it needs it",
                 text="Filmed from an angle? Camera angle → Auto. Camera zooms? Even out zoom. Floating? Feet on the "
                      "ground (on already). A walk that moves across the screen? In place.\n\n"
                      "Then Save Fixed Trace and choose Moving or In place. Your original trace is never changed."),
            dict(screen="settings", before=char_tab, target=lambda: first_tab().from_anim_btn if first_tab() else None,
                 title="Game Settings: add the move",
                 text="Pick the character's tab (The man or The lady), click Add Move from Animation… and "
                      "choose your trace. It's named after it. Click its key box and press the key you want "
                      "(a red key is already used). ▶ Preview plays it in Review; Analytics measures it (speeds, angles, "
                      "timing, in pixels, bones, metres or game units).\n\n"
                      "You can also change keys and values here: changes turn amber and show 'was …'."),
            dict(screen="settings", target=lambda: gs().export_btn if gs() and hasattr(gs(), "export_btn") else None,
                 title="Export moves",
                 text="Export Moves… (Export tab) exports several moves at once (this project's moves start ticked; "
                      "Trace has "
                      "Export Moves… too). Each run goes into a new dated folder in Exports, so nothing is "
                      "overwritten.\n\nEvery move gets its own folder: your trace files exactly as they are, plus pose "
                      "data (<move>_poses.json), a frames table (<move>_frames.csv) and, if you tick them, stickman "
                      "pictures and your trace on the reference frames. Choose your trace or the fixed one, every "
                      "frame or key frames only. Check First shows what will happen without writing anything; after "
                      "the export every file is read back and a summary is saved with it."),
            dict(screen="settings", before=notes_tab, target=lambda: gs().book if gs() else None,
                 title="Notes, feedback and checking",
                 text="Write anything else for Claude: what looks wrong, extra wishes, 'also give it to the lady'.\n\n"
                      "Pick how much checking you want. Quick check saves tokens; ask for a GIF only for a brand-new "
                      "move or when something looks wrong."),
            dict(screen="settings", before=char_tab, target=lambda: gs().copy_btn if gs() else None,
                 title="Copy the prompt",
                 text="Copy Prompt for Claude copies one message with everything: the keys and values you changed, "
                      "your new moves and the traces to build them from, your notes, feedback and checking.\n\n"
                      "The number on the button is how many changes it lists. The Prompt for Claude tab shows the "
                      "text first."),
            dict(screen="settings", target=lambda: gs().done_btn if gs() else None,
                 title="Send it to Claude",
                 text="1.  Open Claude. Start a new session for each new move (it saves tokens).\n"
                      "2.  Paste the prompt (Ctrl+V) and send it.\n"
                      "3.  Claude builds the move: the wind-up and ending, the clip, the key, the Animator, and the "
                      "lady's version if you asked.\n"
                      "4.  When Claude says it's done, click Mark as Done ✓ here, so the next prompt only lists new "
                      "changes.\n"
                      "5.  Test it in Unity. Something wrong? Record it (Win+Alt+R), open the recording in Source, press S "
                      "on the bad frame, write it in Feedback, and copy the prompt again.",
                 button=("Copy My Prompt Now", lambda: gs() and gs().copy_prompt())),
            dict(screen="animate", target=lambda: s.animate.stage if s.animate else None,
                 title="Animate: animate without a video",
                 text="Make stickman animations yourself. File → New Animation… starts one (File → Import Trace… "
                      "brings in a traced move).\n\n"
                      "Pose (Q): drag a joint to turn its bone (the rest follows), drag the red hip to move, "
                      "right-drag to turn the body. K keys the frame; the in-betweens are made for you and bones "
                      "never change length (Advanced tab: untick Lock Proportions, then Ctrl+drag, to stretch on "
                      "purpose).\n\n"
                      "Pen / Brush / Eraser (P B E) draw frame by frame on drawing layers, with onion skin (O), "
                      "Hold ± for how long a drawing stays, and Duplicate / Insert / Delete Frame. Skeletons and "
                      "drawings share one timeline. Several characters: A selects all, drag a hip to move them "
                      "together.\n\nTick Enable Rigging (Advanced tab) to rig your own drawing: place the 12 "
                      "joints on it, Bind, and pose it like a stickman. Export… makes PNG / GIF, or a new move for "
                      "Trace, Review and Game Settings."),
            dict(screen="animate", target=lambda: s.animate.ribbon if s.animate else None,
                 title="Make your own: paint, figures, paths, stories",
                 text="Paint… opens a paint window: line, box, ellipse, polygon, curve (shapes stay editable), "
                      "fill, gradient, pick, select / lasso to move, resize, turn and flip, and Import Picture. The "
                      "same tools are on the Draw tab for drawing layers.\n\n"
                      "Add → Figure builds your own skeleton: Build (J), Ctrl+drag from any joint grows a bone (tails, "
                      "wings, a tree). Each bone can be a line, circle, box, ellipse or your own picture. Turn into "
                      "Figure (Arrange tab) gives a stickman extra bones. Add → Picture… adds a prop or a "
                      "background. The selected track's settings show under Properties on the left.\n\n"
                      "Attach To… then click a joint: a sword follows the hand. Path (H): draw a line and it travels "
                      "along it. Story… splits the animation into scenes with choices (play it, or export a web page). "
                      "Library… keeps your characters, props and backgrounds for every animation."),
        ]

    # ---------------------------------------------------------------- running
    def start(self, i=0):
        self.end(quiet=True)
        self.i = i
        self.root.bind("<Configure>", self.on_move, add="+")
        self.show()

    def show(self):
        step = self.steps[self.i]
        if step.get("screen"):
            self.s.show(step["screen"])
        if step.get("before"):
            step["before"]()
        self.root.update_idletasks()
        self.root.after(60, self.draw)    # let the screen lay itself out first

    def go(self, d):
        j = self.i + d
        if 0 <= j < len(self.steps):
            self.i = j
            self.show()
        elif j >= len(self.steps):
            self.end()

    def end(self, quiet=False):
        for b in self.bars:
            b.destroy()
        self.bars = []
        if self.card is not None:
            self.card.destroy()
            self.card = None
        if not quiet:
            self.s.tour_done()

    def on_move(self, e):
        if e.widget is self.root and self.card is not None:
            if self.move_id:
                self.root.after_cancel(self.move_id)
            self.move_id = self.root.after(80, self.draw)

    # ---------------------------------------------------------------- drawing
    def target_box(self):
        step = self.steps[self.i]
        try:
            t = step.get("target") and step["target"]()
        except (AttributeError, tk.TclError, IndexError, TypeError):
            t = None
        widgets = [w for w in (t if isinstance(t, list) else [t]) if w is not None]
        box = None
        for w in widgets:
            try:
                if not w.winfo_ismapped():
                    continue
                x, y = w.winfo_rootx(), w.winfo_rooty()
                b = (x, y, x + w.winfo_width(), y + w.winfo_height())
            except tk.TclError:
                continue
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        return box

    def draw(self):
        self.move_id = None
        for b in self.bars:
            b.destroy()
        self.bars = []
        box = self.target_box()
        if box:
            x0, y0, x1, y1 = box[0] - PAD, box[1] - PAD, box[2] + PAD, box[3] + PAD
            for (x, y, w, h) in ((x0, y0, x1 - x0, BAR), (x0, y1 - BAR, x1 - x0, BAR),
                                 (x0, y0, BAR, y1 - y0), (x1 - BAR, y0, BAR, y1 - y0)):
                bar = tk.Toplevel(self.root, bg=hud.RED)
                bar.overrideredirect(True)
                bar.transient(self.root)
                bar.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")
                bar.lift()
                self.bars.append(bar)
        self.draw_card(box)

    def draw_card(self, box):
        step = self.steps[self.i]
        if self.card is not None:
            self.card.destroy()
        c = tk.Toplevel(self.root, bg=hud.PANEL, highlightthickness=2, highlightbackground=hud.RED,
                        highlightcolor=hud.RED)
        c.overrideredirect(True)
        c.transient(self.root)
        self.card = c
        inner = tk.Frame(c, bg=hud.PANEL, padx=18, pady=14)
        inner.pack(fill="both", expand=True)
        top = tk.Frame(inner, bg=hud.PANEL)
        top.pack(fill="x")
        hud.tag(top, f"Tour  {self.i + 1} / {len(self.steps)}", bg=hud.PANEL).pack(side="left")
        prog = tk.Canvas(top, height=6, width=160, bg=hud.PANEL, highlightthickness=0)
        prog.pack(side="left", fill="x", expand=True, padx=(10, 0))
        prog.bind("<Configure>", lambda e: self.draw_progress(prog))
        tk.Label(inner, text=step["title"].upper(), bg=hud.PANEL, fg=hud.TEXT, font=(hud.F_SEMI, 15),
                 anchor="w", justify="left", wraplength=440).pack(fill="x", pady=(10, 4))
        tk.Label(inner, text=step["text"], bg=hud.PANEL, fg=hud.DIM, font=hud.FONT, anchor="w", justify="left",
                 wraplength=440).pack(fill="x")
        if step.get("button"):
            label, fn = step["button"]
            hud.Button(inner, label, fn, kind="red").pack(anchor="w", pady=(12, 0))
        nav = tk.Frame(inner, bg=hud.PANEL)
        nav.pack(fill="x", pady=(16, 0))
        hud.Button(nav, "End Tour", self.end, kind="ghost", padx=10).pack(side="left")
        last = self.i == len(self.steps) - 1
        hud.Button(nav, "Done  ✓" if last else "Next  ▶", lambda: self.go(1), kind="red", padx=14).pack(side="right")
        if self.i > 0:
            hud.Button(nav, "◀  Back", lambda: self.go(-1), padx=10).pack(side="right", padx=(0, 6))
        for seq, fn in (("<Right>", lambda e: self.go(1)), ("<Return>", lambda e: self.go(1)),
                        ("<Left>", lambda e: self.go(-1)), ("<Escape>", lambda e: self.end())):
            c.bind(seq, fn)
        c.update_idletasks()
        cw, ch = c.winfo_reqwidth(), c.winfo_reqheight()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        if box is None:   # nothing to point at: centre it
            x, y = rx + (rw - cw) // 2, ry + (rh - ch) // 2
        else:
            x0, y0, x1, y1 = box
            gap = 18
            if x1 + gap + cw <= rx + rw:            # to the right
                x, y = x1 + gap, y0
            elif x0 - gap - cw >= rx:               # to the left
                x, y = x0 - gap - cw, y0
            elif y1 + gap + ch <= ry + rh:          # below
                x, y = x0, y1 + gap
            else:                                   # above, or over the top of a big target
                x, y = x0, max(ry, y0 - gap - ch)
            if (x1 - x0) * (y1 - y0) > 0.5 * rw * rh:   # a target that fills the screen: card in its corner
                x, y = x1 - cw - 30, y1 - ch - 30
            x = min(max(x, rx + 8), rx + rw - cw - 8)
            y = min(max(y, ry + 8), ry + rh - ch - 8)
        c.geometry(f"{cw}x{ch}+{int(x)}+{int(y)}")
        c.update_idletasks()
        for b in self.bars:
            b.lift()
        c.lift()
        c.focus_force()

    def draw_progress(self, c):
        c.delete("all")
        w = c.winfo_width()
        c.create_rectangle(0, 2, w, 4, fill=hud.LINE, outline="")
        c.create_rectangle(0, 1, w * (self.i + 1) / len(self.steps), 5, fill=hud.RED, outline="")
