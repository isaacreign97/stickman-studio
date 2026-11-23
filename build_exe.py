"""Build the Windows download: dist\\Stickman Studio\\ (Stickman Studio.exe + app\\) and a release .zip.

usage:  python build_exe.py            (needs:  pip install -r requirements.txt pyinstaller)

The .exe is a small launcher with its own Python, Tk, Pillow, OpenCV and numpy built in (stickman_studio\\studio_exe.py).
It runs the studio's scripts from the app\\ folder next to it, so the download needs no Python install.
Work is kept in Documents\\Stickman Studio unless a config.json next to the .exe says otherwise.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "stickman_studio")
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")
NAME = "Stickman Studio"


def version():
    with open(os.path.join(APP, "studio.py"), encoding="utf-8") as fh:
        return re.search(r'^VERSION = "([^"]+)"', fh.read(), re.M).group(1)


def main():
    ver = version()
    out = os.path.join(DIST, NAME)
    if os.path.exists(out):
        shutil.rmtree(out)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
           "--name", NAME, "--icon", os.path.join(APP, "studio.ico"), "--distpath", DIST, "--workpath", WORK,
           "--specpath", WORK, "--exclude-module", "matplotlib", "--exclude-module", "IPython",
           "--exclude-module", "pytest", os.path.join(APP, "studio_exe.py")]
    if subprocess.run(cmd).returncode:
        print("PyInstaller failed.")
        return 1
    app = os.path.join(out, "app")
    os.makedirs(app)
    for n in sorted(os.listdir(APP)):
        if os.path.splitext(n)[1].lower() in (".py", ".ico", ".png") and n != "studio_exe.py":
            shutil.copyfile(os.path.join(APP, n), os.path.join(app, n))
    for n in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(os.path.join(ROOT, n), os.path.join(out, n))
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Stickman Studio {ver}\r\n\r\nDouble-click \"{NAME}.exe\" to start. Keep this whole folder together "
                 "(the app and _internal folders are part of it).\r\nYour work is saved in Documents\\Stickman Studio."
                 "\r\nYou can drag a video, GIF or pictures onto the .exe to open them in Source.\r\n\r\n"
                 "Help, updates and source code: see the GitHub page this came from.\r\n")
    z = os.path.join(DIST, f"Stickman-Studio-{ver}-windows-x64.zip")
    if os.path.exists(z):
        os.remove(z)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for base, _, files in os.walk(out):
            for n in files:
                p = os.path.join(base, n)
                zf.write(p, os.path.relpath(p, DIST))
    print(f"\nBuilt {out}\nZip   {z}  ({os.path.getsize(z) / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
