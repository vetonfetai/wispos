"""Shared helpers for the Wisp OS apps (Settings, Welcome, App Store)."""
import configparser
import os
import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Gdk  # noqa: E402

HOME = os.path.expanduser("~")
CONF_DIR = os.path.join(HOME, ".config", "wisp")
SETTINGS_FILE = os.path.join(CONF_DIR, "settings.ini")
ROOT_HELPER = "/usr/libexec/wisp/wisp-root"
WALLPAPER_DIR = "/usr/share/backgrounds/wisp"
IS_LIVE = os.path.exists("/etc/wisp-live")

DEFAULTS = {
    "appearance": {
        "theme": "dark",
        "wallpaper": WALLPAPER_DIR + "/night.png",
        "effects": "true",
        "text_scale": "1.0",
        "accent": "blue",
        "cursor_size": "24",
    },
    "display": {"output": "", "mode": "", "night_light": "false", "night_warmth": "50"},
    "desktop": {"panel_position": "bottom", "clock_24h": "true", "clock_widget": "true", "weather": "true"},
    "notifications": {"dnd": "false", "position": "top-right"},
    "mouse": {"speed": "0", "natural": "false", "tap": "true", "left_handed": "false", "dwt": "true"},
    "keyboard": {"layout": "us", "layout2": "", "repeat_delay": "500", "repeat_rate": "30"},
    "power": {"blank_minutes": "15"},
    "updates": {"notify": "true"},
    "welcome": {"show": "true"},
}

# Accent colours: name -> (colour, label). Pastel tones so dark text stays readable on them.
ACCENTS = {
    "blue": ("#8ab4ff", "Blue"),
    "lavender": ("#b48cff", "Lavender"),
    "pink": ("#ff8ac0", "Pink"),
    "orange": ("#ffb08a", "Orange"),
    "yellow": ("#f2d06b", "Yellow"),
    "green": ("#8fd99b", "Green"),
    "teal": ("#6fd6c8", "Teal"),
}


def accent_color(cp=None):
    cp = cp or load_settings()
    return ACCENTS.get(cp["appearance"].get("accent", "blue"), ACCENTS["blue"])[0]


def lighten(hex_color, amount=0.18):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"

CSS = """
.wisp-title { font-size: 22px; font-weight: 800; }
.wisp-subtitle { color: alpha(currentColor, 0.65); }
.wisp-section { font-weight: 700; font-size: 13px; margin-top: 8px; }
.wisp-card {
    background-color: alpha(currentColor, 0.05);
    border: 1px solid alpha(currentColor, 0.09);
    border-radius: 14px;
    padding: 14px;
}
.wisp-card:hover { background-color: alpha(currentColor, 0.08); }
.wisp-accent, button.wisp-accent {
    background-image: none;
    background-color: #8ab4ff;
    color: #0d0f14;
    border: none;
    border-radius: 10px;
    font-weight: 700;
    padding: 6px 16px;
}
button.wisp-accent:hover { background-color: #a3c4ff; }
button.wisp-accent:disabled { background-color: alpha(#8ab4ff, 0.35); color: alpha(#0d0f14, 0.6); }
button.wisp-danger { color: #ff7a90; }
button.wisp-pill { border-radius: 10px; padding: 6px 14px; }
.wisp-muted { color: alpha(currentColor, 0.6); }
.wisp-big-icon { -gtk-icon-style: regular; }
list.wisp-list, list.wisp-list row { background-color: transparent; }
list.wisp-list row { border-radius: 10px; padding: 6px 8px; }
.wisp-thumb { border-radius: 10px; border: 2px solid transparent; padding: 2px; }
.wisp-thumb-selected { border-color: #8ab4ff; }
.wisp-sidebar { background-color: alpha(currentColor, 0.03); }
.wisp-stat { font-size: 20px; font-weight: 800; }
.wisp-heading { margin-top: 14px; opacity: 0.8; }
scrolledwindow.wisp-card { padding: 4px; }
scrolledwindow.wisp-card treeview, scrolledwindow.wisp-card treeview.view { background-color: transparent; }
treeview.view header button { border: none; background: none; font-weight: 700; padding: 6px 10px; }
levelbar trough { border-radius: 6px; min-height: 8px; }
levelbar block.filled { background-color: #8ab4ff; border-radius: 6px; }
"""


def apply_css():
    accent = accent_color()
    css = CSS.replace("#a3c4ff", lighten(accent)).replace("#8ab4ff", accent)
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


# ---------- settings ----------

def load_settings():
    cp = configparser.ConfigParser()
    cp.read_dict(DEFAULTS)
    cp.read(SETTINGS_FILE)
    return cp


def save_settings(cp):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        cp.write(f)
    os.replace(tmp, SETTINGS_FILE)


# ---------- memory ----------

def read_meminfo():
    """/proc/meminfo in bytes."""
    m = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            m[k] = int(v.split()[0]) * 1024
    return m


def memory_used(m):
    """Memory in use, counted the same way as the free command: disk cache doesn't count."""
    cache = m.get("Cached", 0) + m.get("SReclaimable", 0)
    return max(m["MemTotal"] - m.get("MemFree", 0) - m.get("Buffers", 0) - cache, 0)


# ---------- commands ----------

def run(cmd, timeout=20):
    """Run a command, return (exit code, combined output). Never raises."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def spawn(cmd):
    """Start a program detached from us."""
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def have(program):
    return shutil.which(program) is not None


def in_thread(work, done=None):
    """Run work() in a thread, then done(result) on the GTK main loop."""
    def target():
        result = work()
        if done:
            GLib.idle_add(lambda: (done(result), False)[1])
    threading.Thread(target=target, daemon=True).start()


def root_cmd(*args):
    return ["doas", "-n", ROOT_HELPER, *args]


class TaskDialog(Gtk.Dialog):
    """Runs a root task and shows its live output. on_done(ok) is called at the end."""

    def __init__(self, parent, title, args, on_done=None):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.set_default_size(560, 340)
        self.on_done = on_done
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        head = Gtk.Box(spacing=10)
        self.spinner = Gtk.Spinner()
        self.spinner.start()
        self.label = Gtk.Label(label=title + "…", xalign=0)
        self.label.get_style_context().add_class("wisp-section")
        head.pack_start(self.spinner, False, False, 0)
        head.pack_start(self.label, True, True, 0)
        box.pack_start(head, False, False, 0)
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR)
        sw.add(self.view)
        box.pack_start(sw, True, True, 0)
        self.close_btn = self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.close_btn.set_sensitive(False)
        self.connect("response", lambda *_: self.destroy())
        self.show_all()
        threading.Thread(target=self._work, args=(args,), daemon=True).start()

    def _append(self, text):
        buf = self.view.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        self.view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
        return False

    def _work(self, args):
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                GLib.idle_add(self._append, line)
            ok = p.wait() == 0
        except OSError as e:
            GLib.idle_add(self._append, str(e))
            ok = False
        GLib.idle_add(self._finish, ok)

    def _finish(self, ok):
        self.spinner.stop()
        self.label.set_text("Done" if ok else "Something went wrong - see the details below")
        self.close_btn.set_sensitive(True)
        if self.on_done:
            self.on_done(ok)
        return False


def message(parent, title, text, error=False):
    d = Gtk.MessageDialog(transient_for=parent, modal=True,
                          message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                          buttons=Gtk.ButtonsType.OK, text=title)
    d.format_secondary_text(text)
    d.run()
    d.destroy()


def icon(name, size=48):
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.DIALOG)
    img.set_pixel_size(size)
    return img


def label(text, cls=None, xalign=0, wrap=False):
    lbl = Gtk.Label(label=text, xalign=xalign)
    if wrap:
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(60)
    if cls:
        for c in cls.split():
            lbl.get_style_context().add_class(c)
    return lbl


def button(text, cls=None, on_click=None):
    b = Gtk.Button(label=text)
    if cls:
        for c in cls.split():
            b.get_style_context().add_class(c)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return b
