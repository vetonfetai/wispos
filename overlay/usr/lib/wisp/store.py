#!/usr/bin/python3
"""Wisp App Store: featured apps, search all Alpine packages, system updates."""
import os
import re
import sys
import time

sys.path.insert(0, "/usr/lib/wisp")
from wisplib import (IS_LIVE, TaskDialog, apply_css, button, in_thread, label,  # noqa: E402
                     message, root_cmd, run, spawn, Gtk, GLib)
from gi.repository import Pango  # noqa: E402

# (package, name, description, icon, category, approx download MB)
FEATURED = [
    ("chromium", "Chromium", "Fast web browser from the Chrome project", "chromium", "Internet", 110),
    ("librewolf", "LibreWolf", "Privacy-focused Firefox edition", "librewolf", "Internet", 90),
    ("thunderbird", "Thunderbird", "Email and calendar", "thunderbird", "Internet", 80),
    ("telegram-desktop", "Telegram", "Messaging app", "telegram", "Internet", 60),
    ("transmission-gtk", "Transmission", "Simple torrent downloads", "transmission", "Internet", 4),
    ("libreoffice", "LibreOffice", "Full office suite: Word, Excel and PowerPoint files", "libreoffice-startcenter", "Office", 300),
    ("xournalpp", "Xournal++", "Handwritten notes and PDF annotation", "com.github.xournalpp.xournalpp", "Office", 10),
    ("keepassxc", "KeePassXC", "Password manager", "keepassxc", "Office", 15),
    ("geany", "Geany", "Light code editor", "geany", "Development", 6),
    ("gimp", "GIMP", "Photo editing", "gimp", "Creative", 120),
    ("inkscape", "Inkscape", "Vector drawing", "inkscape", "Creative", 100),
    ("krita", "Krita", "Digital painting", "krita", "Creative", 200),
    ("darktable", "darktable", "Photo workflow and RAW editing", "darktable", "Creative", 60),
    ("blender", "Blender", "3D modelling and animation", "blender", "Creative", 250),
    ("vlc", "VLC", "Plays any video or audio file", "vlc", "Media", 50),
    ("audacity", "Audacity", "Record and edit audio", "audacity", "Media", 40),
    ("obs-studio", "OBS Studio", "Screen recording and streaming", "com.obsproject.Studio", "Media", 80),
    ("kdenlive", "Kdenlive", "Video editing", "kdenlive", "Media", 150),
    ("shotwell", "Shotwell", "Photo library", "shotwell", "Media", 20),
    ("supertuxkart", "SuperTuxKart", "Kart racing game", "supertuxkart", "Games", 450),
    ("gnome-mines", "Mines", "Classic minesweeper", "gnome-mines", "Games", 3),
    ("aisleriot", "Solitaire", "80+ card games", "gnome-aisleriot", "Games", 10),
    ("gnome-chess", "Chess", "Play chess", "gnome-chess", "Games", 5),
]
INDEX_MAX_AGE = 6 * 3600
SKIP_SUFFIXES = ("-dev", "-doc", "-dbg", "-lang", "-static", "-openrc", "-libs", "-pyc",
                 "-bash-completion", "-zsh-completion", "-fish-completion", "-tests", "-lib")


def installed(pkg):
    return run(["apk", "info", "-e", pkg], timeout=10)[0] == 0


def index_is_fresh():
    newest = 0
    for d in ("/var/cache/apk", "/etc/apk/cache", "/lib/apk/db"):
        try:
            for f in os.listdir(d):
                if f.startswith("APKINDEX"):
                    newest = max(newest, os.path.getmtime(os.path.join(d, f)))
        except OSError:
            pass
    return time.time() - newest < INDEX_MAX_AGE


def desktop_file_for(pkg):
    code, out = run(["apk", "info", "-L", pkg], timeout=10)
    for line in out.splitlines():
        if line.startswith("usr/share/applications/") and line.endswith(".desktop"):
            return os.path.basename(line)[:-8]
    return None


class Store(Gtk.Window):
    def __init__(self):
        super().__init__(title="App Store")
        self.set_default_size(980, 660)
        self.set_icon_name("system-software-install")
        self.theme = Gtk.IconTheme.get_default()

        hb = Gtk.HeaderBar(show_close_button=True, title="App Store")
        self.set_titlebar(hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sw = Gtk.StackSwitcher(stack=self.stack)
        hb.set_custom_title(sw)
        self.spinner = Gtk.Spinner()
        hb.pack_end(self.spinner)

        self.stack.add_titled(self.build_featured(), "featured", "Featured")
        self.stack.add_titled(self.build_search(), "search", "Search")
        self.stack.add_titled(self.build_updates(), "updates", "Updates")
        self.add(self.stack)
        self.show_all()
        self.ensure_index()

    # ---------- package index ----------
    def ensure_index(self, then=None):
        if index_is_fresh():
            if then:
                then()
            return
        self.spinner.start()

        def done(res):
            self.spinner.stop()
            if res[0] != 0:
                message(self, "Can't reach the app catalog",
                        "Check your internet connection (Settings → Wi-Fi), then try again.", error=True)
            elif then:
                then()
        in_thread(lambda: run(root_cmd("apk-update"), timeout=120), done)

    def pkg_icon(self, name, size=48):
        img = Gtk.Image()
        n = name if self.theme.has_icon(name) else "application-x-executable"
        img.set_from_icon_name(n, Gtk.IconSize.DIALOG)
        img.set_pixel_size(size)
        return img

    def action_button(self, pkg, refresh):
        if installed(pkg):
            box = Gtk.Box(spacing=6)
            desk = desktop_file_for(pkg)
            if desk:
                box.pack_start(button("Open", "wisp-pill", lambda: spawn(["gtk-launch", desk])), False, False, 0)
            box.pack_start(button("Remove", "wisp-pill wisp-danger", lambda: self.remove(pkg, refresh)), False, False, 0)
            return box
        return button("Install", "wisp-accent", lambda: self.install(pkg, refresh))

    def install(self, pkg, refresh):
        if IS_LIVE:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.OK_CANCEL, text="Install in live mode?")
            d.format_secondary_text("In live mode apps are kept in memory and disappear when you restart. "
                                    "Install Wisp OS to keep them.")
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return
        self.ensure_index(lambda: TaskDialog(self, f"Installing {pkg}", root_cmd("apk-add", pkg),
                                             lambda ok: refresh()))

    def remove(self, pkg, refresh):
        TaskDialog(self, f"Removing {pkg}", root_cmd("apk-del", pkg), lambda ok: refresh())

    # ---------- featured ----------
    def build_featured(self):
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.featured_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.featured_box.set_border_width(24)
        sw.add(self.featured_box)
        self.fill_featured()
        return sw

    def fill_featured(self):
        for c in self.featured_box.get_children():
            self.featured_box.remove(c)
        self.featured_box.pack_start(label("Get apps", "wisp-title"), False, False, 0)
        self.featured_box.pack_start(label("Hand-picked apps that run well on Wisp. Use Search to find anything else.",
                                           "wisp-muted"), False, False, 0)
        cats = []
        for item in FEATURED:
            if item[4] not in cats:
                cats.append(item[4])
        for cat in cats:
            self.featured_box.pack_start(label(cat, "wisp-section"), False, False, 6)
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                               min_children_per_line=2, column_spacing=12, row_spacing=12, homogeneous=True)
            for pkg, name, desc, icon_name, _c, mb in FEATURED:
                if _c != cat:
                    continue
                card = Gtk.Box(spacing=12)
                card.get_style_context().add_class("wisp-card")
                card.pack_start(self.pkg_icon(icon_name), False, False, 0)
                t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
                t.pack_start(label(name, "wisp-section"), False, False, 0)
                d = label(desc, "wisp-muted")
                d.set_ellipsize(Pango.EllipsizeMode.END)
                d.set_tooltip_text(f"{desc}\nAbout {mb} MB download")
                t.pack_start(d, False, False, 0)
                card.pack_start(t, True, True, 0)
                act = self.action_button(pkg, self.fill_featured)
                act.set_valign(Gtk.Align.CENTER)
                card.pack_end(act, False, False, 0)
                flow.add(card)
            self.featured_box.pack_start(flow, False, False, 0)
        self.featured_box.show_all()

    # ---------- search ----------
    def build_search(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(24)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search 20,000+ packages, e.g. “music”, “vscode”, “game”")
        self.search_entry.connect("activate", lambda e: self.do_search())
        box.pack_start(self.search_entry, False, False, 0)
        self.search_info = label("Press Enter to search.", "wisp-muted")
        box.pack_start(self.search_info, False, False, 0)
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.get_style_context().add_class("wisp-list")
        sw.add(self.results)
        box.pack_start(sw, True, True, 0)
        return box

    def do_search(self):
        q = self.search_entry.get_text().strip()
        if not q:
            return
        self.search_info.set_text("Searching…")

        def work():
            code, out = run(["apk", "search", "-v", "-d", q], timeout=30)
            found = []
            for line in out.splitlines():
                m = re.match(r"^(\S+?)-(\d[^ ]*-r\d+) - (.*)$", line)
                if not m:
                    continue
                name, desc = m.group(1), m.group(3)
                if name.endswith(SKIP_SUFFIXES) or name.startswith(("py3-", "perl-", "lua5", "ruby-", "font-", "linux-firmware")):
                    continue
                score = 0 if name == q else 1 if name.startswith(q) else 2 if q in name else 3
                found.append((score, name, desc))
            found.sort()
            return found[:60]

        self.ensure_index(lambda: in_thread(work, self.show_results))

    def show_results(self, found):
        for c in self.results.get_children():
            self.results.remove(c)
        self.search_info.set_text(f"{len(found)} results" if found else "Nothing found. Try another word.")
        for _s, name, desc in found:
            r = Gtk.Box(spacing=12)
            r.set_border_width(6)
            r.pack_start(self.pkg_icon(name, 32), False, False, 0)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            t.pack_start(label(name, "wisp-section"), False, False, 0)
            d = label(desc, "wisp-muted")
            d.set_ellipsize(Pango.EllipsizeMode.END)
            t.pack_start(d, False, False, 0)
            r.pack_start(t, True, True, 0)
            r.pack_end(self.action_button(name, self.do_search), False, False, 0)
            self.results.add(r)
        self.results.show_all()

    # ---------- updates ----------
    def build_updates(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(24)
        box.pack_start(label("Updates", "wisp-title"), False, False, 0)
        self.upd_info = label("Check for updates to Wisp OS and all your apps.", "wisp-muted", wrap=True)
        box.pack_start(self.upd_info, False, False, 0)
        btns = Gtk.Box(spacing=8)
        btns.pack_start(button("Check now", "wisp-pill", self.check_updates), False, False, 0)
        self.upd_btn = button("Install updates", "wisp-accent",
                              lambda: TaskDialog(self, "Updating", root_cmd("apk-upgrade"),
                                                 lambda ok: self.check_updates()))
        btns.pack_start(self.upd_btn, False, False, 0)
        box.pack_start(btns, False, False, 0)
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.upd_list = Gtk.Label(xalign=0, yalign=0, selectable=True)
        self.upd_list.get_style_context().add_class("wisp-muted")
        sw.add(self.upd_list)
        box.pack_start(sw, True, True, 0)
        return box

    def check_updates(self):
        self.upd_info.set_text("Checking…")
        self.spinner.start()

        def work():
            run(root_cmd("apk-update"), timeout=120)
            return run(["apk", "version", "-l", "<"], timeout=60)[1]

        def done(out):
            self.spinner.stop()
            lines = [ln.split()[0] for ln in out.splitlines()[1:] if ln.strip()]
            if lines:
                self.upd_info.set_text(f"{len(lines)} updates available.")
                self.upd_list.set_text("\n".join(lines))
            else:
                self.upd_info.set_text("Everything is up to date.")
                self.upd_list.set_text("")
        in_thread(work, done)


def main():
    GLib.set_prgname("wisp-store")
    GLib.set_application_name("App Store")
    apply_css()
    w = Store()
    w.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
