@echo off
REM Builds FoxReader.exe on Windows. Needs Python 3.10+.
REM Optional: put ffmpeg.exe in this folder first and it is bundled into the app (used for the equalizer, bitrate, graphs).
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :err
set EXTRA=
if exist ffmpeg.exe set EXTRA=--add-binary "ffmpeg.exe;."
python -m PyInstaller --noconfirm --clean --windowed --name FoxReader --icon logo.png --add-data "logo.png;." %EXTRA% foxreader.py || goto :err
echo.
echo Done: dist\FoxReader\FoxReader.exe
pause & exit /b 0
:err
echo Build failed.
pause & exit /b 1
