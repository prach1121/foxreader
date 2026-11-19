
![platform](https://img.shields.io/badge/platform-Windows-0078D6)
![language](https://img.shields.io/badge/language-Python-3776AB)
![framework](https://img.shields.io/badge/framework-PySide6-41CD52)
![browser](https://img.shields.io/badge/browser-Chromium-4285F4)
![engine](https://img.shields.io/badge/browser_engine-QtWebEngine-41CD52)
![player](https://img.shields.io/badge/media-FFmpeg-007808)
![status](https://img.shields.io/badge/status-Active-brightgreen)
![version](https://img.shields.io/badge/version-1.0-blueviolet)

## What it is
All-in-one media app: videos, music and pictures in one window and one playlist (pictures: zoom, pan, rotate, slideshow).

## For GitHub users
FoxReader keeps media, downloads, web sessions, drafts and cache data outside the source directory at runtime.
Do not commit `build/`, `dist/`, `.cache/`, `cache-file/`, `songs/`, or `__pycache__/`; the included
`.gitignore` excludes them. Rebuild locally with `build_exe.bat` on Windows.

## About
Owner: **Prach**. Help > About FoxReader shows features and info; Help > Keyboard Shortcuts (F1) lists all hotkeys.

## Tabs
FoxReader starts with one tab, **Watch Video** (videos, music, pictures, playlist, equalizer). Click **+** (Ctrl+T) to open a **New Tab**, which asks what you want to open; picking a code or text file opens a **Writing Code** tab (editor + sandbox), and picking a video, song or picture goes to Watch Video. There is one tab of each kind, and the Writing Code tab only exists while you are using it. Close a tab with its x (Ctrl+W); the last tab can't be closed. Switch with Ctrl+1 / Ctrl+2. A video or song keeps playing while you code. Ctrl+N makes a new code file.

## Split view
Click **Split** (next to the **+**), or press **Ctrl+\\**, to see two tabs side by side: the current tab moves to the right pane and another tab (your previous one, or a New Tab chooser if you only have one tab) shows on the left. Click any other tab to show it on the left; click the right tab to focus it. Drag the divider to resize. Click **Unsplit** (or Ctrl+\\ again) to go back to one view. Closing the right tab also leaves split view. Works with Watch Video, Writing Code and Web tabs, so you can watch a video while coding or browsing.

## Web browser
A built-in Chromium browser (QtWebEngine), so you don't need another program. Click **+** (Ctrl+T) and pick **Web**, or use File > Open Web Browser Tab (Ctrl+B). You can open as many browser tabs as you like. Type a web address or a search (searches use Google); links that open in a new window become new tabs; downloads go to your Downloads folder; cookies and logins are kept between runs. Alt+Left / Alt+Right = back / forward, Ctrl+R = reload, F6 = address bar. HTML5 fullscreen (e.g. YouTube) works. Needs QtWebEngine: with PySide6 6.12 or newer install it with `pip install PySide6-WebEngine`.

## User agent
Tools > **Browser User Agent...** sets what the browser tabs tell websites they are (Chrome, Firefox, Safari, Edge, Android / iPhone / iPad presets, or any custom string). The choice is remembered, applies to all browser tabs (also to `navigator.userAgent` in pages) and open tabs reload when you press OK. Pick *Default (Chromium)* to go back.

## DNS
Every browser tab has a **DNS** button in its toolbar (or Tools > **Browser DNS...**): pick **Default**, **OpenDNS**, **Cloudflare**, **Google Public DNS** or **Custom** (type one or more DNS server IPs, e.g. `9.9.9.9, 149.112.112.112`). The choice is remembered and the open pages reload. How it works: the first time a browser tab opens, FoxReader starts a small local SOCKS5 helper (127.0.0.1, port chosen automatically, only this computer can reach it) and the browser sends its connections through it. The helper looks each name up on the DNS server you picked (plain DNS on port 53, TCP when the answer is big), or with the computer's normal DNS when *Default* is picked, and you can change it at any time without restarting. Only the built-in browser is affected, not the player or the rest of the computer. A network that blocks port 53 to outside servers will fail with a custom DNS: pick Default again. If the computer is set to use a proxy, FoxReader leaves the browser's network alone and the DNS can't be changed.

## Permission popups
When a page asks for your **location (GPS)**, **camera**, **microphone**, **screen recording**, **notifications**, clipboard and similar, a popup asks Allow / Block. Tick *Remember my choice for this site* to stop being asked; Tools > **Site Permissions...** lists the saved choices and lets you remove them. The computer's own privacy settings still apply (for example camera access on Windows / macOS), and location needs a location service on the computer.

## Auto-save and accidental close
When you change a text or code file (type or delete text), FoxReader copies it to the **cache-file** folder (next to foxreader.py) every 8 seconds. The original file is never touched until you press Save; saving also removes the copy. The addresses of your open web pages (and the open code file) are saved every 25 seconds to `cache-file/session.json`.

- **Close a tab** (Writing Code or a web page): the tab closes and a popup in the bottom-right says *We saved your file! Click if this is an accidental close.* with a **Reopen** button (also File > Reopen Closed Tab, Ctrl+Shift+T). Reopening puts your text back, even the changes you had not saved.
- **Close the window**: your work is saved first, then the same popup appears for 6 seconds. Click **Accidental close - stay open** to keep working, or **Close now** (or just wait).
- **Next start**: if there is saved text or web pages from last time, a popup offers **Restore** (or Dismiss to delete the saved copies). Unsaved text is no longer asked about with a Save / Discard question when you close: it stays in cache-file until you restore or dismiss it.
- Change `AUTOSAVE_SECONDS` / `SESSION_SECONDS` in foxreader.py to adjust the timing.

## Auto-hide controls
While a video plays, the bottom control bar hides after 3 seconds without mouse movement. Move the mouse (or point at the bottom edge) to bring it back. It always stays visible when paused. Change `HIDE_CONTROLS_SECONDS` in foxreader.py to adjust the delay.

## Sandbox
Open a .py / .js / .java / .html file and press Run (F5). Needs `node` for JavaScript and a JDK (11+) for Java; HTML needs PySide6 with QtWebEngine (included in the normal PySide6 install).

## Animations
Popups slide up and fade in/out, pictures fade in when you change them, picture zoom (wheel / +/-) glides smoothly, and the New Tab chooser fades in. Turn them on or off in the **Settings** menu, or set the speed in Settings > **Preferences...** (Ctrl+,).

## Settings
Settings > **Preferences...** (Ctrl+,) has animation speed, how long the video controls wait before hiding, and how often text and web pages are auto-saved. Everything is remembered; *Reset to defaults* puts it all back. The constants at the top of foxreader.py are only the defaults.

## Build a .exe (Windows)
Double-click **build_exe.bat**. It installs the requirements and PyInstaller and makes `dist\FoxReader\FoxReader.exe`. Your songs / cache-file folders are created next to the .exe.

## Playback
FoxReader plays with Qt's built-in **FFmpeg** engine (no VLC needed). It also uses the `ffmpeg` program for the equalizer, bitrate / resolution and graphs: it is found next to FoxReader (`ffmpeg.exe`), inside the app if you put `ffmpeg.exe` beside `build_exe.bat` before building, or on the PATH. Moving an equalizer slider re-encodes the file with the new sound in the background: the original keeps playing, then switches to the encoded version at the same spot when it is ready (cached for next time). Moving the slider again cancels the unfinished encode instead of queueing it.
