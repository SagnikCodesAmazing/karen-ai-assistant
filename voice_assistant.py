import sys
import os
import threading
import time
import json
import subprocess
import webbrowser
import math
import re
from difflib import SequenceMatcher
import shutil
import queue
from datetime import datetime
import pystray # pyright: ignore[reportMissingImports]
from pystray import MenuItem as item # pyright: ignore[reportMissingImports]
import PIL.Image
import PIL.ImageDraw
import numpy as np
import sounddevice as sd
import pyttsx3 # pyright: ignore[reportMissingImports]
import ollama # pyright: ignore[reportMissingImports]
import pyaudio # pyright: ignore[reportMissingModuleSource]
import struct
import wave
import whisper
import torch
import platform
import winreg
import pythoncom
import ctypes
import win32com.client

from karen_hud import KarenHUD

try:
    from playwright.sync_api import sync_playwright  # pip install playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Configuration - Adjust these as needed
USE_PORCUPINE = False

# Wake word & phrases configuration
WAKEWORD = "karen"

# Multi-word wake triggers & custom responses
WAKE_PHRASES = {
    # "Daddy is home" special phrases
    "wake up karen daddy is home": "Welcome home, sir. All systems are online. How may I assist you?",
    "wake up karen daddys home": "Welcome home, sir. All systems are online. How may I assist you?",
    "wake up daddy is home": "Welcome home, sir. All systems are online. How may I assist you?",
    "wake up daddys home": "Welcome home, sir. All systems are online. How may I assist you?",
    "daddy is home": "Welcome home, sir. All systems are online. How may I assist you?",
    "daddys home": "Welcome home, sir. All systems are online. How may I assist you?",
    "daddy home": "Welcome home, sir. All systems are online. How may I assist you?",

    # Standard wake triggers (always respond "Yes?")
    "wake up karen": "Yes?",
    "wake up": "Yes?",
    "hey karen": "Yes?",
}

# Common Whisper interpretations / pronunciations of "Karen"
WAKEWORD_VARIANTS = {
    "karen", "karin", "karyn", "kairen", "kareen", "kahren",
    "caren", "carrin", "karren",
}

# Lower = more tolerant, but also more false positives.
WAKEWORD_SIMILARITY_THRESHOLD = 0.72

MODEL_PATH = "vosk-model-small-en-in-0.4"  # Leftover from an old Vosk-based version, not used anymore. Whisper is the STT engine now.
WHISPER_MODEL = "base.en"  # small.en: real-time-ish on CPU with a solid accuracy jump over base.en.
                             # medium.en is more accurate still but 10-20s+ per command on CPU - not practical for a live assistant.
SAMPLE_RATE = 16000
BUFFER_SIZE = 4096
MAX_RECORD_SECONDS = 8
SILENCE_THRESHOLD = 250  # Adjust based on microphone sensitivity (lower = more sensitive)
SILENCE_DURATION = 1.2   # Seconds of silence to stop recording (was 0.8 - too aggressive, cut off phrases like "close current window" after "close")
ENERGY_THRESHOLD = 150   # For wake word detection (energy-based) (lower = more sensitive)
CONVERSATION_TIMEOUT = 5.0  # Seconds of silence to end conversation and go back to wake detection
OLLAMA_MODEL = "llama3"  # Ollama model used for question answering (changed to phi)
OLLAMA_TIMEOUT = 10.0  # Seconds to wait for Ollama response

# Whisper's initial_prompt nudges its language model toward expected words.
# Listing the assistant's own command vocabulary here reduces misrecognition
# of these specific words even though it doesn't guarantee it.
TRANSCRIBE_PROMPT = (
    "Karen. Wake up Karen daddy is home. Daddy is home. Wake up Karen. "
    "Call Tuhin. Video call Mom. Make a call to Alex. Hang up. End call. "
    "Send message to Tuhin: are you free? Message Tuhin hello. Text Mom I am coming home. "
    "Open chat with Tuhin. Next chat. Previous chat. Mute chat. Archive chat. Mark as unread. "
    "New chat. New group. Open WhatsApp settings. Show WhatsApp shortcuts. "
    "Open Chrome. Open Brave. Launch Spotify. Start Notepad. Open WhatsApp. "
    "Open YouTube. Play the first video. Open the first result. "
    "Scroll down. Scroll up. Go back. Go forward. Pause video. Fullscreen. Refresh. "
    "Close current window. Close this app. Shut this window. "
    "Search for. Google. Look up. Find. "
    "Create a folder called Projects. Make a directory named Notes. "
    "Enter it. Go into the folder. Navigate to directory. "
    "Create a file called notes dot text. "
    "Exit. Quit. Goodbye."
)

# Global variables
tts_engine = None
tts_queue = queue.Queue()
tts_thread = None
tts_ready = threading.Event()
tts_speaking = threading.Event()
is_listening = False
whisper_model = None
device = "cpu"
last_interaction_time = 0.0
in_conversation = False

# HUD overlay instance (initialised in main)
hud = None  # type: KarenHUD | None

# Filesystem navigation state (used by CREATE_DIR / ENTER_DIR / CREATE_FILE).
# Since each voice command is processed independently, there's no real shell
# session to "cd" in - current_dir is our stand-in for that.
current_dir = os.path.expanduser("~")
last_created_dir = None

# Browser automation state - lets voice commands act on a live browser page
# (e.g. "open brave" -> "open youtube" -> "open the first video") instead of
# just launching apps blind. Uses a dedicated profile so it doesn't collide
# with a normal, already-open browser window.
BROWSER_DEBUG_PORT = 9222
# Fallback profile used only if a browser's real profile directory can't be found.
BROWSER_AUTOMATION_PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".voice_assistant_browser_profile")
_pw_instance = None
_browser_conn = None
browser_page = None
active_browser_name = None

KNOWN_SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "amazon": "https://www.amazon.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
    "wikipedia": "https://www.wikipedia.org",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "linkedin": "https://www.linkedin.com",
    "spotify": "https://open.spotify.com",
    "twitch": "https://www.twitch.tv",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "pinterest": "https://www.pinterest.com",
    "tiktok": "https://www.tiktok.com",
    "bing": "https://www.bing.com",
    "yahoo": "https://www.yahoo.com",
    "notion": "https://www.notion.so",
    "figma": "https://www.figma.com",
    "canva": "https://www.canva.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "google docs": "https://docs.google.com",
    "sheets": "https://sheets.google.com",
    "google sheets": "https://sheets.google.com",
    "calendar": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "perplexity": "https://www.perplexity.ai",
    "coursera": "https://www.coursera.org",
    "udemy": "https://www.udemy.com",
}


def create_tray_image():
    """Create a simple icon for the system tray."""
    image = PIL.Image.new('RGB', (64, 64), color='black')
    dc = PIL.ImageDraw.Draw(image)
    dc.rectangle((16, 16, 48, 48), fill='white')
    dc.ellipse((24, 24, 40, 40), fill='blue')
    return image

def on_exit(icon, item):
    """Exit the application."""
    icon.stop()
    sys.exit(0)

def on_show_settings(icon, item):
    """Show settings (placeholder)."""
    print("Settings clicked")

def setup_tray():
    """Setup the system tray icon and menu."""
    image = create_tray_image()
    menu = (item('Settings', on_show_settings),
            item('Exit', on_exit))
    icon = pystray.Icon("voice_assistant", image, "Voice Assistant", menu)
    icon.run()

def _tts_worker():
    """
    Dedicated Windows SAPI TTS worker.

    COM must be initialized inside this thread because
    Windows SAPI is a COM-based API.
    """
    global tts_engine

    pythoncom.CoInitialize()

    try:
        print("Initializing Windows SAPI TTS...")

        tts_engine = win32com.client.Dispatch("SAPI.SpVoice")

        # Volume: 0-100
        tts_engine.Volume = 100

        # Rate: -10 to 10
        tts_engine.Rate = 1

        # Try to select a good voice
        voices = tts_engine.GetVoices()

        selected_voice = None

        for i in range(voices.Count):
            voice = voices.Item(i)
            description = voice.GetDescription().lower()

            print(f"Available voice: {description}")

            # Prefer Zira / female English voice
            if "zira" in description:
                selected_voice = voice
                break

        if selected_voice is None and voices.Count > 0:
            selected_voice = voices.Item(0)

        if selected_voice is not None:
            tts_engine.Voice = selected_voice

        print("Windows SAPI TTS ready")

        tts_ready.set()

        while True:
            text = tts_queue.get()

            if text is None:
                break

            try:
                print(f"TTS: Speaking: {text}")

                tts_speaking.set()

                # 0x0 = synchronous speech
                tts_engine.Speak(
                    str(text),
                    0
                )

                print("TTS: Finished speaking")

            except Exception as e:
                print(f"SAPI TTS ERROR: {repr(e)}")

            finally:
                tts_speaking.clear()
                tts_queue.task_done()

    except Exception as e:
        print(f"SAPI initialization ERROR: {repr(e)}")
        tts_ready.set()

    finally:
        tts_engine = None
        pythoncom.CoUninitialize()


def initialize_tts():
    """Start the dedicated Windows SAPI TTS thread."""

    global tts_thread

    print("Starting TTS worker...")

    tts_thread = threading.Thread(
        target=_tts_worker,
        daemon=True,
        name="SAPI-TTS"
    )

    tts_thread.start()

    if tts_ready.wait(timeout=10):

        if tts_engine is not None:
            print("TTS initialized successfully")
        else:
            print("TTS initialization failed")

    else:
        print("TTS initialization timed out")


def speak(text):
    """
    Queue text for Windows SAPI speech.
    """

    if not text:
        return

    text = str(text).strip()

    if not text:
        return

    print(f"TTS queue: {text}")

    if tts_engine is None:
        print("TTS engine is not available")
        return

    tts_queue.put(text)


def load_whisper_model():
    """Load Whisper model for speech recognition (device-aware, FP16 if GPU)."""
    global whisper_model, device
    print(f"Loading Whisper model ({WHISPER_MODEL})...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    whisper_model = whisper.load_model(WHISPER_MODEL, device=device)
    if device == "cuda":
        whisper_model = whisper_model.half()
        print("Whisper model set to FP16 on GPU")
    else:
        print(f"Whisper model loaded on {device}")

def close_current_window():
    """
    Close the currently focused Windows application/window.
    Uses WM_CLOSE so the application can shut down normally.
    """

    try:
        user32 = ctypes.windll.user32

        # Get the currently focused window
        hwnd = user32.GetForegroundWindow()

        if not hwnd:
            print("No foreground window found.")
            return False

        # Get window title for logging
        length = user32.GetWindowTextLengthW(hwnd)

        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)

        window_title = title_buffer.value

        print(f"Closing current window: {window_title}")

        # WM_CLOSE = 0x0010
        user32.PostMessageW(
            hwnd,
            0x0010,
            0,
            0
        )

        return True

    except Exception as e:
        print(f"Failed to close current window: {e}")
        return False


def sanitize_name(name: str) -> str:
    """
    Clean up a spoken folder/file name for filesystem use.
    Strips characters that are illegal in Windows names and no slashes,
    since nested paths aren't supported through voice commands.
    """
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip(" .")
    return name


def create_directory(name: str):
    """Create a folder inside current_dir. Returns the new path or None."""
    global last_created_dir

    clean_name = sanitize_name(name)
    if not clean_name:
        return None

    try:
        new_path = os.path.join(current_dir, clean_name)
        os.makedirs(new_path, exist_ok=True)
        last_created_dir = new_path
        print(f"Created directory: {new_path}")
        return new_path
    except Exception as e:
        print(f"Failed to create directory: {e}")
        return None


def enter_directory(raw_name: str):
    """
    Move current_dir into the given folder (relative to current_dir, or
    absolute). "it" / "that" / "there" refers to the last created folder.
    Returns the new current_dir or None if the folder doesn't exist.
    """
    global current_dir

    check = raw_name.strip().lower()

    if check in ("it", "that", "there", ""):
        if last_created_dir and os.path.isdir(last_created_dir):
            current_dir = last_created_dir
            print(f"Entered directory: {current_dir}")
            return current_dir
        print("No recently created directory to enter.")
        return None

    clean_name = sanitize_name(raw_name)
    candidate = clean_name if os.path.isabs(clean_name) else os.path.join(current_dir, clean_name)

    if os.path.isdir(candidate):
        current_dir = candidate
        print(f"Entered directory: {current_dir}")
        return current_dir

    print(f"Directory not found: {candidate}")
    return None


def create_file_in_dir(name: str):
    """Create (touch) an empty file inside current_dir. Returns the new path or None."""
    clean_name = sanitize_name(name)
    if not clean_name:
        return None

    try:
        path = os.path.join(current_dir, clean_name)
        with open(path, 'a'):
            pass
        print(f"Created file: {path}")
        return path
    except Exception as e:
        print(f"Failed to create file: {e}")
        return None


def _find_browser_executable(app_name):
    """Look up the installed path for a known browser, or None."""
    app_paths = {
        "brave": [
            os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ],
        "edge": [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "chrome": [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ],
    }
    for path in app_paths.get(app_name, []):
        if os.path.isfile(path):
            return path
    return None


def _real_profile_dir(app_name):
    """The actual everyday profile directory for a browser (logins, bookmarks, etc.)."""
    dirs = {
        "brave": os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\User Data"),
        "chrome": os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data"),
        "edge": os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data"),
    }
    return dirs.get(app_name)


def _process_name_for_browser(app_name):
    return {"brave": "brave.exe", "chrome": "chrome.exe", "edge": "msedge.exe"}.get(app_name)


def _is_process_running(proc_name):
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {proc_name}"],
            text=True, timeout=5
        )
        return proc_name.lower() in output.lower()
    except Exception:
        return False


def _close_existing_browser(app_name):
    """
    Close any running instance of this browser so a fresh launch can bind
    the remote-debugging port on the real profile. Chromium mostly ignores
    --remote-debugging-port if another window already owns the profile.
    Graceful close first, forced kill as fallback, then clean up any
    singleton lock files a forced kill can leave behind (these otherwise
    block the profile from being reused).
    """
    proc_name = _process_name_for_browser(app_name)
    if not proc_name or not _is_process_running(proc_name):
        return

    print(f"Closing existing {app_name} windows before automated relaunch...")
    try:
        subprocess.run(["taskkill", "/IM", proc_name], capture_output=True, timeout=5)
        time.sleep(1.0)
        if _is_process_running(proc_name):
            subprocess.run(["taskkill", "/F", "/IM", proc_name], capture_output=True, timeout=5)
            time.sleep(1.0)
    except Exception as e:
        print(f"Could not close existing {app_name} processes: {e}")

    profile_dir = _real_profile_dir(app_name)
    if profile_dir and os.path.isdir(profile_dir):
        for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                path = os.path.join(profile_dir, lock_file)
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def launch_browser_with_automation(app_name, initial_url=None):
    """
    Launch a Chromium-based browser (brave/chrome/edge) with a remote-debugging
    port on the user's real profile (bookmarks/logins/history), then connect
    Playwright to it over CDP. Firefox isn't Chromium-based and isn't
    supported for this.

    If the browser is already running with a CDP port (e.g. from a previous
    assistant session), we try to reconnect first — avoiding a disruptive
    close-and-relaunch cycle.

    Args:
        app_name: Browser name ("brave", "chrome", "edge").
        initial_url: URL to open in the browser on launch. Defaults to Google.

    Returns True if a controllable page is now available.
    """
    global _pw_instance, _browser_conn, browser_page, active_browser_name

    if initial_url is None:
        initial_url = "https://www.google.com"

    if not PLAYWRIGHT_AVAILABLE:
        print("playwright not installed - falling back to a plain launch (no in-page control).")
        return False

    exe_path = _find_browser_executable(app_name)
    if not exe_path:
        return False

    # ── Try reconnecting to an already-running browser first ──
    proc_name = _process_name_for_browser(app_name) or ""
    if proc_name and _is_process_running(proc_name):
        try:
            pw = sync_playwright().start()
            conn = pw.chromium.connect_over_cdp(
                f"http://localhost:{BROWSER_DEBUG_PORT}", timeout=3000
            )
            context = conn.contexts[0] if conn.contexts else conn.new_context()
            browser_page = context.pages[0] if context.pages else context.new_page()
            _pw_instance = pw
            _browser_conn = conn
            active_browser_name = app_name
            print(f"Reconnected to existing {app_name} (no relaunch needed).")
            return True
        except Exception as e:
            print(f"Could not reconnect to running {app_name}: {e} — will relaunch.")

    # ── Fresh launch (close existing instance first) ──
    profile_dir = _real_profile_dir(app_name) or BROWSER_AUTOMATION_PROFILE_DIR
    os.makedirs(profile_dir, exist_ok=True)

    if _is_process_running(proc_name):
        speak(f"Closing your current {app_name} windows first")
    _close_existing_browser(app_name)

    try:
        subprocess.Popen([
            exe_path,
            f"--remote-debugging-port={BROWSER_DEBUG_PORT}",
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            initial_url,
        ])
        print(f"Launched {app_name} (real profile) with remote debugging on port {BROWSER_DEBUG_PORT}")
        print(f"Initial URL: {initial_url}")

        # Give the browser a moment to open the CDP port before connecting.
        for attempt in range(10):
            time.sleep(0.5)
            try:
                _pw_instance = sync_playwright().start()
                _browser_conn = _pw_instance.chromium.connect_over_cdp(
                    f"http://localhost:{BROWSER_DEBUG_PORT}"
                )
                context = _browser_conn.contexts[0] if _browser_conn.contexts else _browser_conn.new_context()
                browser_page = context.pages[0] if context.pages else context.new_page()
                active_browser_name = app_name
                print("Connected to browser for automation.")
                return True
            except Exception:
                continue

        print("Could not connect to browser for automation after launch.")
        return False

    except Exception as e:
        print(f"Failed to launch browser with automation: {e}")
        return False


def get_browser_page():
    """
    Return a live, controllable page, reconnecting if the previous session
    died. Returns None if no browser is under automation control.
    """
    global _pw_instance, _browser_conn, browser_page

    if browser_page is not None:
        try:
            browser_page.title()  # cheap call to check the connection is alive
            return browser_page
        except Exception:
            print("Browser automation session died, will need to relaunch.")
            browser_page = None
            _browser_conn = None
            _pw_instance = None

    return None


# ──────────────────────────────────────────────────────────────
#  Universal Application Discovery
# ──────────────────────────────────────────────────────────────

_installed_apps = {}   # name_lower → exe_path  (populated once at startup)

# Common spoken name → likely Start Menu / registry name.
# Helps when Whisper hears "vs code" but the shortcut is "Visual Studio Code".
SPOKEN_APP_ALIASES = {
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "code": "visual studio code",
    "file explorer": "explorer",
    "files": "explorer",
    "word": "word",
    "excel": "excel",
    "powerpoint": "powerpoint",
    "ppt": "powerpoint",
    "teams": "microsoft teams",
    "outlook": "outlook",
    "spotify": "spotify",
    "discord": "discord",
    "slack": "slack",
    "zoom": "zoom",
    "vlc": "vlc media player",
    "media player": "vlc media player",
    "obs": "obs studio",
    "gimp": "gimp",
    "audacity": "audacity",
    "steam": "steam",
    "blender": "blender",
    "unity": "unity hub",
    "terminal": "windows terminal",
    "cmd": "command prompt",
    "calculator": "calculator",
    "calc": "calculator",
    "paint": "paint",
    "snipping tool": "snipping tool",
    "task manager": "task manager",
    "control panel": "control panel",
    "settings": "settings",
    "notepad": "notepad",
    "photos": "photos",
    "brave browser": "brave",
    "microsoft edge": "edge",
    "brave browser browser": "brave",
    "edge browser": "edge",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "mozilla firefox": "firefox",
    "firefox browser": "firefox",
}


def _scan_start_menu():
    """
    Walk both the per-user and system-wide Start Menu folders,
    resolve every .lnk shortcut to its target .exe, and return
    a dict of {name_lower: exe_path}.
    """
    apps = {}
    start_menu_dirs = [
        os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"),
            r"Microsoft\Windows\Start Menu\Programs",
        ),
        os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs",
        ),
    ]

    # Prefixes that indicate non-app shortcuts (uninstallers, docs, etc.)
    skip_prefixes = (
        "uninstall", "remove", "readme", "help",
        "documentation", "license", "changelog", "release notes",
    )

    try:
        shell = win32com.client.Dispatch("WScript.Shell")
    except Exception as e:
        print(f"Start Menu scan: could not create WScript.Shell: {e}")
        return apps

    for start_dir in start_menu_dirs:
        if not os.path.isdir(start_dir):
            continue
        for root, _dirs, files in os.walk(start_dir):
            for f in files:
                if not f.lower().endswith(".lnk"):
                    continue

                name = os.path.splitext(f)[0].lower().strip()

                if any(name.startswith(p) for p in skip_prefixes):
                    continue

                lnk_path = os.path.join(root, f)
                try:
                    shortcut = shell.CreateShortCut(lnk_path)
                    target = shortcut.TargetPath
                    if (
                        target
                        and target.lower().endswith(".exe")
                        and os.path.isfile(target)
                    ):
                        if name not in apps:
                            apps[name] = target
                except Exception:
                    continue

    return apps


def _scan_registry_app_paths():
    """
    Read HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths
    for applications registered via their installers.
    """
    apps = {}
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        try:
                            value, _ = winreg.QueryValueEx(subkey, None)
                            if value and os.path.isfile(value):
                                name = os.path.splitext(subkey_name)[0].lower().strip()
                                if name not in apps:
                                    apps[name] = value
                        except OSError:
                            pass
                    i += 1
                except OSError:
                    break
    except Exception as e:
        print(f"Registry scan warning: {e}")
    return apps


def _scan_installed_apps():
    """
    Discover all installed applications on this machine.
    Merges Start Menu shortcuts + Windows Registry App Paths.
    Called once at startup; results cached in _installed_apps.
    """
    global _installed_apps

    print("Scanning installed applications...")
    t0 = time.time()

    try:
        pythoncom.CoInitialize()
        com_initialized = True
    except Exception:
        com_initialized = False

    try:
        # Start Menu shortcuts (richest source on most machines)
        apps = _scan_start_menu()

        # Registry App Paths (picks up apps that don't have Start Menu shortcuts)
        for name, path in _scan_registry_app_paths().items():
            if name not in apps:
                apps[name] = path

        _installed_apps = apps
        elapsed = time.time() - t0
        print(f"Found {len(_installed_apps)} installed applications ({elapsed:.1f}s)")

        # Log a few for debugging
        for name in sorted(list(_installed_apps.keys()))[:10]:
            print(f"  • {name}: {_installed_apps[name]}")
        if len(_installed_apps) > 10:
            print(f"  … and {len(_installed_apps) - 10} more")

    finally:
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _find_best_app_match(spoken_name):
    """
    Find the best matching installed application for a spoken name.

    Order of preference:
      1. Spoken alias → exact lookup
      2. Exact name match
      3. Substring containment ("spotify" matches "spotify music")
      4. Fuzzy match (SequenceMatcher ≥ 0.55)

    Returns (matched_name, exe_path) or (None, None).
    """
    spoken = spoken_name.lower().strip()

    # 1. Spoken alias
    alias = SPOKEN_APP_ALIASES.get(spoken)
    if alias and alias in _installed_apps:
        return alias, _installed_apps[alias]

    # 2. Exact match
    if spoken in _installed_apps:
        return spoken, _installed_apps[spoken]

    # 3. Substring containment (prefer shorter names = more specific)
    substring_matches = []
    for app_name in _installed_apps:
        if spoken in app_name or app_name in spoken:
            substring_matches.append(app_name)

    if substring_matches:
        # Pick the shortest match (most specific)
        best = min(substring_matches, key=len)
        print(f"Substring matched '{spoken_name}' → '{best}'")
        return best, _installed_apps[best]

    # 4. Fuzzy match
    best_score = 0.0
    best_name = None

    for app_name in _installed_apps:
        score = SequenceMatcher(None, spoken, app_name).ratio()
        if score > best_score:
            best_score = score
            best_name = app_name

    if best_score >= 0.55 and best_name is not None:
        print(f"Fuzzy matched '{spoken_name}' → '{best_name}' (score={best_score:.2f})")
        return best_name, _installed_apps[best_name]

    return None, None


def open_application(app_name):
    """
    Open any application on the system.

    Fallback chain:
      1. Chromium browser automation (Brave / Chrome / Edge)
      2. Dynamic Start Menu + Registry lookup with fuzzy matching
      3. PATH lookup via shutil.which()
      4. Windows shell association via os.startfile()
      5. PowerShell Start-Process (catches UWP / Store apps)
    """
    app_name_original = app_name
    app_name = app_name.lower().strip()

    # Resolve spoken browser aliases so automation still works
    browser_aliases = {
        "brave browser": "brave",
        "microsoft edge": "edge",
        "brave browser browser": "brave",
        "edge browser": "edge",
        "google chrome": "chrome",
        "chrome browser": "chrome",
        "mozilla firefox": "firefox",
        "firefox browser": "firefox",
    }
    resolved = browser_aliases.get(app_name, app_name)

    # ── Step 1: Chromium browser automation ──
    if resolved in ("brave", "chrome", "edge"):
        if launch_browser_with_automation(resolved):
            return
        # If automation fails, fall through to generic launch

    # ── Step 2: Dynamic app lookup (Start Menu + Registry + fuzzy) ──
    matched_name, matched_path = _find_best_app_match(app_name)
    if matched_path:
        try:
            subprocess.Popen([matched_path])
            print(f"Opened '{matched_name}': {matched_path}")
            return
        except Exception as e:
            print(f"Failed to launch '{matched_path}': {e}")

    # ── Step 3: PATH lookup ──
    exe = shutil.which(app_name) or shutil.which(app_name + ".exe")
    if exe:
        try:
            subprocess.Popen([exe])
            print(f"Opened '{app_name}' from PATH: {exe}")
            return
        except Exception as e:
            print(f"Failed to launch from PATH: {e}")

    # ── Step 4: Windows shell association ──
    try:
        os.startfile(app_name)
        print(f"Opened '{app_name}' via shell association")
        return
    except OSError:
        pass

    # ── Step 5: PowerShell Start-Process (UWP / Store apps) ──
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Start-Process '{app_name}'"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            print(f"Opened '{app_name}' via PowerShell Start-Process")
            return
    except Exception:
        pass

    # ── All methods exhausted ──
    print(f"Could not find application: {app_name}")
    speak(f"I couldn't find {app_name_original} on this computer")


def navigate_to_site(name_or_url: str):
    """
    Navigate the automated browser page to a known site name or a raw URL.
    Launches a browser first (defaulting to brave, then chrome, then edge)
    if none is currently under automation control.

    Resolution order:
      1. KNOWN_SITES shortcut
      2. Already looks like a domain (has a dot, no spaces)
      3. Try https://www.{name}.com  (quick HEAD check)
      4. Fall back to a Google search

    Returns True on success.
    """
    global browser_page

    # ── Resolve target URL early so we can pass it to the browser launch ──
    key = name_or_url.strip().lower()
    if key in KNOWN_SITES:
        url = KNOWN_SITES[key]
    elif "." in key and " " not in key:
        # Looks like a domain already (e.g. "example.com")
        url = key if key.startswith("http") else f"https://{key}"
    else:
        # Try the obvious https://www.{name}.com guess before searching.
        guess = f"https://www.{key.replace(' ', '')}.com"
        url = guess if _url_is_reachable(guess) else f"https://www.google.com/search?q={key.replace(' ', '+')}"

    page = get_browser_page()

    if page is None:
        # No active automated session — launch browser directly to target URL
        # so it opens the right page immediately (no racy double-navigation).
        launched = False
        for fallback in ("brave", "chrome", "edge"):
            if _find_browser_executable(fallback):
                launched = launch_browser_with_automation(fallback, initial_url=url)
                break
        page = get_browser_page()

        if page is None:
            return False

        if launched:
            # Browser was freshly launched with the target URL — wait for it
            # to finish loading instead of navigating again.
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.bring_to_front()
                print(f"Browser opened directly to {url}")
                return True
            except Exception as e:
                print(f"Wait for initial page load failed: {e}, will try goto")
                # Fall through to the goto below as a fallback.

    try:
        page.bring_to_front()
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        print(f"Navigated to {url}")
        return True
    except Exception as e:
        print(f"Failed to navigate to {url}: {e}")
        return False


def _url_is_reachable(url: str, timeout: float = 3.0) -> bool:
    """Quick HEAD request to check if a URL resolves to a real site."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def click_first_video():
    """Click the first video on the current page (YouTube homepage / search).

    Uses pure JavaScript execution instead of Playwright locators because
    YouTube's Polymer web-components cause Playwright's wait_for /
    wait_for_selector to hang indefinitely.  A single page.evaluate() call
    runs inside the browser context, finds the first visible video link,
    and clicks it — fast and can't hang.
    """
    page = get_browser_page()
    if page is None:
        return False

    # Give YouTube a moment to render its video grid after navigation.
    import time as _time
    _time.sleep(3)

    # Pure JS approach — runs inside the page, no Playwright waiting.
    try:
        result = page.evaluate("""
            () => {
                // Strategy 1: YouTube-specific title links
                const ytSelectors = [
                    'ytd-rich-item-renderer a#video-title-link',
                    'ytd-rich-item-renderer a[href*="/watch"]',
                    'ytd-video-renderer a#video-title',
                    'ytd-video-renderer a[href*="/watch"]',
                    'ytd-compact-video-renderer a[href*="/watch"]',
                    'ytd-grid-video-renderer a[href*="/watch"]',
                ];

                for (const sel of ytSelectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0 &&
                            rect.top >= 0 && rect.bottom <= window.innerHeight + 100) {
                            el.click();
                            return {success: true, method: sel};
                        }
                    }
                }

                // Strategy 2: Any visible /watch link on the page
                const watchLinks = document.querySelectorAll('a[href*="/watch?v="]');
                for (const a of watchLinks) {
                    const rect = a.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 &&
                        rect.top >= 0 && rect.bottom <= window.innerHeight + 100) {
                        a.click();
                        return {success: true, method: 'a[href*="/watch?v="]'};
                    }
                }

                // Strategy 3: Click the thumbnail image container
                const thumbs = document.querySelectorAll('a#thumbnail[href*="/watch"]');
                for (const t of thumbs) {
                    const rect = t.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 &&
                        rect.top >= 0 && rect.bottom <= window.innerHeight + 100) {
                        t.click();
                        return {success: true, method: 'a#thumbnail'};
                    }
                }

                // Collect debug info if nothing worked
                const totalWatch = document.querySelectorAll('a[href*="/watch"]').length;
                const totalRich = document.querySelectorAll('ytd-rich-item-renderer').length;
                const totalVid = document.querySelectorAll('ytd-video-renderer').length;
                return {
                    success: false,
                    debug: `watch_links=${totalWatch}, rich_items=${totalRich}, video_renderers=${totalVid}, url=${location.href}`
                };
            }
        """)

        if result and result.get("success"):
            print(f"Clicked first video via JS: {result.get('method')}")
            return True
        else:
            debug = result.get("debug", "unknown") if result else "evaluate returned None"
            print(f"Could not find a video to click. Debug: {debug}")
            return False

    except Exception as e:
        print(f"click_first_video JS execution failed: {e}")
        return False


def click_first_result():
    """Click the first organic result on a Google search results page."""
    page = get_browser_page()
    if page is None:
        return False

    selectors = [
        "#search a h3",       # Google search result heading
        "#rso a h3",          # alternate Google results container
    ]

    for selector in selectors:
        try:
            heading = page.locator(selector).first
            heading.wait_for(state="visible", timeout=4000)
            heading.click()
            print(f"Clicked first result via selector: {selector}")
            return True
        except Exception:
            continue

    print("Could not find a result to click.")
    return False


# ──────────────────────────────────────────────────────────────
#  Direct Browser Actions (no LLM, instant execution)
# ──────────────────────────────────────────────────────────────

def browser_scroll(direction: str = "down", amount: int = 3):
    """Scroll the automated browser page up or down."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        pixels = 400 * amount
        if direction == "up":
            pixels = -pixels
        page.mouse.wheel(0, pixels)
        print(f"Scrolled {direction} by {pixels}px")
        return True
    except Exception as e:
        print(f"Scroll failed: {e}")
        return False


def browser_go_back():
    """Navigate the automated browser page back."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        page.go_back(wait_until="domcontentloaded", timeout=10000)
        print("Went back")
        return True
    except Exception as e:
        print(f"Go back failed: {e}")
        return False


def browser_go_forward():
    """Navigate the automated browser page forward."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        page.go_forward(wait_until="domcontentloaded", timeout=10000)
        print("Went forward")
        return True
    except Exception as e:
        print(f"Go forward failed: {e}")
        return False


def browser_refresh():
    """Reload the current page."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        page.reload(wait_until="domcontentloaded", timeout=10000)
        print("Refreshed page")
        return True
    except Exception as e:
        print(f"Refresh failed: {e}")
        return False


def browser_toggle_play():
    """Toggle play/pause on a media page (works on YouTube and most HTML5 players).

    Uses YouTube's JS player API first for reliability, then falls back to
    the 'k' keyboard shortcut (YouTube's play/pause that works regardless of
    focus), then generic HTML5 <video> element toggle, and finally Space.
    """
    page = get_browser_page()
    if page is None:
        return False
    try:
        # Strategy 1: Use the HTML5 <video> element API directly (works on
        # YouTube AND any other site with a <video> tag).
        result = page.evaluate("""
            () => {
                const video = document.querySelector('video');
                if (!video) return {success: false, reason: 'no_video'};
                if (video.paused) {
                    video.play();
                    return {success: true, action: 'played'};
                } else {
                    video.pause();
                    return {success: true, action: 'paused'};
                }
            }
        """)
        if result and result.get("success"):
            action = result.get("action", "toggled")
            print(f"Video {action} via JS API")
            return True

        # Strategy 2: Press 'k' — YouTube's universal play/pause shortcut
        # (works even when the player doesn't have keyboard focus, unlike Space).
        current_url = page.url or ""
        if "youtube.com" in current_url or "youtu.be" in current_url:
            page.keyboard.press("k")
            print("Toggled play/pause via 'k' key (YouTube)")
            return True

        # Strategy 3: Fallback to Space for non-YouTube players
        page.keyboard.press("Space")
        print("Toggled play/pause via Space key")
        return True

    except Exception as e:
        print(f"Toggle play failed: {e}")
        return False


def browser_toggle_fullscreen():
    """Toggle fullscreen on a video page (YouTube: 'f' key)."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        page.keyboard.press("f")
        print("Toggled fullscreen")
        return True
    except Exception as e:
        print(f"Fullscreen toggle failed: {e}")
        return False


def browser_toggle_mute():
    """Toggle mute on a video page (YouTube: 'm' key)."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        page.keyboard.press("m")
        print("Toggled mute")
        return True
    except Exception as e:
        print(f"Mute toggle failed: {e}")
        return False


def browser_close_tab():
    """Close the current browser tab."""
    page = get_browser_page()
    if page is None:
        return False
    try:
        page.close()
        print("Closed current tab")
        return True
    except Exception as e:
        print(f"Close tab failed: {e}")
        return False


def browser_new_tab():
    """Open a new tab in the automated browser."""
    global browser_page
    if _browser_conn is None:
        return False
    try:
        context = _browser_conn.contexts[0] if _browser_conn.contexts else None
        if context is None:
            return False
        browser_page = context.new_page()
        browser_page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=10000)
        print("Opened new tab")
        return True
    except Exception as e:
        print(f"New tab failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────
#  LLM-Powered Browser Actions (Ollama interprets the command)
# ──────────────────────────────────────────────────────────────

def _extract_page_context(page, max_elements: int = 40) -> str:
    """
    Pull a compact summary of the page's visible interactive elements
    so the LLM can decide what to click / type / interact with.
    """
    try:
        context_parts = [f"Page URL: {page.url}", f"Page title: {page.title()}"]

        # Grab visible interactive elements via JavaScript
        js_code = """
            () => {
                const MAX = %d;
                const results = [];
                const selectors = 'a, button, input, textarea, select, [role="button"], [onclick], video, [role="link"], [role="tab"], [role="menuitem"]';
                const nodes = document.querySelectorAll(selectors);
                for (const el of nodes) {
                    if (results.length >= MAX) break;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    if (rect.bottom < 0 || rect.top > window.innerHeight) continue;

                    const tag = el.tagName.toLowerCase();
                    const text = (el.textContent || '').trim().substring(0, 80);
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    const placeholder = el.getAttribute('placeholder') || '';
                    const href = el.getAttribute('href') || '';
                    const elType = el.getAttribute('type') || '';
                    const elId = el.id || '';
                    const elName = el.getAttribute('name') || '';
                    const role = el.getAttribute('role') || '';

                    let selector = tag;
                    if (elId) selector = '#' + elId;
                    else if (elName) selector = tag + '[name="' + elName + '"]';
                    else if (ariaLabel) selector = tag + '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]';
                    else if (placeholder) selector = tag + '[placeholder="' + placeholder.replace(/"/g, '\\\\"') + '"]';

                    results.push({
                        index: results.length,
                        tag,
                        selector,
                        text: text.substring(0, 60),
                        ariaLabel: ariaLabel.substring(0, 60),
                        placeholder,
                        href: href.substring(0, 80),
                        type: elType,
                        role,
                    });
                }
                return results;
            }
        """ % max_elements

        elements = page.evaluate(js_code)

        if elements:
            context_parts.append("\nVisible interactive elements:")
            for el in elements:
                parts = [f"[{el['index']}] <{el['tag']}>"]
                if el.get('text'):
                    parts.append(f'text="{el["text"]}"')
                if el.get('ariaLabel'):
                    parts.append(f'aria-label="{el["ariaLabel"]}"')
                if el.get('placeholder'):
                    parts.append(f'placeholder="{el["placeholder"]}"')
                if el.get('href'):
                    parts.append(f'href="{el["href"]}"')
                if el.get('type'):
                    parts.append(f'type="{el["type"]}"')
                if el.get('role'):
                    parts.append(f'role="{el["role"]}"')
                parts.append(f'selector="{el["selector"]}"')
                context_parts.append("  " + " ".join(parts))
        else:
            context_parts.append("No interactive elements found on page.")

        return "\n".join(context_parts)

    except Exception as e:
        print(f"Failed to extract page context: {e}")
        return f"Page URL: {page.url}\n(Could not extract page elements)"


def _llm_plan_browser_action(user_command: str, page_context: str) -> dict | None:
    """
    Ask the local LLM to decide what Playwright action to take.

    Returns a dict like:
        {"action": "click", "selector": "#video-title"}
        {"action": "type", "selector": "input[name=search]", "text": "hello"}
        {"action": "press", "key": "Enter"}
        {"action": "scroll", "direction": "down"}
        {"action": "none", "reason": "..."}
    """
    prompt = (
        'You are a browser automation assistant. The user gave a voice command '
        'and you must decide what action to take on the current web page.\n\n'
        f'User command: "{user_command}"\n\n'
        f'Current page context:\n{page_context}\n\n'
        'Respond with ONLY a JSON object (no markdown, no explanation) describing the action. '
        'Supported actions:\n'
        '- {"action": "click", "selector": "CSS_SELECTOR"} - click an element\n'
        '- {"action": "type", "selector": "CSS_SELECTOR", "text": "TEXT_TO_TYPE"} - click an input and type text\n'
        '- {"action": "press", "key": "KEY_NAME"} - press a keyboard key (Enter, Space, Escape, Tab, ArrowDown)\n'
        '- {"action": "scroll", "direction": "down"} or {"action": "scroll", "direction": "up"}\n'
        '- {"action": "navigate", "url": "URL"} - go to a URL\n'
        '- {"action": "none", "reason": "REASON"} - if you cannot determine what to do\n\n'
        'Pick the best matching element from the page context. '
        'If the user says "first video", pick the first video link. '
        'If they say "search bar", pick the search input. '
        'Use the selector from the page context.\n\nJSON:'
    )

    try:
        response = ollama.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={
                "num_predict": 200,
                "temperature": 0.1,
            },
        )
        raw = response.get("response", "").strip()
        print(f"LLM browser action raw: {raw}")

        # Extract JSON from the response (LLM sometimes wraps in markdown)
        json_match = re.search(r'\{[^{}]*\}', raw)
        if json_match:
            return json.loads(json_match.group())
        return None

    except Exception as e:
        print(f"LLM browser action planning failed: {e}")
        return None


def _execute_browser_action(page, action: dict) -> bool:
    """Execute a planned browser action on the Playwright page."""
    act = action.get("action", "none")
    print(f"Executing browser action: {action}")

    try:
        if act == "click":
            selector = action.get("selector", "")
            if not selector:
                return False
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=5000)
            locator.click()
            print(f"Clicked: {selector}")
            return True

        elif act == "type":
            selector = action.get("selector", "")
            text = action.get("text", "")
            if not selector or not text:
                return False
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=5000)
            locator.click()
            locator.fill(text)
            print(f"Typed '{text}' into {selector}")
            return True

        elif act == "press":
            key = action.get("key", "")
            if not key:
                return False
            page.keyboard.press(key)
            print(f"Pressed key: {key}")
            return True

        elif act == "scroll":
            direction = action.get("direction", "down")
            return browser_scroll(direction)

        elif act == "navigate":
            url = action.get("url", "")
            if not url:
                return False
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            print(f"Navigated to: {url}")
            return True

        elif act == "none":
            reason = action.get("reason", "unknown")
            print(f"LLM chose no action: {reason}")
            return False

        else:
            print(f"Unknown browser action: {act}")
            return False

    except Exception as e:
        print(f"Browser action execution failed: {e}")
        return False


def handle_browser_action(command: str) -> bool:
    """
    Full pipeline: extract page context -> LLM plans action -> execute.
    Returns True on success.
    """
    page = get_browser_page()
    if page is None:
        return False

    print(f"Handling browser action: '{command}'")
    page_context = _extract_page_context(page)
    action = _llm_plan_browser_action(command, page_context)

    if action is None:
        print("LLM could not plan an action.")
        return False

    return _execute_browser_action(page, action)


# ──────────────────────────────────────────────────────────────
#  WhatsApp Complete Voice Automation Suite
# ──────────────────────────────────────────────────────────────

def _get_whatsapp_call_window():
    """Find and return dedicated WhatsApp Call window if active."""
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            title = (w.title or "").strip().lower()
            if any(k in title for k in ("whatsapp call", "whatsapp video call", "whatsapp audio call", "call with")):
                return w
        for w in gw.getAllWindows():
            title = (w.title or "").strip().lower()
            if "call" in title and "whatsapp" in title:
                return w
    except Exception:
        pass
    return None


def _get_whatsapp_window():
    """Find and return the active or top-level WhatsApp PyGetWindow instance."""
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            title = (w.title or "").strip().lower()
            if "whatsapp" in title:
                return w
    except Exception:
        pass
    return None


def whatsapp_open_and_focus():
    """Ensure WhatsApp Desktop is launched and brought to the foreground."""
    try:
        import pygetwindow as gw
    except ImportError:
        pass

    try:
        subprocess.Popen(["powershell", "-NoProfile", "-Command", "Start-Process 'whatsapp:'"])
    except Exception as e:
        print(f"WhatsApp launch error: {e}")
        try:
            os.startfile("whatsapp:")
        except Exception:
            pass

    time.sleep(1.8)

    w = _get_whatsapp_window()
    if w:
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
            time.sleep(0.3)
        except Exception as e:
            print(f"Window activate warning: {e}")
    return w


def _uia_find_and_click_button(target_type: str = "voice") -> bool:
    """
    Search for a UI Automation Button element inside WhatsApp
    and trigger it via InvokePattern or coordinate click.
    target_type: 'voice', 'video', or 'end_call'
    """
    try:
        import pyautogui
        import comtypes.client
        comtypes.CoInitialize()
        # pyrefly: ignore [missing-import]
        from comtypes.gen.UIAutomationClient import (
            CUIAutomation, IUIAutomation, TreeScope_Descendants, TreeScope_Children,
            UIA_ButtonControlTypeId, UIA_ControlTypePropertyId,
            UIA_InvokePatternId, IUIAutomationInvokePattern
        )

        uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        root = uia.GetRootElement()

        # Find WhatsApp window in top-level elements
        wa_el = None
        wa_rect = None
        children = root.FindAll(TreeScope_Children, uia.CreateTrueCondition())
        for i in range(children.Length):
            c = children.GetElement(i)
            name = (c.CurrentName or "").lower()
            cls = (c.CurrentClassName or "").lower()
            if "whatsapp" in name or "whatsapp" in cls or "call" in name:
                wa_el = c
                wa_rect = c.CurrentBoundingRectangle
                if target_type == "end_call" and "call" in name:
                    break
                if "whatsapp" in name:
                    break

        search_root = root if target_type == "end_call" else (wa_el if wa_el else root)
        btn_cond = uia.CreatePropertyCondition(UIA_ControlTypePropertyId, UIA_ButtonControlTypeId)
        buttons = search_root.FindAll(TreeScope_Descendants, btn_cond)

        # Blocked sidebar navigation tabs (prevents clicking 'Calls' / 'Chats' tabs on left sidebar)
        blocked_names = {
            "calls", "calls tab", "call tab", "chats", "chats tab", "status",
            "settings", "profile", "starred messages", "archive", "archived chats", "meta ai"
        }
        blocked_ids = {"callstab", "callsbutton", "chatstab", "navview", "sidebar", "navigation"}

        for i in range(buttons.Length):
            btn = buttons.GetElement(i)
            b_name = (btn.CurrentName or "").strip().lower()
            b_help = (btn.CurrentHelpText or "").strip().lower()
            b_id = (btn.CurrentAutomationId or "").strip().lower()

            # Ignore navigation sidebar buttons
            if b_name in blocked_names or b_help in blocked_names:
                continue
            if any(bid in b_id for bid in blocked_ids):
                continue

            # Verify target match
            matched = False
            if target_type == "video":
                if any(k in b_name or k in b_help for k in ("video call", "start video call", "videocall")) or "videocall" in b_id:
                    matched = True
            elif target_type == "voice":
                if any(k in b_name or k in b_help for k in ("voice call", "audio call", "start voice call", "start audio call")) or "voicecall" in b_id or "audiocall" in b_id:
                    matched = True
            elif target_type == "end_call":
                if any(k in b_name or k in b_help for k in ("end call", "leave call", "hang up", "disconnect call", "cancel call")) or "endcall" in b_id:
                    matched = True

            if not matched:
                continue

            # Geometric check: ensure button is in top header of conversation (right half of window), not left sidebar
            rect = btn.CurrentBoundingRectangle
            cx = int((rect.left + rect.right) / 2)
            cy = int((rect.top + rect.bottom) / 2)

            if wa_rect and target_type in ("voice", "video"):
                w_width = wa_rect.right - wa_rect.left
                # Call buttons must be on the right side (> 35% from left) and in top header (< 150px from top)
                if cx < (wa_rect.left + w_width * 0.35):
                    continue
                if cy > (wa_rect.top + 150):
                    continue

            print(f"UIA matched chat header button: Name='{btn.CurrentName}', Help='{btn.CurrentHelpText}', Pos=({cx},{cy})")

            # Try Invoke Pattern
            try:
                pat = btn.GetCurrentPattern(UIA_InvokePatternId)
                if pat:
                    inv = pat.QueryInterface(IUIAutomationInvokePattern)
                    inv.Invoke()
                    print("Invoked button via UIA pattern!")
                    return True
            except Exception:
                pass

            # Fallback: Click center coordinates of element
            if cx > 0 and cy > 0:
                pyautogui.click(cx, cy)
                print(f"Clicked button at ({cx}, {cy})")
                return True

    except Exception as e:
        print(f"UIA button search exception: {e}")

    return False


def whatsapp_search_and_open_chat(contact_name: str) -> bool:
    """Focus search in WhatsApp, type contact_name, and open the chat."""
    try:
        import pyautogui
        import pyperclip
    except ImportError:
        print("pyautogui or pyperclip not installed.")
        return False

    clean_name = contact_name.strip()
    if not clean_name:
        return False

    whatsapp_open_and_focus()

    # 1. Switch to Chats tab & Trigger Search
    pyautogui.hotkey('ctrl', '1')
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'f')
    time.sleep(0.3)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.1)
    pyautogui.press('backspace')
    time.sleep(0.1)

    # 2. Paste contact name
    pyperclip.copy(clean_name)
    pyautogui.hotkey('ctrl', 'v')
    print(f"Searching WhatsApp for '{clean_name}'...")
    time.sleep(1.0)

    # 3. Open chat
    pyautogui.press('enter')
    time.sleep(0.3)
    pyautogui.press('down')
    time.sleep(0.15)
    pyautogui.press('enter')
    time.sleep(0.8)
    return True


def whatsapp_call(contact_name: str, call_type: str = "voice") -> bool:
    """
    Open WhatsApp Desktop, search for contact_name, open their chat,
    and initiate a voice or video call.
    Uses UIA element finding, chat header coordinates, and keyboard fallbacks.
    """
    import pyautogui

    clean_name = contact_name.strip()
    if not clean_name:
        return False

    print(f"Initiating WhatsApp {call_type} call to '{clean_name}'")
    whatsapp_search_and_open_chat(clean_name)
    time.sleep(0.6)

    # Strategy 1: UI Automation Button Click (with strict chat header filter)
    clicked = _uia_find_and_click_button(call_type)
    if clicked:
        print(f"Successfully started {call_type} call to {clean_name} via UIA.")
        return True

    # Strategy 2: Window-relative Header Coordinates (clicks the exact top right chat icons)
    w = _get_whatsapp_window()
    if w and not w.isMinimized:
        try:
            right = w.right
            top = w.top
            # In WhatsApp desktop active chat header:
            # Video Call is ~145px from right, Voice Call is ~105px from right, y is ~52px from top
            if call_type == "video":
                click_x = right - 145
                click_y = top + 52
            else:
                click_x = right - 105
                click_y = top + 52

            pyautogui.click(click_x, click_y)
            print(f"Clicked {call_type} call button in chat header at coordinate ({click_x}, {click_y})")
            return True
        except Exception as e:
            print(f"Coordinate click fallback warning: {e}")

    # Strategy 3: Shortcut fallbacks
    if call_type == "video":
        pyautogui.hotkey('ctrl', 'shift', 'v')
    else:
        pyautogui.hotkey('ctrl', 'shift', 'c')

    return True


def whatsapp_send_message(contact_name: str, message: str) -> bool:
    """
    Open chat with contact_name and send the message text.
    """
    import pyautogui
    import pyperclip

    clean_name = contact_name.strip()
    clean_msg = message.strip()
    if not clean_name or not clean_msg:
        return False

    print(f"Sending WhatsApp message to '{clean_name}': '{clean_msg}'")
    whatsapp_search_and_open_chat(clean_name)
    time.sleep(0.5)

    # Focus is now in the message input field at bottom
    pyperclip.copy(clean_msg)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)
    pyautogui.press('enter')
    print("Message sent.")
    return True


def whatsapp_hang_up() -> bool:
    """
    Hang up / cut / disconnect an ongoing WhatsApp call.
    """
    import pyautogui

    print("Attempting to hang up / cut WhatsApp call...")

    # Strategy 1: Dedicated Call Window handling
    call_win = _get_whatsapp_call_window()
    if call_win:
        try:
            if call_win.isMinimized:
                call_win.restore()
            call_win.activate()
            time.sleep(0.15)
            # Alt+F4 closes the active call window instantly, cutting the call
            pyautogui.hotkey('alt', 'f4')
            print("Terminated call window via Alt+F4.")
            return True
        except Exception as e:
            print(f"Call window termination warning: {e}")

    # Strategy 2: UIA Button Search for End Call / Leave Call
    clicked = _uia_find_and_click_button("end_call")
    if clicked:
        print("Call ended via UIA button.")
        return True

    # Strategy 3: Focus WhatsApp window and send disconnect signals
    w = _get_whatsapp_window()
    if w:
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
            time.sleep(0.15)
        except Exception:
            pass

    pyautogui.hotkey('ctrl', 'shift', 'e')
    time.sleep(0.15)
    pyautogui.hotkey('ctrl', 'shift', 'h')
    time.sleep(0.15)
    pyautogui.press('esc')
    print("Sent hang up key commands.")
    return True


def whatsapp_action(action_type: str) -> bool:
    """
    Execute standard WhatsApp desktop actions & shortcuts via voice.
    """
    import pyautogui

    whatsapp_open_and_focus()

    action_type = action_type.lower().strip()
    print(f"Executing WhatsApp action: '{action_type}'")

    if action_type == "next_chat":
        pyautogui.hotkey('ctrl', 'tab')
    elif action_type == "previous_chat":
        pyautogui.hotkey('ctrl', 'shift', 'tab')
    elif action_type == "new_chat":
        pyautogui.hotkey('ctrl', 'n')
    elif action_type == "new_group":
        pyautogui.hotkey('ctrl', 'shift', 'n')
    elif action_type == "mute_chat":
        pyautogui.hotkey('ctrl', 'shift', 'm')
    elif action_type == "archive_chat":
        pyautogui.hotkey('ctrl', 'e')
    elif action_type == "unread_chat":
        pyautogui.hotkey('ctrl', 'shift', 'u')
    elif action_type == "delete_chat":
        pyautogui.hotkey('ctrl', 'shift', 'd')
    elif action_type == "pin_chat":
        pyautogui.hotkey('ctrl', 'shift', 'p')
    elif action_type == "settings":
        pyautogui.hotkey('ctrl', ',')
    elif action_type == "profile":
        pyautogui.hotkey('ctrl', 'p')
    elif action_type == "show_shortcuts":
        pyautogui.hotkey('ctrl', '/')
    elif action_type == "search_in_chat":
        pyautogui.hotkey('ctrl', 'shift', 'f')
    else:
        print(f"Unknown WhatsApp action: '{action_type}'")
        return False

    return True


def trim_silence(audio_np: np.ndarray, sample_rate: int, threshold: int = 500, min_silence_duration: float = 0.3):
    """
    Trim leading and trailing silence from a mono float32 audio array in range [-1, 1].
    threshold: absolute amplitude below which considered silent.
    min_silence_duration: seconds of silence needed to consider as start/end.
    Returns trimmed audio.
    """
    # Convert to absolute amplitude
    abs_audio = np.abs(audio_np)
    # Determine silent frames
    silent = abs_audio < threshold
    # Find first non-silent from start
    if len(silent) == 0:
        return audio_np
    # Find first index where not silent
    idx_start = np.argmax(~silent) if np.any(~silent) else len(silent)
    # Find last index where not silent
    idx_end = len(silent) - np.argmax(~silent[::-1]) if np.any(~silent) else -1
    if idx_start >= len(silent) or idx_end < 0:
        return np.array([], dtype=np.float32)
    # Ensure we have at least min_silence_duration of audio? Not needed.
    trimmed = audio_np[idx_start:idx_end+1]
    # If trimmed is too short, fallback to original
    if len(trimmed) < int(sample_rate * 0.1):  # less than 0.1 sec
        return audio_np
    return trimmed


def normalize_text(text: str) -> str:
    """
    Normalize Whisper output for wake-word matching.
    """
    text = text.lower().strip()

    # Remove punctuation
    text = re.sub(r"[^a-z0-9\s]", "", text)

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    return text


def wake_word_similarity(word: str) -> float:
    """
    Compare a recognized word against all known Karen variants.
    Returns the highest similarity score.
    """
    word = normalize_text(word)

    if not word:
        return 0.0

    best_score = 0.0

    for variant in WAKEWORD_VARIANTS:
        score = SequenceMatcher(
            None,
            word,
            variant
        ).ratio()

        best_score = max(best_score, score)

    return best_score


def detect_wake_word(text: str):
    """
    Detect Karen, 'daddy is home', and other wake phrases.

    Returns:
        (detected: bool, remaining_command: str, matched_word_or_phrase: str, score: float, greeting: str)
    """
    normalized = normalize_text(text)

    if not normalized:
        return False, "", "", 0.0, ""

    # 1. Multi-word wake phrases (e.g. "wake up karen daddy is home", "daddy is home")
    for phrase, greeting in WAKE_PHRASES.items():
        if normalized == phrase or normalized.startswith(phrase + " "):
            remaining = normalized[len(phrase):].strip()
            print(f"Wake phrase triggered: '{phrase}' (greeting: '{greeting}')")
            return True, remaining, phrase, 1.0, greeting

    # 2. Individual word matching against WAKEWORD_VARIANTS
    words = normalized.split()

    best_score = 0.0
    best_index = -1
    best_word = ""

    for i, word in enumerate(words):
        score = wake_word_similarity(word)

        if score > best_score:
            best_score = score
            best_index = i
            best_word = word

    # Wake word wasn't strong enough
    if best_score < WAKEWORD_SIMILARITY_THRESHOLD:
        return False, text, "", best_score, ""

    # Everything after the wake word is the command
    remaining_words = words[best_index + 1:]
    remaining_command = " ".join(remaining_words).strip()

    # Default greeting for "Karen"
    greeting = "Yes?"

    print(
        f"Wake word detected: '{best_word}' "
        f"(similarity={best_score:.2f})"
    )

    return True, remaining_command, best_word, best_score, greeting


def transcribe_audio(audio_data: bytes):
    """Transcribe raw audio data using Whisper."""
    if len(audio_data) == 0:
        print("No audio data")
        return ""
    try:
        # Convert int16 bytes to float32 numpy array normalized to [-1, 1]
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        # Whisper expects mono audio; ensure shape (samples,)
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=1)
        # Trim leading/trailing silence to speed up transcription
        audio_np = trim_silence(audio_np, SAMPLE_RATE, threshold=SILENCE_THRESHOLD/32768.0, min_silence_duration=0.2)
        if len(audio_np) == 0:
            print("Audio silent after trimming")
            return ""
        # Run Whisper transcription
        result = whisper_model.transcribe(
            audio_np,
            language="en",
            initial_prompt=TRANSCRIBE_PROMPT,
            # Greedy decoding (temperature=0) commits to its first guess even when
            # unsure. Beam search plus a temperature fallback ladder makes Whisper
            # retry with more exploration when its confidence checks fail, instead
            # of locking in a bad transcription.
            temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
            beam_size=5,
            best_of=5,
            condition_on_previous_text=False
        )
        text = result.get("text", "").strip()
        print(f"Recognized: '{text}'")
        return text
    except Exception as e:
        print(f"Error in Whisper transcription: {e}")
        return ""


def extract_name_after_trigger(command: str, triggers):
    """
    Find a trigger phrase in command and return whatever comes after it
    as the entity name, stripping filler words like "called"/"named".
    Also detects a trailing "... and enter it" suffix.
    Returns (name, enter_after).
    """
    cmd_lower = command.lower()
    enter_after = False

    for suffix in (" and enter it", " then enter it", " and go into it", " and enter into it"):
        if cmd_lower.endswith(suffix):
            command = command[: -len(suffix)]
            cmd_lower = cmd_lower[: -len(suffix)]
            enter_after = True
            break

    for trigger in triggers:
        idx = cmd_lower.find(trigger)
        if idx == -1:
            continue
        remainder = command[idx + len(trigger):].strip()
        for kw in ("called ", "named ", "name "):
            if remainder.lower().startswith(kw):
                remainder = remainder[len(kw):].strip()
                break
        remainder = remainder.rstrip(".!?,;:")
        return remainder, enter_after

    return "", enter_after


def extract_call_target(command: str):
    """
    Extract contact name and call type (voice/video) from phrases like:
      - 'call Tuhin'
      - 'make a call to Tuhin'
      - 'call Tuhin on whatsapp'
      - 'video call Tuhin'
      - 'whatsapp call Mom'
    Returns (name: str, call_type: str)
    """
    cmd = command.strip().rstrip(".!?,;:")
    cmd_lower = cmd.lower()

    is_video = "video" in cmd_lower

    # Strip trailing "on whatsapp" / "via whatsapp" etc.
    for suffix in (" on whatsapp", " via whatsapp", " in whatsapp", " using whatsapp", " on what's app"):
        if cmd_lower.endswith(suffix):
            cmd = cmd[: -len(suffix)].strip()
            cmd_lower = cmd.lower()
            break

    # Trigger prefixes (ordered longest first to prevent greedy sub-matching)
    call_triggers = (
        "make a whatsapp video call to ",
        "make a whatsapp voice call to ",
        "make a whatsapp audio call to ",
        "make a whatsapp call to ",
        "make a video call to ",
        "make a voice call to ",
        "make a audio call to ",
        "make a call to ",
        "whatsapp video call to ",
        "whatsapp voice call to ",
        "whatsapp audio call to ",
        "whatsapp call to ",
        "whatsapp video call ",
        "whatsapp voice call ",
        "whatsapp audio call ",
        "whatsapp call ",
        "video call to ",
        "voice call to ",
        "audio call to ",
        "video call ",
        "voice call ",
        "audio call ",
        "place a call to ",
        "call to ",
        "call ",
    )

    for trigger in call_triggers:
        if cmd_lower.startswith(trigger):
            name = cmd[len(trigger):].strip()
            if name.lower().startswith("to "):
                name = name[3:].strip()
            return name, ("video" if is_video else "voice")

    return "", ("video" if is_video else "voice")


def extract_whatsapp_message(command: str):
    """
    Extract contact name and message text from commands like:
      - 'send message to Tuhin: are you free?'
      - 'message Tuhin I am coming over'
      - 'text Tuhin hello how are you'
      - 'send a message to Tuhin saying I am on my way'
    Returns (contact: str, message: str) or (None, None)
    """
    cmd = command.strip()
    cmd_lower = cmd.lower()

    for s in (" on whatsapp", " in whatsapp", " via whatsapp"):
        if cmd_lower.endswith(s):
            cmd = cmd[:-len(s)].strip()
            cmd_lower = cmd.lower()
            break

    patterns = [
        r"^(?:send\s+(?:a\s+)?message\s+to|message|text|send\s+text\s+to)\s+([a-zA-Z0-9\s]+?)(?:\s*[:,\-]\s*|\s+saying\s+|\s+that\s+|\s+to\s+say\s+)(.+)$",
        r"^(?:send\s+(?:a\s+)?message\s+to|message|text|send\s+text\s+to)\s+([a-zA-Z0-9]+)\s+(.+)$",
    ]

    for pat in patterns:
        m = re.match(pat, cmd, re.IGNORECASE)
        if m:
            contact = m.group(1).strip()
            msg = m.group(2).strip()
            if contact and msg:
                return contact, msg

    return None, None


def classify_command(command: str):
    """
    Rule-based intent classification.
    Returns tuple (intent, entities dict).
    intents: OPEN_APP, SEARCH_WEB, ASK_QUESTION, EXIT, CLOSE_CURRENT,
             CREATE_DIR, ENTER_DIR, CREATE_FILE, WHATSAPP_CALL, WHATSAPP_END_CALL,
             WHATSAPP_SEND_MESSAGE, WHATSAPP_OPEN_CHAT, WHATSAPP_ACTION,
             NAVIGATE_SITE, BROWSER_DIRECT, BROWSER_ACTION
    """
    print(f"Classify command received: '{command}'")
    cmd_lower = command.strip().lower()

    # Exit commands
    if any(word in cmd_lower for word in ("exit", "quit", "stop", "goodbye", "bye")):
        print("Classified as EXIT")
        return "EXIT", {}

    # ---------------- WHATSAPP FULL VOICE CONTROLS ----------------
    # 1. End / Hang up / Cut call
    end_call_phrases = (
        "hang up", "hang up the call", "hang up call", "end call", "end the call",
        "disconnect call", "disconnect the call", "disconnect",
        "cut the call", "cut call", "cut this call", "cut phone", "cut the phone",
        "drop the call", "drop call", "leave call", "leave the call",
        "stop the call", "stop call", "cancel the call", "cancel call"
    )
    if cmd_lower in end_call_phrases or any(cmd_lower.startswith(p) for p in (
        "hang up", "end call", "end the call", "disconnect call", "cut the call", "cut call", "drop the call"
    )):
        print("Classified as WHATSAPP_END_CALL")
        return "WHATSAPP_END_CALL", {}

    # 2. Send Message on WhatsApp
    msg_contact, msg_text = extract_whatsapp_message(command)
    if msg_contact and msg_text:
        print(f"Classified as WHATSAPP_SEND_MESSAGE, contact: '{msg_contact}', message: '{msg_text}'")
        return "WHATSAPP_SEND_MESSAGE", {"contact": msg_contact, "message": msg_text}

    # 3. Initiate Call
    call_contact, call_type = extract_call_target(command)
    if call_contact:
        print(f"Classified as WHATSAPP_CALL, contact: '{call_contact}', type: {call_type}")
        return "WHATSAPP_CALL", {"contact": call_contact, "call_type": call_type}

    # 4. Open chat / Search chat
    for prefix in ("open chat with ", "chat with ", "open whatsapp chat with ", "search whatsapp for ", "find on whatsapp "):
        if cmd_lower.startswith(prefix):
            target = command[len(prefix):].strip().rstrip(".!?,;:")
            if target:
                print(f"Classified as WHATSAPP_OPEN_CHAT, contact: '{target}'")
                return "WHATSAPP_OPEN_CHAT", {"contact": target}

    # 5. WhatsApp Desktop Actions & Shortcuts
    wa_action_map = {
        "next chat": "next_chat",
        "previous chat": "previous_chat",
        "prev chat": "previous_chat",
        "new chat": "new_chat",
        "start new chat": "new_chat",
        "new group": "new_group",
        "create new group": "new_group",
        "mute chat": "mute_chat",
        "unmute chat": "mute_chat",
        "mute this chat": "mute_chat",
        "archive chat": "archive_chat",
        "archive this chat": "archive_chat",
        "mark as unread": "unread_chat",
        "mark chat as unread": "unread_chat",
        "delete chat": "delete_chat",
        "delete this chat": "delete_chat",
        "pin chat": "pin_chat",
        "unpin chat": "pin_chat",
        "open whatsapp settings": "settings",
        "whatsapp settings": "settings",
        "open whatsapp profile": "profile",
        "whatsapp profile": "profile",
        "show whatsapp shortcuts": "show_shortcuts",
        "whatsapp shortcuts": "show_shortcuts",
    }
    for phrase, action in wa_action_map.items():
        if cmd_lower == phrase:
            print(f"Classified as WHATSAPP_ACTION, action: {action}")
            return "WHATSAPP_ACTION", {"action": action}

    # Close current application/window
    # Keyword-based instead of exact-phrase matching, since Whisper output
    # wording varies a lot ("close current window" vs "close the window"
    # vs "close this app" etc.) and exact substrings kept missing valid commands.
    close_triggers = ("close", "shut", "kill")
    close_targets = ("window", "app", "application", "this", "current", "that", "program")

    has_close_trigger = any(t in cmd_lower for t in close_triggers)
    has_close_target = any(t in cmd_lower for t in close_targets)

    if has_close_trigger and has_close_target:
        print("Classified as CLOSE_CURRENT")
        return "CLOSE_CURRENT", {}

    # Create a directory/folder
    create_dir_triggers = (
        "create a folder", "create folder",
        "make a folder", "make folder",
        "create a directory", "create directory",
        "make a directory", "make directory",
        "new folder", "new directory",
    )
    if any(t in cmd_lower for t in create_dir_triggers):
        name, enter_after = extract_name_after_trigger(command, create_dir_triggers)
        print(f"Classified as CREATE_DIR, name: '{name}', enter_after: {enter_after}")
        return "CREATE_DIR", {"name": name, "enter_after": enter_after}

    # Enter/navigate into a directory
    enter_dir_triggers = (
        "enter the folder", "enter folder",
        "enter the directory", "enter directory",
        "go into the folder", "go into folder",
        "go into the directory", "go into directory",
        "navigate to the folder", "navigate to folder",
        "navigate to the directory", "navigate to directory",
        "go to the folder", "go to folder",
        "cd into",
    )
    if cmd_lower in ("enter it", "go into it", "enter that", "go into that"):
        print("Classified as ENTER_DIR, name: 'it'")
        return "ENTER_DIR", {"name": "it"}

    if any(t in cmd_lower for t in enter_dir_triggers):
        name, _ = extract_name_after_trigger(command, enter_dir_triggers)
        if not name:
            name = "it"
        print(f"Classified as ENTER_DIR, name: '{name}'")
        return "ENTER_DIR", {"name": name}

    # Create a file
    create_file_triggers = (
        "create a file", "create file",
        "make a file", "make file",
        "new file",
    )
    if any(t in cmd_lower for t in create_file_triggers):
        name, _ = extract_name_after_trigger(command, create_file_triggers)
        print(f"Classified as CREATE_FILE, name: '{name}'")
        return "CREATE_FILE", {"name": name}

    # Direct browser commands (work when browser is active or explicit)
    has_browser = (get_browser_page() is not None) if PLAYWRIGHT_AVAILABLE else False

    if cmd_lower in ("scroll down", "scroll down a bit", "scroll down more", "page down", "scroll"):
        print("Classified as BROWSER_DIRECT, action: scroll_down")
        return "BROWSER_DIRECT", {"action": "scroll_down"}
    if cmd_lower in ("scroll up", "scroll up a bit", "scroll up more", "page up"):
        print("Classified as BROWSER_DIRECT, action: scroll_up")
        return "BROWSER_DIRECT", {"action": "scroll_up"}

    if cmd_lower in ("go back", "back page", "previous page") or (has_browser and cmd_lower in ("back", "previous")):
        print("Classified as BROWSER_DIRECT, action: go_back")
        return "BROWSER_DIRECT", {"action": "go_back"}
    if cmd_lower in ("go forward", "forward page", "next page") or (has_browser and cmd_lower in ("forward", "next")):
        print("Classified as BROWSER_DIRECT, action: go_forward")
        return "BROWSER_DIRECT", {"action": "go_forward"}
    if cmd_lower in ("refresh", "reload", "refresh page", "reload page"):
        print("Classified as BROWSER_DIRECT, action: refresh")
        return "BROWSER_DIRECT", {"action": "refresh"}

    if cmd_lower in (
        "pause", "resume", "play", "unpause",
        "pause video", "play video", "resume video", "stop video", "continue video",
        "pause the video", "play the video", "resume the video", "stop the video",
        "continue the video", "unpause the video", "unpause video",
        "pause it", "resume it", "play it", "stop it",
        "pause this", "resume this", "play this",
    ):
        print("Classified as BROWSER_DIRECT, action: toggle_play")
        return "BROWSER_DIRECT", {"action": "toggle_play"}
    if cmd_lower in ("fullscreen", "full screen", "toggle fullscreen", "exit fullscreen"):
        print("Classified as BROWSER_DIRECT, action: toggle_fullscreen")
        return "BROWSER_DIRECT", {"action": "toggle_fullscreen"}
    if cmd_lower in ("mute", "unmute", "mute video", "unmute video", "mute the video", "unmute the video"):
        print("Classified as BROWSER_DIRECT, action: toggle_mute")
        return "BROWSER_DIRECT", {"action": "toggle_mute"}

    if cmd_lower in ("close tab", "close this tab", "shut tab"):
        print("Classified as BROWSER_DIRECT, action: close_tab")
        return "BROWSER_DIRECT", {"action": "close_tab"}
    if cmd_lower in ("new tab", "open a new tab", "open new tab"):
        print("Classified as BROWSER_DIRECT, action: new_tab")
        return "BROWSER_DIRECT", {"action": "new_tab"}

    # Fast-path click first video / result
    if any(phrase in cmd_lower for phrase in (
        "first video", "play first video", "open first video", "watch first video",
        "play the first video", "open the first video", "watch the first video", "click the first video"
    )):
        print("Classified as CLICK_FIRST_VIDEO")
        return "CLICK_FIRST_VIDEO", {}

    if any(phrase in cmd_lower for phrase in (
        "first result", "open first result", "click first result",
        "the first result", "open the first result", "click the first result",
        "the first link", "open the first link", "click the first link"
    )):
        print("Classified as CLICK_FIRST_RESULT")
        return "CLICK_FIRST_RESULT", {}

    # Opening an application OR navigating to a website ("open youtube", "open brave", "open reddit")
    if (
        cmd_lower.startswith("open ")
        or cmd_lower.startswith("launch ")
        or cmd_lower.startswith("start ")
        or cmd_lower.startswith("go to ")
        or cmd_lower.startswith("navigate to ")
    ):
        for trigger in ("open ", "launch ", "start ", "go to ", "navigate to "):
            if cmd_lower.startswith(trigger):
                target = command[len(trigger):].strip()
                target = target.rstrip(".!?,;:")
                target_lower = target.lower()

                # Don't treat in-page actions as open app/site
                if target_lower in ("the first video", "first video", "the first result", "first result"):
                    break

                if target_lower in KNOWN_SITES:
                    print(f"Classified as NAVIGATE_SITE, site: {target}")
                    return "NAVIGATE_SITE", {"site": target}

                if "." in target_lower and " " not in target_lower:
                    print(f"Classified as NAVIGATE_SITE (domain), site: {target}")
                    return "NAVIGATE_SITE", {"site": target}

                # "go to"/"navigate to" strongly implies a website, not an app
                if trigger in ("go to ", "navigate to "):
                    print(f"Classified as NAVIGATE_SITE, site: {target}")
                    return "NAVIGATE_SITE", {"site": target}

                # If browser session is active, check if target is an app or a website
                if has_browser:
                    matched_name, matched_path = _find_best_app_match(target)
                    if not matched_path:
                        print(f"Classified as NAVIGATE_SITE (active browser fallback), site: {target}")
                        return "NAVIGATE_SITE", {"site": target}

                print(f"Classified as OPEN_APP, app: {target}")
                return "OPEN_APP", {"app": target}

    # In-page browser actions when browser is active (click X, type Y, search X on page)
    if has_browser:
        browser_action_triggers = (
            "click ", "press ", "type ", "enter text ", "fill ", "search for ",
            "select ", "tap ", "play the ", "open the ", "watch the ", "like ", "subscribe"
        )
        if any(cmd_lower.startswith(t) for t in browser_action_triggers):
            print(f"Classified as BROWSER_ACTION, command: '{command}'")
            return "BROWSER_ACTION", {"command": command}

    # Searching the web
    if any(kw in cmd_lower for kw in ("search", "google", "look up", "find")):
        # Remove the trigger word and take the rest as query
        for kw in ("search", "google", "look up", "find"):
            if kw in cmd_lower:
                idx = cmd_lower.find(kw)
                query = command[idx+len(kw):].strip()
                if query:
                    print(f"Classified as SEARCH_WEB, query: {query}")
                    return "SEARCH_WEB", {"query": query}
                break
    # Default to question
    print(f"Classified as ASK_QUESTION")
    return "ASK_QUESTION", {"question": command}


def _hud_set_state(state):
    """Safely emit HUD state if available."""
    if hud is not None:
        hud.state_changed.emit(state)


def _hud_set_transcript(text):
    """Safely emit HUD transcript if available."""
    if hud is not None:
        hud.transcript_updated.emit(text)


def _hud_set_response(text):
    """Safely emit HUD response if available."""
    if hud is not None:
        hud.response_updated.emit(text)


def process_command(command):
    """Process the recognized command."""
    global last_interaction_time, in_conversation, is_listening

    print(f"Processing command: '{command}'")

    # Update HUD to THINKING while we classify + act
    _hud_set_state("THINKING")

    try:
        intent, entities = classify_command(command)

        print(f"Classified intent: {intent}, entities: {entities}")


        # ---------------- WHATSAPP CALL ----------------
        if intent == "WHATSAPP_CALL":
            contact = entities.get("contact", "").strip()
            call_type = entities.get("call_type", "voice")
            if not contact:
                speak("Who would you like to call on WhatsApp?")
            else:
                speak(f"Calling {contact} on WhatsApp")
                _hud_set_state("THINKING")
                success = whatsapp_call(contact, call_type)
                if not success:
                    speak(f"Sorry, I couldn't place the call to {contact}")

        # ---------------- WHATSAPP END CALL / HANG UP ----------------
        elif intent == "WHATSAPP_END_CALL":
            speak("Ending call")
            whatsapp_hang_up()

        # ---------------- WHATSAPP SEND MESSAGE ----------------
        elif intent == "WHATSAPP_SEND_MESSAGE":
            contact = entities.get("contact", "").strip()
            message = entities.get("message", "").strip()
            if not contact:
                speak("Who should I send the message to?")
            elif not message:
                speak("What is the message?")
            else:
                speak(f"Sending message to {contact}")
                _hud_set_state("THINKING")
                success = whatsapp_send_message(contact, message)
                if not success:
                    speak(f"Sorry, I couldn't send the message to {contact}")

        # ---------------- WHATSAPP OPEN CHAT ----------------
        elif intent == "WHATSAPP_OPEN_CHAT":
            contact = entities.get("contact", "").strip()
            if not contact:
                speak("Which chat would you like to open?")
            else:
                speak(f"Opening chat with {contact}")
                whatsapp_search_and_open_chat(contact)

        # ---------------- WHATSAPP ACTIONS / SHORTCUTS ----------------
        elif intent == "WHATSAPP_ACTION":
            action = entities.get("action", "")
            action_names = {
                "next_chat": "Next chat",
                "previous_chat": "Previous chat",
                "new_chat": "New chat",
                "new_group": "New group",
                "mute_chat": "Muting chat",
                "archive_chat": "Archiving chat",
                "unread_chat": "Marking as unread",
                "delete_chat": "Deleting chat",
                "pin_chat": "Pinning chat",
                "settings": "Opening WhatsApp settings",
                "profile": "Opening WhatsApp profile",
                "show_shortcuts": "Showing WhatsApp shortcuts",
            }
            spoken_text = action_names.get(action, "Executing action")
            speak(spoken_text)
            whatsapp_action(action)

        # ---------------- OPEN APP ----------------
        elif intent == "OPEN_APP":
            app_name = entities.get("app", "").lower()

            print(f"Opening app: {app_name}")

            speak(f"Opening {app_name}")
            open_application(app_name)
        elif intent == "CLOSE_CURRENT":

            speak("Closing")
            time.sleep(0.15)

            close_current_window()

        # ---------------- CREATE DIRECTORY ----------------
        elif intent == "CREATE_DIR":
            name = entities.get("name", "").strip()
            enter_after = entities.get("enter_after", False)

            if not name:
                speak("What should I name the folder?")
            else:
                new_path = create_directory(name)

                if new_path:
                    speak(f"Created folder {name}")

                    if enter_after:
                        enter_directory("it")
                        speak(f"Now inside {name}")

                else:
                    speak(f"Sorry, I couldn't create the folder {name}")

        # ---------------- ENTER DIRECTORY ----------------
        elif intent == "ENTER_DIR":
            name = entities.get("name", "it")
            result = enter_directory(name)

            if result:
                speak(f"Entered {os.path.basename(result) or result}")
            else:
                speak("I couldn't find that folder")

        # ---------------- CREATE FILE ----------------
        elif intent == "CREATE_FILE":
            name = entities.get("name", "").strip()

            if not name:
                speak("What should I name the file?")
            else:
                new_path = create_file_in_dir(name)

                if new_path:
                    speak(f"Created file {name}")
                else:
                    speak(f"Sorry, I couldn't create the file {name}")

        # ---------------- NAVIGATE TO SITE (in-page control) ----------------
        elif intent == "NAVIGATE_SITE":
            site = entities.get("site", "").strip()

            if not site:
                speak("Which site do you want to open?")
            elif not PLAYWRIGHT_AVAILABLE:
                speak(
                    "In-page browser control needs the playwright package. "
                    "I'll just open your browser instead."
                )
                open_application("brave")
            else:
                speak(f"Opening {site}")
                if not navigate_to_site(site):
                    speak(f"Sorry, I couldn't open {site}")

        # ---------------- CLICK FIRST VIDEO ----------------
        elif intent == "CLICK_FIRST_VIDEO":
            if not PLAYWRIGHT_AVAILABLE or get_browser_page() is None:
                speak("I don't have an active browser session to click in.")
            elif click_first_video():
                speak("Playing the first video")
            else:
                speak("I couldn't find a video to click.")

        # ---------------- CLICK FIRST RESULT ----------------
        elif intent == "CLICK_FIRST_RESULT":
            if not PLAYWRIGHT_AVAILABLE or get_browser_page() is None:
                speak("I don't have an active browser session to click in.")
            elif click_first_result():
                speak("Opening the first result")
            else:
                speak("I couldn't find a result to click.")

        # ---------------- DIRECT BROWSER ACTIONS ----------------
        elif intent == "BROWSER_DIRECT":
            action = entities.get("action", "")
            if not PLAYWRIGHT_AVAILABLE or get_browser_page() is None:
                speak("I don't have an active browser window to control.")
            elif action == "scroll_down":
                browser_scroll("down")
            elif action == "scroll_up":
                browser_scroll("up")
            elif action == "go_back":
                browser_go_back()
            elif action == "go_forward":
                browser_go_forward()
            elif action == "refresh":
                browser_refresh()
            elif action == "toggle_play":
                if browser_toggle_play():
                    speak("Done")
                else:
                    speak("I couldn't toggle the video")
            elif action == "toggle_fullscreen":
                browser_toggle_fullscreen()
            elif action == "toggle_mute":
                browser_toggle_mute()
            elif action == "close_tab":
                browser_close_tab()
            elif action == "new_tab":
                browser_new_tab()

        # ---------------- LLM-POWERED BROWSER ACTION ----------------
        elif intent == "BROWSER_ACTION":
            if not PLAYWRIGHT_AVAILABLE or get_browser_page() is None:
                speak("I don't have an active browser window to control.")
            else:
                _hud_set_state("THINKING")
                success = handle_browser_action(command)
                if not success:
                    speak("I couldn't perform that action on this page.")

        # ---------------- WEB SEARCH ----------------
        elif intent == "SEARCH_WEB":
            query = entities.get("query", "")

            if query:
                print(f"Searching for: {query}")
                speak(f"Searching for {query}")
                webbrowser.open(
                    f"https://www.google.com/search?q={query}"
                )

            else:
                speak("I didn't catch a search query.")

        # ---------------- QUESTION ----------------
        elif intent == "ASK_QUESTION":
            question = entities.get("question", command).strip()

            print(f"Question received: '{question}'")

            greetings = [
                "hello",
                "hi",
                "hey",
                "good morning",
                "good afternoon",
                "good evening"
            ]

            if any(greet in question.lower() for greet in greetings):
                speak("Hello! How can I help you today?")

            else:
                speak("Let me think about that...")
                _hud_set_state("THINKING")

                try:
                    prompt = (
                        "Answer the following question concisely "
                        "and factually. Use minimum words:\n"
                        f"{question}"
                    )

                    response = ollama.generate(
                        model=OLLAMA_MODEL,
                        prompt=prompt,
                        options={
                            "num_predict": 128,
                            "temperature": 0.2
                        }
                    )

                    answer = response.get("response", "").strip()

                    print(f"Ollama answer: '{answer}'")

                    if answer:
                        _hud_set_state("SPEAKING")
                        _hud_set_response(answer)
                        speak(answer)

                    else:
                        speak("Sorry, I couldn't find an answer.")

                except Exception as e:
                    print(f"Ollama error: {e}")
                    _hud_set_state("ERROR")
                    speak(
                        "Sorry, I encountered an error "
                        "while thinking."
                    )

        # ---------------- EXIT ----------------
        elif intent == "EXIT":
            speak("Goodbye!")
            _hud_set_state("IDLE")

            # Wait for Goodbye to finish
            try:
                tts_queue.join()
            except Exception:
                pass

            is_listening = False
            in_conversation = False
            return

        else:
            speak("I'm not sure how to help with that.")

        last_interaction_time = time.time()

    except Exception as e:

        print(f"Error processing command: {e}")
        _hud_set_state("ERROR")
        speak("Sorry, I encountered an error.")

        in_conversation = True


def listen_for_speech(timeout=None):
    """
    Listen for speech energy > SILENCE_THRESHOLD, record until silence,
    return audio bytes. If timeout is not None, return None if no speech
    detected within timeout seconds.
    """
    global is_listening
    start_time = time.time()
    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BUFFER_SIZE,
                           dtype='int16', channels=1) as stream:
        while is_listening:
            # Check timeout
            if timeout is not None and (time.time() - start_time) > timeout:
                return None
            try:
                data = stream.read(BUFFER_SIZE)[0]
                audio_np = np.frombuffer(data, dtype=np.int16)
                # Calculate RMS energy
                energy = math.sqrt(np.mean(audio_np.astype(float)**2))
                if energy > SILENCE_THRESHOLD:
                    # Speech detected, start recording
                    frames = []
                    silent_chunks = 0
                    max_silent_chunks = int(SAMPLE_RATE / BUFFER_SIZE * SILENCE_DURATION)
                    max_total_chunks = int(SAMPLE_RATE / BUFFER_SIZE * MAX_RECORD_SECONDS)
                    frames.append(data)
                    while True:
                        data = stream.read(BUFFER_SIZE)[0]
                        frames.append(data)
                        audio_np = np.frombuffer(data, dtype=np.int16)
                        energy = math.sqrt(np.mean(audio_np.astype(float)**2))
                        if energy < SILENCE_THRESHOLD:
                            silent_chunks += 1
                        else:
                            silent_chunks = 0
                        if silent_chunks > max_silent_chunks:
                            break
                        if len(frames) > max_total_chunks:
                            print("Hit MAX_RECORD_SECONDS, stopping recording.")
                            break
                    return b''.join(frames)
            except Exception as e:
                print(f"Error in listen_for_speech: {e}")
                time.sleep(0.1)
    return None


def listen_for_wake_and_process():
    """
    Main voice loop.

    IDLE:
        Only responds when "Karen" is detected.

    CONVERSATION:
        After waking, subsequent speech is treated as commands
        until the conversation times out.
    """

    global is_listening, in_conversation, last_interaction_time

    print("Listening for wake triggers: KAREN / 'Daddy is home'")

    while is_listening:

        # ---------------------------------------------------------
        # 1. LISTEN
        # ---------------------------------------------------------

        audio_data = listen_for_speech(
            timeout=None if not in_conversation else CONVERSATION_TIMEOUT
        )

        if not is_listening:
            break

        # ---------------------------------------------------------
        # 2. CONVERSATION TIMEOUT
        # ---------------------------------------------------------

        if audio_data is None:

            if in_conversation:
                print("Conversation timed out.")
                in_conversation = False
                _hud_set_state("IDLE")
                print("Back to wake-word detection.")

            continue

        # ---------------------------------------------------------
        # 3. TRANSCRIBE
        # ---------------------------------------------------------

        text = transcribe_audio(audio_data)

        if not text:
            continue

        print(f"Whisper heard: '{text}'")

        # ---------------------------------------------------------
        # 4. CONVERSATION MODE
        # ---------------------------------------------------------

        if in_conversation:

            print("Conversation mode: processing command.")
            _hud_set_transcript(text)

            process_command(text)

            continue

        # ---------------------------------------------------------
        # 5. IDLE MODE -> CHECK FOR WAKE WORDS & PHRASES
        # ---------------------------------------------------------

        detected, command, matched_word, score, greeting = detect_wake_word(text)

        if not detected:

            print(
                f"No wake word detected "
                f"(best similarity={score:.2f})"
            )

            # IMPORTANT:
            # Do NOT process random speech while idle.
            continue

        # ---------------------------------------------------------
        # 6. WAKE TRIGGERED (Karen, "Daddy is home")
        # ---------------------------------------------------------

        print(
            f"WAKE TRIGGERED "
            f"(heard='{matched_word}', score={score:.2f})"
        )

        last_interaction_time = time.time()
        in_conversation = True

        # Show the HUD in LISTENING state
        _hud_set_state("LISTENING")

        # ---------------------------------------------------------
        # 7. WAKE WORD + COMMAND IN SAME SENTENCE
        # ---------------------------------------------------------

        if command:

            print(f"Command after wake word: '{command}'")
            _hud_set_transcript(command)

            process_command(command)

        # ---------------------------------------------------------
        # 8. WAKE WORD / PHRASE ONLY (Speak custom greeting)
        # ---------------------------------------------------------

        else:

            print(f"Wake word only. Greeting: '{greeting}'")

            speak(greeting)

        # Small delay prevents accidental immediate re-trigger
        time.sleep(0.2)


def _start_hud_thread():
    """
    Launch the PySide6 / Qt event loop on a daemon thread.

    QApplication.exec() blocks, so it must live in its own thread.
    The HUD widget communicates with the voice loop entirely through
    Qt Signals which are thread-safe.
    """
    global hud

    from PySide6.QtWidgets import QApplication  # local import keeps it optional

    qt_app = QApplication.instance()
    if qt_app is None:
        qt_app = QApplication(sys.argv)

    hud = KarenHUD()

    print("HUD overlay ready (Qt event loop running in background)")

    qt_app.exec()


def main():
    """Main function to start the voice assistant."""
    global is_listening

    print("Starting Voice Assistant...")

    # Launch HUD overlay (Qt event loop) in its own daemon thread
    hud_thread = threading.Thread(target=_start_hud_thread, daemon=True, name="HUD-Qt")
    hud_thread.start()
    time.sleep(0.5)  # Give Qt a moment to initialise the window

    # Discover all installed applications (Start Menu + Registry)
    _scan_installed_apps()

    # Initialize TTS
    initialize_tts()
    # Load Whisper model
    load_whisper_model()
    # Initial greeting
    speak("Voice assistant is ready. Say Karen when you need me.")

    # Start system tray in a separate thread
    tray_thread = threading.Thread(target=setup_tray, daemon=True)
    tray_thread.start()

    # Start wake word detection and command processing
    is_listening = True
    listen_for_wake_and_process()

    # If we ever exit the listening loop (should not happen unless stopped)
    is_listening = False


if __name__ == "__main__":
    # Check if Ollama is running
    try:
        ollama.list()
    except Exception as e:
        print("Ollama server may not be running. Please start it with 'ollama serve'")
        print("And make sure you have a model installed (e.g., 'ollama pull llama3')")
        # We'll continue anyway and handle errors when they occur

    main()