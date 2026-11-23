"""Stickman Studio.exe: a small launcher with its own Python, Tk, Pillow, OpenCV and numpy built in.

The app itself (studio.py and the scripts next to it, plus Game Settings) is read from the scripts folder every time
the .exe starts, so a change to any script shows up the next time you open it: no rebuild needed. Rebuild
(build_studio_exe.py) only when a script starts using a library that isn't imported below.

config.json next to the .exe says where things are:
    {"scripts": [...folders to look for studio.py...], "images": ..., "settings": ..., "unity": ...}
The .exe also stands in for python.exe: the scripts run helpers as  sys.executable -I helper.py args.
Errors go to error.log next to the .exe (and a message box).
"""
import json
import os
import runpy
import sys
import traceback

# Everything the scripts use, so PyInstaller packs it into the .exe (the scripts are read from disk at run time).
import argparse  # noqa: F401
import collections  # noqa: F401
import copy  # noqa: F401
import csv  # noqa: F401  (analytics and export CSV files)
import ctypes  # noqa: F401
import glob  # noqa: F401
import hashlib  # noqa: F401  (Phase 9 history; already in the v1.x .exe, so no rebuild was needed)
import math  # noqa: F401
import random  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401
import stat  # noqa: F401
import statistics  # noqa: F401
import subprocess  # noqa: F401
import time  # noqa: F401
import tkinter  # noqa: F401
import tkinter.colorchooser  # noqa: F401
import tkinter.filedialog  # noqa: F401
import tkinter.font  # noqa: F401
import tkinter.messagebox  # noqa: F401
import tkinter.simpledialog  # noqa: F401
import tkinter.ttk  # noqa: F401
import zipfile  # noqa: F401  (Phase 9 project backups; already in the v1.x .exe)
import cv2  # noqa: F401
import numpy  # noqa: F401
from PIL import (Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps,  # noqa: F401
                 ImageSequence, ImageTk)

DEFAULT_SCRIPTS = os.path.join(os.path.expanduser("~"), ".claude", "skills", "stickman-reference-animation", "scripts")


def home():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


def documents():
    """Documents\\Stickman Studio: where a fresh install keeps its work (never inside Program Files)."""
    return os.path.join(os.path.expanduser("~"), "Documents", "Stickman Studio")


def log_path():
    """error.log next to the .exe, or in Documents\\Stickman Studio when that folder can't be written to."""
    if os.access(home(), os.W_OK):
        return os.path.join(home(), "error.log")
    os.makedirs(documents(), exist_ok=True)
    return os.path.join(documents(), "error.log")


def load_config():
    cfg = {"scripts": [os.path.join(home(), "app"), DEFAULT_SCRIPTS],
           "images": os.path.join(documents(), "Images"),
           "settings": os.path.join(documents(), "Game Settings"),
           "unity": ""}
    try:
        with open(os.path.join(home(), "config.json"), encoding="utf-8-sig") as fh:   # Notepad may add a BOM
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    if isinstance(cfg["scripts"], str):
        cfg["scripts"] = [cfg["scripts"]]
    return cfg


def show_error(text):
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    try:
        import tkinter.messagebox as mb
        r = tkinter.Tk()
        r.withdraw()
        mb.showerror("Stickman Studio", text[-1500:] + f"\n\n(Also saved in {log_path()})")
        r.destroy()
    except Exception:
        pass


def tk_error(self, exc, val, tb):
    """Errors inside the window: log them and show them, instead of losing them (there's no console)."""
    text = "".join(traceback.format_exception(exc, val, tb))
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    try:
        import tkinter.messagebox as mb
        mb.showerror("Stickman Studio", f"Something went wrong:\n\n{val}\n\nDetails are in {log_path()}", parent=self)
    except Exception:
        pass


def main():
    if sys.stdout is None or sys.stderr is None:   # a windowed .exe has no console: keep prints from crashing
        out = open(os.path.join(os.path.dirname(log_path()), "output.log"), "a", encoding="utf-8")
        sys.stdout = sys.stdout or out
        sys.stderr = sys.stderr or out
    args = sys.argv[1:]

    # standing in for python.exe:  Stickman Studio.exe -I some_script.py args
    rest = args[1:] if args and args[0] == "-I" else args
    if rest and rest[0].lower().endswith(".py") and os.path.isfile(rest[0]):
        script = os.path.abspath(rest[0])
        sys.argv = [script] + rest[1:]
        sys.path.insert(0, os.path.dirname(script))
        runpy.run_path(script, run_name="__main__")
        return 0

    cfg = load_config()
    scripts = next((d for d in cfg["scripts"] if os.path.isfile(os.path.join(d, "studio.py"))), None)
    if not scripts:
        show_error("Can't find studio.py. Looked in:\n  " + "\n  ".join(cfg["scripts"]) +
                   "\n\nPut the right folder in config.json next to Stickman Studio.exe.")
        return 1
    tkinter.Tk.report_callback_exception = tk_error
    sys.path.insert(0, scripts)
    studio = os.path.join(scripts, "studio.py")
    flags = ["--images", cfg["images"], "--settings", cfg["settings"]]
    if cfg.get("unity"):
        flags += ["--unity", cfg["unity"]]
    ico = os.path.join(scripts, "studio.ico")
    if os.path.exists(ico):
        flags += ["--icon", ico]
    os.makedirs(cfg["images"], exist_ok=True)
    sys.argv = [studio] + flags + args
    runpy.run_path(studio, run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    except Exception:
        show_error(traceback.format_exc())
        code = 1
    sys.exit(code)
