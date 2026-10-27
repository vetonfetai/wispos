"""Applies Wisp settings to the running desktop. Used at login and by Settings."""
import filecmp
import os
import re
import shutil
import subprocess
import time

from wisplib import (CONF_DIR, HOME, IS_LIVE, WALLPAPER_DIR, accent_color, have, load_settings,
                     run, spawn)

THEMES = {
    "dark": {"gtk": "adw-gtk3-dark", "icons": "Papirus-Dark", "openbox": "Wisp", "prefer_dark": 1},
    "light": {"gtk": "adw-gtk3", "icons": "Papirus", "openbox": "Wisp-Light", "prefer_dark": 0},
}
CONFIG = os.path.join(HOME, ".config")
XSETTINGS_CONF = os.path.join(CONFIG, "xsettingsd", "xsettingsd.conf")
PCMANFM_DESKTOP = os.path.join(CONFIG, "pcmanfm", "default", "desktop-items-0.conf")
TINT2RC = os.path.join(CONFIG, "tint2", "tint2rc")
CONKY_CONF = os.path.join(CONFIG, "conky", "wisp.conf")
DUNSTRC = os.path.join(CONFIG, "dunst", "dunstrc")
PANEL_HEIGHT = 44
SKEL_VERSION = "/usr/share/wisp/skel-version"
# Desktop configs that Wisp owns. After an update they're refreshed from /etc/skel;
# the user's choices live in settings.ini and are applied on top at every login.
MANAGED_CONFIGS = [
    ".xinitrc", ".config/openbox/rc.xml", ".config/openbox/menu.xml", ".config/openbox/autostart",
    ".config/openbox/environment", ".config/tint2/tint2rc", ".config/conky/wisp.conf",
    ".config/dunst/dunstrc", ".config/picom/picom.conf", ".config/rofi/config.rasi",
]


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _set_keys(path, values, fmt="{k} = {v}", sep=r"\s*=\s*", create=None):
    """Replace 'key = value' lines in a config file; add missing keys to the end."""
    text = _read(path)
    if text is None:
        if create is None:
            return
        text = create
    for k, v in values.items():
        line = fmt.format(k=k, v=v)
        pat = re.compile(rf"^[ \t]*{re.escape(k)}{sep}.*$", re.M)
        if pat.search(text):
            text = pat.sub(lambda _m: line, text, count=1)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    _write(path, text)


def apply_theme(cp, live=True):
    t = THEMES.get(cp["appearance"]["theme"], THEMES["dark"])
    dark = t["prefer_dark"] == 1
    scale = float(cp["appearance"].get("text_scale", "1.0") or 1.0)
    cursor = int(cp["appearance"].get("cursor_size", "24") or 24)
    accent = accent_color(cp)
    dpi = int(96 * scale)
    gtk_settings = f"""[Settings]
gtk-theme-name={t['gtk']}
gtk-icon-theme-name={t['icons']}
gtk-font-name=Inter 10
gtk-cursor-theme-name=Adwaita
gtk-cursor-theme-size={cursor}
gtk-application-prefer-dark-theme={t['prefer_dark']}
gtk-decoration-layout=menu:minimize,maximize,close
gtk-xft-antialias=1
gtk-xft-hinting=1
gtk-xft-hintstyle=hintslight
gtk-xft-rgba=rgb
gtk-xft-dpi={dpi * 1024}
gtk-enable-event-sounds=0
gtk-enable-input-feedback-sounds=0
"""
    _write(os.path.join(CONFIG, "gtk-3.0", "settings.ini"), gtk_settings)
    # GTK4 apps (e.g. the advanced sound mixer) read their own file
    _write(os.path.join(CONFIG, "gtk-4.0", "settings.ini"),
           "\n".join(l for l in gtk_settings.splitlines() if "xft-dpi" not in l) + "\n")
    accent_css = (f"@define-color accent_bg_color {accent};\n@define-color accent_color {accent};\n"
                  f"@define-color accent_fg_color #0d0f14;\n")
    for v in ("gtk-3.0", "gtk-4.0"):
        _write(os.path.join(CONFIG, v, "gtk.css"), "/* Written by Wisp Settings (accent colour) */\n" + accent_css)
    _write(XSETTINGS_CONF, f"""Net/ThemeName "{t['gtk']}"
Net/IconThemeName "{t['icons']}"
Net/EnableEventSounds 0
Net/EnableInputFeedbackSounds 0
Gtk/FontName "Inter 10"
Gtk/CursorThemeName "Adwaita"
Gtk/CursorThemeSize {cursor}
Gtk/DecorationLayout "menu:minimize,maximize,close"
Xft/Antialias 1
Xft/Hinting 1
Xft/HintStyle "hintslight"
Xft/RGBA "rgb"
Xft/DPI {dpi * 1024}
""")
    p = subprocess.Popen(["xrdb", "-merge"], stdin=subprocess.PIPE, text=True)
    p.communicate(f"Xft.dpi: {dpi}\nXcursor.size: {cursor}\nXcursor.theme: Adwaita\n")
    rc = os.path.join(CONFIG, "openbox", "rc.xml")
    xml = _read(rc)
    if xml:
        new = re.sub(r"(<theme>\s*<name>)[^<]*(</name>)", rf"\g<1>{t['openbox']}\g<2>", xml, count=1)
        if new != xml:
            _write(rc, new)
    text = _read(CONKY_CONF)
    if text:
        colors = {"default_color": "e6e9f2" if dark else "1d2130", "color1": "b8bdd0" if dark else "4a5068",
                  "color2": accent[1:] if dark else "3d6fe0", "default_shade_color": "00000066" if dark else "ffffff55"}
        for k, v in colors.items():
            text = re.sub(rf"(\b{k} = ')[0-9a-fA-F]+(')", rf"\g<1>{v}\g<2>", text)
        _write(CONKY_CONF, text)
    theme_apps(dark, accent)
    _set_keys(DUNSTRC, {"highlight": f'"{accent}"'})
    if live:
        run(["pkill", "-HUP", "-x", "xsettingsd"], timeout=5)
        run(["openbox", "--reconfigure"], timeout=5)
        restart_conky(cp)


def theme_apps(dark, accent):
    """Colours for apps that draw their own backgrounds."""
    bg = "#0d0f14" if dark else "#f4f5f8"
    _set_keys(os.path.join(CONFIG, "gpicview", "gpicview.conf"), {"bg": bg, "bg_full": "#000000"},
              fmt="{k}={v}", sep="=", create="[General]\n")
    calc = {
        "display_bkg_color": "#151821" if dark else "#ffffff",
        "display_result_color": "#e6e9f2" if dark else "#1d2130",
        "display_stack_color": "#a3abc2" if dark else "#4a5068",
        "display_module_active_color": accent if dark else "#3d6fe0",
        "display_module_inactive_color": "#4a5068" if dark else "#a3abc2",
        "display_result_font": "Inter Bold 26",
        "display_stack_font": "Inter 11",
        "display_module_font": "Inter Bold 8",
        "button_width": "52",
        "button_height": "34",
    }
    _set_keys(os.path.join(CONFIG, "galculator", "galculator.conf"),
              {k: (v if v.isdigit() else f'"{v}"') for k, v in calc.items()},
              fmt="{k}={v}", sep="=", create="[general]\n")


def write_desktop_conf(cp):
    wp = cp["appearance"]["wallpaper"]
    if not os.path.exists(wp):
        wp = WALLPAPER_DIR + "/night.png"
    _write(PCMANFM_DESKTOP, f"""[*]
wallpaper_mode=crop
wallpaper_common=1
wallpaper={wp}
desktop_bg=#0d0f14
desktop_fg=#ffffff
desktop_shadow=#000000
desktop_font=Inter 10
show_wm_menu=1
sort=mtime;ascending;
show_documents=0
show_trash=1
show_mounts=1
""")


def apply_wallpaper(cp, live=True):
    write_desktop_conf(cp)
    if live:
        spawn(["pcmanfm", f"--set-wallpaper={cp['appearance']['wallpaper']}", "--wallpaper-mode=crop"])


def apply_effects(cp):
    on = cp["appearance"].getboolean("effects")
    running = run(["pgrep", "-x", "picom"], timeout=5)[0] == 0
    if on and not running:
        spawn(["picom", "--config", os.path.join(CONFIG, "picom", "picom.conf")])
    elif not on and running:
        run(["pkill", "-x", "picom"], timeout=5)


# ---------- desktop: taskbar, clock widget ----------

def apply_desktop(cp, live=True):
    d = cp["desktop"]
    top = d.get("panel_position") == "top"
    h24 = d.getboolean("clock_24h")
    _set_keys(TINT2RC, {
        "panel_position": f"{'top' if top else 'bottom'} center horizontal",
        "time1_format": "%H:%M" if h24 else "%I:%M %p",
    })
    text = _read(CONKY_CONF)
    if text:
        text = re.sub(r"(gap_y = )\d+", rf"\g<1>{48 + (PANEL_HEIGHT if top else 0)}", text)
        text = re.sub(r"\$\{time %[HIl]:%M\}", "${time %H:%M}" if h24 else "${time %I:%M}", text)
        weather = "${voffset 6}${alignr}${font Inter:size=12}${color2}${execi 900 wisp-weather}${color}${font}"
        text = re.sub(r"\n[^\n]*wisp-weather[^\n]*", "", text)
        if d.getboolean("weather"):
            text = text.replace("\n]]", "\n" + weather + "\n]]", 1)
        _write(CONKY_CONF, text)
    apply_notifications(cp, live=False)
    if live:
        run(["pkill", "-x", "tint2"], timeout=5)
        time.sleep(0.3)
        spawn(["tint2"])
        restart_conky(cp)
        restart_dunst(cp)


def restart_conky(cp):
    run(["pkill", "-x", "conky"], timeout=5)
    if cp["desktop"].getboolean("clock_widget") and have("conky"):
        time.sleep(0.2)
        spawn(["conky", "-d", "-c", CONKY_CONF])


# ---------- notifications ----------

def apply_notifications(cp, live=True):
    pos = cp["notifications"].get("position", "top-right")
    top_panel = cp["desktop"].get("panel_position") == "top"
    origin = {"top-right": "top-right", "top-center": "top-center", "bottom-right": "bottom-right"}.get(pos, "top-right")
    edge = 16 + (PANEL_HEIGHT if (origin.startswith("top") and top_panel) or
                 (origin.startswith("bottom") and not top_panel) else 0)
    _set_keys(DUNSTRC, {"origin": origin, "offset": f"(16, {edge})"})
    if live:
        restart_dunst(cp)


def restart_dunst(cp):
    run(["pkill", "-x", "dunst"], timeout=5)
    time.sleep(0.3)
    spawn(["dunst"])
    if cp["notifications"].getboolean("dnd"):
        time.sleep(0.5)
        run(["dunstctl", "set-paused", "true"], timeout=5)


def apply_dnd(cp):
    run(["dunstctl", "set-paused", "true" if cp["notifications"].getboolean("dnd") else "false"], timeout=5)


# ---------- input ----------

def apply_keyboard(cp):
    k = cp["keyboard"]
    layouts = ",".join(x for x in (k.get("layout") or "us", k.get("layout2", "")) if x)
    cmd = ["setxkbmap", "-layout", layouts, "-option", ""]
    if "," in layouts:
        cmd += ["-option", "grp:alt_shift_toggle"]
    run(cmd, timeout=5)
    run(["xset", "r", "rate", k.get("repeat_delay", "500"), k.get("repeat_rate", "30")], timeout=5)


def pointer_devices():
    out = run(["xinput", "list"], timeout=5)[1] if have("xinput") else ""
    return re.findall(r"id=(\d+)\s+\[slave\s+pointer", out)


def apply_mouse(cp):
    m = cp["mouse"]
    want = {
        "libinput Accel Speed": [m.get("speed", "0")],
        "libinput Natural Scrolling Enabled": ["1" if m.getboolean("natural") else "0"],
        "libinput Tapping Enabled": ["1" if m.getboolean("tap") else "0"],
        "libinput Left Handed Enabled": ["1" if m.getboolean("left_handed") else "0"],
        "libinput Disable While Typing Enabled": ["1" if m.getboolean("dwt") else "0"],
    }
    for dev in pointer_devices():
        props = run(["xinput", "list-props", dev], timeout=5)[1]
        for prop, val in want.items():
            if re.search(rf"^\s*{re.escape(prop)} \(\d+\):", props, re.M):
                run(["xinput", "set-prop", dev, prop, *val], timeout=5)


# ---------- display ----------

def connected_outputs():
    return re.findall(r"^(\S+) connected", run(["xrandr", "--query"], timeout=10)[1], re.M)


def apply_display(cp):
    out, mode = cp["display"]["output"], cp["display"]["mode"]
    if out and mode:
        run(["xrandr", "--output", out, "--mode", mode], timeout=10)
    apply_night_light(cp)


def apply_night_light(cp):
    on = cp["display"].getboolean("night_light")
    w = max(0, min(100, int(cp["display"].get("night_warmth", "50") or 50))) / 100
    gamma = f"1:{1 - 0.22 * w:.2f}:{1 - 0.5 * w:.2f}" if on else "1:1:1"
    for o in connected_outputs():
        run(["xrandr", "--output", o, "--gamma", gamma], timeout=10)


def apply_power(cp):
    mins = int(cp["power"]["blank_minutes"] or 0)
    if mins <= 0:
        run(["xset", "s", "off", "-dpms"], timeout=5)
    else:
        s = str(mins * 60)
        run(["xset", "s", s, s, "+dpms", "dpms", s, s, s], timeout=5)


def make_desktop_shortcuts():
    flag = os.path.join(CONF_DIR, "desktop-shortcuts-done")
    if os.path.exists(flag):
        return
    desk = os.path.join(HOME, "Desktop")
    os.makedirs(desk, exist_ok=True)
    apps = ["firefox", "pcmanfm", "wisp-store", "wisp-settings"]
    if IS_LIVE:
        apps.append("wisp-install")
    for a in apps:
        src = f"/usr/share/applications/{a}.desktop"
        if os.path.exists(src):
            dst = os.path.join(desk, f"{a}.desktop")
            shutil.copy(src, dst)
            os.chmod(dst, 0o755)
    os.makedirs(CONF_DIR, exist_ok=True)
    open(flag, "w").close()


def migrate_user_config():
    """Bring this user's desktop configs up to date after a Wisp update.
    Returns the new version if anything was refreshed, else None."""
    new = (_read(SKEL_VERSION) or "").strip()
    mine_path = os.path.join(CONF_DIR, "skel-version")
    mine = (_read(mine_path) or "").strip()
    if not new or new == mine:
        return None
    backup = os.path.join(CONF_DIR, "backup-before-update")
    shutil.rmtree(backup, ignore_errors=True)
    for rel in MANAGED_CONFIGS:
        src, dst = os.path.join("/etc/skel", rel), os.path.join(HOME, rel)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            if filecmp.cmp(src, dst, shallow=False):
                continue
            os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
            shutil.copy2(dst, os.path.join(backup, rel))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    _write(mine_path, new + "\n")
    return new if mine else None


def start_session():
    updated = migrate_user_config()
    cp = load_settings()
    apply_theme(cp, live=False)
    apply_desktop(cp, live=False)
    spawn(["xsettingsd", "-c", XSETTINGS_CONF])
    apply_keyboard(cp)
    apply_display(cp)
    apply_power(cp)
    apply_mouse(cp)
    make_desktop_shortcuts()
    write_desktop_conf(cp)
    spawn(["pcmanfm", "--desktop"])
    if os.path.exists("/usr/libexec/pipewire-launcher"):
        spawn(["/usr/libexec/pipewire-launcher"])
    apply_effects(cp)
    spawn(["tint2"])
    spawn(["dunst"])
    if cp["desktop"].getboolean("clock_widget") and have("conky"):
        spawn(["conky", "-d", "-c", CONKY_CONF])
    time.sleep(2)
    spawn(["nm-applet"])
    if cp["notifications"].getboolean("dnd"):
        apply_dnd(cp)
    if cp["welcome"].getboolean("show"):
        spawn(["wisp-welcome"])
    if updated:
        spawn(["notify-send", "-a", "Wisp OS", "-i", "wisp", "Wisp OS was updated",
               f"You're now on version {updated}. Your settings were kept."])
    if cp["updates"].getboolean("notify") and not IS_LIVE:
        spawn(["wisp-update-check"])


if __name__ == "__main__":
    start_session()
