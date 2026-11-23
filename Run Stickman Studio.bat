@echo off
rem Run Stickman Studio from the source code (needs Python 3.11+ and:  py -m pip install -r requirements.txt).
rem Your work is saved in Documents\Stickman Studio. Drag a video, GIF or pictures onto this file to open them.
python "%~dp0stickman_studio\studio.py" %*
if errorlevel 1 pause
