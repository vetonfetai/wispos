#!/usr/bin/python3
"""Wisp Settings: network, display, sound, look, desktop, input, time, apps, power, storage, updates."""
import configparser
import glob
import os
import re
import shutil
import sys
import time

sys.path.insert(0, "/usr/lib/wisp")
import wispsession as ws  # noqa: E402
from wisplib import (ACCENTS, IS_LIVE, WALLPAPER_DIR, TaskDialog, apply_css, button, have,  # noqa: E402
                     icon, in_thread, label, load_settings, memory_used, message, read_meminfo, root_cmd, run,
                     save_settings, spawn, Gtk, GLib)
from gi.repository import GdkPixbuf, Pango  # noqa: E402

LAYOUTS = [
    ("us", "English (US)"), ("gb", "English (UK)"), ("al", "Albanian"), ("de", "German"),
    ("fr", "French"), ("it", "Italian"), ("es", "Spanish"), ("pt", "Portuguese"),
    ("br", "Portuguese (Brazil)"), ("nl", "Dutch"), ("se", "Swedish"), ("no", "Norwegian"),
    ("dk", "Danish"), ("fi", "Finnish"), ("pl", "Polish"), ("cz", "Czech"), ("hu", "Hungarian"),
    ("ro", "Romanian"), ("rs", "Serbian"), ("mk", "Macedonian"), ("hr", "Croatian"), ("gr", "Greek"),
    ("tr", "Turkish"), ("ru", "Russian"), ("ua", "Ukrainian"), ("ch", "Swiss"), ("be", "Belgian"),
    ("ara", "Arabic"), ("il", "Hebrew"), ("in", "Indian"), ("jp", "Japanese"), ("kr", "Korean"),
    ("cn", "Chinese"),
]
# Default apps: (key, label, icon, mime types)
APP_KINDS = [
    ("web", "Web browser", "internet-web-browser",
     ["x-scheme-handler/http", "x-scheme-handler/https", "text/html", "application/xhtml+xml"]),
    ("files", "Files", "system-file-manager", ["inode/directory"]),
    ("text", "Text editor", "accessories-text-editor", ["text/plain", "text/markdown", "application/x-shellscript"]),
    ("images", "Images", "image-x-generic", ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"]),
    ("music", "Music", "audio-x-generic", ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4", "audio/aac"]),
    ("video", "Video", "video-x-generic", ["video/mp4", "video/x-matroska", "video/webm", "video/x-msvideo", "video/quicktime"]),
    ("pdf", "PDF documents", "application-pdf", ["application/pdf"]),
    ("mail", "Email", "internet-mail", ["x-scheme-handler/mailto"]),
]
MIMEAPPS = os.path.expanduser("~/.config/mimeapps.list")
NMCLI_SPLIT = re.compile(r"(?<!\\):")


def nm_fields(line):
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in NMCLI_SPLIT.split(line)]


def page_box(title=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_border_width(28)
    if title:
        box.pack_start(label(title, "wisp-title"), False, False, 0)
    return box


def section(box, text):
    box.pack_start(label(text, "wisp-section wisp-heading"), False, False, 0)


def row(title, subtitle, widget):
    r = Gtk.Box(spacing=12)
    r.get_style_context().add_class("wisp-card")
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
    texts.pack_start(label(title, "wisp-section"), False, False, 0)
    if subtitle:
        texts.pack_start(label(subtitle, "wisp-muted", wrap=True), False, False, 0)
    r.pack_start(texts, True, True, 0)
    if widget is not None:
        widget.set_valign(Gtk.Align.CENTER)
        r.pack_end(widget, False, False, 0)
    return r


def combo(options, active, on_change):
    c = Gtk.ComboBoxText()
    for value, text in options:
        c.append(value, text)
    if not c.set_active_id(active):
        c.set_active(0)
    c.connect("changed", lambda w: on_change(w.get_active_id()))
    return c


def switch(active, on_change):
    s = Gtk.Switch(active=active)
    s.connect("state-set", lambda _w, st: (on_change(st), False)[1])
    return s


def slider(lo, hi, step, value, width=240):
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    s.set_size_request(width, -1)
    s.set_draw_value(False)
    s.set_value(value)
    return s


class Debounce:
    """Call fn(value) once a slider has stopped moving for a moment."""

    def __init__(self, fn, ms=250):
        self.fn, self.ms, self.src = fn, ms, None

    def __call__(self, value):
        if self.src:
            GLib.source_remove(self.src)
        self.src = GLib.timeout_add(self.ms, self._fire, value)

    def _fire(self, value):
        self.src = None
        self.fn(value)
        return False


def human(n):
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def wp_status():
    """Parse 'wpctl status' into sinks, sources and app streams."""
    res = {"sinks": [], "sources": [], "streams": []}
    code, out = run(["wpctl", "status"], timeout=10)
    if code != 0:
        return None
    section_name, in_audio = None, False
    for raw in out.splitlines():
        s = re.sub(r"[│├└─]", " ", raw).strip()
        if not s:
            continue
        if s in ("Audio", "Video", "Settings"):
            in_audio, section_name = s == "Audio", None
            continue
        if not in_audio:
            continue
        m = re.match(r"(Devices|Sinks|Sources|Filters|Streams):", s)
        if m:
            section_name = m.group(1).lower()
            continue
        if section_name not in res:
            continue
        m = re.match(r"(\*)?\s*(\d+)\.\s+(.*?)\s*(?:\[vol:\s*([\d.]+)(\s+MUTED)?\])?$", s)
        if not m or ">" in m.group(3) or "<" in m.group(3):
            continue
        res[section_name].append({"default": bool(m.group(1)), "id": m.group(2), "name": m.group(3).strip(),
                                  "vol": float(m.group(4)) if m.group(4) else None, "muted": bool(m.group(5))})
    return res


def desktop_entries():
    """All visible apps: desktop id -> (name, icon, mime types)."""
    apps = {}
    for path in sorted(glob.glob("/usr/share/applications/*.desktop")):
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            cp.read(path, encoding="utf-8")
            e = cp["Desktop Entry"]
        except (configparser.Error, KeyError, UnicodeDecodeError):
            continue
        if e.get("NoDisplay", "false").lower() == "true" or e.get("Type") != "Application":
            continue
        mimes = [m for m in e.get("MimeType", "").split(";") if m]
        apps[os.path.basename(path)] = (e.get("Name", ""), e.get("Icon", "application-x-executable"), mimes)
    return apps


class Settings(Gtk.Window):
    def __init__(self, start_page=None):
        super().__init__(title="Settings")
        self.set_default_size(940, 660)
        self.set_icon_name("preferences-system")
        self.cp = load_settings()

        hb = Gtk.HeaderBar(show_close_button=True, title="Settings")
        self.set_titlebar(hb)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sidebar = Gtk.ListBox()
        sidebar.get_style_context().add_class("wisp-list")
        sidebar.set_size_request(220, -1)
        side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        side_scroll.add(sidebar)
        side_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_wrap.get_style_context().add_class("wisp-sidebar")
        side_wrap.set_border_width(8)
        side_wrap.pack_start(side_scroll, True, True, 0)

        pages = [
            ("wifi", "Wi-Fi & Network", "network-wireless", self.page_wifi),
            ("display", "Display", "video-display", self.page_display),
            ("sound", "Sound", "audio-speakers", self.page_sound),
            ("appearance", "Appearance", "preferences-desktop-wallpaper", self.page_appearance),
            ("desktop", "Desktop & Taskbar", "user-desktop", self.page_desktop),
            ("notifications", "Notifications", "preferences-system-notifications", self.page_notifications),
            ("mouse", "Mouse & Touchpad", "input-mouse", self.page_mouse),
            ("keyboard", "Keyboard", "preferences-desktop-keyboard", self.page_keyboard),
            ("datetime", "Date & Time", "preferences-system-time", self.page_datetime),
            ("apps", "Default Apps", "preferences-desktop-default-applications", self.page_apps),
            ("power", "Power", "battery", self.page_power),
            ("storage", "Storage", "drive-harddisk", self.page_storage),
            ("updates", "Updates", "system-software-update", self.page_updates),
            ("about", "About", "help-about", self.page_about),
        ]
        self.rows, self.builders, self.built = {}, {}, set()
        for key, title, icon_name, build in pages:
            r = Gtk.ListBoxRow()
            b = Gtk.Box(spacing=12)
            b.set_border_width(4)
            b.pack_start(icon(icon_name, 22), False, False, 0)
            b.pack_start(label(title), False, False, 0)
            r.add(b)
            r.key = key
            sidebar.add(r)
            self.rows[key] = r
            self.builders[key] = build
            holder = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            self.stack.add_named(holder, key)
        sidebar.connect("row-selected", lambda lb, r: r and self.show_page(r.key))

        main = Gtk.Box()
        main.pack_start(side_wrap, False, False, 0)
        main.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        main.pack_start(self.stack, True, True, 0)
        self.add(main)
        self.show_all()
        sidebar.select_row(self.rows.get(start_page) or self.rows["wifi"])

    def show_page(self, key):
        # Pages are built the first time they're opened, so Settings starts fast
        if key not in self.built:
            self.built.add(key)
            holder = self.stack.get_child_by_name(key)
            holder.add(self.builders[key]())
            holder.show_all()
        self.stack.set_visible_child_name(key)

    def save(self):
        save_settings(self.cp)

    def setting(self, section_name, key, value, apply=None):
        self.cp[section_name][key] = value
        self.save()
        if apply:
            apply(self.cp)

    # ---------------- Wi-Fi ----------------
    def page_wifi(self):
        box = page_box()
        head = Gtk.Box(spacing=10)
        head.pack_start(label("Wi-Fi & Network", "wisp-title"), True, True, 0)
        self.wifi_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.wifi_switch.connect("state-set", self.on_wifi_toggle)
        head.pack_end(self.wifi_switch, False, False, 0)
        box.pack_start(head, False, False, 0)
        self.net_status = label("Checking connection…", "wisp-muted", wrap=True)
        self.net_status.set_selectable(True)
        box.pack_start(self.net_status, False, False, 0)

        bar = Gtk.Box(spacing=8)
        bar.pack_start(label("Networks nearby", "wisp-section wisp-heading"), True, True, 0)
        self.wifi_spinner = Gtk.Spinner()
        bar.pack_end(button("Advanced…", "wisp-pill", lambda: spawn(["nm-connection-editor"])), False, False, 0)
        bar.pack_end(button("Hidden network…", "wisp-pill", self.wifi_hidden), False, False, 0)
        bar.pack_end(button("Refresh", "wisp-pill", lambda: self.refresh_wifi(rescan=True)), False, False, 0)
        bar.pack_end(self.wifi_spinner, False, False, 0)
        box.pack_start(bar, False, False, 0)

        self.wifi_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.wifi_list.get_style_context().add_class("wisp-list")
        box.pack_start(self.wifi_list, False, False, 0)

        section(box, "More")
        self.airplane = Gtk.Switch()
        self.airplane.connect("state-set", self.on_airplane)
        box.pack_start(row("Airplane mode", "Turns off Wi-Fi and mobile data", self.airplane), False, False, 0)
        GLib.idle_add(lambda: (self.refresh_wifi(), False)[1])
        return box

    def on_wifi_toggle(self, sw, state):
        if getattr(self, "_wifi_updating", False):
            return False
        in_thread(lambda: run(["nmcli", "radio", "wifi", "on" if state else "off"]),
                  lambda _: GLib.timeout_add(1500, lambda: (self.refresh_wifi(rescan=state), False)[1]))
        return False

    def on_airplane(self, sw, state):
        if getattr(self, "_wifi_updating", False):
            return False
        in_thread(lambda: run(["nmcli", "radio", "all", "off" if state else "on"]),
                  lambda _: GLib.timeout_add(1500, lambda: (self.refresh_wifi(rescan=not state), False)[1]))
        return False

    def refresh_wifi(self, rescan=False):
        self.wifi_spinner.start()

        def work():
            radio = run(["nmcli", "radio", "wifi"])[1].strip()
            all_radio = run(["nmcli", "-t", "-f", "WIFI,WWAN", "radio", "all"])[1].strip()
            general = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])[1]
            if not any(nm_fields(line)[1:2] == ["wifi"] for line in general.splitlines()):
                radio = "no-adapter"
            ips = {}
            for line in general.splitlines():
                f = nm_fields(line)
                if len(f) >= 4 and f[2] == "connected" and f[1] in ("ethernet", "wifi"):
                    ip = run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", f[0]])[1].strip().split("|")[0]
                    ips[f[0]] = ip.split("/")[0]
            nets = []
            if radio == "enabled":
                code, out = run(["nmcli", "-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                                 "device", "wifi", "list", "--rescan", "yes" if rescan else "auto"], timeout=30)
                seen = set()
                for line in out.splitlines():
                    f = nm_fields(line)
                    if len(f) < 4 or not f[1] or f[1] in seen:
                        continue
                    seen.add(f[1])
                    nets.append({"active": f[0] == "*", "ssid": f[1],
                                 "signal": int(f[2] or 0), "secure": f[3] not in ("", "--")})
                nets.sort(key=lambda n: (not n["active"], -n["signal"]))
            known = set()
            for line in run(["nmcli", "-t", "-e", "yes", "-f", "NAME", "connection", "show"])[1].splitlines():
                known.add(nm_fields(line)[0])
            airplane = all_radio.startswith("disabled") and "enabled" not in all_radio
            return radio, general, nets, known, ips, airplane

        in_thread(work, self.show_wifi)

    def show_wifi(self, result):
        radio, general, nets, known, ips, airplane = result
        self.wifi_spinner.stop()
        self._wifi_updating = True
        self.wifi_switch.set_active(radio == "enabled")
        self.airplane.set_active(airplane)
        self._wifi_updating = False
        status = []
        for line in general.splitlines():
            f = nm_fields(line)
            if len(f) >= 4 and f[2] == "connected" and f[1] in ("ethernet", "wifi"):
                ip = f" · IP {ips[f[0]]}" if ips.get(f[0]) else ""
                status.append(f"Connected via {'Wi-Fi' if f[1] == 'wifi' else 'cable'}: {f[3]}{ip}")
        self.net_status.set_text("\n".join(status) or "Not connected")
        for child in self.wifi_list.get_children():
            self.wifi_list.remove(child)
        self.wifi_switch.set_sensitive(radio != "no-adapter")
        if radio == "no-adapter":
            self.wifi_list.add(label("No Wi-Fi adapter found. Plug in a cable or a USB Wi-Fi adapter.", "wisp-muted"))
        elif radio != "enabled":
            self.wifi_list.add(label("Wi-Fi is off.", "wisp-muted"))
        elif not nets:
            self.wifi_list.add(label("No networks found. Try Refresh.", "wisp-muted"))
        for n in nets:
            r = Gtk.Box(spacing=12)
            r.set_border_width(6)
            strength = "excellent" if n["signal"] > 75 else "good" if n["signal"] > 50 else "ok" if n["signal"] > 25 else "weak"
            r.pack_start(icon(f"network-wireless-signal-{strength}-symbolic", 20), False, False, 0)
            name = label(n["ssid"])
            name.set_ellipsize(Pango.EllipsizeMode.END)
            r.pack_start(name, True, True, 0)
            if n["secure"]:
                r.pack_start(icon("changes-prevent-symbolic", 14), False, False, 0)
            if n["active"]:
                r.pack_end(button("Disconnect", "wisp-pill", lambda s=n["ssid"]: self.wifi_disconnect(s)), False, False, 0)
                r.pack_end(label("Connected", "wisp-muted"), False, False, 0)
            else:
                r.pack_end(button("Connect", "wisp-accent", lambda net=n: self.wifi_connect(net, net["ssid"] in known)), False, False, 0)
                if n["ssid"] in known:
                    r.pack_end(button("Forget", "wisp-pill", lambda s=n["ssid"]: self.wifi_forget(s)), False, False, 0)
            self.wifi_list.add(r)
        self.wifi_list.show_all()

    def ask_password(self, title, ask_name=False):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("Connect", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("wisp-accent")
        d.set_default_response(Gtk.ResponseType.OK)
        area = d.get_content_area()
        area.set_border_width(18)
        area.set_spacing(10)
        name_entry = None
        if ask_name:
            area.add(label("Network name"))
            name_entry = Gtk.Entry(activates_default=True)
            area.add(name_entry)
            area.add(label("Password (leave empty for open networks)"))
        else:
            area.add(label(title.replace("Connect to ", "Password for ")))
        entry = Gtk.Entry(visibility=False, activates_default=True)
        area.add(entry)
        show = Gtk.CheckButton(label="Show password")
        show.connect("toggled", lambda c: entry.set_visibility(c.get_active()))
        area.add(show)
        d.show_all()
        resp = d.run()
        result = (name_entry.get_text().strip() if name_entry else None, entry.get_text())
        d.destroy()
        return result if resp == Gtk.ResponseType.OK else None

    def wifi_connect(self, net, known):
        password = None
        if net["secure"] and not known:
            ans = self.ask_password(f"Connect to {net['ssid']}")
            if ans is None:
                return
            password = ans[1]
        if known:
            cmd = ["nmcli", "connection", "up", "id", net["ssid"]]
        else:
            cmd = ["nmcli", "device", "wifi", "connect", net["ssid"]]
            if password:
                cmd += ["password", password]
        self.run_nm(cmd)

    def wifi_hidden(self):
        ans = self.ask_password("Connect to a hidden network", ask_name=True)
        if not ans or not ans[0]:
            return
        cmd = ["nmcli", "device", "wifi", "connect", ans[0], "hidden", "yes"]
        if ans[1]:
            cmd += ["password", ans[1]]
        self.run_nm(cmd)

    def run_nm(self, cmd):
        self.wifi_spinner.start()

        def done(res):
            code, out = res
            if code != 0:
                message(self, "Could not connect", out.strip() or "Check the password and try again.", error=True)
            self.refresh_wifi()
        in_thread(lambda: run(cmd, timeout=60), done)

    def wifi_disconnect(self, ssid):
        in_thread(lambda: run(["nmcli", "connection", "down", "id", ssid]), lambda _: self.refresh_wifi())

    def wifi_forget(self, ssid):
        in_thread(lambda: run(["nmcli", "connection", "delete", "id", ssid]), lambda _: self.refresh_wifi())

    # ---------------- Display ----------------
    def page_display(self):
        box = page_box("Display")
        self.outputs = {}
        current_out, current_mode = None, None
        out = None
        for line in run(["xrandr", "--query"])[1].splitlines():
            m = re.match(r"^(\S+) connected", line)
            if m:
                out = m.group(1)
                self.outputs[out] = []
                continue
            if re.match(r"^\S", line):
                out = None
                continue
            m = re.match(r"^\s+(\d+x\d+)\S*\s+(.*)", line)
            if out and m:
                if m.group(1) not in self.outputs[out]:
                    self.outputs[out].append(m.group(1))
                if "*" in m.group(2):
                    current_out, current_mode = out, m.group(1)

        self.out_combo = Gtk.ComboBoxText()
        for o in self.outputs:
            self.out_combo.append(o, o)
        self.mode_combo = Gtk.ComboBoxText()
        self.out_combo.connect("changed", self.fill_modes)
        if current_out:
            self.out_combo.set_active_id(current_out)
            self.mode_combo.set_active_id(current_mode)
        elif self.outputs:
            self.out_combo.set_active(0)
        if len(self.outputs) > 1:
            box.pack_start(row("Screen", "Which screen to change", self.out_combo), False, False, 0)
        apply_btn = button("Apply", "wisp-accent", self.apply_resolution)
        res = Gtk.Box(spacing=8)
        res.pack_start(self.mode_combo, False, False, 0)
        res.pack_start(apply_btn, False, False, 0)
        box.pack_start(row("Resolution", "Sharper text at the screen's native (highest) resolution", res), False, False, 0)

        scale = combo([("1.0", "100%"), ("1.1", "110%"), ("1.25", "125%"), ("1.5", "150%"), ("1.75", "175%"), ("2.0", "200%")],
                      self.cp["appearance"]["text_scale"], lambda v: self.setting("appearance", "text_scale", v, ws.apply_theme))
        box.pack_start(row("Text size", "Makes text and apps bigger. Some apps need a restart.", scale), False, False, 0)

        if glob.glob("/sys/class/backlight/*"):
            bright = slider(5, 100, 5, 80)
            code, out = run(["brightnessctl", "-m"])
            try:
                bright.set_value(float(out.split(",")[3].rstrip("%")))
            except (IndexError, ValueError):
                pass
            bright.connect("value-changed", lambda s: run(["brightnessctl", "-q", "set", f"{int(s.get_value())}%"]))
            box.pack_start(row("Brightness", None, bright), False, False, 0)

        section(box, "Night light")
        d = self.cp["display"]
        box.pack_start(row("Night light", "Warmer colours that are easier on the eyes in the evening",
                           switch(d.getboolean("night_light"),
                                  lambda st: self.setting("display", "night_light", "true" if st else "false", ws.apply_night_light))),
                       False, False, 0)
        warm = slider(10, 100, 5, int(d.get("night_warmth", "50")))
        apply_warm = Debounce(lambda v: self.setting("display", "night_warmth", str(int(v)), ws.apply_night_light))
        warm.connect("value-changed", lambda s: apply_warm(s.get_value()))
        box.pack_start(row("Warmth", "How strong night light is", warm), False, False, 0)
        return box

    def fill_modes(self, combo_box):
        self.mode_combo.remove_all()
        for m in self.outputs.get(combo_box.get_active_id(), []):
            self.mode_combo.append(m, m)
        self.mode_combo.set_active(0)

    def apply_resolution(self):
        out, mode = self.out_combo.get_active_id(), self.mode_combo.get_active_id()
        if not out or not mode:
            return
        old = self.cp["display"]["mode"]
        code, msg = run(["xrandr", "--output", out, "--mode", mode])
        if code != 0:
            message(self, "Could not change resolution", msg, error=True)
            return
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text="Keep this resolution?")
        d.format_secondary_text("It will go back automatically in 15 seconds.")
        d.add_button("Revert", Gtk.ResponseType.CANCEL)
        d.add_button("Keep", Gtk.ResponseType.OK)
        GLib.timeout_add_seconds(15, lambda: (d.response(Gtk.ResponseType.CANCEL), False)[1])
        resp = d.run()
        d.destroy()
        if resp == Gtk.ResponseType.OK:
            self.cp["display"]["output"], self.cp["display"]["mode"] = out, mode
            self.save()
        else:
            run(["xrandr", "--output", out, "--mode", old] if old else ["xrandr", "--output", out, "--auto"])
        ws.apply_night_light(self.cp)

    # ---------------- Sound ----------------
    def page_sound(self):
        box = page_box()
        head = Gtk.Box(spacing=8)
        head.pack_start(label("Sound", "wisp-title"), True, True, 0)
        head.pack_end(button("Advanced mixer", "wisp-pill", lambda: spawn(["pavucontrol"])), False, False, 0)
        head.pack_end(button("Refresh", "wisp-pill", self.refresh_sound), False, False, 0)
        box.pack_start(head, False, False, 0)
        self.sound_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.pack_start(self.sound_box, False, False, 0)
        GLib.idle_add(lambda: (self.refresh_sound(), False)[1])
        return box

    def refresh_sound(self):
        in_thread(wp_status, self.show_sound)

    def volume_slider(self, node_id, vol, muted=None):
        s = slider(0, 100, 1, round((vol or 0) * 100), width=260)
        s.set_draw_value(True)
        s.set_value_pos(Gtk.PositionType.RIGHT)
        s.connect("format-value", lambda _s, v: f"{int(v)}%")
        s.connect("value-changed", lambda w: run(["wpctl", "set-volume", node_id, f"{int(w.get_value())}%"]))
        return s

    def show_sound(self, st):
        for c in self.sound_box.get_children():
            self.sound_box.remove(c)
        if st is None or not st["sinks"]:
            self.sound_box.pack_start(label("No sound device found. If you use HDMI or USB audio, "
                                            "plug it in and press Refresh.", "wisp-muted", wrap=True), False, False, 0)
            self.sound_box.show_all()
            return
        section(self.sound_box, "Output")
        default_sink = next((s for s in st["sinks"] if s["default"]), st["sinks"][0])
        if len(st["sinks"]) > 1:
            out = combo([(s["id"], s["name"]) for s in st["sinks"]], default_sink["id"],
                        lambda v: (run(["wpctl", "set-default", v]), GLib.timeout_add(400, lambda: (self.refresh_sound(), False)[1])))
            self.sound_box.pack_start(row("Play sound through", None, out), False, False, 0)
        vol = Gtk.Box(spacing=12)
        vol.pack_start(self.volume_slider("@DEFAULT_AUDIO_SINK@", default_sink["vol"]), False, False, 0)
        vol.pack_start(switch(not default_sink["muted"], lambda on: run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0" if on else "1"])),
                       False, False, 0)
        self.sound_box.pack_start(row("Volume", default_sink["name"], vol), False, False, 0)

        if st["sources"]:
            section(self.sound_box, "Input")
            default_src = next((s for s in st["sources"] if s["default"]), st["sources"][0])
            if len(st["sources"]) > 1:
                src = combo([(s["id"], s["name"]) for s in st["sources"]], default_src["id"],
                            lambda v: (run(["wpctl", "set-default", v]), GLib.timeout_add(400, lambda: (self.refresh_sound(), False)[1])))
                self.sound_box.pack_start(row("Microphone", None, src), False, False, 0)
            mic = Gtk.Box(spacing=12)
            mic.pack_start(self.volume_slider("@DEFAULT_AUDIO_SOURCE@", default_src["vol"]), False, False, 0)
            mic.pack_start(switch(not default_src["muted"], lambda on: run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0" if on else "1"])),
                           False, False, 0)
            self.sound_box.pack_start(row("Microphone volume", default_src["name"], mic), False, False, 0)

        section(self.sound_box, "Apps")
        if not st["streams"]:
            self.sound_box.pack_start(label("No apps are playing sound right now.", "wisp-muted"), False, False, 0)
        for stream in st["streams"]:
            code, out = run(["wpctl", "get-volume", stream["id"]])
            m = re.search(r"Volume:\s*([\d.]+)", out)
            self.sound_box.pack_start(row(stream["name"], None, self.volume_slider(stream["id"], float(m.group(1)) if m else 1.0)),
                                      False, False, 0)
        self.sound_box.show_all()

    # ---------------- Appearance ----------------
    def page_appearance(self):
        box = page_box("Appearance")
        themes = Gtk.Box(spacing=12, homogeneous=True)
        for key, name, bg, fg in (("dark", "Dark", "#151821", "#e6e9f2"), ("light", "Light", "#f4f5f8", "#1d2130")):
            b = Gtk.Button()
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            preview = Gtk.DrawingArea()
            preview.set_size_request(200, 90)
            preview.connect("draw", self.draw_theme_preview, bg, fg)
            inner.pack_start(preview, False, False, 0)
            inner.pack_start(label(name, "wisp-section", xalign=0.5), False, False, 0)
            b.add(inner)
            b.get_style_context().add_class("wisp-card")
            b.connect("clicked", lambda _b, k=key: self.set_theme(k))
            themes.pack_start(b, True, True, 0)
        section(box, "Style")
        box.pack_start(themes, False, False, 0)

        self.accent_box = Gtk.Box(spacing=10)
        self.fill_accents()
        box.pack_start(row("Accent colour", "Buttons, switches and highlights. Open apps update after a restart.", self.accent_box),
                       False, False, 0)

        section(box, "Wallpaper")
        self.wall_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                     column_spacing=10, row_spacing=10, homogeneous=True)
        box.pack_start(self.wall_flow, False, False, 0)
        self.fill_wallpapers()
        box.pack_start(button("Choose a picture…", "wisp-pill", self.pick_wallpaper), False, False, 0)

        section(box, "More")
        cursor = combo([("24", "Normal"), ("32", "Large"), ("48", "Extra large")], self.cp["appearance"].get("cursor_size", "24"),
                       lambda v: self.setting("appearance", "cursor_size", v, ws.apply_theme))
        box.pack_start(row("Pointer size", "Takes effect fully after you log in again", cursor), False, False, 0)
        effects = switch(self.cp["appearance"].getboolean("effects"),
                         lambda st: self.setting("appearance", "effects", "true" if st else "false", ws.apply_effects))
        box.pack_start(row("Effects", "Rounded corners, shadows and fades. Turn off on very old computers.", effects), False, False, 0)
        return box

    def fill_accents(self):
        for c in self.accent_box.get_children():
            self.accent_box.remove(c)
        current = self.cp["appearance"].get("accent", "blue")
        for key, (color, name) in ACCENTS.items():
            b = Gtk.Button()
            b.set_tooltip_text(name)
            b.set_relief(Gtk.ReliefStyle.NONE)
            dot = Gtk.DrawingArea()
            dot.set_size_request(28, 28)
            dot.connect("draw", self.draw_dot, color, key == current)
            b.add(dot)
            b.connect("clicked", lambda _b, k=key: self.set_accent(k))
            self.accent_box.pack_start(b, False, False, 0)
        self.accent_box.show_all()

    @staticmethod
    def draw_dot(area, cr, color, selected):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        cr.set_source_rgb(r, g, b)
        cr.arc(w / 2, h / 2, min(w, h) / 2 - (4 if selected else 2), 0, 6.2832)
        cr.fill()
        if selected:
            fg = area.get_style_context().get_color(Gtk.StateFlags.NORMAL)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
            cr.set_line_width(2)
            cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 6.2832)
            cr.stroke()

    def set_accent(self, key):
        self.setting("appearance", "accent", key, ws.apply_theme)
        apply_css()
        self.fill_accents()

    @staticmethod
    def draw_theme_preview(area, cr, bg, fg):
        w, h = area.get_allocated_width(), area.get_allocated_height()

        def rgb(hx):
            return tuple(int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))

        def rounded(x, y, rw, rh, r):
            cr.new_sub_path()
            cr.arc(x + rw - r, y + r, r, -1.5708, 0)
            cr.arc(x + rw - r, y + rh - r, r, 0, 1.5708)
            cr.arc(x + r, y + rh - r, r, 1.5708, 3.1416)
            cr.arc(x + r, y + r, r, 3.1416, 4.7124)
            cr.close_path()

        cr.set_source_rgb(0.05, 0.06, 0.08)
        rounded(0, 0, w, h, 10)
        cr.fill()
        cr.set_source_rgb(*rgb(bg))
        rounded(w * 0.12, h * 0.15, w * 0.76, h * 0.7, 8)
        cr.fill()
        cr.set_source_rgb(*rgb(fg))
        cr.rectangle(w * 0.2, h * 0.32, w * 0.35, 6)
        cr.fill()
        cr.set_source_rgba(*rgb(fg), 0.5)
        cr.rectangle(w * 0.2, h * 0.48, w * 0.55, 5)
        cr.rectangle(w * 0.2, h * 0.6, w * 0.45, 5)
        cr.fill()
        cr.set_source_rgb(*rgb(ACCENTS.get(load_settings()["appearance"].get("accent", "blue"), ACCENTS["blue"])[0]))
        rounded(w * 0.62, h * 0.66, w * 0.18, h * 0.12, 4)
        cr.fill()

    def set_theme(self, key):
        self.cp["appearance"]["theme"] = key
        if key == "light" and self.cp["appearance"]["wallpaper"].endswith("/night.png"):
            self.cp["appearance"]["wallpaper"] = WALLPAPER_DIR + "/dawn.png"
            ws.apply_wallpaper(self.cp)
        elif key == "dark" and self.cp["appearance"]["wallpaper"].endswith("/dawn.png"):
            self.cp["appearance"]["wallpaper"] = WALLPAPER_DIR + "/night.png"
            ws.apply_wallpaper(self.cp)
        self.save()
        ws.apply_theme(self.cp)
        self.fill_wallpapers()

    def fill_wallpapers(self):
        for c in self.wall_flow.get_children():
            self.wall_flow.remove(c)
        current = self.cp["appearance"]["wallpaper"]
        files = sorted(glob.glob(WALLPAPER_DIR + "/*.png") + glob.glob(WALLPAPER_DIR + "/*.jpg"))
        files = [f for f in files if not os.path.islink(f)]
        if current not in files and os.path.exists(current) and not os.path.islink(current):
            files.append(current)
        for path in files:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 176, 99, False)
            except GLib.Error:
                continue
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_pixbuf(pb))
            b.get_style_context().add_class("wisp-thumb")
            if path == current:
                b.get_style_context().add_class("wisp-thumb-selected")
            b.set_tooltip_text(os.path.basename(path).rsplit(".", 1)[0].title())
            b.connect("clicked", lambda _b, p=path: self.set_wallpaper(p))
            self.wall_flow.add(b)
        self.wall_flow.show_all()

    def set_wallpaper(self, path):
        self.cp["appearance"]["wallpaper"] = path
        self.save()
        ws.apply_wallpaper(self.cp)
        self.fill_wallpapers()

    def pick_wallpaper(self):
        d = Gtk.FileChooserDialog(title="Choose a picture", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Set as wallpaper", Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("Pictures")
        for mt in ("image/png", "image/jpeg", "image/webp"):
            f.add_mime_type(mt)
        d.add_filter(f)
        d.set_current_folder(os.path.expanduser("~/Pictures"))
        if d.run() == Gtk.ResponseType.OK:
            self.set_wallpaper(d.get_filename())
        d.destroy()

    # ---------------- Desktop & taskbar ----------------
    def page_desktop(self):
        box = page_box("Desktop & Taskbar")
        d = self.cp["desktop"]
        section(box, "Taskbar")
        pos = combo([("bottom", "Bottom"), ("top", "Top")], d.get("panel_position", "bottom"),
                    lambda v: self.setting("desktop", "panel_position", v, ws.apply_desktop))
        box.pack_start(row("Position", "Where the taskbar sits on the screen", pos), False, False, 0)
        box.pack_start(row("24-hour clock", "Show 18:30 instead of 6:30 PM",
                           switch(d.getboolean("clock_24h"),
                                  lambda st: self.setting("desktop", "clock_24h", "true" if st else "false", ws.apply_desktop))),
                       False, False, 0)
        section(box, "Desktop")
        box.pack_start(row("Clock on the desktop", "The big clock in the top corner",
                           switch(d.getboolean("clock_widget"),
                                  lambda st: self.setting("desktop", "clock_widget", "true" if st else "false", ws.restart_conky))),
                       False, False, 0)
        box.pack_start(row("Weather", "Shown under the desktop clock. Uses your internet connection to find your town.",
                           switch(d.getboolean("weather"),
                                  lambda st: self.setting("desktop", "weather", "true" if st else "false", ws.apply_desktop))),
                       False, False, 0)
        box.pack_start(row("Desktop icons", "Add or remove shortcuts by dragging apps into the Desktop folder",
                           button("Open Desktop folder", "wisp-pill", lambda: spawn(["pcmanfm", os.path.expanduser("~/Desktop")]))),
                       False, False, 0)
        section(box, "Shortcuts")
        grid = Gtk.Grid(column_spacing=24, row_spacing=8)
        grid.get_style_context().add_class("wisp-card")
        keys = [("Super + Space", "Find and open apps"), ("Super + Enter", "Terminal"), ("Super + E", "Files"),
                ("Super + B", "Web browser"), ("Super + I", "Settings"), ("Super + Left / Right", "Snap window to half the screen"),
                ("Super + Up", "Maximise"), ("Super + D", "App launcher"), ("Super + Tab / Alt + Tab", "Switch windows"),
                ("Super + L", "Lock screen"), ("Ctrl + Alt + Delete", "Task Manager"), ("Print", "Screenshot")]
        for i, (k, v) in enumerate(keys):
            grid.attach(label(k), 0, i, 1, 1)
            grid.attach(label(v, "wisp-muted"), 1, i, 1, 1)
        box.pack_start(grid, False, False, 0)
        return box

    # ---------------- Notifications ----------------
    def page_notifications(self):
        box = page_box("Notifications")
        n = self.cp["notifications"]
        box.pack_start(row("Do not disturb", "Hide pop-ups. Urgent alerts like low battery still show.",
                           switch(n.getboolean("dnd"),
                                  lambda st: self.setting("notifications", "dnd", "true" if st else "false", ws.apply_dnd))),
                       False, False, 0)
        pos = combo([("top-right", "Top right"), ("top-center", "Top centre"), ("bottom-right", "Bottom right")],
                    n.get("position", "top-right"), lambda v: self.setting("notifications", "position", v, ws.apply_notifications))
        box.pack_start(row("Position", "Where pop-ups appear", pos), False, False, 0)
        btns = Gtk.Box(spacing=8)
        btns.pack_start(button("Send a test", "wisp-pill", lambda: spawn(
            ["notify-send", "-a", "Settings", "-i", "preferences-system-notifications", "Hello from Wisp",
             "This is what notifications look like."])), False, False, 0)
        btns.pack_start(button("Clear history", "wisp-pill", lambda: run(["dunstctl", "history-clear"])), False, False, 0)
        box.pack_start(row("Try it", None, btns), False, False, 0)
        return box

    # ---------------- Mouse & touchpad ----------------
    def page_mouse(self):
        box = page_box("Mouse & Touchpad")
        m = self.cp["mouse"]
        if not have("xinput"):
            box.pack_start(label("Mouse settings need the xinput tool.", "wisp-muted"), False, False, 0)
            return box
        speed = slider(-1, 1, 0.1, float(m.get("speed", "0") or 0))
        speed.add_mark(0, Gtk.PositionType.BOTTOM, None)
        apply_speed = Debounce(lambda v: self.setting("mouse", "speed", f"{v:.1f}", ws.apply_mouse))
        speed.connect("value-changed", lambda s: apply_speed(s.get_value()))
        box.pack_start(row("Pointer speed", "Slow on the left, fast on the right", speed), False, False, 0)

        def flag(key, title, sub):
            box.pack_start(row(title, sub, switch(m.getboolean(key), lambda st: self.setting(
                "mouse", key, "true" if st else "false", ws.apply_mouse))), False, False, 0)

        flag("natural", "Natural scrolling", "Content moves with your fingers, like on a phone")
        flag("left_handed", "Left-handed", "Swap the left and right buttons")
        section(box, "Touchpad")
        flag("tap", "Tap to click", "Tap the touchpad instead of pressing it")
        flag("dwt", "Turn off while typing", "Stops accidental clicks from your palm")
        return box

    # ---------------- Keyboard ----------------
    def page_keyboard(self):
        box = page_box("Keyboard")
        k = self.cp["keyboard"]
        box.pack_start(row("Keyboard layout", None,
                           combo(LAYOUTS, k["layout"], lambda v: self.setting("keyboard", "layout", v, ws.apply_keyboard))),
                       False, False, 0)
        box.pack_start(row("Second layout", "Switch between the two with Alt + Shift",
                           combo([("", "None")] + LAYOUTS, k.get("layout2", ""),
                                 lambda v: self.setting("keyboard", "layout2", v or "", ws.apply_keyboard))),
                       False, False, 0)
        section(box, "Typing")
        delay = slider(150, 1000, 50, int(k.get("repeat_delay", "500")))
        apply_delay = Debounce(lambda v: self.setting("keyboard", "repeat_delay", str(int(v)), ws.apply_keyboard))
        delay.connect("value-changed", lambda s: apply_delay(s.get_value()))
        box.pack_start(row("Repeat delay", "How long to hold a key before it repeats", delay), False, False, 0)
        rate = slider(10, 60, 5, int(k.get("repeat_rate", "30")))
        apply_rate = Debounce(lambda v: self.setting("keyboard", "repeat_rate", str(int(v)), ws.apply_keyboard))
        rate.connect("value-changed", lambda s: apply_rate(s.get_value()))
        box.pack_start(row("Repeat speed", "How fast a held key repeats", rate), False, False, 0)
        box.pack_start(row("Test it here", None, Gtk.Entry(placeholder_text="Type something…")), False, False, 0)
        return box

    # ---------------- Date & time ----------------
    def page_datetime(self):
        box = page_box("Date & Time")
        self.clock_label = label("", "wisp-stat")
        self.clock_sub = label("", "wisp-muted")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.get_style_context().add_class("wisp-card")
        card.pack_start(self.clock_label, False, False, 0)
        card.pack_start(self.clock_sub, False, False, 0)
        box.pack_start(card, False, False, 0)
        self.tick_clock()
        GLib.timeout_add_seconds(1, self.tick_clock)

        zones = []
        try:
            with open("/usr/share/zoneinfo/tzdata.zi") as f:
                for line in f:
                    if line.startswith("Z ") or line.startswith("L "):
                        name = line.split()[1] if line.startswith("Z ") else line.split()[2]
                        if "/" in name and not name.startswith(("Etc/", "SystemV", "US/")):
                            zones.append(name)
        except OSError:
            pass
        zones = sorted(set(zones))
        current = ""
        try:
            current = os.path.realpath("/etc/localtime").split("/zoneinfo/", 1)[1]
        except IndexError:
            pass
        tz = Gtk.ComboBoxText.new_with_entry()
        for z in zones:
            tz.append(z, z.replace("_", " "))
        tz.get_child().set_text(current.replace("_", " ") or "UTC")
        completion = Gtk.EntryCompletion()
        store = Gtk.ListStore(str)
        for z in zones:
            store.append([z.replace("_", " ")])
        completion.set_model(store)
        completion.set_text_column(0)
        tz.get_child().set_completion(completion)
        tz_btn = button("Set", "wisp-accent", lambda: self.set_timezone(tz.get_child().get_text()))
        tzbox = Gtk.Box(spacing=8)
        tzbox.pack_start(tz, False, False, 0)
        tzbox.pack_start(tz_btn, False, False, 0)
        box.pack_start(row("Time zone", "Start typing a city, e.g. Europe/Berlin", tzbox), False, False, 0)
        self.ntp_switch = Gtk.Switch(active=os.path.exists("/etc/runlevels/default/ntpd"))
        self.ntp_switch.connect("state-set", self.on_ntp)
        box.pack_start(row("Set time automatically", "Keeps the clock right using the internet", self.ntp_switch), False, False, 0)
        box.pack_start(row("24-hour clock", "Show 18:30 instead of 6:30 PM",
                           switch(self.cp["desktop"].getboolean("clock_24h"),
                                  lambda st: self.setting("desktop", "clock_24h", "true" if st else "false", ws.apply_desktop))),
                       False, False, 0)
        return box

    def tick_clock(self):
        h24 = self.cp["desktop"].getboolean("clock_24h")
        self.clock_label.set_text(time.strftime("%H:%M:%S" if h24 else "%I:%M:%S %p").lstrip("0"))
        self.clock_sub.set_text(time.strftime("%A, %d %B %Y · %Z"))
        return True

    def on_ntp(self, sw, state):
        def done(res):
            code, out = res
            if code != 0:
                message(self, "Could not change automatic time", out.strip(), error=True)
            sw.set_active(os.path.exists("/etc/runlevels/default/ntpd"))
        in_thread(lambda: run(root_cmd("ntp", "on" if state else "off"), timeout=30), done)
        return False

    def set_timezone(self, text):
        zone = text.strip().replace(" ", "_")
        code, out = run(root_cmd("timezone", zone))
        if code != 0:
            message(self, "Could not set time zone", out.strip() or zone, error=True)
        else:
            os.environ.pop("TZ", None)
            time.tzset()
            run(["pkill", "-x", "tint2"])
            GLib.timeout_add(500, lambda: (spawn(["tint2"]), False)[1])
            ws.restart_conky(self.cp)
            message(self, "Time zone set", zone.replace("_", " "))

    # ---------------- Default apps ----------------
    def page_apps(self):
        box = page_box("Default Apps")
        box.pack_start(label("Choose which app opens each kind of file or link.", "wisp-muted"), False, False, 0)
        apps = desktop_entries()
        defaults = configparser.ConfigParser(interpolation=None, strict=False)
        defaults.optionxform = str
        defaults.read([p for p in ("/usr/share/applications/mimeapps.list", MIMEAPPS) if os.path.exists(p)])
        current = dict(defaults["Default Applications"]) if defaults.has_section("Default Applications") else {}
        for key, title, icon_name, mimes in APP_KINDS:
            choices = [(did, a) for did, a in apps.items() if any(m in a[2] for m in mimes)]
            if not choices:
                continue
            store = Gtk.ListStore(str, str, str)
            for did, (name, ic, _m) in sorted(choices, key=lambda c: c[1][0].lower()):
                store.append([did, name, ic])
            c = Gtk.ComboBox(model=store)
            c.set_id_column(0)
            pix = Gtk.CellRendererPixbuf()
            c.pack_start(pix, False)
            c.add_attribute(pix, "icon-name", 2)
            txt = Gtk.CellRendererText()
            c.pack_start(txt, True)
            c.add_attribute(txt, "text", 1)
            now = (current.get(mimes[0], "").split(";") or [""])[0]
            if not c.set_active_id(now):
                c.set_active(0)
            c.connect("changed", lambda w, ms=mimes: self.set_default_app(w.get_active_id(), ms))
            box.pack_start(row(title, None, c), False, False, 0)
        return box

    @staticmethod
    def set_default_app(desktop_id, mimes):
        if not desktop_id:
            return
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(MIMEAPPS)
        if not cp.has_section("Default Applications"):
            cp.add_section("Default Applications")
        for m in mimes:
            cp["Default Applications"][m] = desktop_id + ";"
        os.makedirs(os.path.dirname(MIMEAPPS), exist_ok=True)
        with open(MIMEAPPS, "w") as f:
            cp.write(f, space_around_delimiters=False)

    # ---------------- Power ----------------
    def page_power(self):
        box = page_box("Power")
        for b in glob.glob("/sys/class/power_supply/BAT*"):
            try:
                cap = open(b + "/capacity").read().strip()
                st = open(b + "/status").read().strip()
            except OSError:
                continue
            lvl = Gtk.LevelBar(min_value=0, max_value=100, value=int(cap))
            lvl.set_size_request(200, 10)
            box.pack_start(row(f"Battery {cap}%", st, lvl), False, False, 0)
        blank = combo([("5", "5 minutes"), ("10", "10 minutes"), ("15", "15 minutes"), ("30", "30 minutes"), ("60", "1 hour"), ("0", "Never")],
                      self.cp["power"]["blank_minutes"], lambda v: self.setting("power", "blank_minutes", v, ws.apply_power))
        box.pack_start(row("Turn off screen after", "When you're not using the computer", blank), False, False, 0)
        btns = Gtk.Box(spacing=8)
        btns.pack_start(button("Suspend", "wisp-pill", lambda: spawn(["wisp-power", "Suspend"])), False, False, 0)
        btns.pack_start(button("Restart", "wisp-pill", lambda: spawn(["loginctl", "reboot"])), False, False, 0)
        btns.pack_start(button("Shut down", "wisp-pill wisp-danger", lambda: spawn(["loginctl", "poweroff"])), False, False, 0)
        box.pack_start(row("Power off", None, btns), False, False, 0)
        return box

    # ---------------- Storage ----------------
    def page_storage(self):
        box = page_box("Storage")
        st = os.statvfs(os.path.expanduser("~"))
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        bar = Gtk.LevelBar(min_value=0, max_value=1, value=(total - free) / total if total else 0)
        bar.set_size_request(-1, 12)
        for off in ("low", "high", "full"):
            bar.remove_offset_value(off)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("wisp-card")
        card.pack_start(label(f"{human(total - free)} used of {human(total)}", "wisp-section"), False, False, 0)
        card.pack_start(bar, False, False, 0)
        card.pack_start(label(f"{human(free)} free" + ("  ·  Running live: files are kept in memory until you restart" if IS_LIVE else ""),
                              "wisp-muted", wrap=True), False, False, 0)
        box.pack_start(card, False, False, 0)

        section(box, "Your folders")
        self.folder_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.folder_list.pack_start(label("Measuring…", "wisp-muted"), False, False, 0)
        box.pack_start(self.folder_list, False, False, 0)

        section(box, "Free up space")
        box.pack_start(row("Empty the trash", "Permanently deletes everything in the Trash",
                           button("Empty trash", "wisp-pill wisp-danger", self.empty_trash)), False, False, 0)
        box.pack_start(row("Clear temporary files", "Thumbnails and app caches. Apps rebuild them when needed.",
                           button("Clear", "wisp-pill", self.clear_cache)), False, False, 0)
        self.measure_folders()
        return box

    def measure_folders(self):
        home = os.path.expanduser("~")
        folders = [("Desktop", "user-desktop"), ("Documents", "folder-documents"), ("Downloads", "folder-download"),
                   ("Music", "folder-music"), ("Pictures", "folder-pictures"), ("Videos", "folder-videos")]

        def work():
            res = [(name, ic, dir_size(os.path.join(home, name))) for name, ic in folders
                   if os.path.isdir(os.path.join(home, name))]
            res.append(("Trash", "user-trash", dir_size(os.path.join(home, ".local/share/Trash"))))
            res.append(("Temporary files", "edit-clear", dir_size(os.path.join(home, ".cache"))))
            return res

        def show(res):
            for c in self.folder_list.get_children():
                self.folder_list.remove(c)
            for name, ic, size in res:
                r = Gtk.Box(spacing=12)
                r.get_style_context().add_class("wisp-card")
                r.pack_start(icon(ic, 24), False, False, 0)
                r.pack_start(label(name), True, True, 0)
                r.pack_end(label(human(size), "wisp-muted"), False, False, 0)
                self.folder_list.pack_start(r, False, False, 0)
            self.folder_list.show_all()
        in_thread(work, show)

    def confirm(self, title, text, action_label):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.NONE, text=title)
        d.format_secondary_text(text)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button(action_label, Gtk.ResponseType.OK)
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        return ok

    def empty_trash(self):
        if not self.confirm("Empty the trash?", "Everything in the Trash will be deleted for good.", "Empty trash"):
            return
        trash = os.path.expanduser("~/.local/share/Trash")
        for sub in ("files", "info", "expunged"):
            p = os.path.join(trash, sub)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                os.makedirs(p, exist_ok=True)
        self.measure_folders()

    def clear_cache(self):
        cache = os.path.expanduser("~/.cache")
        for name in os.listdir(cache) if os.path.isdir(cache) else []:
            if name in ("wisp",):
                continue
            p = os.path.join(cache, name)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
        self.measure_folders()

    # ---------------- Updates ----------------
    def page_updates(self):
        box = page_box("Updates")
        self.upd_status = label("Wisp OS keeps itself and your apps up to date through Alpine Linux's servers.",
                                "wisp-muted", wrap=True)
        box.pack_start(self.upd_status, False, False, 0)
        btns = Gtk.Box(spacing=8)
        self.upd_spinner = Gtk.Spinner()
        self.check_btn = button("Check now", "wisp-pill", self.check_updates)
        self.install_btn = button("Install updates", "wisp-accent", self.update_system)
        self.install_btn.set_sensitive(False)
        btns.pack_start(self.upd_spinner, False, False, 0)
        btns.pack_start(self.check_btn, False, False, 0)
        btns.pack_start(self.install_btn, False, False, 0)
        box.pack_start(row("Software updates", "Security fixes and new versions of your apps", btns), False, False, 0)
        self.upd_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.upd_list, False, False, 0)
        box.pack_start(row("Tell me about updates", "Checks once a day after you log in and shows a notification",
                           switch(self.cp["updates"].getboolean("notify"),
                                  lambda st: self.setting("updates", "notify", "true" if st else "false"))),
                       False, False, 0)
        if IS_LIVE:
            box.pack_start(label("You're running live from USB. Updates you install now last until you restart.",
                                 "wisp-muted", wrap=True), False, False, 0)
        return box

    def check_updates(self):
        self.upd_spinner.start()
        self.check_btn.set_sensitive(False)
        self.upd_status.set_text("Checking for updates…")

        def work():
            code, out = run(root_cmd("apk-update"), timeout=180)
            if code != 0:
                return None, out
            lines = run(["apk", "version", "-l", "<"], timeout=60)[1].splitlines()
            return [ln.split()[0] for ln in lines if ln and not ln.startswith("Installed")], ""

        def done(res):
            pkgs, err = res
            self.upd_spinner.stop()
            self.check_btn.set_sensitive(True)
            for c in self.upd_list.get_children():
                self.upd_list.remove(c)
            if pkgs is None:
                self.upd_status.set_text("Couldn't check for updates. Are you connected to the internet?")
                return
            self.install_btn.set_sensitive(bool(pkgs))
            if not pkgs:
                self.upd_status.set_text("Everything is up to date.")
                return
            self.upd_status.set_text(f"{len(pkgs)} update{'s' if len(pkgs) != 1 else ''} available.")
            names = Gtk.Label(label=", ".join(pkgs[:60]) + (" …" if len(pkgs) > 60 else ""), xalign=0, wrap=True)
            names.get_style_context().add_class("wisp-muted")
            names.set_selectable(True)
            self.upd_list.pack_start(names, False, False, 0)
            self.upd_list.show_all()
        in_thread(work, done)

    def update_system(self):
        TaskDialog(self, "Updating Wisp OS", root_cmd("apk-upgrade"),
                   on_done=lambda ok: ok and self.upd_status.set_text("Updates installed.") or self.install_btn.set_sensitive(not ok))

    # ---------------- About ----------------
    def page_about(self):
        box = page_box()
        top = Gtk.Box(spacing=18)
        top.pack_start(icon("wisp", 88), False, False, 0)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        ver = "0.1"
        try:
            for line in open("/etc/wisp-release"):
                if line.startswith("WISP_VERSION="):
                    ver = line.split("=", 1)[1].strip()
        except OSError:
            pass
        t.pack_start(label(f"Wisp OS {ver}", "wisp-title"), False, False, 0)
        t.pack_start(label("Light as a wisp. Built on Alpine Linux." + ("  ·  Running live" if IS_LIVE else ""), "wisp-muted"), False, False, 0)
        top.pack_start(t, True, True, 0)
        box.pack_start(top, False, False, 0)

        cpu = "Unknown"
        try:
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    cpu = re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
                    break
        except OSError:
            pass
        mem = read_meminfo()
        total = mem["MemTotal"] / 1048576
        used = memory_used(mem) / 1048576
        st = os.statvfs("/")
        disk_total = st.f_blocks * st.f_frsize / 1e9
        disk_free = st.f_bavail * st.f_frsize / 1e9
        gpu = ""
        for line in run(["sh", "-c", "cat /sys/class/drm/card*/device/uevent 2>/dev/null"])[1].splitlines():
            if line.startswith("DRIVER="):
                gpu = line.split("=", 1)[1]
                break
        info = [("Processor", cpu), ("Memory", f"{used:.0f} MB used of {total:.0f} MB"),
                ("Disk", f"{disk_free:.1f} GB free of {disk_total:.1f} GB"), ("Graphics driver", gpu or "Generic"),
                ("Kernel", os.uname().release)]
        grid = Gtk.Grid(column_spacing=24, row_spacing=10)
        grid.get_style_context().add_class("wisp-card")
        for i, (k, v) in enumerate(info):
            grid.attach(label(k, "wisp-muted"), 0, i, 1, 1)
            val = label(v)
            val.set_selectable(True)
            grid.attach(val, 1, i, 1, 1)
        box.pack_start(grid, False, False, 0)

        hostname = open("/etc/hostname").read().strip() if os.path.exists("/etc/hostname") else "wisp"
        name = Gtk.Entry(text=hostname, width_chars=18)
        rename = Gtk.Box(spacing=8)
        rename.pack_start(name, False, False, 0)
        rename.pack_start(button("Rename", "wisp-pill", lambda: self.rename(name.get_text())), False, False, 0)
        box.pack_start(row("Computer name", "How this computer shows up on your network", rename), False, False, 0)
        btns = Gtk.Box(spacing=8)
        btns.pack_start(button("Task Manager", "wisp-pill", lambda: spawn(["wisp-taskmanager", "performance"])), False, False, 0)
        if IS_LIVE:
            btns.pack_start(button("Install Wisp OS", "wisp-accent", lambda: spawn(["gtk-launch", "wisp-install"])), False, False, 0)
        box.pack_start(btns, False, False, 0)
        return box

    def rename(self, name):
        name = name.strip()
        code, out = run(root_cmd("hostname", name))
        if code != 0:
            message(self, "Could not rename this computer",
                    "Use letters, numbers and dashes only, e.g. my-laptop.", error=True)
        else:
            message(self, "Renamed", f"This computer is now called “{name}”.")


def main():
    GLib.set_prgname("wisp-settings")
    GLib.set_application_name("Settings")
    apply_css()
    start = sys.argv[1] if len(sys.argv) > 1 else None
    win = Settings(start)
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
