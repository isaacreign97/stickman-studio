# Third-party notices

Stickman Studio's own code is under the MIT licence (see `LICENSE`). The Windows download also contains these
third-party components, each under its own licence:

| Component | Version in the download | Licence | Where to get it |
|---|---|---|---|
| Python | 3.14 | Python Software Foundation License | https://www.python.org |
| Tcl/Tk (the window toolkit) | 8.6 | Tcl/Tk License (BSD-style) | https://www.tcl.tk |
| Pillow | 13.0 | MIT-CMU (HPND) License | https://python-pillow.org |
| NumPy (incl. OpenBLAS) | 2.5 | BSD 3-Clause | https://numpy.org |
| OpenCV (`opencv-python`) | 5.0 | Apache License 2.0 | https://opencv.org, https://github.com/opencv/opencv-python |
| FFmpeg (inside OpenCV, `opencv_videoio_ffmpeg*.dll`) | as shipped with opencv-python 5.0 | LGPL 2.1 or later | https://ffmpeg.org |
| PyInstaller bootloader | 6.22 | GPL 2.0 with the bootloader exception (allows distribution) | https://pyinstaller.org |

**FFmpeg (LGPL):** FFmpeg is used unmodified, as the separate library file `opencv_videoio_ffmpeg*.dll` that
comes with OpenCV. You may replace that file with another compatible build. Its source code and licence are
available from https://ffmpeg.org and from the opencv-python project.

The full licence texts of the Python packages are inside the download's `_internal` folder (the
`*.dist-info` folders), and on the projects' websites listed above.

Stickman Studio uses no AI, machine learning or pose detection, and it sends nothing over the internet.
