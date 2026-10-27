#!/usr/bin/python3
"""Wisp Welcome: first-login screen with the most useful next steps."""
import sys

sys.path.insert(0, "/usr/lib/wisp")
from wisplib import (IS_LIVE, apply_css, button, icon, label, load_settings,  # noqa: E402
                     save_settings, spawn, Gtk, GLib)


def card(icon_name, title, text, on_click):
    b = Gtk.Button()
    b.get_style_context().add_class("wisp-card")
    inner = Gtk.Box(spacing=14)
    inner.set_border_width(4)
    inner.pack_start(icon(icon_name, 40), False, False, 0)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.CENTER)
    texts.pack_start(label(title, "wisp-section"), False, False, 0)
    texts.pack_start(label(text, "wisp-muted", wrap=True), False, False, 0)
    inner.pack_start(texts, True, True, 0)
    b.add(inner)
    b.connect("clicked", lambda *_: on_click())
    return b


class Welcome(Gtk.Window):
    def __init__(self):
        super().__init__(title="Welcome to Wisp OS")
        self.set_default_size(760, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("wisp")
        self.cp = load_settings()
        hb = Gtk.HeaderBar(show_close_button=True, title="Welcome")
        self.set_titlebar(hb)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_border_width(32)

        hero = Gtk.Box(spacing=20)
        hero.pack_start(icon("wisp", 84), False, False, 0)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        t.pack_start(label("Welcome to Wisp OS", "wisp-title"), False, False, 0)
        sub = ("You're running live from USB: nothing on this computer has been changed."
               if IS_LIVE else "Fast, light and ready. Here are a few things to get started.")
        t.pack_start(label(sub, "wisp-subtitle", wrap=True), False, False, 0)
        hero.pack_start(t, True, True, 0)
        box.pack_start(hero, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        cards = [
            ("network-wireless", "Connect to Wi-Fi", "Get online in a couple of clicks.",
             lambda: spawn(["wisp-settings", "wifi"])),
            ("system-software-install", "Get apps", "Browsers, office, games, creative tools.",
             lambda: spawn(["wisp-store"])),
            ("preferences-desktop-wallpaper", "Make it yours", "Wallpaper, dark or light style, text size.",
             lambda: spawn(["wisp-settings", "appearance"])),
        ]
        if IS_LIVE:
            cards.append(("drive-harddisk", "Install Wisp OS", "Put Wisp on this computer's disk.",
                          lambda: spawn(["gtk-launch", "wisp-install"])))
        else:
            cards.append(("preferences-system", "Settings", "Display, sound, keyboard, time zone.",
                          lambda: spawn(["wisp-settings"])))
        for i, c in enumerate(cards):
            grid.attach(card(*c), i % 2, i // 2, 1, 1)
        box.pack_start(grid, False, False, 0)

        tips = Gtk.Grid(column_spacing=18, row_spacing=6)
        tips.get_style_context().add_class("wisp-card")
        shortcuts = [("Super + Space", "Find and open apps"), ("Super + Enter", "Terminal"),
                     ("Super + Left / Right", "Snap window to half the screen"),
                     ("Right-click desktop", "Main menu"), ("Print", "Screenshot")]
        tips.attach(label("Handy shortcuts", "wisp-section"), 0, 0, 2, 1)
        for i, (k, v) in enumerate(shortcuts, start=1):
            tips.attach(label(k), 0, i, 1, 1)
            tips.attach(label(v, "wisp-muted"), 1, i, 1, 1)
        box.pack_start(tips, False, False, 0)

        bottom = Gtk.Box(spacing=10)
        show = Gtk.CheckButton(label="Show this when I log in")
        show.set_active(self.cp["welcome"].getboolean("show"))
        show.connect("toggled", self.on_show)
        bottom.pack_start(show, False, False, 0)
        bottom.pack_end(button("Let's go", "wisp-accent", self.destroy), False, False, 0)
        box.pack_end(bottom, False, False, 0)

        self.add(box)
        self.show_all()

    def on_show(self, check):
        self.cp["welcome"]["show"] = "true" if check.get_active() else "false"
        save_settings(self.cp)


def main():
    GLib.set_prgname("wisp-welcome")
    GLib.set_application_name("Welcome")
    apply_css()
    w = Welcome()
    w.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
