#!/usr/bin/env python3
"""FoxReader - desktop media player with a VLC-style UI.

Needs:  pip install PySide6 numpy      (+ ffmpeg for bitrate/resolution/graphs)
Run:    python foxreader.py  [files...]
"""
import sys
import os as _os; _os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")     # play with Qt's FFmpeg engine (same codecs as ffmpeg, no VLC / Windows codecs needed)
if len(sys.argv) > 2 and sys.argv[1] == "--sandbox-exec":   # child process of the code sandbox: set limits, then become the program to run
    import os, subprocess
    cmd = sys.argv[2:]
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15)); resource.setrlimit(resource.RLIMIT_FSIZE, (20 << 20, 20 << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if os.environ.pop("FOX_SANDBOX_AS", ""): resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    except (ImportError, ValueError, OSError): os.environ.pop("FOX_SANDBOX_AS", None)
    if os.name == "nt": sys.exit(subprocess.run(cmd).returncode)
    os.execvp(cmd[0], cmd)
import codecs, hashlib, ipaddress, json, os, random, re, select, shutil, socket, socketserver, struct, subprocess, tempfile, threading, time
from pathlib import Path
import numpy as np
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, Property, Qt, QTimer, Signal, QObject, QUrl, QProcess, QProcessEnvironment, QSettings, QStandardPaths, QCoreApplication, QEvent
from PySide6.QtGui import (QTransform, QAction, QColor, QPainter, QPen, QKeySequence, QPixmap, QIcon, QPolygonF, QPainterPath,
    QLinearGradient, QBrush, QFontDatabase, QSyntaxHighlighter, QTextCharFormat, QFont, QTextCursor)
from PySide6.QtCore import QPointF, QRectF, QSize, QPoint
from PySide6.QtGui import QCursor, QShortcut, QActionGroup
from PySide6.QtNetwork import QNetworkProxy
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QGraphicsOpacityEffect, QMenu, QInputDialog, QDialog, QDialogButtonBox, QCheckBox
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QListWidget, QListWidgetItem, QDockWidget, QFileDialog, QStackedWidget, QFrame,
    QComboBox, QGridLayout, QMessageBox, QPlainTextEdit, QTextBrowser, QSplitter, QScrollArea, QTabBar, QToolButton, QLineEdit, QProgressBar)
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings, QWebEngineUrlRequestInterceptor
    HAVE_WEB = True
except ImportError:
    HAVE_WEB = False

if sys.platform.startswith("win"):      # never pop up a black console window when ffmpeg (or any helper) is started
    _Popen = subprocess.Popen
    class _QuietPopen(_Popen):
        def __init__(self, *a, **k):
            k["creationflags"] = k.get("creationflags", 0) | 0x08000000      # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _QuietPopen

FROZEN = getattr(sys, "frozen", False)      # True when running as the built .exe
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent     # user data lives next to the program
RES = Path(getattr(sys, "_MEIPASS", BASE))   # bundled files (the logo)
SONGS, CACHE, LOGO = BASE / "songs", BASE / ".cache", RES / "logo.png"
DRAFTS = BASE / "cache-file"       # auto-saved copies of text being edited + the list of open web pages (the original files are never touched)
SONGS.mkdir(exist_ok=True); CACHE.mkdir(exist_ok=True); DRAFTS.mkdir(exist_ok=True)
def _find_ffmpeg():
    """ffmpeg next to the program (or bundled in the .exe) first, then the PATH."""
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    for d in (BASE, RES, BASE / "ffmpeg", BASE / "ffmpeg" / "bin"):
        if (d / exe).is_file(): return str(d / exe)
    return shutil.which("ffmpeg")
FFMPEG = _find_ffmpeg()
VIDEO_EXT = {".mp4", ".m4v", ".webm", ".ogv", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".mpg", ".mpeg", ".3gp", ".3g2", ".vob", ".m2ts", ".mts", ".divx", ".xvid", ".asf", ".rm", ".rmvb", ".f4v", ".ogm", ".dv", ".mxf", ".mpv", ".m2v", ".qt", ".wtv", ".amv", ".nsv", ".gxf", ".vro", ".trp", ".tp", ".tod"}
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".flac", ".weba", ".wma", ".aiff", ".aif",
             ".ape", ".amr", ".mka", ".mpc", ".wv", ".ac3", ".dsf", ".dsd", ".mp2", ".mp1", ".m4b", ".m4r", ".spx", ".tta", ".au", ".snd",
             ".ra", ".dts", ".eac3", ".caf", ".mid", ".midi", ".kar", ".mod", ".xm", ".it", ".s3m", ".mlp", ".thd", ".oma", ".gsm", ".wax", ".mp4a"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".svg", ".ppm", ".pgm", ".pbm", ".pnm", ".jfif", ".jfi", ".jp2", ".j2k", ".jpx", ".jxl", ".avif", ".heic", ".heif", ".tga", ".dds", ".icns", ".wbmp", ".xbm", ".xpm", ".svgz", ".pcx", ".psd", ".exr", ".hdr", ".apng", ".mng",
             ".cr2", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}
PLAYLIST_EXT = {".m3u", ".m3u8", ".pls"}
CODE_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".py", ".java"}
TEXT_EXT = {".txt", ".md", ".markdown"} | CODE_EXT
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT | IMAGE_EXT | TEXT_EXT
SLIDE_SECONDS = 4
AUTOSAVE_SECONDS = 8           # changed text is copied to the cache-file folder this often
SESSION_SECONDS = 25           # the open web addresses are saved this often
HIDE_CONTROLS_SECONDS = 3      # video controls hide after this many seconds without mouse movement
BITRATES = [0, 64, 96, 128, 192, 256, 320]
RESOLUTIONS = [0, 240, 360, 480, 720, 1080]
SR = 44100
PRESETS = {"Flat": (0, 0, 0, 0), "Bass Boost": (9, 3, -1, 0), "Vocal": (-3, 1, 6, 2),
           "Treble Boost": (-2, -1, 2, 8), "Party": (7, 0, 1, 5)}
# 4 user sliders -> 10 equalizer bands
BAND_MAP = [0, 0, 0, 1, 1, 2, 2, 2, 3, 3]
RANGES = [(20, 250), (250, 800), (800, 4000), (4000, 16000)]

STYLE = """
QMainWindow, QWidget { background:#fdfcfa; color:#2b3d4a; font-size:13px; }
QMenuBar { background:#fdfcfa; padding:4px 8px; } QMenuBar::item { padding:4px 8px; border-radius:4px; }
QMenuBar::item:selected, QMenu::item:selected { background:#e8f3fc; color:#1f6fae; }
QMenu { background:#fff; border:1px solid #e3e8ec; padding:4px; } QMenu::item { padding:4px 24px; border-radius:4px; }
QPushButton { background:transparent; border:none; border-radius:6px; padding:8px; }
QPushButton:hover { background:#e8f3fc; } QPushButton:pressed { background:#d6eafa; }
QPushButton#primary { background:#3aa6ee; color:#fff; padding:8px 16px; font-weight:600; }
QPushButton#primary:hover { background:#2f94da; }
QSlider::groove:horizontal { height:4px; background:#e3e8ec; border-radius:2px; }
QSlider::sub-page:horizontal { background:#3aa6ee; border-radius:2px; }
QSlider::handle:horizontal { background:#fff; border:2px solid #3aa6ee; width:8px; margin:-6px 0; border-radius:6px; }
QSlider#seek::handle:horizontal { background:#ff8a2b; border:2px solid #fff; width:10px; margin:-7px 0; border-radius:7px; }
QSlider::groove:vertical { width:4px; background:#e3e8ec; border-radius:2px; }
QSlider::add-page:vertical { background:#3aa6ee; border-radius:2px; }
QSlider::handle:vertical { background:#fff; border:2px solid #3aa6ee; height:8px; margin:0 -6px; border-radius:6px; }
QListWidget { background:#fdfcfa; border:none; padding:4px; outline:0; }
QListWidget::item { padding:8px; border-radius:6px; } QListWidget::item:hover { background:#f1f6fa; }
QListWidget::item:selected { background:#e8f3fc; color:#1f6fae; }
QDockWidget::title { background:#fdfcfa; padding:8px 12px; font-weight:600; border-bottom:1px solid #e3e8ec; }
QComboBox { background:#fff; border:1px solid #e3e8ec; border-radius:6px; padding:4px 8px; }
QStatusBar { background:#fdfcfa; color:#6b7f8c; border-top:1px solid #e3e8ec; }
QLabel { background:transparent; }
QPlainTextEdit, QTextBrowser { background:#fff; border:1px solid #e3e8ec; border-radius:6px; padding:10px; selection-background-color:#cfe6f8; selection-color:#1f3a4d; }
QPushButton#tool { background:#fff; border:1px solid #e3e8ec; padding:6px 14px; } QPushButton#tool:hover { background:#e8f3fc; }
QPushButton#run { background:#2f9e44; color:#fff; padding:6px 16px; font-weight:600; } QPushButton#run:hover { background:#278a3a; }
QPushButton#run[running="true"] { background:#d6336c; } QPushButton#run[running="true"]:hover { background:#bd2b5e; }
QPushButton#card { background:#fff; border:1px solid #e3e8ec; border-radius:12px; text-align:center; }
QPushButton#card:hover { background:#f3f9fe; border-color:#3aa6ee; } QPushButton#card:pressed { background:#e8f3fc; }
QPushButton#recent { color:#1f6fae; text-align:left; padding:4px 10px; } QPushButton#recent:hover { background:#e8f3fc; }
QScrollArea { background:transparent; }
QPushButton#tool:checked { background:#e8f3fc; border-color:#3aa6ee; color:#1f6fae; font-weight:600; }
QLineEdit { background:#fff; border:1px solid #e3e8ec; border-radius:16px; padding:6px 14px; selection-background-color:#cfe6f8; selection-color:#1f3a4d; }
QLineEdit:focus { border:1px solid #3aa6ee; }
QProgressBar#webprog { border:none; background:transparent; } QProgressBar#webprog::chunk { background:#3aa6ee; }
QFrame#tabwrap { background:#fdfcfa; border:none; border-bottom:1px solid #e3e8ec; }
QTabBar { background:transparent; }
QTabBar::tab { background:transparent; color:#6b7f8c; font-size:14px; font-weight:600; padding:10px 22px; margin-right:6px; border:none; border-bottom:3px solid transparent; }
QTabBar::tab:hover { color:#1f6fae; background:#f3f9fe; }
QTabBar::tab:selected { color:#1f6fae; border-bottom:3px solid #3aa6ee; }
QToolButton#addtab { background:transparent; border:none; border-radius:6px; padding:0 10px; font-size:22px; font-weight:600; color:#6b7f8c; }
QToolButton#tabclose { background:transparent; border:none; border-radius:10px; } QToolButton#tabclose:hover { background:#d6eafa; }
QToolButton#addtab:hover { background:#e8f3fc; color:#1f6fae; }
QLabel#home_title { font-size:30px; font-weight:700; color:#2f4a5c; }
QLabel#home_sub, QLabel#home_hint, QLabel#card_desc, QLabel#code_desc, QLabel#code_tip, QLabel#recent_head { color:#6b7f8c; }
QLabel#home_sub { font-size:16px; } QLabel#card_desc { font-size:11px; }
QLabel#card_name { font-size:15px; font-weight:600; } QLabel#recent_head { font-weight:600; margin-top:12px; }
QLabel#code_title { font-size:26px; font-weight:700; color:#2f4a5c; } QLabel#code_desc { font-size:14px; }
QLabel#code_tip { margin-top:6px; }
"""

DARK_STYLE = """
QMainWindow, QWidget { background:#171a1f; color:#dce6ed; font-size:13px; }
QMenuBar { background:#171a1f; padding:4px 8px; } QMenuBar::item { padding:4px 8px; border-radius:4px; }
QMenuBar::item:selected, QMenu::item:selected { background:#263746; color:#76bdf0; }
QMenu { background:#20252b; border:1px solid #35414b; padding:4px; } QMenu::item { padding:4px 24px; border-radius:4px; }
QPushButton { background:transparent; color:#dce6ed; border:none; border-radius:6px; padding:8px; }
QPushButton:hover { background:#263746; } QPushButton:pressed { background:#304656; }
QPushButton#primary { background:#3aa6ee; color:#fff; padding:8px 16px; font-weight:600; }
QPushButton#primary:hover { background:#4bb2f5; }
QSlider::groove:horizontal { height:4px; background:#35414b; border-radius:2px; }
QSlider::sub-page:horizontal { background:#3aa6ee; border-radius:2px; }
QSlider::handle:horizontal { background:#dce6ed; border:2px solid #3aa6ee; width:8px; margin:-6px 0; border-radius:6px; }
QSlider#seek::handle:horizontal { background:#ff8a2b; border:2px solid #dce6ed; width:10px; margin:-7px 0; border-radius:7px; }
QSlider::groove:vertical { width:4px; background:#35414b; border-radius:2px; }
QSlider::add-page:vertical { background:#3aa6ee; border-radius:2px; }
QSlider::handle:vertical { background:#dce6ed; border:2px solid #3aa6ee; height:8px; margin:0 -6px; border-radius:6px; }
QListWidget { background:#171a1f; border:none; padding:4px; outline:0; }
QListWidget::item { padding:8px; border-radius:6px; } QListWidget::item:hover { background:#20282f; }
QListWidget::item:selected { background:#263746; color:#76bdf0; }
QDockWidget::title { background:#171a1f; color:#dce6ed; padding:8px 12px; font-weight:600; border-bottom:1px solid #35414b; }
QComboBox { background:#20252b; color:#dce6ed; border:1px solid #35414b; border-radius:6px; padding:4px 8px; }
QComboBox QAbstractItemView { background:#20252b; color:#dce6ed; selection-background-color:#263746; selection-color:#76bdf0; }
QStatusBar { background:#171a1f; color:#9fb0bd; border-top:1px solid #35414b; }
QLabel { background:transparent; }
QPlainTextEdit, QTextBrowser { background:#20252b; color:#dce6ed; border:1px solid #35414b; border-radius:6px; padding:10px; selection-background-color:#31566f; selection-color:#fff; }
QPushButton#tool { background:#20252b; color:#dce6ed; border:1px solid #35414b; padding:6px 14px; } QPushButton#tool:hover { background:#263746; }
QPushButton#run { background:#2f9e44; color:#fff; padding:6px 16px; font-weight:600; } QPushButton#run:hover { background:#278a3a; }
QPushButton#run[running="true"] { background:#d6336c; } QPushButton#run[running="true"]:hover { background:#bd2b5e; }
QPushButton#card { background:#20252b; border:1px solid #35414b; border-radius:12px; text-align:center; }
QPushButton#card:hover { background:#263746; border-color:#3aa6ee; } QPushButton#card:pressed { background:#304656; }
QPushButton#recent { color:#76bdf0; text-align:left; padding:4px 10px; } QPushButton#recent:hover { background:#263746; }
QScrollArea { background:transparent; }
QPushButton#tool:checked { background:#263746; border-color:#3aa6ee; color:#76bdf0; font-weight:600; }
QLineEdit { background:#20252b; color:#dce6ed; border:1px solid #35414b; border-radius:16px; padding:6px 14px; selection-background-color:#31566f; selection-color:#fff; }
QLineEdit:focus { border:1px solid #3aa6ee; }
QProgressBar#webprog { border:none; background:transparent; } QProgressBar#webprog::chunk { background:#3aa6ee; }
QFrame#tabwrap { background:#171a1f; border:none; border-bottom:1px solid #35414b; }
QTabBar { background:transparent; }
QTabBar::tab { background:transparent; color:#9fb0bd; font-size:14px; font-weight:600; padding:10px 22px; margin-right:6px; border:none; border-bottom:3px solid transparent; }
QTabBar::tab:hover { color:#76bdf0; background:#20282f; }
QTabBar::tab:selected { color:#76bdf0; border-bottom:3px solid #3aa6ee; }
QToolButton#addtab { background:transparent; border:none; border-radius:6px; padding:0 10px; font-size:22px; font-weight:600; color:#9fb0bd; }
QToolButton#tabclose { background:transparent; border:none; border-radius:10px; } QToolButton#tabclose:hover { background:#304656; }
QToolButton#addtab:hover { background:#263746; color:#76bdf0; }
QLabel#home_title { font-size:30px; font-weight:700; color:#dce6ed; }
QLabel#home_sub, QLabel#home_hint, QLabel#card_desc, QLabel#code_desc, QLabel#code_tip, QLabel#recent_head { color:#9fb0bd; }
QLabel#home_sub { font-size:16px; } QLabel#home_hint { } QLabel#card_desc { font-size:11px; }
QLabel#card_name { font-size:15px; font-weight:600; } QLabel#recent_head { font-weight:600; margin-top:12px; }
QLabel#code_title { font-size:26px; font-weight:700; color:#dce6ed; } QLabel#code_desc { font-size:14px; }
QLabel#code_tip { margin-top:6px; }
"""


def fmt(ms):
    s = max(0, int(ms // 1000)); h, r = divmod(s, 3600)
    return f"{h}:{r // 60:02d}:{r % 60:02d}" if h else f"{r // 60}:{r % 60:02d}"



INK = "#2f4a5c"
def icon(name, color=INK, size=20):
    pm = QPixmap(size * 2, size * 2); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.scale(size * 2 / 20, size * 2 / 20)
    p.setPen(Qt.NoPen); p.setBrush(QColor(color)); pen = QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    poly = lambda *pts: p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    if name == "play": poly((6, 3.5), (16, 10), (6, 16.5))
    elif name == "pause": p.drawRoundedRect(QRectF(5, 4, 3.6, 12), 1, 1); p.drawRoundedRect(QRectF(11.4, 4, 3.6, 12), 1, 1)
    elif name == "stop": p.drawRoundedRect(QRectF(5, 5, 10, 10), 1.5, 1.5)
    elif name == "next": poly((5, 4), (13, 10), (5, 16)); p.drawRoundedRect(QRectF(13.5, 4, 2.2, 12), 1, 1)
    elif name == "prev": poly((15, 4), (7, 10), (15, 16)); p.drawRoundedRect(QRectF(4.3, 4, 2.2, 12), 1, 1)
    elif name == "fs":
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        for (x, y, dx, dy) in ((3.5, 3.5, 1, 1), (16.5, 3.5, -1, 1), (3.5, 16.5, 1, -1), (16.5, 16.5, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 4 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 4 * dy))
    elif name == "eq":
        p.setPen(pen)
        for x, k in ((5, 6), (10, 12), (15, 8)):
            p.drawLine(QPointF(x, 3.5), QPointF(x, 16.5)); p.setBrush(QColor("#fff")); p.drawEllipse(QPointF(x, k), 2.2, 2.2)
    elif name == "list":
        p.setPen(pen)
        for y in (5, 10, 15): p.drawLine(QPointF(4, y), QPointF(16, y))
    elif name == "vol":
        poly((3, 8), (6.5, 8), (11, 4), (11, 16), (6.5, 12), (3, 12))
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawArc(QRectF(8, 6, 8, 8), -50 * 16, 100 * 16); p.drawArc(QRectF(6, 3.5, 13, 13), -50 * 16, 100 * 16)
    elif name == "music":
        p.drawEllipse(QPointF(7.5, 14.5), 3, 2.4); p.setPen(pen); p.drawLine(QPointF(10.2, 14), QPointF(10.2, 4)); p.drawLine(QPointF(10.2, 4), QPointF(15, 6))
    elif name == "video":
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(3.5, 5, 13, 10), 2, 2)
        p.setPen(Qt.NoPen); p.setBrush(QColor(color)); poly((8.5, 7.5), (12.5, 10), (8.5, 12.5))
    elif name == "image":
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(3.5, 4.5, 13, 11), 2, 2)
        p.setPen(Qt.NoPen); p.setBrush(QColor(color)); p.drawEllipse(QPointF(7.5, 8.2), 1.5, 1.5)
        poly((4.5, 14.5), (8.5, 10.5), (11, 13), (13, 11), (15.5, 14.5))
    elif name == "folder":
        p.setPen(pen); p.setBrush(Qt.NoBrush); fp = QPainterPath(QPointF(3, 5.5)); [fp.lineTo(QPointF(x, y)) for x, y in ((8, 5.5), (9.8, 7.5), (17, 7.5), (17, 15.5), (3, 15.5))]
        fp.closeSubpath(); p.drawPath(fp)
    elif name == "files":
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(7.5, 3.5, 9, 10), 1.8, 1.8); p.drawRoundedRect(QRectF(3.5, 6.5, 9, 10), 1.8, 1.8)
    elif name == "home":
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(2.5, 10), QPointF(10, 3.5), QPointF(17.5, 10)]))
        p.drawPolyline(QPolygonF([QPointF(5, 8.5), QPointF(5, 16.5), QPointF(15, 16.5), QPointF(15, 8.5)]))
    elif name == "code":
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(7.5, 5.5), QPointF(3, 10), QPointF(7.5, 14.5)]))
        p.drawPolyline(QPolygonF([QPointF(12.5, 5.5), QPointF(17, 10), QPointF(12.5, 14.5)]))
        p.drawLine(QPointF(11, 4), QPointF(9, 16))
    elif name == "web":
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawEllipse(QPointF(10, 10), 7, 7); p.drawEllipse(QPointF(10, 10), 3.2, 7); p.drawLine(QPointF(3, 10), QPointF(17, 10))
    elif name in ("back", "fwd"):
        p.setPen(pen); p.setBrush(Qt.NoBrush); d = 1 if name == "back" else -1; x0 = 3.5 if name == "back" else 16.5
        p.drawLine(QPointF(x0, 10), QPointF(x0 + d * 13, 10)); p.drawPolyline(QPolygonF([QPointF(x0 + d * 5.5, 4.5), QPointF(x0, 10), QPointF(x0 + d * 5.5, 15.5)]))
    elif name == "reload":
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawArc(QRectF(4, 4, 12, 12), 60 * 16, 280 * 16)
        p.drawPolyline(QPolygonF([QPointF(11.5, 2.8), QPointF(14.8, 4.6), QPointF(12.6, 7.8)]))
    elif name == "close":
        p.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap)); p.drawLine(QPointF(6, 6), QPointF(14, 14)); p.drawLine(QPointF(14, 6), QPointF(6, 14))
    elif name == "text":
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(4.5, 3, 11, 14), 2, 2)
        for y in (7, 10, 13): p.drawLine(QPointF(7, y), QPointF(13, y))
    p.end(); pm.setDevicePixelRatio(2); return QIcon(pm)


def smooth_path(pts, start=None):
    """Smooth curve through pts (Catmull-Rom converted to cubic beziers)."""
    path = QPainterPath(pts[0] if start is None else start)
    if start is not None: path.lineTo(pts[0])
    n = len(pts)
    for i in range(n - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, n - 1)]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6, p1.y() + (p2.y() - p0.y()) / 6)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6, p2.y() - (p3.y() - p1.y()) / 6)
        path.cubicTo(c1, c2, p2)
    return path


def draft_path(path): return DRAFTS / (hashlib.sha1(os.path.abspath(path).encode("utf-8", "replace")).hexdigest()[:16] + ".draft.json")

def write_json(p, obj):
    tmp = Path(str(p) + ".tmp"); tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, p)

def read_json(p):
    try: d = json.loads(Path(p).read_text(encoding="utf-8")); return d if isinstance(d, dict) else None
    except (OSError, ValueError): return None

def discard_draft(path):
    try: draft_path(path).unlink()
    except OSError: pass

def disk_text(path):
    """The text of a file the way the editor shows it (same encodings as TextView.load)."""
    data = Path(path).read_bytes(); enc = "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8"
    for e in (enc, "cp874", "latin-1"):
        try: return data.decode(e).replace("\r\n", "\n")
        except UnicodeDecodeError: pass
    return ""


ANIM_MS = 220    # length of the interface animations (0 turns them off)

def fade_in(w, ms=None):
    """Fade a plain (non-video, non-web) widget in. The effect is removed afterwards so it costs nothing."""
    if not ANIM_MS or not w.isVisible(): return
    ms = ms or ANIM_MS
    fx = QGraphicsOpacityEffect(w); fx.setOpacity(0.0); w.setGraphicsEffect(fx)
    a = QPropertyAnimation(fx, b"opacity", w); a.setDuration(ms); a.setStartValue(0.0); a.setEndValue(1.0); a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: w.setGraphicsEffect(None)); a.start(QPropertyAnimation.DeleteWhenStopped); w._fade = a


class QtPlayer(QObject):
    """Media player built on Qt Multimedia (no VLC needed). Small VLC-like API so the rest of the app stays simple."""
    def __init__(self):
        super().__init__(); self.p = QMediaPlayer(); self.ao = QAudioOutput(); self.p.setAudioOutput(self.ao)
        self._at = 0; self._ended = False; self.p.mediaStatusChanged.connect(self._status)

    def _status(self, st):
        M = QMediaPlayer.MediaStatus
        if st == M.LoadedMedia and self._at: self.p.setPosition(int(self._at)); self._at = 0
        elif st == M.EndOfMedia: self._ended = True
    def take_ended(self): e, self._ended = self._ended, False; return e
    def set_video(self, widget): self.p.setVideoOutput(widget)
    def set_media(self, path, at=0): self._ended = False; self._at = at; self.p.setSource(QUrl.fromLocalFile(path))
    def play(self): self.p.play()
    def pause(self): self.p.pause() if self.is_playing() else self.p.play()
    def set_pause(self, on): self.p.pause() if on else self.p.play()
    def stop(self): self._at = 0; self.p.stop()
    def is_playing(self): return self.p.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    def get_time(self): return int(self.p.position())
    def get_length(self): return int(self.p.duration())
    def is_seekable(self): return self.p.isSeekable()
    def set_time(self, ms): self.p.setPosition(int(ms))
    def set_position(self, f): self.p.setPosition(int(f * max(0, self.p.duration())))
    def audio_set_volume(self, v): self.ao.setVolume(max(0, min(100, v)) / 100)
    def audio_toggle_mute(self): self.ao.setMuted(not self.ao.isMuted())


class Toast(QFrame):
    """A small popup in the bottom-right corner of the window, with buttons and an optional countdown."""
    def __init__(self, win):
        super().__init__(win, Qt.Tool | Qt.FramelessWindowHint); self.win = win; self.on_timeout = None
        self.setAttribute(Qt.WA_ShowWithoutActivating); self.setObjectName("toast"); self.setFixedWidth(370)
        self.setStyleSheet("QFrame#toast{background:#2b3d4a;border-radius:10px;} QLabel{color:#fff;background:transparent;} QLabel#tt{font-size:15px;font-weight:700;} QLabel#tx{color:#c9d6df;}"
            "QPushButton{background:#3aa6ee;color:#fff;border:none;border-radius:6px;padding:7px 12px;font-weight:600;} QPushButton:hover{background:#2f94da;}"
            "QPushButton#plain{background:transparent;color:#c9d6df;border:1px solid #56687a;} QPushButton#plain:hover{background:#38505f;}")
        self.tt = QLabel(); self.tt.setObjectName("tt"); self.tt.setWordWrap(True); self.tx = QLabel(); self.tx.setObjectName("tx"); self.tx.setWordWrap(True)
        self.row = QHBoxLayout(); self.row.setSpacing(8); lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)
        lay.addWidget(self.tt); lay.addWidget(self.tx); lay.addLayout(self.row)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.expire); win.installEventFilter(self)

    def show_msg(self, title, text, buttons, ms=0, on_timeout=None):
        """buttons: [(label, function, quiet)]. Clicking one closes the popup, then runs the function."""
        while self.row.count():
            w = self.row.takeAt(0).widget()
            if w: w.hide(); w.deleteLater()
        self.tt.setText(title); self.tx.setText(text)
        for label, fn, quiet in buttons:
            b = QPushButton(label); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
            if quiet: b.setObjectName("plain")
            b.clicked.connect(lambda _=0, f=fn: (self.hide_toast(), f and f())); self.row.addWidget(b)
        self.on_timeout = on_timeout; self.layout().activate(); self.setFixedHeight(self.layout().totalHeightForWidth(self.width()))
        self.place(); self.animate_in(); self.raise_(); self.timer.start(ms) if ms else self.timer.stop()

    def place(self):
        w = self.win; tl = w.mapToGlobal(QPoint(0, 0)); self.move(tl.x() + w.width() - self.width() - 22, tl.y() + w.height() - self.height() - 52)

    def animate_in(self):
        if hasattr(self, "grp"): self.grp.stop()
        if not ANIM_MS: self.show(); return
        end = self.pos(); self.setWindowOpacity(0.0); self.move(end.x(), end.y() + 24); self.show()
        self.grp = QParallelAnimationGroup(self)
        for prop, a, b in ((b"windowOpacity", 0.0, 1.0), (b"pos", QPoint(end.x(), end.y() + 24), end)):
            an = QPropertyAnimation(self, prop); an.setDuration(ANIM_MS + 80); an.setStartValue(a); an.setEndValue(b); an.setEasingCurve(QEasingCurve.OutCubic); self.grp.addAnimation(an)
        self.grp.start()

    def hide_toast(self):
        self.timer.stop(); self.on_timeout = None
        if hasattr(self, "grp"): self.grp.stop()
        if not ANIM_MS or not self.isVisible(): self.hide(); return
        a = QPropertyAnimation(self, b"windowOpacity", self); a.setDuration(160); a.setStartValue(self.windowOpacity()); a.setEndValue(0.0)
        a.finished.connect(lambda: (self.hide(), self.setWindowOpacity(1.0))); a.start(QPropertyAnimation.DeleteWhenStopped); self.grp = a
    def expire(self): cb = self.on_timeout; self.hide_toast(); cb and cb()
    def eventFilter(self, o, e):
        if o is self.win and self.isVisible() and e.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange): self.place()
        return False


class Bus(QObject):
    transcoded = Signal(str, int, bool, int)   # path, resume ms, play, generation
    analyzed = Signal(object, str)        # pcm, path
    failed = Signal(str)


class Visualizer(QWidget):
    """Shows spectrum + bass/music history (audio files) like a VLC visualisation."""
    def __init__(self, player):
        super().__init__(); self.p = player; self.setMinimumSize(320, 200)
        self.bars = np.zeros(64); self.bass, self.music = [], []

    def update_data(self, pcm, ms, gains):
        if pcm is None or len(pcm) < 2048:
            self.bars *= 0.93; self.update(); return
        i = int(ms / 1000 * SR); i = max(0, min(i, len(pcm) - 2048))
        w = pcm[i:i + 2048] * np.hanning(2048)
        mag = np.abs(np.fft.rfft(w)) / 512
        hz = SR / 2048
        def db(lo, hi):
            a = max(1, min(int(lo / hz), len(mag) - 2)); b = max(a + 1, min(int(hi / hz) + 1, len(mag)))
            return float(np.mean(mag[a:b]))
        out = []
        for b in range(64):
            lo, hi = 20 * 800 ** (b / 64) , 20 * 800 ** ((b + 1) / 64)
            hi = min(hi, SR / 2 - 1)
            v = db(lo, max(hi, lo + hz))
            mid = (lo * hi) ** .5
            g = gains[0 if mid < 250 else 1 if mid < 800 else 2 if mid < 4000 else 3]
            out.append(v * 10 ** (g / 20))
        a = np.nan_to_num(np.clip(np.log10(np.array(out) + 1e-4) / 2 + 1.1, 0, 1))
        # 1) smooth across neighbouring frequency bands (removes jagged spikes)
        k = np.array([1, 2, 3, 4, 3, 2, 1], dtype=float); k /= k.sum()
        a = np.convolve(np.pad(a, 3, mode="edge"), k, mode="valid")
        # 2) smooth over time: fairly quick rise, slow gentle fall (no flicker)
        rate = np.where(a > self.bars, 0.30, 0.10)
        self.bars = np.nan_to_num(self.bars + (a - self.bars) * rate)
        # 3) history lines: exponential moving average so they glide
        b_now, m_now = float(np.mean(self.bars[:20])), float(np.mean(self.bars))
        pb = self.bass[-1] if self.bass else b_now; pm = self.music[-1] if self.music else m_now
        self.bass.append(pb + (b_now - pb) * 0.2); self.music.append(pm + (m_now - pm) * 0.2)
        self.bass, self.music = self.bass[-300:], self.music[-300:]
        self.update()

    def paintEvent(self, _):
        q = QPainter(self); q.setRenderHint(QPainter.Antialiasing); q.fillRect(self.rect(), QColor("#f6fafd"))
        W, H = self.width(), self.height(); pad = 24
        top = int(H * .58); n = len(self.bars)
        # spectrum: one soft filled area, the bright moment of the screen
        pts = [QPointF(pad + i * (W - 2 * pad) / (n - 1), top - float(v) * (top - pad)) for i, v in enumerate(self.bars)]
        curve = smooth_path(pts)
        path = smooth_path(pts, start=QPointF(pad, top)); path.lineTo(QPointF(W - pad, top)); path.closeSubpath()
        g = QLinearGradient(0, pad, 0, top); g.setColorAt(0, QColor("#3aa6ee")); g.setColorAt(1, QColor(58, 166, 238, 30))
        q.setPen(Qt.NoPen); q.setBrush(QBrush(g)); q.drawPath(path)
        q.setPen(QPen(QColor("#2f94da"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); q.setBrush(Qt.NoBrush); q.drawPath(curve)
        # history: bass vs music
        gt = top + 32; gh = H - gt - pad
        q.setPen(QPen(QColor("#e3e8ec"), 1))
        for k in range(3): q.drawLine(pad, int(gt + gh * k / 2), W - pad, int(gt + gh * k / 2))
        for arr, col in ((self.music, "#9fd3f6"), (self.bass, "#1f6fae")):
            if len(arr) > 1:
                q.setPen(QPen(QColor(col), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                pp = [QPointF(pad + j / 299 * (W - 2 * pad), gt + gh - v * gh) for j, v in enumerate(arr)]
                q.drawPath(smooth_path(pp))
        q.setPen(QColor("#6b7f8c")); q.drawText(pad, top + 24, "Bass and music level")
        q.end()


class ImageView(QWidget):
    """Picture viewer: fit-to-window, wheel zoom, drag to pan, rotate."""
    def __init__(self):
        super().__init__(); self.pm = None; self.zoom = 1.0; self.off = QPointF(0, 0); self.drag = None
        self.setMinimumSize(320, 200); self.setMouseTracking(True); self._op = 1.0; self._zt = 1.0
        self.fade = QPropertyAnimation(self, b"opacity", self); self.fade.setDuration(ANIM_MS + 130); self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.zanim = QPropertyAnimation(self, b"zoomv", self); self.zanim.setDuration(140); self.zanim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_op(self): return self._op
    def _set_op(self, v): self._op = v; self.update()
    opacity = Property(float, _get_op, _set_op)
    def _get_z(self): return self.zoom
    def _set_z(self, v):
        self.zoom = v
        if v <= 1.0: self.off = QPointF(0, 0)
        self.update()
    zoomv = Property(float, _get_z, _set_z)

    def set_pixmap(self, pm):
        self.pm = pm; self.zanim.stop(); self.reset()
        if ANIM_MS: self.fade.stop(); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0); self.fade.start()
    def reset(self): self.zoom = 1.0; self.off = QPointF(0, 0); self.update()
    def rotate(self, deg=90):
        if self.pm: self.pm = self.pm.transformed(QTransform().rotate(deg), Qt.SmoothTransformation); self.reset()
    def zoom_by(self, f):
        base = self._zt if self.zanim.state() == QPropertyAnimation.Running else self.zoom
        self._zt = max(0.2, min(16.0, base * f))
        if not ANIM_MS: self._set_z(self._zt); return
        self.zanim.stop(); self.zanim.setStartValue(self.zoom); self.zanim.setEndValue(self._zt); self.zanim.start()

    def paintEvent(self, _):
        q = QPainter(self); q.setRenderHint(QPainter.SmoothPixmapTransform); q.fillRect(self.rect(), QColor("#14181c"))
        if self.pm and not self.pm.isNull():
            pw, ph = self.pm.width() / self.pm.devicePixelRatio(), self.pm.height() / self.pm.devicePixelRatio()
            sc = min(self.width() / pw, self.height() / ph) * self.zoom
            w, h = pw * sc, ph * sc
            q.setOpacity(self._op)
            q.drawPixmap(QRectF((self.width() - w) / 2 + self.off.x(), (self.height() - h) / 2 + self.off.y(), w, h),
                         self.pm, QRectF(self.pm.rect()))
        q.end()

    def wheelEvent(self, e): self.zoom_by(1.15 ** (e.angleDelta().y() / 120))
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.drag = e.position(); self.setCursor(Qt.ClosedHandCursor)
    def mouseMoveEvent(self, e):
        if self.drag is not None and self.zoom > 1.0: self.off += e.position() - self.drag; self.drag = e.position(); self.update()
    def mouseReleaseEvent(self, e): self.drag = None; self.unsetCursor()


# ---------- syntax colouring ----------
def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat(); f.setForeground(QColor(color))
    if bold: f.setFontWeight(QFont.Bold)
    if italic: f.setFontItalic(True)
    return f

FMT = {"keyword": _fmt("#7c3aed", bold=True), "string": _fmt("#2f9e44"), "comment": _fmt("#8a99a5", italic=True),
       "number": _fmt("#e8590c"), "func": _fmt("#1f6fae"), "class": _fmt("#0c8599", bold=True), "builtin": _fmt("#0c8599"),
       "tag": _fmt("#d6336c", bold=True), "attr": _fmt("#e8590c"), "prop": _fmt("#1f6fae"), "deco": _fmt("#c2185b"),
       "special": _fmt("#c2185b")}
_w = lambda words: r"\b(?:" + "|".join(words.split()) + r")\b"
_NUM = r"\b(?:0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?[fFdDlL]?)\b"
_DQ, _SQ = r'"(?:\\.|[^"\\])*"?', r"'(?:\\.|[^'\\])*'?"
_PFX = r"[rRbBuUfF]{0,2}"
# a language = (base rules [(regex, format, group)], tokens [(regex, kind)])
#   token kinds: "string" | "comment" | (end_text_or_regex, format) for constructs that can span several lines.
#   Tokens are scanned left to right, so a "//" inside a string is not taken for a comment.
LANGS = {
    "py": ([(_w("False None True and as assert async await break class continue def del elif else except finally for from global if "
                "import in is lambda nonlocal not or pass raise return try while with yield match case"), "keyword", 0),
            (_w("print len range int str float bool list dict set tuple open type isinstance enumerate zip map filter sorted sum min max "
                "abs any all super self cls object Exception ValueError KeyError TypeError"), "builtin", 0),
            (r"\b(\w+)(?=\()", "func", 1), (r"\bdef\s+(\w+)", "func", 1), (r"\bclass\s+(\w+)", "class", 1),
            (r"^\s*(@[\w.]+)", "deco", 1), (_NUM, "number", 0)],
           [(_PFX + '"""', ('"""', "string")), (_PFX + "'''", ("'''", "string")),
            (_PFX + _DQ, "string"), (_PFX + _SQ, "string"), (r"#.*", "comment")]),
    "js": ([(_w("break case catch class const continue debugger default delete do else export extends finally for function if import "
                "in instanceof let new of return super switch this throw try typeof var void while with yield async await static get set "
                "null true false undefined NaN Infinity"), "keyword", 0),
            (_w("console document window Math JSON Object Array String Number Promise Map Set Date RegExp Error"), "builtin", 0),
            (r"\b([A-Za-z_$][\w$]*)(?=\s*\()", "func", 1), (r"\b[A-Z][\w$]*\b", "class", 0), (_NUM, "number", 0)],
           [(r"/\*", ("*/", "comment")), (r"//.*", "comment"), (r"`", ("`", "string")), (_DQ, "string"), (_SQ, "string")]),
    "java": ([(_w("abstract assert break case catch class continue default do else enum extends final finally for if implements import "
                  "instanceof interface native new package private protected public return static strictfp super switch synchronized this "
                  "throw throws transient try volatile while var record sealed permits null true false"), "keyword", 0),
              (_w("int long short byte float double char boolean void String Integer Long Double Boolean Object List Map Set ArrayList "
                  "HashMap System Math"), "builtin", 0),
              (r"\b([A-Za-z_]\w*)(?=\s*\()", "func", 1), (r"\b[A-Z]\w*\b", "class", 0), (r"@\w+", "deco", 0), (_NUM, "number", 0)],
             [(r"/\*", ("*/", "comment")), (r"//.*", "comment"), ('"""', ('"""', "string")), (_DQ, "string"), (_SQ, "string")]),
    "css": ([(r"[.#][A-Za-z_][\w-]*", "class", 0), (r"[\w-]+(?=\s*:\s*[^;{}]*(?:;|\}|$))", "prop", 0), (r"@[\w-]+", "keyword", 0),
             (r"!important\b", "keyword", 0), (r"#[0-9a-fA-F]{3,8}\b", "number", 0),
             (r"-?\d*\.?\d+(?:px|em|rem|%|vh|vw|vmin|vmax|pt|cm|mm|s|ms|deg|fr)?\b", "number", 0), (r"\b[\w-]+(?=\()", "func", 0)],
            [(r"/\*", ("*/", "comment")), (_DQ, "string"), (_SQ, "string")]),
    "html": ([(r"</?\s*([A-Za-z][\w:-]*)", "tag", 0), (r"/?>", "tag", 0), (r"<!\w+[^>]*>", "keyword", 0),
              (r"([A-Za-z_:@][\w:.-]*)(?=\s*=)", "attr", 1), (r"=\s*(\"[^\"]*\"?|'[^']*'?)", "string", 1), (r"&#?\w+;", "special", 0)],
             [(r"<!--", ("-->", "comment"))]),
}
LANGS["htm"], LANGS["mjs"] = LANGS["html"], LANGS["js"]


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, doc): super().__init__(doc); self.set_lang(None)

    def set_lang(self, lang):
        spec = LANGS.get(lang)
        self.base = [(re.compile(r, re.M), f, g) for r, f, g in spec[0]] if spec else []
        self.kinds = [k for _, k in spec[1]] if spec else []
        self.tok = re.compile("|".join(f"(?P<t{i}>{r})" for i, (r, _) in enumerate(spec[1]))) if spec else None
        self.ends = [re.compile(re.escape(k[0])) if isinstance(k, tuple) else None for k in self.kinds]
        self.rehighlight()

    def highlightBlock(self, text):
        self.setCurrentBlockState(0)
        if not self.tok: return
        for rx, f, g in self.base:
            for m in rx.finditer(text):
                if m.end(g) > m.start(g): self.setFormat(m.start(g), m.end(g) - m.start(g), FMT[f])
        pos, prev = 0, self.previousBlockState()
        if prev > 0:                                   # continuing a multi-line comment / string
            e = self.ends[prev - 1].search(text); f = FMT[self.kinds[prev - 1][1]]
            if not e: self.setFormat(0, len(text), f); self.setCurrentBlockState(prev); return
            self.setFormat(0, e.end(), f); pos = e.end()
        while pos <= len(text):
            m = self.tok.search(text, pos)
            if not m: break
            i = int(m.lastgroup[1:]); k = self.kinds[i]
            if isinstance(k, tuple):
                e = self.ends[i].search(text, m.end()); f = FMT[k[1]]
                if not e: self.setFormat(m.start(), len(text) - m.start(), f); self.setCurrentBlockState(i + 1); return
                self.setFormat(m.start(), e.end() - m.start(), f); pos = e.end()
            else:
                self.setFormat(m.start(), m.end() - m.start(), FMT[k]); pos = max(m.end(), pos + 1)


class CodeEdit(QPlainTextEdit):
    """Plain-text editor that keeps indentation; in code mode Tab inserts 4 spaces and a trailing ':' '{' '(' '[' indents the next line."""
    code = False
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Tab and self.code and not e.modifiers():
            self.insertPlainText("    "); return
        if k == Qt.Key_Backtab and self.code:
            c = self.textCursor(); c.movePosition(QTextCursor.StartOfBlock); t = c.block().text()
            n = min(4, len(t) - len(t.lstrip(" ")))
            if n: c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, n); c.removeSelectedText()
            return
        if k in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ControlModifier:
            line = self.textCursor().block().text()[:self.textCursor().positionInBlock()]
            ind = line[:len(line) - len(line.lstrip(" \t"))]
            if self.code and line.rstrip().endswith((":", "{", "(", "[")): ind += "    "
            super().keyPressEvent(e); self.insertPlainText(ind); return
        super().keyPressEvent(e)


# ---------- sandbox: run code safely ----------
# Python / JavaScript / Java run in a throw-away temp folder, in a separate process with a stripped environment,
# CPU / memory / file-size / time limits, no keyboard input, and (on Linux) no network.
# HTML runs in an off-the-record browser pane with JavaScript on, but the internet blocked and only files from the page's own folder allowed.
# This is a safety net against accidents (endless loops, runaway memory, wiping files), not a security boundary against deliberately malicious code.
RUN_EXT = {".py", ".js", ".mjs", ".java", ".html", ".htm"}
RUN_SECONDS, MAX_OUT = 15, 200_000
_NET_OK = None


def net_isolation():
    """True when this machine can run a program with no network (Linux user namespaces via `unshare`)."""
    global _NET_OK
    if _NET_OK is None:
        try: _NET_OK = sys.platform.startswith("linux") and bool(shutil.which("unshare")) and \
                       subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
        except Exception: _NET_OK = False
    return _NET_OK


def run_command(path):
    """-> (argv, None) or (None, why not). argv uses the bare file name; it runs inside the temp folder."""
    ext, name = Path(path).suffix.lower(), Path(path).name
    if ext == ".py": return [sys.executable, "-I", "-u", name], None
    if ext in (".js", ".mjs"):
        node = shutil.which("node") or shutil.which("nodejs")
        return ([node, "--max-old-space-size=256", name], None) if node else (None, "Node.js was not found. Install it from nodejs.org to run JavaScript.")
    if ext == ".java":
        java = shutil.which("java")
        return ([java, "-Xmx256m", "-Dfile.encoding=UTF-8", name], None) if java else (None, "Java (JDK 11 or newer) was not found. Install a JDK to run Java files.")
    return None, "This file type can't be run."


class Sandbox(QObject):
    output = Signal(str); done = Signal(str)

    def __init__(self):
        super().__init__(); self.proc, self.tmp, self.size, self.reason = None, None, 0, ""
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(lambda: self.kill(f"Stopped: {RUN_SECONDS} second time limit reached."))

    @property
    def running(self): return self.proc is not None

    def start(self, path, text):
        cmd, err = run_command(path)
        if not cmd: self.done.emit(err); return
        net = net_isolation(); self.tmp = tempfile.mkdtemp(prefix="foxsandbox_"); self.size, self.reason = 0, ""
        (Path(self.tmp) / Path(path).name).write_text(text, encoding="utf-8")
        env = QProcessEnvironment()
        for k, v in (("PATH", os.environ.get("PATH", "")), ("SYSTEMROOT", os.environ.get("SYSTEMROOT", "")), ("HOME", self.tmp), ("TMPDIR", self.tmp),
                     ("TEMP", self.tmp), ("TMP", self.tmp), ("LANG", "C.UTF-8"), ("PYTHONIOENCODING", "utf-8")):
            if v: env.insert(k, v)
        if cmd[0] == sys.executable: env.insert("FOX_SANDBOX_AS", "1")          # also cap Python's memory (Node / Java have their own flags)
        p = self.proc = QProcess(self); p.setProcessEnvironment(env); p.setWorkingDirectory(self.tmp); p.setProcessChannelMode(QProcess.MergedChannels)
        p.setProgram(sys.executable); p.setArguments(([] if FROZEN else [str(Path(__file__).resolve())]) + ["--sandbox-exec"] + (["unshare", "-rn", "--"] if net else []) + cmd)
        p.readyRead.connect(self.read); p.started.connect(p.closeWriteChannel); p.finished.connect(self.finished); p.errorOccurred.connect(self.failed)
        self.output.emit(f"$ {Path(cmd[0]).stem} {Path(path).name}\n[sandbox: temp folder, {RUN_SECONDS}s limit, "
                         + ("no network" if net else "network NOT blocked on this system") + ", no keyboard input]\n\n")
        p.start(); self.timer.start(RUN_SECONDS * 1000)

    def read(self):
        data = bytes(self.proc.readAll()); self.size += len(data)
        self.output.emit(data.decode("utf-8", errors="replace").replace(self.tmp + os.sep, ""))   # hide the temp folder path
        if self.size > MAX_OUT: self.kill("Stopped: too much output.")

    def kill(self, why="Stopped."):
        if self.proc: self.reason = self.reason or why; self.proc.kill()

    def failed(self, err):
        if err == QProcess.FailedToStart: self.reason = "Could not start the program."; self.finished(-1, QProcess.CrashExit)

    def finished(self, code, status):
        if not self.proc: return
        self.timer.stop()
        if self.proc.bytesAvailable(): self.read()
        msg = self.reason or (f"[finished, exit code {code}]" if status == QProcess.NormalExit and code >= 0 else f"[stopped by the sandbox or crashed, code {code}]")
        self.proc.deleteLater(); self.proc = None; shutil.rmtree(self.tmp, ignore_errors=True); self.done.emit(msg)

    def stop_now(self):
        if self.proc: self.reason = "Stopped."; self.proc.kill(); self.proc.waitForFinished(1000)


if HAVE_WEB:
    class WebGuard(QWebEngineUrlRequestInterceptor):
        """Blocks every request except data:/blob: and local files inside the page's own folder."""
        def __init__(self): super().__init__(); self.base = ""; self.blocked = []
        def inside(self, p):
            try: return os.path.commonpath([os.path.realpath(p), self.base]) == self.base
            except ValueError: return False
        def allowed(self, u): return u.scheme() in ("data", "blob", "about") or (u.isLocalFile() and self.inside(u.toLocalFile()))
        def interceptRequest(self, info):
            u = info.requestUrl()
            if not self.allowed(u): info.block(True); self.blocked.append(u.toString()[:120])

    class SandboxPage(QWebEnginePage):
        console = Signal(str)
        def __init__(self, profile, guard, parent=None): super().__init__(profile, parent); self.guard = guard
        def javaScriptConsoleMessage(self, level, msg, line, src):
            tag = {1: "warn: ", 2: "error: "}.get(int(getattr(level, "value", level)), "")
            self.console.emit(f"{tag}{msg}   (line {line})\n")
        def acceptNavigationRequest(self, url, typ, main):
            if self.guard.allowed(url): return True
            self.console.emit(f"blocked: {url.toString()[:120]}\n"); return False


def make_web_sandbox(parent):
    guard = WebGuard(); prof = QWebEngineProfile(parent)            # no name = off-the-record: nothing is stored on disk
    prof.setUrlRequestInterceptor(guard); prof.downloadRequested.connect(lambda d: d.cancel())
    page = SandboxPage(prof, guard, parent); st = page.settings(); A = QWebEngineSettings.WebAttribute
    for name, val in (("JavascriptCanOpenWindows", False), ("JavascriptCanAccessClipboard", False), ("LocalContentCanAccessRemoteUrls", False),
                      ("LocalContentCanAccessFileUrls", True), ("PluginsEnabled", False), ("AllowRunningInsecureContent", False),
                      ("ScreenCaptureEnabled", False), ("WebRTCPublicInterfacesOnly", True), ("LocalStorageEnabled", False)):
        if hasattr(A, name): st.setAttribute(getattr(A, name), val)
    view = QWebEngineView(parent); view.setPage(page); return view, page, guard


class TextView(QWidget):
    """Editor for .txt / .md. For Markdown, a button switches between the raw source (## and **) and the formatted view."""
    changed = Signal(); new_req = Signal(); open_req = Signal()

    def __init__(self):
        super().__init__(); self.path, self.enc, self.crlf, self.kind = None, "utf-8", False, ""
        self.name = QLabel(); self.name.setStyleSheet("font-weight:600")
        self.save_b = QPushButton("Save"); self.save_b.setObjectName("primary"); self.save_b.setToolTip("Save (Ctrl+S)"); self.save_b.clicked.connect(self.save)
        self.md_b = QPushButton("Show formatted"); self.md_b.setObjectName("tool"); self.md_b.setCheckable(True)
        self.md_b.setToolTip("Show the formatted / rendered version (Ctrl+Shift+M)"); self.md_b.clicked.connect(self.set_preview)
        self.edit = CodeEdit(); self.hl = CodeHighlighter(self.edit.document()); self.edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont); f.setPointSize(11); self.edit.setFont(f); self.edit.setTabStopDistance(32)
        self.edit.document().modificationChanged.connect(lambda _: self.changed.emit())
        self.view = QTextBrowser(); self.view.setOpenExternalLinks(True)
        self.pages = QStackedWidget(); self.pages.addWidget(self.edit); self.pages.addWidget(self.view)
        self.run_b = QPushButton("Run"); self.run_b.setObjectName("run"); self.run_b.setToolTip("Run safely in the sandbox (F5)"); self.run_b.clicked.connect(self.toggle_run)
        self.console = QPlainTextEdit(); self.console.setReadOnly(True); self.console.hide(); self.console.setFont(f); self.console.setMaximumBlockCount(5000)
        self.console.setStyleSheet("background:#14181c; color:#d7e3ec; border:none; border-radius:6px; padding:8px;")
        self.sb = Sandbox(); self.sb.output.connect(self.out); self.sb.done.connect(self.run_done)
        self.web, self.web_page, self.web_guard, self.web_on = None, None, None, False
        self.split = QSplitter(Qt.Vertical); self.split.addWidget(self.pages); self.split.addWidget(self.console); self.split.setSizes([420, 160]); self.split.setChildrenCollapsible(False)
        self.new_b = QPushButton("New"); self.new_b.setObjectName("tool"); self.new_b.setToolTip("New code file (Ctrl+N)"); self.new_b.clicked.connect(self.new_req.emit)
        self.open_b = QPushButton("Open"); self.open_b.setObjectName("tool"); self.open_b.setToolTip("Open a code or text file"); self.open_b.clicked.connect(self.open_req.emit)
        top = QHBoxLayout(); top.setSpacing(8); top.addWidget(self.new_b); top.addWidget(self.open_b); top.addWidget(self.name, 1); top.addWidget(self.run_b); top.addWidget(self.md_b); top.addWidget(self.save_b)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 12, 16, 12); lay.setSpacing(8); lay.addLayout(top); lay.addWidget(self.split, 1)

    @property
    def dirty(self): return self.edit.document().isModified()

    # ----- sandbox -----
    def out(self, t):
        c = self.console.textCursor(); c.movePosition(QTextCursor.End); c.insertText(t); self.console.setTextCursor(c); self.console.ensureCursorVisible()

    def set_running(self, on):
        self.run_b.setText("Stop" if on else "Run"); self.run_b.setProperty("running", on)
        self.run_b.style().unpolish(self.run_b); self.run_b.style().polish(self.run_b)

    def run_done(self, msg):
        if self.console.toPlainText() and not self.console.toPlainText().endswith("\n"): self.out("\n")
        self.out(msg + "\n"); self.set_running(False)

    def running(self): return self.sb.running or self.web_on

    def toggle_run(self):
        if self.running(): self.stop_run(); return
        if not self.path or self.run_b.isHidden(): return
        self.console.clear(); self.console.show()
        if self.kind == "html": self.run_html()
        else: self.set_running(True); self.sb.start(self.path, self.edit.toPlainText())

    def run_html(self):
        if self.web is None:
            self.web, self.web_page, self.web_guard = make_web_sandbox(self); self.pages.addWidget(self.web)
            self.web_page.console.connect(self.out)
        base = os.path.realpath(str(Path(self.path).parent)); self.web_guard.base = base
        self.set_preview(False); self.md_b.setEnabled(False)
        self.out("[browser sandbox: JavaScript on, internet blocked, only files from this folder can load]\n\n")
        self.web_page.setHtml(self.edit.toPlainText(), QUrl.fromLocalFile(base + os.sep))
        self.pages.setCurrentIndex(2); self.web_on = True; self.set_running(True)

    def stop_run(self):
        if self.sb.running: self.sb.stop_now()
        if self.web_on:
            self.web_on = False; self.web_page.setHtml(""); self.pages.setCurrentIndex(0); self.md_b.setEnabled(True); self.edit.setFocus()
            self.out("[stopped]\n"); self.set_running(False)

    def load(self, path):
        self.stop_run()
        try: data = Path(path).read_bytes()
        except OSError as e: return str(e)
        self.enc = "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8"
        for enc in (self.enc, "cp874", "latin-1"):      # UTF-8 first, then Thai Windows text, then anything
            try: text = data.decode(enc); self.enc = enc; break
            except UnicodeDecodeError: pass
        ext = Path(path).suffix.lower()
        self.crlf = "\r\n" in text; self.path = path
        self.kind = "md" if ext in (".md", ".markdown") else "html" if ext in (".html", ".htm") else ""
        self.edit.code = ext in CODE_EXT; self.edit.setLineWrapMode(QPlainTextEdit.NoWrap if self.edit.code else QPlainTextEdit.WidgetWidth)
        self.hl.set_lang(ext.lstrip(".") if ext in CODE_EXT else None)
        self.name.setText(Path(path).name); self.edit.setPlainText(text.replace("\r\n", "\n")); self.edit.document().setModified(False)
        self.run_b.setVisible(ext in RUN_EXT and (HAVE_WEB or ext not in (".html", ".htm"))); self.console.hide(); self.console.clear()
        self.md_b.setVisible(bool(self.kind)); self.md_b.setChecked(False); self.set_preview(False)
        self.edit.moveCursor(self.edit.textCursor().MoveOperation.Start); return None

    def save(self):
        if not self.path: return True
        text = self.edit.toPlainText()
        if self.crlf: text = text.replace("\n", "\r\n")
        try:
            tmp = Path(self.path + ".tmp"); tmp.write_bytes(text.encode(self.enc, errors="replace")); tmp.replace(self.path)
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e)); return False
        self.edit.document().setModified(False); discard_draft(self.path); return True

    def set_preview(self, on=None):
        on = (not self.md_b.isChecked() if on is None else on) if self.kind else False
        if on:
            self.view.setSearchPaths([str(Path(self.path).parent)])
            (self.view.setHtml if self.kind == "html" else self.view.setMarkdown)(self.edit.toPlainText())
        self.pages.setCurrentIndex(1 if on else 0); self.md_b.setChecked(on)
        self.md_b.setText("Show source" if on else "Show preview" if self.kind == "html" else "Show formatted")
        (self.view if on else self.edit).setFocus()


class EqualizerDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Equalizer & Optimizer", win); self.win = win
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(12)
        top = QHBoxLayout(); top.setSpacing(8); self.preset = QComboBox(); self.preset.addItems(PRESETS)
        self.preset.currentTextChanged.connect(lambda t: self.set_gains(PRESETS[t]))
        auto = QPushButton("Auto Optimize"); auto.setObjectName("primary"); auto.clicked.connect(win.auto_optimize)
        top.addWidget(self.preset, 1); top.addWidget(auto); lay.addLayout(top)
        g = QGridLayout(); g.setHorizontalSpacing(16); g.setVerticalSpacing(8); self.sl, self.lb = [], []
        for i, (name, hz) in enumerate([("Bass", "~120 Hz"), ("Low-pitch", "~400 Hz"), ("Other", "~2 kHz"), ("High-pitch", "~6 kHz+")]):
            s = QSlider(Qt.Vertical); s.setRange(-24, 24); s.setValue(0); s.setMinimumHeight(128)
            l = QLabel("0 dB"); l.setAlignment(Qt.AlignCenter)
            s.valueChanged.connect(lambda v, i=i: self.changed(i, v))
            g.addWidget(QLabel(name), 0, i, Qt.AlignCenter); g.addWidget(s, 1, i, Qt.AlignCenter)
            g.addWidget(l, 2, i); g.addWidget(QLabel(hz), 3, i, Qt.AlignCenter)
            self.sl.append(s); self.lb.append(l)
        lay.addLayout(g)
        self.brl = QLabel("Bitrate: Original"); self.br = QSlider(Qt.Horizontal); self.br.setRange(0, 6)
        self.rel = QLabel("Video resolution: Original"); self.rs = QSlider(Qt.Horizontal); self.rs.setRange(0, 5)
        self.br.valueChanged.connect(lambda v: self.brl.setText(f"Bitrate: {BITRATES[v] or 'Original'}" + (" kbps" if v else "")))
        self.rs.valueChanged.connect(lambda v: self.rel.setText(f"Video resolution: {RESOLUTIONS[v] or 'Original'}" + ("p" if v else "")))
        self.br.sliderReleased.connect(win.reload_quality); self.rs.sliderReleased.connect(win.reload_quality)
        for w_ in (self.brl, self.br, self.rel, self.rs): lay.addWidget(w_)
        if not FFMPEG:
            self.br.setEnabled(False); self.rs.setEnabled(False)
            lay.addWidget(QLabel("Install ffmpeg to enable bitrate / resolution."))
        lay.addStretch(); self.setWidget(w)

    def changed(self, i, v):
        self.lb[i].setText(f"{v / 2:g} dB"); self.win.apply_eq(self.gains())

    def gains(self): return [s.value() / 2 for s in self.sl]

    def set_gains(self, g):
        for s, v in zip(self.sl, g):
            s.blockSignals(True); s.setValue(int(v * 2)); s.blockSignals(False)
        for i, v in enumerate(g): self.lb[i].setText(f"{v:g} dB")
        self.win.apply_eq(list(g))


# ---------- home screen ----------
# kind -> (title, what you get, icon, colour, extensions)
KINDS = {
    "video": ("Video", "MP4, MKV, AVI, MOV...", "video", "#3aa6ee", VIDEO_EXT),
    "music": ("Music", "MP3, FLAC, WAV...\nequalizer & visualizer", "music", "#ff8a2b", AUDIO_EXT),
    "pictures": ("Pictures", "JPG, PNG, GIF, WebP...\nzoom, rotate, slideshow", "image", "#2f9e44", IMAGE_EXT),
    "text": ("Text & Markdown", "TXT, MD\nedit, formatted view", "text", "#6b7f8c", {".txt", ".md", ".markdown"}),
    "code": ("Code", "HTML, JS, PY, Java\ncolours & safe Run", "code", "#7c3aed", CODE_EXT),
    "web": ("Web", "Chromium browser\nbrowse websites here", "web", "#1971c2", set()),
    "playlist": ("Playlist", "M3U, M3U8, PLS", "list", "#0c8599", PLAYLIST_EXT),
    "folder": ("Folder", "everything inside a folder", "folder", "#e8a317", set()),
    "any": ("Any file", "anything FoxReader supports", "files", "#d6336c", MEDIA_EXT | PLAYLIST_EXT),
}


class HomeView(QWidget):
    """What do you want to open? - one card per kind of file, plus recent files."""
    def showEvent(self, e): super().showEvent(e); QTimer.singleShot(0, lambda: fade_in(self))
    pick = Signal(str); recent = Signal(str)

    def __init__(self):
        super().__init__(); outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); outer.addWidget(sa)
        inner = QWidget(); sa.setWidget(inner); col = QVBoxLayout(inner); col.setContentsMargins(24, 16, 24, 16); col.setSpacing(8)
        logo = QLabel(); logo.setAlignment(Qt.AlignCenter)
        if LOGO.exists(): logo.setPixmap(QPixmap(str(LOGO)).scaledToHeight(110, Qt.SmoothTransformation))
        title = QLabel("FoxReader"); title.setObjectName("home_title"); title.setAlignment(Qt.AlignCenter)
        sub = QLabel("What do you want to open?"); sub.setObjectName("home_sub"); sub.setAlignment(Qt.AlignCenter)
        grid = QGridLayout(); grid.setSpacing(12)
        for n, (kind, (name, what, ic, color, _)) in enumerate(KINDS.items()):
            b = QPushButton(); b.setObjectName("card"); b.setFixedSize(150, 120); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(lambda _=0, k=kind: self.pick.emit(k))
            v = QVBoxLayout(b); v.setContentsMargins(10, 12, 10, 10); v.setSpacing(4)
            i = QLabel(); i.setPixmap(icon(ic, color, 34).pixmap(34, 34)); i.setAlignment(Qt.AlignCenter)
            t = QLabel(name); t.setObjectName("card_name"); t.setAlignment(Qt.AlignCenter)
            d = QLabel(what); d.setObjectName("card_desc"); d.setAlignment(Qt.AlignCenter); d.setWordWrap(True)
            for w_ in (i, t, d): w_.setAttribute(Qt.WA_TransparentForMouseEvents)
            v.addWidget(i); v.addWidget(t); v.addWidget(d, 1); grid.addWidget(b, n // 5, n % 5)
        gw = QWidget(); gw.setLayout(grid); gw.setFixedSize(5 * 150 + 4 * 12, 2 * 120 + 12)
        hint = QLabel("...or drag & drop files or folders anywhere in this window"); hint.setObjectName("home_hint"); hint.setAlignment(Qt.AlignCenter)
        self.rbox = QVBoxLayout(); self.rbox.setSpacing(2); self.rhead = QLabel("Recent"); self.rhead.setObjectName("recent_head")
        col.addStretch(1); col.addWidget(logo); col.addWidget(title); col.addWidget(sub); col.addSpacing(10); col.addWidget(gw, 0, Qt.AlignHCenter)
        col.addWidget(hint); col.addWidget(self.rhead, 0, Qt.AlignHCenter); col.addLayout(self.rbox); col.addStretch(2)
        self.set_recent([])

    def set_recent(self, paths):
        while self.rbox.count():
            it = self.rbox.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        paths = [p for p in paths if os.path.isfile(p)][:6]; self.rhead.setVisible(bool(paths))
        for p in paths:
            b = QPushButton(f"{Path(p).name}   -   {Path(p).parent.name or Path(p).parent}"); b.setObjectName("recent"); b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(p); b.clicked.connect(lambda _=0, p=p: self.recent.emit(p)); self.rbox.addWidget(b, 0, Qt.AlignHCenter)


TEMPLATES = {
    ".py": 'print("Hello, FoxReader!")\n',
    ".js": 'console.log("Hello, FoxReader!");\n',
    ".java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello, FoxReader!");\n    }\n}\n',
    ".html": '<!DOCTYPE html>\n<html>\n<head>\n  <meta charset="utf-8">\n  <title>My page</title>\n</head>\n<body>\n  <h1>Hello, FoxReader!</h1>\n</body>\n</html>\n',
    ".md": "# Notes\n\n",
}


def web_url(text):
    """Address-bar text -> URL: a web address is opened (https:// added), anything else becomes a Google search."""
    t = text.strip()
    if not t: return QUrl("about:blank")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t) or t.startswith(("about:", "data:", "file:")): return QUrl.fromUserInput(t)
    host = t.split("/")[0].split("?")[0].split(":")[0]
    if " " not in t and ("." in host or host == "localhost") and not host.endswith("."):
        return QUrl(("http://" if host == "localhost" or re.fullmatch(r"[\d.]+", host) else "https://") + t)
    return QUrl("https://www.google.com/search?q=" + bytes(QUrl.toPercentEncoding(t)).decode())


# ---------- DNS for the browser tabs ----------
# Chromium has no switch for "use this DNS server", so FoxReader runs a tiny local SOCKS5 proxy: the browser hands it the host name,
# the proxy asks the chosen DNS server (plain DNS over UDP, TCP if the answer is big) and connects. Default DNS = no proxy at all.
DNS_PRESETS = {"default": ("Default", []), "opendns": ("OpenDNS", ["208.67.222.222", "208.67.220.220"]),
               "cloudflare": ("Cloudflare", ["1.1.1.1", "1.0.0.1"]), "google": ("Google Public DNS", ["8.8.8.8", "8.8.4.4"]), "custom": ("Custom", [])}
DNS_PORT = 53
_dns_cache, _dns_lock = {}, threading.Lock()

def _qname(host): return b"".join(bytes([len(p)]) + p.encode("idna") for p in host.rstrip(".").split(".") if p) + b"\0"

def _skip_name(b, i):
    while True:
        n = b[i]
        if n == 0: return i + 1
        if n & 0xC0 == 0xC0: return i + 2
        i += 1 + n

def dns_query(server, host, qtype, timeout=3.0):
    """Ask one DNS server for the A (1) or AAAA (28) records of a host. Returns a list of IP strings."""
    q = struct.pack(">HHHHHH", random.randrange(65536), 0x0100, 1, 0, 0, 0) + _qname(host) + struct.pack(">HH", qtype, 1)
    with socket.socket(socket.AF_INET6 if ":" in server else socket.AF_INET, socket.SOCK_DGRAM) as u:
        u.settimeout(timeout); u.sendto(q, (server, DNS_PORT))
        while True:
            data, _ = u.recvfrom(4096)
            if len(data) >= 12 and data[:2] == q[:2]: break
    if struct.unpack(">H", data[2:4])[0] & 0x0200:                      # answer was cut: ask again over TCP
        with socket.create_connection((server, DNS_PORT), timeout) as t:
            t.sendall(struct.pack(">H", len(q)) + q); head = b""
            while len(head) < 2: head += t.recv(2 - len(head))
            n = struct.unpack(">H", head)[0]; data = b""
            while len(data) < n:
                c = t.recv(n - len(data))
                if not c: break
                data += c
    qd, an = struct.unpack(">HH", data[4:8]); i, out = 12, []
    for _ in range(qd): i = _skip_name(data, i) + 4
    for _ in range(an):
        i = _skip_name(data, i); t_, _c, _ttl, ln = struct.unpack(">HHIH", data[i:i + 10]); i += 10
        if t_ == qtype == 1 and ln == 4: out.append(socket.inet_ntop(socket.AF_INET, data[i:i + 4]))
        elif t_ == qtype == 28 and ln == 16: out.append(socket.inet_ntop(socket.AF_INET6, data[i:i + 16]))
        i += ln
    return out

def dns_resolve(servers, host):
    key = (tuple(servers), host.lower())
    with _dns_lock:
        hit = _dns_cache.get(key)
        if hit and time.monotonic() - hit[0] < 120: return hit[1]
    ips = []
    for srv in servers:
        try:
            ips = dns_query(srv, host, 1) + dns_query(srv, host, 28)
            if ips: break
        except (OSError, struct.error, IndexError, UnicodeError): continue
    if ips:
        with _dns_lock: _dns_cache[key] = (time.monotonic(), ips)
    return ips

def _recvn(c, n):
    b = b""
    while len(b) < n:
        d = c.recv(n - len(b))
        if not d: raise OSError("closed")
        b += d
    return b

class _SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        c = self.request; c.settimeout(20); up = None
        try:
            _recvn(c, 1); _recvn(c, _recvn(c, 1)[0]); c.sendall(b"\x05\x00")                       # greeting: no authentication
            _v, cmd, _r, atyp = _recvn(c, 4)
            if atyp == 1: host = socket.inet_ntoa(_recvn(c, 4))
            elif atyp == 4: host = socket.inet_ntop(socket.AF_INET6, _recvn(c, 16))
            elif atyp == 3: host = _recvn(c, _recvn(c, 1)[0]).decode("ascii", "replace")
            else: c.sendall(b"\x05\x08\x00\x01\0\0\0\0\0\0"); return
            port = struct.unpack(">H", _recvn(c, 2))[0]
            if cmd != 1: c.sendall(b"\x05\x07\x00\x01\0\0\0\0\0\0"); return
            servers = self.server.dns_servers
            try: ipaddress.ip_address(host); servers = []
            except ValueError: pass
            if not servers: targets = [host]                                   # Default DNS: the computer's own resolver
            else: targets = dns_resolve(servers, host)                         # chosen DNS server
            for ip in targets:
                try: up = socket.create_connection((ip, port), 10); break
                except OSError: up = None
            if up is None: c.sendall(b"\x05\x04\x00\x01\0\0\0\0\0\0"); return              # host unreachable
            c.sendall(b"\x05\x00\x00\x01\0\0\0\0\0\0"); c.settimeout(None); up.settimeout(None)
            while True:
                r, _, x = select.select([c, up], [], [c, up], 300)
                if not r or x: break
                for sk in r:
                    d = sk.recv(65536)
                    if not d: return
                    (up if sk is c else c).sendall(d)
        except (OSError, ValueError): pass
        finally:
            if up is not None: up.close()

class DnsProxy(socketserver.ThreadingTCPServer):
    daemon_threads = True; allow_reuse_address = True
    def __init__(self): super().__init__(("127.0.0.1", 0), _SocksHandler); self.dns_servers = []; threading.Thread(target=self.serve_forever, daemon=True).start()

# ---------- what a web page may ask for (camera, GPS...) ----------
PERM_TEXT = {"Geolocation": "know your location (GPS)", "MediaVideoCapture": "use your camera", "MediaAudioCapture": "use your microphone",
             "MediaAudioVideoCapture": "use your camera and microphone", "DesktopVideoCapture": "record your screen",
             "DesktopAudioVideoCapture": "record your screen and its sound", "Notifications": "show notifications",
             "ClipboardReadWrite": "read and change your clipboard", "MouseLock": "hide and lock your mouse pointer",
             "LocalFontsAccess": "see the fonts installed on this computer"}


if HAVE_WEB:
    class WebTab(QWidget):
        """A browser tab (Chromium via QtWebEngine): address bar + search, back / forward / reload, links that open a new tab, downloads, fullscreen video."""
        title_changed = Signal(str); icon_changed = Signal(object); open_url = Signal(str); fullscreen_req = Signal(bool); dns_req = Signal(object); perm_req = Signal(str, str, object, object)
        HOME = "https://www.google.com"

        def __init__(self, profile, url=""):
            super().__init__(); self.title, self.loading = "", False
            self.view = QWebEngineView(self); self.web_page = QWebEnginePage(profile, self.view); self.view.setPage(self.web_page)
            self.web_page.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            def tb(ic, tip, f):
                dark = QSettings("FoxReader", "FoxReader").value("theme", "light", type=str) == "dark"
                b = QPushButton(); b.setIcon(icon(ic, "#dce6ed" if dark else INK)); b.setIconSize(QSize(18, 18)); b.setToolTip(tip); b.setFocusPolicy(Qt.NoFocus); b.clicked.connect(f); return b
            self.back_b = tb("back", "Back (Alt+Left)", self.view.back); self.fwd_b = tb("fwd", "Forward (Alt+Right)", self.view.forward)
            self.reload_b = tb("reload", "Reload (Ctrl+R)", self.reload_or_stop); self.home_b = tb("home", "Home page", lambda: self.go(self.HOME))
            self.addr = QLineEdit(); self.addr.setPlaceholderText("Search or type a web address"); self.addr.setClearButtonEnabled(True)
            self.addr.returnPressed.connect(lambda: self.go(self.addr.text()))
            self.bar = QWidget(); bl = QHBoxLayout(self.bar); bl.setContentsMargins(12, 8, 12, 6); bl.setSpacing(4)
            self.dns_b = QPushButton("DNS: Default"); self.dns_b.setObjectName("tool"); self.dns_b.setFocusPolicy(Qt.NoFocus); self.dns_b.setToolTip("Choose the DNS server the browser uses"); self.dns_b.clicked.connect(lambda: self.dns_req.emit(self.dns_b))
            for b in (self.back_b, self.fwd_b, self.reload_b, self.home_b): bl.addWidget(b)
            bl.addSpacing(6); bl.addWidget(self.addr, 1); bl.addWidget(self.dns_b)
            self.prog = QProgressBar(); self.prog.setObjectName("webprog"); self.prog.setRange(0, 100); self.prog.setTextVisible(False); self.prog.setFixedHeight(3); self.prog.hide()
            lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0); lay.addWidget(self.bar); lay.addWidget(self.prog); lay.addWidget(self.view, 1)
            v, pg = self.view, self.web_page
            v.urlChanged.connect(self.on_url); v.titleChanged.connect(self.on_title); v.iconChanged.connect(self.icon_changed.emit)
            v.loadStarted.connect(lambda: self.set_loading(True)); v.loadFinished.connect(lambda _ok: self.set_loading(False)); v.loadProgress.connect(self.on_progress)
            pg.newWindowRequested.connect(lambda r: self.open_url.emit(r.requestedUrl().toString()))
            if hasattr(pg, "permissionRequested"): pg.permissionRequested.connect(self.on_permission)            # Qt 6.8+
            else: pg.featurePermissionRequested.connect(self.on_feature)
            pg.fullScreenRequested.connect(lambda r: (r.accept(), self.fullscreen_req.emit(r.toggleOn())))
            for key, f in (("Alt+Left", v.back), ("Alt+Right", v.forward), ("Ctrl+R", self.reload_or_stop), ("F6", self.focus_address), ("Alt+D", self.focus_address)):
                sc = QShortcut(QKeySequence(key), self); sc.setContext(Qt.WidgetWithChildrenShortcut); sc.activated.connect(f)
            self.update_nav(); self.go(url or self.HOME)

        def on_permission(self, perm):
            self.perm_req.emit(perm.origin().toString(), perm.permissionType().name, perm.grant, perm.deny)
        def on_feature(self, origin, feature):
            P = QWebEnginePage.PermissionPolicy; pg = self.web_page
            self.perm_req.emit(origin.toString(), feature.name, lambda: pg.setFeaturePermission(origin, feature, P.PermissionGrantedByUser), lambda: pg.setFeaturePermission(origin, feature, P.PermissionDeniedByUser))
        def set_dns_label(self, name): self.dns_b.setText("DNS: " + name)

        def go(self, text): self.view.setUrl(web_url(text)); self.view.setFocus()
        def focus_address(self): self.addr.setFocus(); self.addr.selectAll()
        def focus_page(self): self.view.setFocus()
        def reload_or_stop(self): self.view.stop() if self.loading else self.view.reload()
        def update_nav(self):
            h = self.web_page.history(); self.back_b.setEnabled(h.canGoBack()); self.fwd_b.setEnabled(h.canGoForward())
        def on_url(self, u):
            if not self.addr.hasFocus(): self.addr.setText("" if u.toString() == "about:blank" else u.toString()); self.addr.setCursorPosition(0)
            self.update_nav()
        def on_title(self, t): self.title = t; self.title_changed.emit(t)
        def on_progress(self, n): self.prog.setValue(n); self.prog.setVisible(self.loading and n < 100)
        def set_loading(self, on):
            self.loading = on; self.reload_b.setIcon(icon("close" if on else "reload")); self.reload_b.setToolTip("Stop" if on else "Reload (Ctrl+R)")
            if not on: self.prog.hide(); self.update_nav()


TAB_ORDER = ("watch", "code", "new")
TAB_INFO = {"watch": ("Watch Video", "video"), "code": ("Writing Code", "code"), "new": ("New Tab", "folder")}
TAB_RANK = {"watch": 0, "code": 1, "new": 3}      # browser tabs ("web1", "web2"...) sit between Writing Code and New Tab


USER_AGENTS = [
    ("Default (Chromium)", ""),
    ("Chrome - Windows", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Chrome - macOS", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Chrome - Linux", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Firefox - Windows", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"),
    ("Safari - macOS", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Edge - Windows", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"),
    ("Chrome - Android phone", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"),
    ("Safari - iPhone", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"),
    ("Safari - iPad", "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"),
]


class CodeHome(QWidget):
    """Shown in the Writing Code tab until a file is open."""
    def showEvent(self, e): super().showEvent(e); QTimer.singleShot(0, lambda: fade_in(self))
    new_req = Signal(); open_req = Signal()

    def __init__(self):
        super().__init__(); col = QVBoxLayout(self); col.setContentsMargins(24, 16, 24, 16); col.setSpacing(10)
        ic = QLabel(); ic.setPixmap(icon("code", "#3aa6ee", 56).pixmap(56, 56)); ic.setAlignment(Qt.AlignCenter)
        t = QLabel("Writing Code"); t.setObjectName("code_title"); t.setAlignment(Qt.AlignCenter)
        d = QLabel("Create a new file or open one, then press Run (F5) to try it in the safe sandbox.\nPython, JavaScript, Java, HTML, CSS, Markdown and text files are supported.")
        d.setObjectName("code_desc"); d.setAlignment(Qt.AlignCenter)
        tip = QLabel("Tip: a video or song keeps playing while you code. Switch back with Ctrl+1."); tip.setObjectName("code_tip"); tip.setAlignment(Qt.AlignCenter)
        nb = QPushButton("New file"); nb.setObjectName("primary"); nb.setCursor(Qt.PointingHandCursor); nb.clicked.connect(self.new_req.emit)
        ob = QPushButton("Open file..."); ob.setObjectName("tool"); ob.setCursor(Qt.PointingHandCursor); ob.clicked.connect(self.open_req.emit)
        row = QHBoxLayout(); row.setSpacing(10); row.addStretch(1); row.addWidget(nb); row.addWidget(ob); row.addStretch(1)
        col.addStretch(1); col.addWidget(ic); col.addWidget(t); col.addWidget(d); col.addSpacing(8); col.addLayout(row); col.addWidget(tip); col.addStretch(2)


class Player(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("FoxReader"); self.setWindowIcon(QIcon(str(LOGO))); self.resize(1100, 680); self.setAcceptDrops(True); self.setFocusPolicy(Qt.StrongFocus)
        self.mp = QtPlayer()
        self.bus = Bus(); self.bus.transcoded.connect(self.on_transcoded); self.bus.analyzed.connect(self.on_analyzed)
        self.bus.failed.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.files, self.idx, self.pcm, self.pcm_path, self.seeking = [], -1, None, "", False
        self.last_pos, self.idle_t = None, time.monotonic(); self.tw = 0; self.eq = tuple([0.0] * 4); self.eq_used = tuple([0.0] * 4); self.lock = threading.Lock(); self.enc_gen = 0; self.enc_proc = None; self.slideshow = False; self.slide_t = 0.0

        # center: video frame / visualizer
        self.video = QVideoWidget(); self.video.setStyleSheet("background:#000"); self.mp.set_video(self.video)
        self.viz = Visualizer(self.mp)
        self.imgv = ImageView()
        self.stack = QStackedWidget(); self.stack.addWidget(self.viz); self.stack.addWidget(self.video); self.stack.addWidget(self.imgv)
        self.home = HomeView(); self.home.pick.connect(self.open_kind); self.home.recent.connect(self.open_recent)
        self.tv = TextView(); self.tv.changed.connect(self.update_title); self.stack.addWidget(self.home)
        # controls
        self.seek = QSlider(Qt.Horizontal); self.seek.setObjectName("seek"); self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "seeking", True))
        self.seek.sliderReleased.connect(self.do_seek)
        self.cur, self.dur = QLabel("0:00"), QLabel("0:00")
        def mk(ic, f, tip=""):
            dark = QSettings("FoxReader", "FoxReader").value("theme", "light", type=str) == "dark"
            b = QPushButton(); b.setIcon(icon(ic, "#dce6ed" if dark else INK)); b.setIconSize(QSize(20, 20)); b.clicked.connect(f); b.setToolTip(tip); return b
        self.b_play = mk("play", self.toggle, "Play / Pause (Space)")
        self.b_stop = mk("stop", self.stop, "Stop"); self.b_prev = mk("prev", self.prev, "Previous"); self.b_next = mk("next", self.next, "Next")
        self.b_home = mk("home", self.go_home, "Home - choose what to open (Ctrl+H)")
        self.b_fs = mk("fs", self.fullscreen, "Fullscreen (F)")
        self.b_eq = mk("eq", lambda: self.eqd.setVisible(not self.eqd.isVisible()), "Equalizer"); 
        self.b_pl = mk("list", lambda: self.pld.setVisible(not self.pld.isVisible()), "Playlist")
        self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0, 125); self.vol.setValue(80); self.vol.setFixedWidth(112)
        self.vol.valueChanged.connect(lambda v: self.mp.audio_set_volume(v))
        dark = QSettings("FoxReader", "FoxReader").value("theme", "light", type=str) == "dark"
        self.vl = QLabel(); self.vl.setPixmap(icon("vol", "#dce6ed" if dark else INK).pixmap(20, 20))
        bar = QHBoxLayout(); bar.setContentsMargins(12, 0, 12, 8); bar.setSpacing(4)
        for b in (self.b_home, self.b_play, self.b_prev, self.b_stop, self.b_next, self.b_fs, self.b_eq, self.b_pl): bar.addWidget(b)
        bar.addStretch(); bar.addWidget(self.vl); bar.addWidget(self.vol)
        sk = QHBoxLayout(); sk.setContentsMargins(12, 8, 12, 0); sk.setSpacing(12); sk.addWidget(self.cur); sk.addWidget(self.seek, 1); sk.addWidget(self.dur)
        self.ctrl = QWidget(); cl = QVBoxLayout(self.ctrl); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(4)
        cl.addLayout(sk); cl.addLayout(bar)
        c = QWidget(); l = QVBoxLayout(c); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(0)
        l.addWidget(self.stack, 1); l.addWidget(self.ctrl)

        # tabs: 1 = Watch Video (player, music, pictures), 2 = Writing Code (editor + sandbox). Each keeps its own state.
        self.code_home = CodeHome(); self.code_pages = QStackedWidget(); self.code_pages.addWidget(self.code_home); self.code_pages.addWidget(self.tv)
        for w_ in (self.code_home, self.tv): w_.new_req.connect(self.new_code); w_.open_req.connect(self.open_code_dialog)
        # tabs are opened on demand: at the start there is only "Watch Video". "+" opens a chooser; a "Writing Code" tab appears
        # when you open or create a code file. Each kind of tab exists once (one player, one editor).
        self.tab_w = {"watch": c, "code": self.code_pages}; self.launcher = None
        self.pages = QStackedWidget(); self.pages.addWidget(c); self.pages.addWidget(self.code_pages)
        self.tabs = QTabBar(); self.tabs.setDrawBase(False); self.tabs.setExpanding(False); self.tabs.setCursor(Qt.PointingHandCursor)
        self.tabs.setIconSize(QSize(20, 20)); self.tabs.setFocusPolicy(Qt.NoFocus)
        self.ensure_tab("watch"); self.pages.setCurrentWidget(c); self.cur_key = "watch"
        self.tabs.currentChanged.connect(self.on_tab); self.tabs.tabCloseRequested.connect(self.close_tab)
        self.add_b = QToolButton(); self.add_b.setObjectName("addtab"); self.add_b.setText("+"); self.add_b.setToolTip("New tab (Ctrl+T)")
        self.add_b.setCursor(Qt.PointingHandCursor); self.add_b.setFocusPolicy(Qt.NoFocus); self.add_b.clicked.connect(self.new_tab)
        self.tabwrap = QFrame(); self.tabwrap.setObjectName("tabwrap"); tl = QHBoxLayout(self.tabwrap); tl.setContentsMargins(12, 4, 12, 0); tl.setSpacing(4)
        self.split_b = QToolButton(); self.split_b.setObjectName("addtab"); self.split_b.setText("Split"); self.split_b.setStyleSheet("font-size:13px;")
        self.split_b.setToolTip("Split view: show this tab next to another tab (Ctrl+\\)"); self.split_b.setCursor(Qt.PointingHandCursor); self.split_b.setFocusPolicy(Qt.NoFocus); self.split_b.clicked.connect(self.toggle_split)
        tl.addWidget(self.tabs); tl.addWidget(self.add_b); tl.addWidget(self.split_b); tl.addStretch(1)
        root = QWidget(); rl = QVBoxLayout(root); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0); rl.addWidget(self.tabwrap)
        self.pages2 = QStackedWidget(); self.split = QSplitter(Qt.Horizontal); self.split.setChildrenCollapsible(False); self.split.setHandleWidth(3)
        self.split.addWidget(self.pages); self.split.addWidget(self.pages2); self.pages2.hide(); self.split_key = None; self.left_key = "watch"; self.prev_key = None
        rl.addWidget(self.split, 1)
        self.setCentralWidget(root); self.saved_docks = (True, False)

        self.plist = QListWidget(); self.plist.itemDoubleClicked.connect(lambda it: self.play_index(self.plist.row(it)))
        self.pld = QDockWidget("Playlist", self); self.pld.setWidget(self.plist); self.addDockWidget(Qt.RightDockWidgetArea, self.pld)
        self.eqd = EqualizerDock(self); self.addDockWidget(Qt.RightDockWidgetArea, self.eqd); self.eqd.hide()
        self.make_menus(); self.mp.audio_set_volume(80)

        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(33)
        self.add_files(sorted(str(p) for p in SONGS.iterdir() if p.suffix.lower() in MEDIA_EXT | PLAYLIST_EXT))
        n = len(self.files); self.add_files([a for a in sys.argv[1:] if os.path.isfile(a)])
        if len(self.files) > n: self.play_index(n)                      # files given on the command line / "Open with" start right away
        else: self.go_home(first=True)
        self.setup_recovery()

    # ---------- menus ----------
    def make_menus(self):
        mb = self.menuBar(); self.plain_keys = []
        def add(menu, text, f, key=None):
            a = QAction(text, self); a.triggered.connect(f)
            if key: a.setShortcut(QKeySequence(key))
            if key and not any(t in key for t in ("Ctrl", "Alt", "Shift", "Meta")) and not re.fullmatch(r"F\d+", key) and key != "Esc": self.plain_keys.append(a)
            menu.addAction(a); self.addAction(a); a.setShortcutContext(Qt.WindowShortcut); return a
        m = mb.addMenu("&File")
        add(m, "Home", self.go_home, "Ctrl+H"); add(m, "New Tab", self.new_tab, "Ctrl+T"); add(m, "Open Web Browser Tab", self.open_web, "Ctrl+B"); add(m, "Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W"); add(m, "Reopen Closed Tab", self.reopen_closed, "Ctrl+Shift+T"); m.addSeparator()
        for k in ("video", "music", "pictures", "text", "code", "playlist"): add(m, f"Open {KINDS[k][0]}...", lambda k=k: self.open_kind(k))
        add(m, "New Code File...", self.new_code, "Ctrl+N"); add(m, "Open Any File(s)...", self.open_files, "Ctrl+O"); add(m, "Open Folder...", self.open_folder, "Ctrl+F"); m.addSeparator()
        add(m, "Save Text File", self.tv.save, "Ctrl+S"); add(m, "Clear Playlist", self.clear); m.addSeparator(); add(m, "Quit", self.close, "Ctrl+Q")
        m = mb.addMenu("&Playback")
        add(m, "Play / Pause", self.toggle, "Space"); add(m, "Stop", self.stop, "S")
        add(m, "Next", self.next, "N"); add(m, "Previous", self.prev, "P")
        add(m, "Jump Forward 10s", lambda: self.jump(10000), "Right"); add(m, "Jump Backward 10s", lambda: self.jump(-10000), "Left")
        m = mb.addMenu("&Audio")
        add(m, "Increase Volume", lambda: self.vol.setValue(self.vol.value() + 5), "Up")
        add(m, "Decrease Volume", lambda: self.vol.setValue(self.vol.value() - 5), "Down")
        add(m, "Mute", lambda: self.mp.audio_toggle_mute(), "M")
        m = mb.addMenu("&Video"); add(m, "Fullscreen", self.fullscreen, "F")
        for key, fn in (("F11", self.fullscreen), ("Esc", self.exit_fullscreen)):
            a = QAction(self); a.setShortcut(QKeySequence(key)); a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(fn); self.addAction(a)
        m = mb.addMenu("&Tools"); add(m, "Equalizer && Optimizer", lambda: self.eqd.setVisible(not self.eqd.isVisible()), "Ctrl+E")
        add(m, "Auto Optimize", self.auto_optimize); add(m, "Browser User Agent...", self.user_agent_dialog)
        add(m, "Browser DNS...", lambda: self.dns_menu()); add(m, "Site Permissions...", self.permissions_dialog)
        add(m, "Run Code in Sandbox / Stop", self.run_code, "F5")
        m = mb.addMenu("&Settings")
        self.theme_act = QAction("Dark mode", self, checkable=True)
        self.theme_act.setChecked(self.settings().value("theme", "light", type=str) == "dark")
        self.theme_act.toggled.connect(self.set_theme)
        m.addAction(self.theme_act)
        self.anim_act = QAction("Animations", self, checkable=True); self.anim_act.setChecked(bool(ANIM_MS)); self.anim_act.toggled.connect(self.toggle_animations); m.addAction(self.anim_act)
        m.addSeparator(); add(m, "Preferences...", self.preferences_dialog, "Ctrl+,")
        m = mb.addMenu("V&iew"); add(m, "Watch Video Tab", lambda: self.show_tab("watch"), "Ctrl+1"); add(m, "Writing Code Tab", lambda: self.show_tab("code"), "Ctrl+2")
        add(m, "Split Tab / Unsplit", self.toggle_split, "Ctrl+\\"); m.addSeparator()
        add(m, "Playlist", lambda: self.pld.setVisible(not self.pld.isVisible()), "Ctrl+L")
        m.addSeparator()
        add(m, "Zoom In (pictures)", lambda: self.imgv.zoom_by(1.25), "+"); add(m, "Zoom Out (pictures)", lambda: self.imgv.zoom_by(0.8), "-")
        add(m, "Fit to Window", self.imgv.reset, "0"); add(m, "Rotate Picture", self.imgv.rotate, "R")
        add(m, "Slideshow On / Off", self.toggle_slideshow, "Ctrl+Shift+S")
        m.addSeparator(); add(m, "Markdown / HTML: Preview / Source", lambda: self.tv.path and self.tv.set_preview(), "Ctrl+Shift+M")
        m = mb.addMenu("&Help")
        add(m, "Keyboard Shortcuts", self.show_shortcuts, "F1"); add(m, "About FoxReader", self.show_about)

    def show_shortcuts(self):
        QMessageBox.information(self, "Keyboard Shortcuts",
            "<h3>Keyboard Shortcuts</h3><table cellpadding='3'>"
            "<tr><td><b>Ctrl+H</b></td><td>Home - choose what to open</td></tr>"
            "<tr><td><b>Ctrl+1 / Ctrl+2</b></td><td>Switch to the Watch Video / Writing Code tab</td></tr>"
            "<tr><td><b>Ctrl+\\</b></td><td>Split the current tab next to another tab / back to one view</td></tr>"
            "<tr><td><b>Tools &gt; Browser User Agent</b></td><td>Choose or type the user agent the browser tabs send</td></tr>"
            "<tr><td><b>Tools &gt; Browser DNS</b></td><td>Pick OpenDNS / Cloudflare / Google / Custom / Default (or click DNS in a browser tab)</td></tr>"
            "<tr><td><b>Tools &gt; Site Permissions</b></td><td>See or remove saved camera / location / microphone choices</td></tr>"
            "<tr><td><b>Ctrl+Shift+T</b></td><td>Reopen the tab you just closed (your text is kept in the cache-file folder)</td></tr>"
            "<tr><td><b>Ctrl+T / Ctrl+W</b></td><td>New tab (choose what to open) / close tab</td></tr>"
            "<tr><td><b>Ctrl+N</b></td><td>New code file</td></tr>"
            "<tr><td><b>Space</b></td><td>Play / Pause</td></tr>"
            "<tr><td><b>S</b></td><td>Stop</td></tr>"
            "<tr><td><b>N / P</b></td><td>Next / Previous</td></tr>"
            "<tr><td><b>Left / Right</b></td><td>Jump 10 seconds back / forward (previous / next on pictures)</td></tr>"
            "<tr><td><b>Up / Down</b></td><td>Volume up / down</td></tr>"
            "<tr><td><b>M</b></td><td>Mute</td></tr>"
            "<tr><td><b>F or F11</b></td><td>Toggle fullscreen</td></tr>"
            "<tr><td><b>Esc</b></td><td>Exit fullscreen</td></tr>"
            "<tr><td><b>Ctrl+O</b></td><td>Open file(s)</td></tr>"
            "<tr><td><b>Ctrl+F</b></td><td>Open folder</td></tr>"
            "<tr><td><b>Ctrl+E</b></td><td>Equalizer &amp; Optimizer</td></tr>"
            "<tr><td><b>Ctrl+L</b></td><td>Playlist</td></tr>"
            "<tr><td><b>+ / - / 0</b></td><td>Pictures: zoom in / out / fit (mouse wheel too, drag to pan)</td></tr>"
            "<tr><td><b>R</b></td><td>Rotate picture</td></tr>"
            "<tr><td><b>Ctrl+Shift+S</b></td><td>Slideshow on / off (Space also toggles on a picture)</td></tr>"
            "<tr><td><b>Ctrl+S</b></td><td>Save the text / Markdown file being edited</td></tr>"
            "<tr><td><b>F5</b></td><td>Run the code in the sandbox (Python, JavaScript, Java, HTML) / stop it</td></tr>"
            "<tr><td><b>Ctrl+Shift+M</b></td><td>Markdown / HTML: switch between source and formatted view</td></tr>"
            "<tr><td><b>Ctrl+Q</b></td><td>Quit</td></tr>"
            "<tr><td><b>F1</b></td><td>This help</td></tr></table>")

    def show_about(self):
        ff = "found" if FFMPEG else "not found (bitrate, resolution and graphs are disabled)"
        box = QMessageBox(self); box.setWindowTitle("About FoxReader")
        if LOGO.exists(): box.setIconPixmap(QPixmap(str(LOGO)).scaledToHeight(96, Qt.SmoothTransformation))
        box.setText(
            "<h2>FoxReader</h2>"
            "<p>An all-in-one app: videos, music, pictures, text and code in one window and one playlist, "
            "with an equalizer, song auto-optimizer, bitrate control and video resolution control.</p>"
            "<p><b>Owner:</b> Prach</p>"
            "<h4>Features</h4><ul>"
            "<li>Plays most audio and video formats (powered by Qt Multimedia)</li>"
            "<li>Opens pictures (PNG, JPG, GIF, BMP, WebP, TIFF, SVG, HEIC, AVIF, JPEG 2000, TGA...) with zoom, pan, rotate and slideshow</li>"
            "<li>Opens playlist files (.m3u, .m3u8, .pls)</li>"
            "<li>Sandbox: runs Python, JavaScript and Java safely (temp folder, time / memory limits, no network on Linux) and HTML in a locked-down browser pane</li>"
            "<li>Edits text and code files (.txt, .md, .html, .css, .js, .py, .java) with syntax colours; Markdown and HTML have a button for the formatted view</li>"
            "<li>4-band equalizer (Bass, Low-pitch, Other, High-pitch) with presets</li>"
            "<li>Auto Optimize: analyzes the whole song and balances the EQ for you</li>"
            "<li>Bitrate and video resolution sliders (re-encoded with ffmpeg and cached)</li>"
            "<li>Live spectrum and Bass-vs-Music graph for audio files</li>"
            "<li>Drag &amp; drop, playlist, and automatic loading of the <i>songs</i> folder</li></ul>"
            f"<p><b>ffmpeg:</b> {ff}<br><b>Songs folder:</b> {SONGS}</p>"
            "<p>Press <b>F1</b> for keyboard shortcuts.</p>"
            "<p>&copy; Prach. All rights reserved.</p>"); box.exec()

    # ---------- playlist ----------
    @staticmethod
    def read_playlist(pl):
        """Return the local media files listed in an .m3u / .m3u8 / .pls file."""
        out = []; base = Path(pl).parent
        try: lines = Path(pl).read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError: return out
        for ln in lines:
            ln = ln.strip()
            if ln.lower().startswith("file") and "=" in ln: ln = ln.split("=", 1)[1].strip()   # pls
            if not ln or ln.startswith("#") or "=" in ln[:12] or ln.lower().startswith(("http:", "https:", "rtsp:", "mms:")): continue
            q = Path(ln) if Path(ln).is_absolute() else base / ln
            if q.is_file(): out.append(str(q))
        return out

    def add_files(self, paths):
        expanded = []
        for p in paths: expanded += self.read_playlist(p) if Path(p).suffix.lower() in PLAYLIST_EXT else [p]
        code = [p for p in expanded if Path(p).suffix.lower() in TEXT_EXT]; paths = [p for p in expanded if p not in code]
        if code: self.open_code(code[-1])
        for p in paths:
            if Path(p).suffix.lower() in MEDIA_EXT:
                self.files.append(p); x = Path(p).suffix.lower()
                self.plist.addItem(QListWidgetItem(icon("video" if x in VIDEO_EXT else "image" if x in IMAGE_EXT else "code" if x in CODE_EXT else "text" if x in TEXT_EXT else "music", "#3aa6ee"), Path(p).stem))
    def settings(self): return QSettings("FoxReader", "FoxReader")
    def start_dir(self): d = self.settings().value("lastdir", "", type=str); return d if d and os.path.isdir(d) else str(SONGS)
    def recent_files(self): return [p for p in self.settings().value("recent", [], type=list) if isinstance(p, str)]
    def remember(self, path):
        r = [path] + [p for p in self.recent_files() if p != path]; st = self.settings()
        st.setValue("recent", r[:8]); st.setValue("lastdir", str(Path(path).parent))

    def open_kind(self, kind):
        if kind == "folder": return self.open_folder()
        if kind == "web": return self.open_web()
        g = lambda ext: " ".join("*" + e for e in sorted(ext)); name, ext = KINDS[kind][0], KINDS[kind][4]
        if kind == "any":
            flt = (f"All supported files ({g(ext)});;Playlists ({g(PLAYLIST_EXT)});;Videos ({g(VIDEO_EXT)});;Music ({g(AUDIO_EXT)});;"
                   f"Pictures ({g(IMAGE_EXT)});;Text and code ({g(TEXT_EXT)})")
        else: flt = f"{name} ({g(ext)});;All files (*)"
        fs, _ = QFileDialog.getOpenFileNames(self, f"Open {name}", self.start_dir(), flt)
        if fs: n = len(self.files); self.add_files(fs); len(self.files) > n and self.play_index(n)
        return bool(fs)
    def open_files(self): self.open_kind("any")
    def open_recent(self, path):
        n = len(self.files); self.add_files([path]); len(self.files) > n and self.play_index(n)
        return True
    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Open Folder", self.start_dir())
        if d: n = len(self.files); self.add_files(sorted(str(p) for p in Path(d).iterdir() if p.is_file())); len(self.files) > n and self.play_index(n)
        return bool(d)
    def go_home(self, first=False):
        self.mp.stop(); self.slideshow = False; self.idx = -1; self.pcm, self.pcm_path = None, ""
        self.plist.setCurrentRow(-1); self.plist.clearSelection(); self.seek.setValue(0); self.seek.setEnabled(False); self.set_play(False)
        self.refresh_title(); self.home.set_recent(self.recent_files()); self.stack.setCurrentWidget(self.home)
        if self.cur_tab() == "watch": self.statusBar().showMessage(f"{len(self.files)} item(s) in the playlist. Pick what to open, or drop files here." if self.files else "Pick what to open, or drop files here.")
    def clear(self):
        self.stop(); self.files.clear(); self.plist.clear(); self.idx = -1; self.go_home()
    def dragEnterEvent(self, e): e.acceptProposedAction()
    def dropEvent(self, e):
        paths = []
        for u in e.mimeData().urls():
            p = u.toLocalFile(); paths += sorted(str(q) for q in Path(p).iterdir() if q.is_file()) if os.path.isdir(p) else [p]   # folders: add what is inside
        n = len(self.files); self.add_files(paths)
        if len(self.files) > n: self.play_index(n)

    # ---------- playback ----------
    def is_video(self): return 0 <= self.idx < len(self.files) and Path(self.files[self.idx]).suffix.lower() in VIDEO_EXT

    def is_image(self): return 0 <= self.idx < len(self.files) and Path(self.files[self.idx]).suffix.lower() in IMAGE_EXT

    def update_title(self):
        i = self.tab_of("code")
        if i >= 0: self.tabs.setTabText(i, "Writing Code" + (" *" if self.tv.dirty else ""))
        self.refresh_title()

    def refresh_title(self):
        if self.cur_tab() == "new": t = "New Tab"
        elif self.cur_tab().startswith("web"): t = self.tab_w[self.cur_tab()].title or "Browser"
        elif self.cur_tab() == "code": t = (f"{'* ' if self.tv.dirty else ''}{Path(self.tv.path).name}" if self.tv.path else "Writing Code")
        elif self.idx >= 0: t = Path(self.files[self.idx]).stem
        else: self.setWindowTitle("FoxReader"); return
        self.setWindowTitle(f"{t} - FoxReader")

    # ---------- tabs ----------
    def key_at(self, i): return self.tabs.tabData(i) if i >= 0 else ""
    def tab_of(self, key):
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == key: return i
        return -1
    def cur_tab(self): return self.key_at(self.tabs.currentIndex())

    def ensure_tab(self, key):
        """Create the tab if it is not open yet (Watch Video, then Writing Code, then New Tab). Returns its index."""
        i = self.tab_of(key)
        if i < 0:
            rk = lambda k: TAB_RANK.get(k, 2); pos = sum(1 for n in range(self.tabs.count()) if rk(self.key_at(n)) <= rk(key)); text, ic = TAB_INFO.get(key, ("Browser", "web"))
            self.tabs.blockSignals(True); i = self.tabs.insertTab(pos, icon(ic, "#3aa6ee"), text); self.tabs.setTabData(i, key); self.tabs.blockSignals(False)
            dark = self.settings().value("theme", "light", type=str) == "dark"
            b = QToolButton(); b.setObjectName("tabclose"); b.setIcon(icon("close", "#9fb0bd" if dark else "#6b7f8c", 14)); b.setIconSize(QSize(14, 14)); b.setFixedSize(20, 20)
            b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); b.setToolTip("Close tab (Ctrl+W)"); b.clicked.connect(lambda _=0, k=key: self.close_tab(self.tab_of(k)))
            self.tabs.setTabButton(i, QTabBar.RightSide, b); self.sync_close()
        return i

    def sync_close(self):
        """A lone tab has no close button."""
        n = self.tabs.count()
        for i in range(n):
            b = self.tabs.tabButton(i, QTabBar.RightSide)
            if b: b.setVisible(n > 1)

    def select(self, i):
        if i < 0: return
        if self.tabs.currentIndex() == i: self.on_tab(i)
        else: self.tabs.setCurrentIndex(i)

    def show_tab(self, key): self.select(self.ensure_tab(key))

    def remove_tab(self, i):
        self.tabs.blockSignals(True); self.tabs.removeTab(i); self.tabs.blockSignals(False); self.sync_close()

    def new_tab(self):
        """+ : a tab that asks what you want to open."""
        if self.launcher is None:
            self.launcher = HomeView(); self.pages.addWidget(self.launcher)
            self.launcher.pick.connect(self.launcher_pick); self.launcher.recent.connect(self.launcher_recent)
        self.launcher.set_recent(self.recent_files()); self.tab_w["new"] = self.launcher; self.show_tab("new")

    def launcher_pick(self, kind):
        if self.open_kind(kind): self.finish_launcher()
    def launcher_recent(self, path):
        if self.open_recent(path): self.finish_launcher()

    def finish_launcher(self):
        """Something was opened from the New Tab chooser: the chooser has done its job, so close it."""
        k, i = self.cur_tab(), self.tab_of("new")
        if i >= 0 and k != "new": self.remove_tab(i); self.discard_launcher(); self.select(self.tab_of(k)); self.fix_split()

    def discard_launcher(self):
        if self.launcher is not None: self.pages.removeWidget(self.launcher); self.launcher.deleteLater(); self.launcher = None; self.tab_w.pop("new", None)

    # ---------- auto-save + recovery (anti accidental close) ----------
    def setup_recovery(self):
        self.toast = Toast(self); self.closed = []; self.draft_hash = {}; self._quit_ok = False; self.quit_pending = False; self.recovery_hold = False
        self.t_draft = QTimer(self); self.t_draft.timeout.connect(self.autosave_draft); self.t_draft.start(AUTOSAVE_SECONDS * 1000)
        self.t_sess = QTimer(self); self.t_sess.timeout.connect(self.save_session); self.t_sess.start(SESSION_SECONDS * 1000)
        self.load_prefs()
        QTimer.singleShot(700, self.offer_recovery)

    def autosave_draft(self, force=False):
        """Copy the text being edited (if it changed) to cache-file/. The real file is not touched. Returns False if the copy failed."""
        tv = self.tv
        if not tv.path: return True
        try:
            if tv.dirty:
                text = tv.edit.toPlainText(); h = hash(text); dp = draft_path(tv.path)
                if self.draft_hash.get(tv.path) != h or not dp.exists():
                    write_json(dp, {"path": tv.path, "text": text, "cursor": tv.edit.textCursor().position(), "time": time.time()}); self.draft_hash[tv.path] = h
            elif tv.path in self.draft_hash: discard_draft(tv.path); self.draft_hash.pop(tv.path, None)      # edited back to the original: no draft needed
        except OSError: return False
        return True

    def has_web_pages(self):
        return any(k.startswith("web") and w.view.url().toString() not in ("", "about:blank") for k, w in self.tab_w.items())

    def save_session(self, clean=False):
        """Save the addresses of the open web pages (and the open code file) to cache-file/session.json."""
        if self.recovery_hold: return          # the last session has not been restored or dismissed yet: keep it
        web = [{"url": w.view.url().toString(), "title": w.title} for k, w in self.tab_w.items()
               if k.startswith("web") and w.view.url().toString() not in ("", "about:blank")]
        try: write_json(DRAFTS / "session.json", {"time": time.time(), "clean": clean, "web": web, "code": self.tv.path if self.tab_of("code") >= 0 else None})
        except OSError: pass

    def list_drafts(self):
        out = []
        for f in DRAFTS.glob("*.draft.json"):
            d = read_json(f)
            if not d or not isinstance(d.get("path"), str) or not isinstance(d.get("text"), str): f.unlink(missing_ok=True); continue
            try:
                if not os.path.isfile(d["path"]) or disk_text(d["path"]) == d["text"]: f.unlink(missing_ok=True); continue      # nothing to restore
            except OSError: continue
            out.append(d)
        return sorted(out, key=lambda d: d.get("time", 0), reverse=True)

    def offer_recovery(self):
        sess = read_json(DRAFTS / "session.json") or {}; unclean = not sess.get("clean", True)
        web = sess.get("web", []) if unclean and isinstance(sess.get("web"), list) else []
        code = sess.get("code") if unclean and isinstance(sess.get("code"), str) and os.path.isfile(sess.get("code")) else None
        drafts = self.list_drafts(); self.pending = {"web": [w for w in web if isinstance(w, dict) and w.get("url")], "drafts": drafts, "code": code}
        if not self.pending["web"] and not drafts and not code: return
        self.recovery_hold = True
        parts = []
        if drafts: parts.append("unsaved text in " + ", ".join(Path(d["path"]).name for d in drafts[:3]) + ("..." if len(drafts) > 3 else ""))
        elif code: parts.append("the file " + Path(code).name)
        if self.pending["web"]: parts.append(f"{len(self.pending['web'])} web page(s)")
        self.toast.show_msg("We saved your work!", "Last time FoxReader closed there was " + " and ".join(parts) + ". Your original files were not changed. Restore it?",
            [("Restore", self.do_recovery, False), ("Dismiss", self.drop_recovery, True)], ms=25000)

    def do_recovery(self):
        pend, self.recovery_hold = self.pending, False
        for w in pend["web"]:
            if HAVE_WEB: self.open_web(w["url"])
        if pend["drafts"]:
            d = pend["drafts"][0]; self.restore_code(d["path"], d["text"], d.get("cursor", 0)); pend["drafts"] = pend["drafts"][1:]
        elif pend["code"]: self.restore_code(pend["code"])
        pend["web"] = []; pend["code"] = None; self.save_session()
        if pend["drafts"]:
            n = pend["drafts"][0]; self.recovery_hold = False
            self.toast.show_msg("More saved text", f"{Path(n['path']).name} (and {len(pend['drafts']) - 1} more) also has saved changes. Restore the next one?",
                [("Restore next", self.do_recovery, False), ("Dismiss", self.drop_recovery, True)], ms=25000)

    def drop_recovery(self):
        for d in getattr(self, "pending", {}).get("drafts", []): discard_draft(d["path"])
        self.pending = {"web": [], "drafts": [], "code": None}; self.recovery_hold = False; self.save_session(clean=True)

    def restore_code(self, path, text=None, cursor=0):
        """Open a file in the Writing Code tab and, if given, put the saved (unsaved-to-disk) text back in it."""
        if not os.path.isfile(path): self.statusBar().showMessage("That file no longer exists: " + path, 5000); return
        self.open_code(path)
        if self.tv.path != path or text is None: return
        if text != self.tv.edit.toPlainText():
            self.tv.edit.setPlainText(text); self.tv.edit.document().setModified(True)
            c = self.tv.edit.textCursor(); c.setPosition(max(0, min(int(cursor or 0), len(text)))); self.tv.edit.setTextCursor(c)

    def snapshot_code(self):
        tv = self.tv
        if not tv.path or self.code_pages.currentWidget() is not tv: return None
        return {"kind": "code", "path": tv.path, "text": tv.edit.toPlainText() if tv.dirty else None, "cursor": tv.edit.textCursor().position()}

    def reopen_closed(self):
        if not self.closed: self.statusBar().showMessage("No closed tab to reopen.", 3000); return
        e = self.closed.pop()
        if e["kind"] == "code": self.restore_code(e["path"], e.get("text"), e.get("cursor", 0))
        elif HAVE_WEB: self.open_web(e["url"])

    def closed_toast(self, e):
        self.closed.append(e); self.closed = self.closed[-10:]
        if e["kind"] == "code":
            name = Path(e["path"]).name; extra = " Your changes are kept in the cache-file folder; the original file was not changed." if e.get("text") is not None else ""
            self.toast.show_msg("We saved your file!", f"{name} was closed.{extra} Click if this is an accidental close.", [("Reopen", self.reopen_closed, False)], ms=12000)
        else:
            self.toast.show_msg("We saved your page!", (e.get("title") or e["url"])[:60] + " was closed. Click if this is an accidental close.", [("Reopen", self.reopen_closed, False)], ms=12000)

    def confirm_quit(self):
        """Closing the window: the work is already saved; wait a few seconds so an accidental click can be undone."""
        self.quit_pending = True; dirty = self.tv.dirty
        self.toast.show_msg("We saved your file!" if dirty else "We saved your web pages!", "FoxReader is closing. Click if this is an accidental close.",
            [("Accidental close - stay open", lambda: setattr(self, "quit_pending", False), False), ("Close now", self.finish_quit, True)], ms=6000, on_timeout=self.finish_quit)

    def finish_quit(self): self._quit_ok = True; self.close()

    # ---------- split view ----------
    def move_tab(self, key, to_right):
        """Move a tab's page between the left and the right pane (the tab stays in the tab bar)."""
        w = self.tab_w[key]; src, dst = (self.pages, self.pages2) if to_right else (self.pages2, self.pages)
        src.removeWidget(w); dst.addWidget(w); dst.setCurrentWidget(w); w.show()
        if key == "watch": QTimer.singleShot(80, self.bind_video)       # the video frame got a new native window: point the player at it again

    def toggle_split(self):
        self.unsplit() if self.split_key else self.split_tab()

    def split_tab(self):
        """Show the current tab on the right and another tab on the left (a New Tab chooser if there is no other tab)."""
        key = self.cur_tab()
        if not key or self.split_key: return
        if self.tabs.count() < 2: self.new_tab()
        others = [self.key_at(n) for n in range(self.tabs.count()) if self.key_at(n) != key]
        left = self.prev_key if self.prev_key in others else self.left_key if self.left_key in others else others[-1]
        self.split_key = key; self.move_tab(key, True); self.pages2.show()
        self.split.setSizes([self.split.width() // 2, self.split.width() // 2])
        self.select(self.tab_of(left)); self.statusBar().showMessage("Split view  -  click a tab to show it on the left; Ctrl+\\ or Split to go back", 6000)
        self.split_b.setText("Unsplit")

    def unsplit(self):
        if not self.split_key: return
        key, self.split_key = self.split_key, None; self.move_tab(key, False); self.pages2.hide(); self.split_b.setText("Split")
        self.select(self.tab_of(self.cur_key if self.tab_of(self.cur_key) >= 0 else key))

    def fix_split(self):
        """After a tab closed: keep the left pane valid, or leave split view if only one tab is left."""
        if not self.split_key: return
        others = [self.key_at(n) for n in range(self.tabs.count()) if self.key_at(n) != self.split_key]
        if not others: self.unsplit()
        elif self.left_key not in others: self.select(self.tab_of(others[-1]))

    def other_pane(self, key):
        """The pane that does not hold this tab (only while split)."""
        if not self.split_key: return None
        return self.pages2 if self.tab_w[key].parentWidget() is self.pages else self.pages

    # ---------- browser DNS ----------
    def dns_mode(self):
        m = self.settings().value("dns", "default", type=str); return m if m in DNS_PRESETS else "default"

    def dns_servers(self):
        m = self.dns_mode()
        if m != "custom": return DNS_PRESETS[m][1]
        return [x.strip() for x in self.settings().value("dns_custom", "", type=str).replace(";", ",").split(",") if x.strip()]

    def system_proxy(self):
        """True if the computer is set up to use a proxy (then FoxReader leaves the browser's network alone)."""
        try:
            from PySide6.QtNetwork import QNetworkProxyFactory, QNetworkProxyQuery
            return any(p.type() in (QNetworkProxy.Socks5Proxy, QNetworkProxy.HttpProxy, QNetworkProxy.HttpCachingProxy) and p.hostName()
                       for p in QNetworkProxyFactory.systemProxyForQuery(QNetworkProxyQuery(QUrl("https://example.com"))))
        except Exception: return False

    def apply_dns(self):
        """Use the chosen DNS in the browser. QtWebEngine reads its proxy only when the browser starts, so the local helper is
        installed once, before the first browser tab; later the helper just looks names up on whichever DNS is chosen."""
        if getattr(self, "_dnsp", None) is None and not getattr(self, "_wp", None) and not self.system_proxy():
            self._dnsp = DnsProxy(); QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.Socks5Proxy, "127.0.0.1", self._dnsp.server_address[1]))
        if getattr(self, "_dnsp", None) is not None:
            self._dnsp.dns_servers = self.dns_servers() if self.dns_mode() != "default" else []; _dns_cache.clear()
        for k, w in self.tab_w.items():
            if k.startswith("web"): w.set_dns_label(self.dns_label())

    def dns_label(self): return DNS_PRESETS[self.dns_mode()][0] if getattr(self, "_dnsp", None) is not None and (self.dns_servers() or self.dns_mode() == "default") else "Default"

    def dns_menu(self, anchor=None):
        """Popup with the DNS choices (OpenDNS, Cloudflare, Google Public DNS, Custom, Default)."""
        if not HAVE_WEB: return
        if getattr(self, "_wp", None) is not None and getattr(self, "_dnsp", None) is None:
            QMessageBox.information(self, "Browser DNS", "This computer uses a proxy, so FoxReader leaves the browser's network settings alone and the DNS can't be changed here."); return
        menu = QMenu(self); grp = QActionGroup(menu); grp.setExclusive(True); cur = self.dns_mode(); acts = {}
        for key, (name, ips) in DNS_PRESETS.items():
            a = menu.addAction(name + (f"   ({', '.join(ips)})" if ips else "   (" + ", ".join(self.dns_servers()) + ")" if key == "custom" and self.dns_servers() else "")); a.setCheckable(True); a.setChecked(key == cur); grp.addAction(a); acts[a] = key
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor is not None else QCursor.pos()
        a = menu.exec(pos)
        if a is not None: self.choose_dns(acts[a])

    def choose_dns(self, key):
        st = self.settings()
        if key == "custom":
            txt, ok = QInputDialog.getText(self, "Custom DNS", "DNS server IP address(es), separated by commas\n(for example 9.9.9.9, 149.112.112.112):", text=st.value("dns_custom", "", type=str))
            if not ok: return
            ips = [x.strip() for x in txt.replace(";", ",").split(",") if x.strip()]
            try:
                for x in ips: ipaddress.ip_address(x)
            except ValueError: QMessageBox.warning(self, "Custom DNS", "That is not a valid IP address."); return
            if not ips: key = "default"
            else: st.setValue("dns_custom", ", ".join(ips))
        st.setValue("dns", key); self.apply_dns()
        for k, w in self.tab_w.items():
            if k.startswith("web"): w.view.reload()
        self.statusBar().showMessage("Browser DNS: " + DNS_PRESETS[key][0] + (" (" + ", ".join(self.dns_servers()) + ")" if self.dns_servers() else ""), 6000)

    # ---------- permission popups ----------
    def saved_perms(self):
        try: d = json.loads(self.settings().value("site_permissions", "{}", type=str)); return d if isinstance(d, dict) else {}
        except ValueError: return {}

    def save_perms(self, d): self.settings().setValue("site_permissions", json.dumps(d))

    def web_permission(self, origin, kind, allow, block):
        """A page asks for the camera, microphone, location, screen... Use the saved answer or pop up a question."""
        def call(f):
            try: f()
            except RuntimeError: pass                                   # the tab was closed while the question was open
        key = f"{origin}|{kind}"; old = self.saved_perms().get(key)
        if old: call(allow if old == "allow" else block); return
        host = QUrl(origin).host() or origin
        box = QMessageBox(self); box.setWindowTitle("Permission request"); box.setIcon(QMessageBox.Question); box.setWindowModality(Qt.WindowModal)
        box.setText(f"<b>{host}</b> wants to {PERM_TEXT.get(kind, 'use: ' + kind)}."); box.setInformativeText("Allow it?")
        ok = box.addButton("Allow", QMessageBox.AcceptRole); no = box.addButton("Block", QMessageBox.RejectRole); box.setDefaultButton(no); box.setEscapeButton(no)
        rem = QCheckBox("Remember my choice for this site"); box.setCheckBox(rem)
        def done():
            yes = box.clickedButton() is ok
            if rem.isChecked(): d = self.saved_perms(); d[key] = "allow" if yes else "block"; self.save_perms(d)
            call(allow if yes else block); box.deleteLater()
        box.finished.connect(done); box.open()

    def permissions_dialog(self):
        d = self.saved_perms(); dlg = QDialog(self); dlg.setWindowTitle("Site Permissions"); dlg.resize(520, 340); lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Choices you saved with \"Remember my choice\". Remove one to be asked again."))
        lst = QListWidget(); lay.addWidget(lst)
        def fill():
            lst.clear()
            for k, v in sorted(d.items()):
                o, kind = k.rsplit("|", 1); it = QListWidgetItem(f"{QUrl(o).host() or o}  -  {PERM_TEXT.get(kind, kind)}  -  {'Allowed' if v == 'allow' else 'Blocked'}"); it.setData(Qt.UserRole, k); lst.addItem(it)
        def remove():
            for it in lst.selectedItems(): d.pop(it.data(Qt.UserRole), None)
            self.save_perms(d); fill()
        def clear(): d.clear(); self.save_perms(d); fill()
        row = QHBoxLayout(); b1, b2, b3 = QPushButton("Remove selected"), QPushButton("Remove all"), QPushButton("Close")
        for b, f in ((b1, remove), (b2, clear), (b3, dlg.accept)): b.setObjectName("tool"); b.clicked.connect(f)
        row.addWidget(b1); row.addWidget(b2); row.addStretch(1); row.addWidget(b3); lay.addLayout(row); fill(); dlg.exec()

    def web_profile(self):
        if getattr(self, "_wp", None) is None:
            self.apply_dns()                                              # before the first browser exists
            self._wp = QWebEngineProfile("FoxReaderBrowser", self)        # a normal (persistent) profile: cookies and logins are kept
            try: self._wp.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)      # FoxReader asks (and remembers) itself
            except AttributeError: pass
            self._wp.downloadRequested.connect(self.on_download)
            self.default_ua = self._wp.httpUserAgent(); ua = self.settings().value("useragent", "", type=str)
            if ua.strip(): self._wp.setHttpUserAgent(ua.strip())          # the user agent chosen in Tools > Browser User Agent
        return self._wp

    def set_user_agent(self, ua):
        """Use this user agent for every browser tab ("" = the built-in Chromium one). Open pages are reloaded."""
        if not HAVE_WEB: return
        wp = self.web_profile(); ua = ua.strip(); wp.setHttpUserAgent(ua or self.default_ua); self.settings().setValue("useragent", ua)
        for k, w in self.tab_w.items():
            if k.startswith("web"): w.view.reload()
        self.statusBar().showMessage("User agent: " + (ua or "default (Chromium)"), 6000)

    # ---- Settings ----
    DEFAULTS = {"anim_ms": 220, "hide_s": 3, "autosave_s": 8, "session_s": 25}

    def set_theme(self, dark):
        theme = "dark" if dark else "light"
        self.settings().setValue("theme", theme)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(DARK_STYLE if dark else STYLE)
        c = "#dce6ed" if dark else INK
        if hasattr(self, "b_play"):
            for name, button in (("play", self.b_play), ("stop", self.b_stop), ("prev", self.b_prev),
                                 ("next", self.b_next), ("home", self.b_home), ("fs", self.b_fs),
                                 ("eq", self.b_eq), ("list", self.b_pl)):
                button.setIcon(icon(name, c, 20))
            self.vl.setPixmap(icon("vol", c, 20).pixmap(20, 20))
        if hasattr(self, "theme_act"):
            self.theme_act.blockSignals(True); self.theme_act.setChecked(dark); self.theme_act.blockSignals(False)
        for key, widget in getattr(self, "tab_w", {}).items():
            if key.startswith("web") and hasattr(widget, "back_b"):
                widget.back_b.setIcon(icon("back", c, 18))
                widget.fwd_b.setIcon(icon("fwd", c, 18))
                widget.reload_b.setIcon(icon("close" if widget.loading else "reload", c, 18))
                widget.home_b.setIcon(icon("home", c, 18))

    def load_prefs(self):
        """Read the saved preferences into the module settings (called at start-up and after the dialog)."""
        global ANIM_MS, HIDE_CONTROLS_SECONDS, AUTOSAVE_SECONDS, SESSION_SECONDS
        st = self.settings(); d = self.DEFAULTS
        ANIM_MS = st.value("anim_ms", d["anim_ms"], type=int); HIDE_CONTROLS_SECONDS = st.value("hide_s", d["hide_s"], type=int)
        AUTOSAVE_SECONDS = st.value("autosave_s", d["autosave_s"], type=int); SESSION_SECONDS = st.value("session_s", d["session_s"], type=int)
        if hasattr(self, "t_draft"): self.t_draft.start(AUTOSAVE_SECONDS * 1000); self.t_sess.start(SESSION_SECONDS * 1000)
        self.imgv.fade.setDuration(ANIM_MS + 130)
        if hasattr(self, "anim_act"): self.anim_act.blockSignals(True); self.anim_act.setChecked(bool(ANIM_MS)); self.anim_act.blockSignals(False)

    def toggle_animations(self, on):
        self.settings().setValue("anim_ms", self.DEFAULTS["anim_ms"] if on else 0); self.load_prefs()

    def preferences_dialog(self):
        from PySide6.QtWidgets import QFormLayout, QSpinBox, QGroupBox
        st = self.settings(); d = self.DEFAULTS
        dlg = QDialog(self); dlg.setWindowTitle("Preferences"); dlg.setMinimumWidth(420); lay = QVBoxLayout(dlg); lay.setSpacing(12)
        def spin(key, lo, hi, suffix, special=""):
            sb = QSpinBox(); sb.setRange(lo, hi); sb.setSuffix(suffix); sb.setValue(st.value(key, d[key], type=int))
            if special: sb.setSpecialValueText(special)
            return sb
        boxes = {}
        for title, rows in (("Appearance", (("anim_ms", "Animation speed", 0, 1000, " ms", "Off"),)),
                            ("Video", (("hide_s", "Hide controls after", 1, 60, " s", ""),)),
                            ("Auto-save", (("autosave_s", "Save open text every", 2, 300, " s", ""), ("session_s", "Save open web pages every", 5, 600, " s", "")))):
            g = QGroupBox(title); f = QFormLayout(g)
            for key, label, lo, hi, suf, sp in rows: boxes[key] = spin(key, lo, hi, suf, sp); f.addRow(label, boxes[key])
            lay.addWidget(g)
        row = QHBoxLayout(); reset = QPushButton("Reset to defaults"); reset.setAutoDefault(False)
        reset.clicked.connect(lambda: [b.setValue(d[k]) for k, b in boxes.items()])
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        row.addWidget(reset); row.addStretch(1); row.addWidget(bb); lay.addLayout(row)
        if dlg.exec():
            for k, b in boxes.items(): st.setValue(k, b.value())
            self.load_prefs()

    def user_agent_dialog(self):
        if not HAVE_WEB:
            QMessageBox.information(self, "Browser", "The built-in browser needs PySide6 with QtWebEngine."); return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        cur = self.web_profile().httpUserAgent() if self.settings().value("useragent", "", type=str).strip() else ""
        dlg = QDialog(self); dlg.setWindowTitle("Browser User Agent"); dlg.resize(620, 0); lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("The user agent is how the browser tabs introduce themselves to websites.\nChoose a preset or type your own. Open browser tabs reload when you press OK."))
        box = QComboBox(); edit = QLineEdit(); edit.setPlaceholderText("Custom user agent (empty = default Chromium)")
        for name, ua in USER_AGENTS: box.addItem(name, ua)
        box.addItem("Custom", None); lay.addWidget(box); lay.addWidget(edit)
        def pick(i):
            ua = box.itemData(i)
            if ua is not None: edit.setText(ua)
            edit.setReadOnly(ua is not None and box.itemText(i) != "Custom")
        box.currentIndexChanged.connect(pick); edit.setText(cur)
        j = next((n for n in range(box.count()) if box.itemData(n) == cur), box.count() - 1); box.setCurrentIndex(j)
        if box.itemData(j) is None: edit.setReadOnly(False); edit.setText(cur)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); lay.addWidget(bb)
        if dlg.exec(): self.set_user_agent(edit.text())

    def open_web(self, url=""):
        """Open a browser tab (Chromium). Returns True if it opened."""
        if not HAVE_WEB:
            QMessageBox.information(self, "Browser", "The built-in browser needs PySide6 with QtWebEngine.\nInstall it with:  pip install PySide6  (on PySide6 6.12 or newer also:  pip install PySide6-WebEngine)"); return False
        self.web_n = getattr(self, "web_n", 0) + 1; key = f"web{self.web_n}"
        tab = WebTab(self.web_profile(), url if isinstance(url, str) else ""); self.tab_w[key] = tab; self.pages.addWidget(tab)
        tab.title_changed.connect(lambda t, k=key: self.web_title(k, t)); tab.icon_changed.connect(lambda ic, k=key: self.web_icon(k, ic))
        tab.dns_req.connect(self.dns_menu); tab.perm_req.connect(self.web_permission); tab.set_dns_label(self.dns_label())
        tab.open_url.connect(self.open_web); tab.fullscreen_req.connect(lambda on, t=tab: self.web_fullscreen(t, on))
        self.show_tab(key); return True

    def web_title(self, key, t):
        i = self.tab_of(key)
        if i >= 0: self.tabs.setTabText(i, (t[:22] + "...") if len(t) > 24 else (t or "Browser")); self.tabs.setTabToolTip(i, t)
        if self.cur_tab() == key: self.refresh_title()

    def web_icon(self, key, ic):
        i = self.tab_of(key)
        if i >= 0 and not ic.isNull(): self.tabs.setTabIcon(i, ic)

    def web_fullscreen(self, tab, on):
        """HTML5 fullscreen (e.g. a YouTube video): hide every bar, and bring them back when the page leaves fullscreen."""
        o = self.other_pane(next((k for k, v in self.tab_w.items() if v is tab), "watch")) if on else getattr(self, "_fs_other", None)
        if o is not None: o.setVisible(not on)
        self._fs_other = o if on else None
        if on: tab.bar.hide(); self.menuBar().hide(); self.tabwrap.hide(); self.statusBar().hide(); self.showFullScreen()
        else: self.showNormal(); self.menuBar().show(); self.tabwrap.show(); self.statusBar().show(); tab.bar.show()

    def on_download(self, d):
        folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home())
        d.setDownloadDirectory(folder); d.accept(); name = d.downloadFileName()
        d.isFinishedChanged.connect(lambda: self.statusBar().showMessage(f"Downloaded {name}  ->  {folder}", 10000))
        self.statusBar().showMessage(f"Downloading {name}...", 4000)

    def close_web(self, key):
        w = self.tab_w.pop(key, None)
        if w is not None: self.pages.removeWidget(w); w.setParent(None); w.deleteLater()

    def reset_code(self):
        self.tv.stop_run(); self.tv.path = None; self.tv.edit.clear(); self.tv.edit.document().setModified(False); self.tv.name.setText("")
        self.code_pages.setCurrentWidget(self.code_home)

    def close_tab(self, i):
        if self.tabs.count() <= 1 or i < 0: return
        key = self.key_at(i); entry = None
        if key == self.split_key: self.unsplit()     # a tab being closed goes back to the normal pane first
        if key == "code":
            entry = self.snapshot_code()
            if self.tv.dirty and not self.autosave_draft(force=True) and not self.maybe_save(): return     # the copy in cache-file failed: ask instead
            self.reset_code()
        elif key == "watch": self.stop(); self.go_home()
        elif key == "new": self.discard_launcher()
        elif key.startswith("web"):
            u = self.tab_w[key].view.url().toString()
            if u not in ("", "about:blank"): entry = {"kind": "web", "url": u, "title": self.tab_w[key].title}
            self.close_web(key)
        was_cur = i == self.tabs.currentIndex(); self.remove_tab(i)
        if was_cur: self.select(max(0, i - 1))
        self.fix_split()
        if entry: self.closed_toast(entry)

    def on_tab(self, i):
        key = self.key_at(i)
        if not key: return
        prev, self.cur_key = self.cur_key, key; self.prev_key = prev
        if key != self.split_key: self.pages.setCurrentWidget(self.tab_w[key]); self.left_key = key     # the right pane keeps its own tab
        if key == "watch":      # the playlist / equalizer belong to the video tab: hidden on the other tabs, restored here
            if prev != "watch": self.pld.setVisible(self.saved_docks[0]); self.eqd.setVisible(self.saved_docks[1])
            self.setFocus()
        else:
            if prev == "watch": self.saved_docks = (self.pld.isVisible(), self.eqd.isVisible())
            self.pld.hide(); self.eqd.hide()
            if key == "code": (self.tv.edit if self.code_pages.currentWidget() is self.tv else self.code_home).setFocus()
            elif key.startswith("web"): w = self.tab_w[key]; w.focus_page() if w.view.url().toString() not in ("", "about:blank") else w.focus_address(); self.statusBar().clearMessage()
        for a in getattr(self, "plain_keys", []): a.setEnabled(not key.startswith("web"))
        self.refresh_title()

    def run_code(self):
        if self.tab_of("code") < 0: return
        self.show_tab("code"); self.tv.toggle_run()

    def open_code(self, path):
        if path == self.tv.path and self.code_pages.currentWidget() is self.tv: self.show_tab("code"); return
        if not self.maybe_save(): return
        err = self.tv.load(path)
        if err: self.statusBar().showMessage(f"Can't open: {err}", 5000); return
        self.remember(path); self.code_pages.setCurrentWidget(self.tv); self.show_tab("code"); self.update_title(); self.tv.edit.setFocus()
        self.statusBar().showMessage(f"Editing {Path(path).name}  -  Ctrl+S to save, F5 to run" + ("  -  use the button to show the formatted / rendered view" if self.tv.kind else ""))

    def open_code_dialog(self):
        flt = "Code and text (" + " ".join("*" + e for e in sorted(TEXT_EXT)) + ");;All files (*)"
        f, _ = QFileDialog.getOpenFileName(self, "Open code file", self.start_dir(), flt)
        if f: self.open_code(f)

    def new_code(self):
        if not self.maybe_save(): return
        flt = "Python (*.py);;JavaScript (*.js);;Java (*.java);;HTML (*.html);;CSS (*.css);;Markdown (*.md);;Text (*.txt)"
        path, sel = QFileDialog.getSaveFileName(self, "New code file", str(Path(self.start_dir()) / "untitled.py"), flt)
        if not path: return
        if not Path(path).suffix:
            m = re.search(r"\*(\.\w+)", sel or ""); path += m.group(1) if m else ".py"
        if not Path(path).exists():
            try: Path(path).write_text(TEMPLATES.get(Path(path).suffix.lower(), ""), encoding="utf-8")
            except OSError as e: QMessageBox.warning(self, "Can't create file", str(e)); return
        self.open_code(path)

    def maybe_save(self):
        """Ask what to do with unsaved text edits. Returns False if the user cancels."""
        if not self.tv.dirty: return True
        r = QMessageBox.question(self, "Unsaved changes", f"Save changes to {Path(self.tv.path).name}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save: return self.tv.save()
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if not self._quit_ok:
            ok = self.autosave_draft(force=True); self.save_session()                    # save everything first
            if self.tv.dirty and not ok and not self.maybe_save(): e.ignore(); return    # could not copy to cache-file: ask the old way
            if (self.tv.dirty and ok) or self.has_web_pages():
                e.ignore()
                if self.quit_pending: QTimer.singleShot(0, self.finish_quit)             # clicked close again: close now
                else: self.confirm_quit()
                return
        self.save_session(clean=True); self.t_draft.stop(); self.t_sess.stop(); self.toast.hide_toast()
        self.tv.stop_run()
        for k in [k for k in self.tab_w if k.startswith("web")]: self.close_web(k)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)      # let the browser pages go before their profile
        e.accept()

    def show_image(self, path):
        pm = QPixmap(path)
        if pm.isNull() and FFMPEG:   # HEIC, AVIF, JPEG 2000, RAW previews... let ffmpeg convert it
            out = CACHE / (hashlib.sha1(f"{path}{os.path.getmtime(path)}".encode()).hexdigest() + ".png")
            if not out.exists():
                try: subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", path, "-frames:v", "1", str(out)], check=True, timeout=60)
                except Exception: pass
            if out.exists(): pm = QPixmap(str(out))
        if pm.isNull(): self.statusBar().showMessage(f"Can't open picture: {Path(path).name}", 5000); return
        self.mp.stop(); self.imgv.set_pixmap(pm); self.stack.setCurrentIndex(2)
        self.seek.setValue(0); self.seek.setEnabled(False); self.slide_t = time.monotonic(); self.set_play(self.slideshow)
        self.statusBar().showMessage(f"{Path(path).name}  -  {pm.width()}x{pm.height()}  ({self.idx + 1}/{len(self.files)})")
        self.setFocus()

    def toggle_slideshow(self):
        self.slideshow = not self.slideshow; self.slide_t = time.monotonic()
        if self.is_image(): self.set_play(self.slideshow)
        self.statusBar().showMessage(f"Slideshow {'on' if self.slideshow else 'off'} ({SLIDE_SECONDS}s per picture)", 3000)

    def play_index(self, i, at=0, play=True, show=True):
        if not 0 <= i < len(self.files): return
        self.show_tab("watch") if show else self.ensure_tab("watch")
        self.idx = i; self.plist.setCurrentRow(i); src = self.files[i]; self.remember(src)
        br, h = BITRATES[self.eqd.br.value()], (RESOLUTIONS[self.eqd.rs.value()] if self.is_video() else 0)
        self.refresh_title()
        if self.is_image():
            self.pcm, self.pcm_path = None, ""; self.show_image(src); return
        self.seek.setEnabled(True)
        eqf = self.eq_filter(); self.eq_used = self.eq
        self.enc_gen += 1; self.cancel_encode()
        if FFMPEG and (br or h or eqf):
            out = self.enc_path(src, br, h, eqf)
            if out.exists(): self.start(str(out), at, play)               # cached: instant
            else:
                self.start(src, at, play)                                 # play the original now, swap when encoding is done
                self.statusBar().showMessage("Encoding in background… (playing original meanwhile)")
                threading.Thread(target=self.transcode, args=(src, br, h, at, play, eqf, self.enc_gen), daemon=True).start()
        else: self.start(src, at, play)
        if self.pcm_path != self.files[i] and FFMPEG:
            self.pcm = None; self.pcm_path = self.files[i]
            threading.Thread(target=self.analyze, args=(self.files[i],), daemon=True).start()

    def bind_video(self): self.mp.set_video(self.video)

    def start(self, path, at, play):
        self.mp.set_media(path, at); vid = self.is_video()       # resumes at `at` once the file is loaded
        self.stack.setCurrentIndex(1 if vid else 0)
        self.mp.play()
        QTimer.singleShot(300, self.setFocus)
        self.resume_token = getattr(self, "resume_token", 0) + 1
        if at: QTimer.singleShot(500, lambda t=self.resume_token: self.verify_resume(int(at), t, 0))
        if not play: QTimer.singleShot(900, lambda: self.mp.set_pause(1))
        self.set_play(True); self.statusBar().showMessage("Playing")

    def verify_resume(self, want, token, tries):
        """Fallback: if the first seek was ignored, keep trying to seek until it lands at the old position."""
        if token != self.resume_token or tries > 12: return
        t = self.mp.get_time()
        if t >= 0 and abs(t - want) < 3000: return
        if self.mp.is_seekable() and self.mp.get_length() > 0: self.mp.set_time(want)
        QTimer.singleShot(300, lambda: self.verify_resume(want, token, tries + 1))

    def enc_path(self, src, br, h, eqf):
        video = Path(src).suffix.lower() in VIDEO_EXT; ext = ".mp4" if video else ".mp3"
        key = hashlib.sha1(f"{src}{os.path.getmtime(src)}{br}{h if video else 0}{eqf}".encode()).hexdigest()
        return CACHE / f"{key}{ext}"

    def cancel_encode(self):
        """Stop an encode that is no longer wanted (slider moved again / another file picked)."""
        p = self.enc_proc
        if p is not None and p.poll() is None:
            try: p.kill()
            except Exception: pass

    def transcode(self, src, br, h, at, play, eqf="", gen=0):
        video = Path(src).suffix.lower() in VIDEO_EXT
        out = self.enc_path(src, br, h, eqf); ext = out.suffix
        tmp = CACHE / f"{out.stem}.tmp{ext}"
        try:
            with self.lock:
                if gen != self.enc_gen: return                        # a newer request replaced this one while it waited
                if not out.exists():
                    if video:
                        cmd = [FFMPEG, "-y", "-loglevel", "error", "-threads", "0", "-i", src]
                        if h: cmd += ["-vf", f"scale=trunc(oh*a/2)*2:'min({h},ih)'"]   # works on old + new ffmpeg (no "-2")
                        cmd += (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p", "-threads", "0"] if h or br else ["-c:v", "copy"])
                        if eqf: cmd += ["-af", eqf]
                        cmd += ["-c:a", "aac", "-strict", "-2", "-b:a", f"{br or 128}k", "-movflags", "+faststart", str(tmp)]
                    else:
                        cmd = [FFMPEG, "-y", "-loglevel", "error", "-threads", "0", "-i", src, "-vn"] + (["-af", eqf] if eqf else []) + ["-codec:a", "libmp3lame", "-b:a", f"{br or 320}k", str(tmp)]
                    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}   # no console window on Windows
                    self.enc_proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)
                    err = self.enc_proc.communicate()[1]
                    if gen != self.enc_gen:                           # cancelled: drop the half-written file, stay silent
                        tmp.unlink(missing_ok=True); return
                    if self.enc_proc.returncode: raise RuntimeError((err or b"").decode("utf-8", "replace").strip()[-200:] or "ffmpeg failed")
                    tmp.replace(out)
            if gen == self.enc_gen: self.bus.transcoded.emit(str(out), int(at), play, gen)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            if gen == self.enc_gen: self.bus.failed.emit(f"Encoding failed: {e}")

    def on_transcoded(self, path, at, play, gen=0):
        if gen != self.enc_gen: return                                # stale result
        # swap from the original to the encoded file at the position the listener has reached now
        if self.mp.is_playing() or at: at = max(0, self.mp.get_time())
        self.start(path, at, self.mp.is_playing())
        self.statusBar().showMessage("Encoding done", 3000)

    def analyze(self, path):
        try:
            raw = subprocess.run([FFMPEG, "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                                 capture_output=True, check=True).stdout
            self.bus.analyzed.emit(np.frombuffer(raw, np.int16).astype(np.float32) / 32768, path)
        except Exception: pass
    def on_analyzed(self, pcm, path):
        if path == self.pcm_path: self.pcm = pcm

    def reload_quality(self):
        if self.idx >= 0: self.play_index(self.idx, max(0, self.mp.get_time()), self.mp.is_playing())

    def set_play(self, on):
        dark = self.settings().value("theme", "light", type=str) == "dark"
        self.b_play.setIcon(icon("pause" if on else "play", "#dce6ed" if dark else INK))

    def toggle(self):
        if self.idx < 0:
            if self.files: self.play_index(0)
            return
        if self.is_image(): self.toggle_slideshow(); return
        self.mp.pause(); QTimer.singleShot(60, lambda: self.set_play(self.mp.is_playing()))
    def stop(self): self.mp.stop(); self.slideshow = False; self.set_play(False); self.seek.setValue(0); self.cur.setText("0:00")
    def next(self): self.files and self.play_index((self.idx + 1) % len(self.files), show=False)
    def prev(self):
        if self.files: self.play_index((self.idx - 1) % len(self.files), show=False) if self.is_image() or self.mp.get_time() < 3000 else self.mp.set_time(0)
    def jump(self, ms):
        if self.is_image(): self.next() if ms > 0 else self.prev(); return
        self.mp.set_time(max(0, self.mp.get_time() + ms))
    def do_seek(self): self.mp.set_position(self.seek.value() / 1000); self.seeking = False
    def fullscreen(self):
        if self.isFullScreen(): self.exit_fullscreen()
        elif self.cur_tab() == "watch": self._vo = self.other_pane("watch"); self._vo and self._vo.hide(); self.showFullScreen(); self.menuBar().hide(); self.pld.hide(); self.eqd.hide(); self.tabwrap.hide()
        self.activateWindow(); self.setFocus()
    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal(); self.menuBar().show(); self.ctrl.show(); self.tabwrap.show()
            if getattr(self, "_vo", None) is not None: self._vo.show(); self._vo = None
        self.activateWindow(); self.setFocus()
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape: self.exit_fullscreen(); return
        if e.key() in (Qt.Key_F, Qt.Key_F11): self.fullscreen(); return
        super().keyPressEvent(e)
    def mouseDoubleClickEvent(self, e): self.fullscreen()

    # ---------- sound ----------
    EQ_HZ = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]
    def eq_filter(self, g=None):
        """ffmpeg equalizer chain for the slider gains ('' when flat). Qt has no live equalizer, so ffmpeg applies it."""
        g = self.eq if g is None else g
        return ",".join(f"equalizer=f={hz}:t=o:w=1:g={g[k]}" for hz, k in zip(self.EQ_HZ, BAND_MAP) if g[k])

    def apply_eq(self, g):
        self.eq = tuple(float(x) for x in g)
        if not hasattr(self, "eq_t"):
            self.eq_t = QTimer(self); self.eq_t.setSingleShot(True); self.eq_t.timeout.connect(self.eq_apply_now)
        self.eq_t.start(700)       # wait until the slider stops moving

    def eq_apply_now(self):
        if self.eq == self.eq_used or self.idx < 0 or self.is_image(): return
        if not FFMPEG: self.statusBar().showMessage("Install ffmpeg to use the equalizer", 4000); return
        self.reload_quality()

    def auto_optimize(self):
        if self.pcm is None or len(self.pcm) < 4096:
            self.statusBar().showMessage("Play a song first (needs ffmpeg for analysis)", 4000); return
        n = len(self.pcm) // 2048; step = max(1, n // 400); acc = np.zeros(1025)
        for k in range(0, n, step):
            acc += np.abs(np.fft.rfft(self.pcm[k * 2048:(k + 1) * 2048] * np.hanning(2048)))
        hz = SR / 2048; lv = []
        for lo, hi in RANGES:
            a = int(lo / hz); b = max(a + 1, min(int(hi / hz), len(acc)))
            lv.append(20 * np.log10(np.mean(acc[a:b]) + 1e-9))
        avg = sum(lv) / 4
        g = [max(-6, min(6, round((avg - v) * 0.5 * 2) / 2)) for v in lv]
        self.eqd.preset.blockSignals(True); self.eqd.set_gains(g); self.eqd.preset.blockSignals(False)
        self.statusBar().showMessage("Optimized for this song", 4000)

    # ---------- ui tick ----------
    def autohide_controls(self):
        """While a video is playing, hide the bottom control bar after HIDE_CONTROLS_SECONDS without mouse movement.
        Moving the mouse, or resting it near the bottom edge (where the bar is), brings it back. The cursor is polled
        globally because the video widget swallows mouse events."""
        now, pos = time.monotonic(), QCursor.pos()
        moved, self.last_pos = pos != self.last_pos, pos
        if not (self.cur_tab() == "watch" and self.is_video() and self.mp.is_playing()) or self.isActiveWindow() is False:
            self.idle_t = now; self.ctrl.isHidden() and self.ctrl.show(); return
        local = self.pages.mapFromGlobal(pos); inside = self.pages.rect().contains(local)
        near_bar = inside and local.y() >= self.pages.height() - 110
        if (moved and inside) or near_bar or self.seeking: self.idle_t = now
        want = now - self.idle_t < HIDE_CONTROLS_SECONDS
        if self.ctrl.isHidden() == want: self.ctrl.setVisible(want)

    def tick(self):
        self.autohide_controls()
        if self.is_image():
            self.cur.setText(""); self.dur.setText("")
            if self.is_image() and self.slideshow and len(self.files) > 1 and time.monotonic() - self.slide_t >= SLIDE_SECONDS: self.next()
            return
        t, ln = self.mp.get_time(), self.mp.get_length()
        if ln > 0 and not self.seeking: self.seek.setValue(int(t / ln * 1000))
        self.cur.setText(fmt(t)); self.dur.setText(fmt(ln))
        if self.mp.is_playing() and not self.is_video(): self.viz.update_data(self.pcm, t, self.eqd.gains())
        elif not self.is_video(): self.viz.update_data(None, 0, [0] * 4)
        if self.mp.take_ended(): self.next()


if __name__ == "__main__":
    if HAVE_WEB: QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    startup_theme = QSettings("FoxReader", "FoxReader").value("theme", "light", type=str)
    app.setStyleSheet(DARK_STYLE if startup_theme == "dark" else STYLE)
    app.setWindowIcon(QIcon(str(LOGO)))
    w = Player(); w.show(); sys.exit(app.exec())
