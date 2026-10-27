#!/usr/bin/python3
"""Wisp Task Manager: what's running, how much CPU and memory it uses, end tasks."""
import collections
import configparser
import glob
import os
import signal
import sys

sys.path.insert(0, "/usr/lib/wisp")
from wisplib import apply_css, button, icon, label, memory_used, read_meminfo, Gtk, GLib, Gdk  # noqa: E402
from gi.repository import Pango  # noqa: E402

PAGE = os.sysconf("SC_PAGE_SIZE")
NCPU = os.cpu_count() or 1
UID = os.getuid()
REFRESH_MS = 2000

# Friendly names for the pieces of the Wisp desktop and common services
BACKGROUND = {
    "Xorg": ("Display server", "video-display"),
    "openbox": ("Window manager", "preferences-system-windows"),
    "tint2": ("Taskbar", "preferences-desktop"),
    "picom": ("Visual effects", "preferences-desktop-effects"),
    "conky": ("Desktop clock", "clock"),
    "dunst": ("Notifications", "preferences-system-notifications"),
    "nm-applet": ("Wi-Fi icon", "network-wireless"),
    "xsettingsd": ("Theme service", "preferences-desktop-theme"),
    "pipewire": ("Sound server", "audio-speakers"),
    "pipewire-pulse": ("Sound server", "audio-speakers"),
    "wireplumber": ("Sound server", "audio-speakers"),
    "NetworkManager": ("Network service", "network-workgroup"),
    "wpa_supplicant": ("Network service", "network-workgroup"),
    "dbus-daemon": ("System messages", "preferences-system"),
    "dbus-launch": ("System messages", "preferences-system"),
    "udevd": ("Device manager", "drive-removable-media"),
    "elogind": ("Login manager", "system-users"),
    "polkitd": ("Permissions service", "dialog-password"),
    "udisksd": ("Disk service", "drive-harddisk"),
    "gvfsd": ("File system service", "folder"),
    "init": ("System startup", "system-run"),
    "supervise-daemon": ("Service supervisor", "system-run"),
    "agetty": ("Console login", "utilities-terminal"),
    "login": ("Console login", "utilities-terminal"),
    "zram": ("Memory compression", "media-flash"),
    "glycin-svg": ("Image loader", "image-x-generic"),
    "glycin-image-rs": ("Image loader", "image-x-generic"),
    "at-spi-bus-launcher": ("Accessibility service", "preferences-desktop-accessibility"),
    "at-spi2-registryd": ("Accessibility service", "preferences-desktop-accessibility"),
    "dconf-service": ("Settings storage", "preferences-system"),
}
WISP_SCRIPTS = {
    "settings.py": ("Settings", "preferences-system"),
    "store.py": ("App Store", "system-software-install"),
    "welcome.py": ("Welcome", "wisp"),
    "taskmanager.py": ("Task Manager", "utilities-system-monitor"),
    "wispsession.py": ("Wisp session", "wisp"),
}
# Ending these closes the desktop
CRITICAL = {"Display server", "Window manager", "Wisp session", "System startup", "Login manager"}


def desktop_apps():
    """Map program name -> (app name, icon) from installed .desktop files."""
    apps = {}
    for path in glob.glob("/usr/share/applications/*.desktop"):
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            cp.read(path, encoding="utf-8")
            e = cp["Desktop Entry"]
        except (configparser.Error, KeyError, UnicodeDecodeError):
            continue
        exe = e.get("Exec", "").split()
        if not exe or not e.get("Name"):
            continue
        prog = os.path.basename(exe[0])
        if prog in ("env", "sh") and len(exe) > 1:
            prog = os.path.basename(exe[1])
        apps.setdefault(prog, (e.get("Name"), e.get("Icon", "application-x-executable")))
    return apps


def read_procs():
    procs = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat", "rb") as f:
                st = f.read().decode(errors="replace")
            r = st.rfind(")")
            comm = st[st.find("(") + 1:r]
            fields = st[r + 2:].split()
            ticks = int(fields[11]) + int(fields[12])
            with open(f"/proc/{d}/statm") as f:
                sm = f.read().split()
            rss, shared = int(sm[1]), int(sm[2])
            if rss == 0:
                continue  # kernel thread
            uid = os.stat(f"/proc/{d}").st_uid
            with open(f"/proc/{d}/cmdline", "rb") as f:
                cmd = [c.decode(errors="replace") for c in f.read().split(b"\0") if c]
        except (OSError, IndexError, ValueError):
            continue
        procs[int(d)] = (comm, ticks, max(rss - shared, 0) * PAGE, uid, cmd)
    return procs


def cpu_times():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)
    return sum(v), idle


def meminfo():
    return read_meminfo()


def fmt_bytes(n):
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    if n >= 10 << 20:
        return f"{n / (1 << 20):.0f} MB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    return f"{n / 1024:.0f} KB"


class Graph(Gtk.DrawingArea):
    """A small line graph of the last minute, 0-100."""

    def __init__(self, rgb, height=190):
        super().__init__()
        self.rgb = rgb
        self.values = collections.deque(maxlen=60)
        self.set_size_request(-1, height)
        self.connect("draw", self.on_draw)

    def push(self, v):
        v = max(0.0, min(100.0, v))
        if not self.values:
            self.values.extend([v] * 60)
        self.values.append(v)
        self.queue_draw()

    def on_draw(self, area, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        fg = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_line_width(1)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
        for i in range(1, 4):
            y = round(h * i / 4) + 0.5
            cr.move_to(0, y)
            cr.line_to(w, y)
        cr.stroke()
        n = len(self.values)
        step = w / (n - 1)
        pts = [(i * step, h - 2 - (v / 100) * (h - 4)) for i, v in enumerate(self.values)]
        cr.move_to(0, h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(w, h)
        cr.close_path()
        r, g, b = self.rgb
        cr.set_source_rgba(r, g, b, 0.18)
        cr.fill()
        cr.set_line_width(2)
        cr.set_line_join(1)
        for i, (x, y) in enumerate(pts):
            cr.line_to(x, y) if i else cr.move_to(x, y)
        cr.set_source_rgba(r, g, b, 1)
        cr.stroke()
        x, y = pts[-1]
        cr.arc(x - 3, y, 3.5, 0, 6.2832)
        cr.fill()


class TaskManager(Gtk.Window):
    COLS = (str, str, str, float, float, str, str, int, bool, str)
    # icon, markup, key, cpu, mem, cpu text, mem text, row kind (0 header 1 app 2 background), mine, search text

    def __init__(self, page=None):
        super().__init__(title="Task Manager")
        self.set_default_size(840, 620)
        self.set_icon_name("utilities-system-monitor")
        self.apps = desktop_apps()
        self.prev_ticks = {}
        self.prev_cpu = cpu_times()
        self.groups = {}
        self.show_system = False

        hb = Gtk.HeaderBar(show_close_button=True)
        self.set_titlebar(hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sw = Gtk.StackSwitcher(stack=self.stack)
        hb.set_custom_title(sw)

        self.stack.add_titled(self.build_processes(), "processes", "Processes")
        self.stack.add_titled(self.build_performance(), "performance", "Performance")
        self.add(self.stack)
        self.connect("key-press-event", self.on_key)
        self.refresh()
        GLib.timeout_add(REFRESH_MS, self.tick)
        self.show_all()
        if page == "performance":
            self.stack.set_visible_child_name("performance")
        GLib.idle_add(self.scroll_top)

    # ---------- Processes ----------
    def build_processes(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(18)

        top = Gtk.Box(spacing=10)
        self.search = Gtk.SearchEntry(placeholder_text="Search apps and processes")
        self.search.set_size_request(280, -1)
        self.search.connect("search-changed", lambda *_: self.filter.refilter())
        top.pack_start(self.search, False, False, 0)
        sys_check = Gtk.CheckButton(label="Show system processes")
        sys_check.connect("toggled", self.on_show_system)
        top.pack_end(sys_check, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.store = Gtk.TreeStore(*self.COLS)
        self.h_apps = self.store.append(None, ["", "<b>Apps</b>", "#apps", 0, 0, "", "", 0, True, ""])
        self.h_bg = self.store.append(None, ["", "<b>Background</b>", "#bg", 0, 0, "", "", 0, True, ""])
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self.visible)
        self.sorted = Gtk.TreeModelSort(model=self.filter)
        for col in (3, 4):
            self.sorted.set_sort_func(col, self.sort_func, col)
        self.sorted.set_sort_column_id(4, Gtk.SortType.DESCENDING)

        self.view = Gtk.TreeView(model=self.sorted, headers_visible=True, enable_search=False)
        self.view.set_show_expanders(False)
        self.view.set_level_indentation(0)
        name_col = Gtk.TreeViewColumn("Name")
        pix = Gtk.CellRendererPixbuf(stock_size=Gtk.IconSize.LARGE_TOOLBAR, xpad=6, ypad=5)
        name_col.pack_start(pix, False)
        name_col.add_attribute(pix, "icon-name", 0)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        name_col.pack_start(txt, True)
        name_col.add_attribute(txt, "markup", 1)
        name_col.set_expand(True)
        self.view.append_column(name_col)
        for title, text_col, sort_col in (("CPU", 5, 3), ("Memory", 6, 4)):
            r = Gtk.CellRendererText(xalign=1.0, xpad=14)
            c = Gtk.TreeViewColumn(title, r, text=text_col)
            c.set_sort_column_id(sort_col)
            c.set_min_width(110)
            c.set_alignment(1.0)
            self.view.append_column(c)
        self.view.get_selection().connect("changed", self.on_select)
        self.view.connect("button-press-event", self.on_click)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.get_style_context().add_class("wisp-card")
        scroll.add(self.view)
        box.pack_start(scroll, True, True, 0)

        bottom = Gtk.Box(spacing=10)
        self.summary = label("", "wisp-muted")
        bottom.pack_start(self.summary, False, False, 0)
        self.end_btn = button("End task", "wisp-accent", self.end_selected)
        self.end_btn.set_sensitive(False)
        bottom.pack_end(self.end_btn, False, False, 0)
        box.pack_start(bottom, False, False, 0)
        return box

    def visible(self, model, it, _data=None):
        kind = model[it][7]
        if kind == 0:
            return True
        if kind == 2 and not self.show_system and not model[it][8]:
            return False
        q = self.search.get_text().strip().lower()
        return not q or q in model[it][9]

    def sort_func(self, model, a, b, col):
        ka, kb = model[a][7], model[b][7]
        if ka == 0 or kb == 0:
            # keep "Apps" above "Background" whichever way the column is sorted
            order = 1 if model[a][2] == "#bg" else -1
            _, direction = self.sorted.get_sort_column_id()
            return order if direction == Gtk.SortType.ASCENDING else -order
        va, vb = model[a][col], model[b][col]
        return (va > vb) - (va < vb)

    def on_show_system(self, check):
        self.show_system = check.get_active()
        self.filter.refilter()
        self.update_headers()

    def classify(self, comm, cmd, uid):
        exe = os.path.basename(cmd[0]) if cmd else comm
        if exe.startswith("python") and len(cmd) > 1:
            script = os.path.basename(cmd[1])
            if script in WISP_SCRIPTS:
                name, ic = WISP_SCRIPTS[script]
                return name, ic, script != "wispsession.py"
            exe = script
        if exe == "pcmanfm" and "--desktop" in cmd:
            return "Desktop icons", "user-desktop", False
        for key in (exe, comm):
            if key in BACKGROUND:
                n, ic = BACKGROUND[key]
                return n, ic, False
        for key in (exe, comm):
            if key in self.apps:
                n, ic = self.apps[key]
                return n, ic, True
        if comm.startswith("gvfs"):
            return "File system service", "folder", False
        return exe or comm, "application-x-executable", False

    def tick(self):
        # Don't spend CPU while minimised; catch up as soon as the window is back
        w = self.get_window()
        if w and w.get_state() & Gdk.WindowState.ICONIFIED:
            return True
        return self.refresh()

    def refresh(self):
        procs = read_procs()
        total, idle = cpu_times()
        dt_total = max(total - self.prev_cpu[0], 1)
        dt_idle = idle - self.prev_cpu[1]
        self.prev_cpu = (total, idle)
        cpu_pct = 100.0 * (1 - dt_idle / dt_total)

        groups = {}
        for pid, (comm, ticks, mem, uid, cmd) in procs.items():
            prev = self.prev_ticks.get(pid)
            cpu = 100.0 * (ticks - prev) / dt_total if prev is not None else 0.0
            name, ic, is_app = self.classify(comm, cmd, uid)
            g = groups.setdefault(name, {"icon": ic, "app": is_app, "cpu": 0.0, "mem": 0, "pids": [], "mine": False, "words": set()})
            g["cpu"] += cpu
            g["mem"] += mem
            g["pids"].append(pid)
            g["mine"] = g["mine"] or uid == UID
            g["words"].update((comm.lower(), name.lower()))
        self.prev_ticks = {pid: p[1] for pid, p in procs.items()}

        for name, g in groups.items():
            n = len(g["pids"])
            markup = GLib.markup_escape_text(name)
            if n > 1:
                markup += f"  <span alpha='55%'>{n} processes</span>"
            cpu_text = f"{g['cpu']:.1f} %" if g["cpu"] >= 0.05 else "0 %"
            row = [g["icon"], markup, name, g["cpu"], float(g["mem"]), cpu_text, fmt_bytes(g["mem"]),
                   1 if g["app"] else 2, g["mine"], " ".join(g["words"])]
            parent = self.h_apps if g["app"] else self.h_bg
            old = self.groups.get(name)
            if old and self.store.is_ancestor(parent, old[0]):
                self.store.set(old[0], list(range(len(row))), row)
                self.groups[name] = (old[0], g["pids"], g["mine"])
            else:
                if old:
                    self.store.remove(old[0])
                self.groups[name] = (self.store.append(parent, row), g["pids"], g["mine"])
        for name in [k for k in self.groups if k not in groups]:
            self.store.remove(self.groups.pop(name)[0])
        self.last_groups = groups
        self.update_headers()
        self.view.expand_all()

        m = meminfo()
        used = memory_used(m)
        self.summary.set_text(f"CPU {cpu_pct:.0f}%   ·   Memory {fmt_bytes(used)} of {fmt_bytes(m['MemTotal'])}"
                              f"   ·   {len(procs)} processes")
        self.update_performance(cpu_pct, m, used, len(procs))
        self.on_select(self.view.get_selection())
        return True

    def scroll_top(self):
        self.view.get_selection().unselect_all()
        self.view.scroll_to_cell(Gtk.TreePath.new_first(), None, True, 0.0, 0.0)
        return False

    def update_headers(self):
        groups = getattr(self, "last_groups", {})
        n_apps = sum(1 for g in groups.values() if g["app"])
        n_bg = sum(1 for g in groups.values() if not g["app"] and (g["mine"] or self.show_system))
        self.store[self.h_apps][1] = f"<b>Apps</b>  <span alpha='55%'>{n_apps}</span>"
        self.store[self.h_bg][1] = f"<b>Background</b>  <span alpha='55%'>{n_bg}</span>"

    def selected(self):
        model, it = self.view.get_selection().get_selected()
        if not it or model[it][7] == 0:
            return None
        return self.groups.get(model[it][2]) and (model[it][2], *self.groups[model[it][2]])

    def on_select(self, sel):
        s = self.selected()
        self.end_btn.set_sensitive(bool(s and s[3]))

    def on_click(self, view, event):
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        s = self.selected()
        if not s:
            return True
        menu = Gtk.Menu()
        for text, sig in (("End task", signal.SIGTERM), ("Force quit", signal.SIGKILL)):
            item = Gtk.MenuItem(label=text)
            item.set_sensitive(s[3])
            item.connect("activate", lambda _i, sg=sig: self.end_selected(sg))
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Delete and self.stack.get_visible_child_name() == "processes":
            self.end_selected()
            return True
        if event.keyval == Gdk.KEY_f and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.search.grab_focus()
            return True
        return False

    def end_selected(self, sig=signal.SIGTERM):
        s = self.selected()
        if not s or not s[3]:
            return
        name, _it, pids, _mine = s
        if name in CRITICAL or name == "Taskbar":
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                  buttons=Gtk.ButtonsType.NONE, text=f"End “{name}”?")
            d.format_secondary_text("This is part of the desktop. Ending it may close your session "
                                    "or leave the screen without a taskbar until you log in again.")
            d.add_button("Cancel", Gtk.ResponseType.CANCEL)
            d.add_button("End it", Gtk.ResponseType.OK)
            resp = d.run()
            d.destroy()
            if resp != Gtk.ResponseType.OK:
                return
        own = os.getpid()
        for pid in pids:
            if pid == own:
                continue
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        if sig == signal.SIGTERM:
            GLib.timeout_add(3000, self.check_ended, name, pids)
        GLib.timeout_add(300, lambda: (self.refresh(), False)[1])

    def check_ended(self, name, pids):
        alive = [p for p in pids if p != os.getpid() and os.path.exists(f"/proc/{p}")]
        if not alive:
            return False
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=f"“{name}” isn't closing")
        d.format_secondary_text("It may be busy or not responding. Force it to quit? Unsaved work will be lost.")
        d.add_button("Wait", Gtk.ResponseType.CANCEL)
        d.add_button("Force quit", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            for p in alive:
                try:
                    os.kill(p, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        d.destroy()
        return False

    # ---------- Performance ----------
    def stat_card(self, title, graph=None):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("wisp-card")
        head = Gtk.Box(spacing=8)
        head.pack_start(label(title, "wisp-section"), False, False, 0)
        value = label("", "wisp-stat", xalign=1)
        head.pack_end(value, False, False, 0)
        card.pack_start(head, False, False, 0)
        sub = label("", "wisp-muted")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        card.pack_start(sub, False, False, 0)
        if graph:
            graph.set_vexpand(True)
            card.pack_start(graph, True, True, 6)
        return card, value, sub

    def build_performance(self):
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        grid.set_border_width(18)
        cpu_model = "Processor"
        try:
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    cpu_model = " ".join(line.split(":", 1)[1].split())
                    break
        except OSError:
            pass
        self.cpu_graph = Graph((0.54, 0.71, 1.0))
        self.mem_graph = Graph((0.71, 0.55, 1.0))
        cpu_card, self.cpu_val, self.cpu_sub = self.stat_card("CPU", self.cpu_graph)
        self.cpu_sub.set_text(f"{cpu_model} · {NCPU} cores")
        mem_card, self.mem_val, self.mem_sub = self.stat_card("Memory", self.mem_graph)
        grid.attach(cpu_card, 0, 0, 1, 1)
        grid.attach(mem_card, 1, 0, 1, 1)

        swap_card, self.swap_val, self.swap_sub = self.stat_card("Compressed memory")
        self.swap_bar = Gtk.LevelBar(min_value=0, max_value=1)
        swap_card.pack_start(self.swap_bar, False, False, 6)
        disk_card, self.disk_val, self.disk_sub = self.stat_card("Disk")
        self.disk_bar = Gtk.LevelBar(min_value=0, max_value=1)
        disk_card.pack_start(self.disk_bar, False, False, 6)
        sys_card, self.up_val, self.up_sub = self.stat_card("Up time")
        grid.attach(swap_card, 0, 1, 1, 1)
        grid.attach(disk_card, 1, 1, 1, 1)
        grid.attach(sys_card, 0, 2, 2, 1)
        for bar in (self.swap_bar, self.disk_bar):
            bar.remove_offset_value("low")
            bar.remove_offset_value("high")
            bar.remove_offset_value("full")
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.add(grid)
        return sc

    def update_performance(self, cpu_pct, m, used, nprocs):
        self.cpu_graph.push(cpu_pct)
        self.cpu_val.set_text(f"{cpu_pct:.0f}%")
        total = m["MemTotal"]
        self.mem_graph.push(100 * used / total)
        self.mem_val.set_text(fmt_bytes(used))
        self.mem_sub.set_text(f"of {fmt_bytes(total)} · {fmt_bytes(m.get('MemAvailable', total - used))} available for apps")
        st, sf = m.get("SwapTotal", 0), m.get("SwapFree", 0)
        self.swap_val.set_text(fmt_bytes(st - sf) if st else "Off")
        self.swap_sub.set_text(f"in use of {fmt_bytes(st)}" if st else "Turned off")
        self.swap_bar.set_value((st - sf) / st if st else 0)
        try:
            vfs = os.statvfs(os.path.expanduser("~"))
            dt, df = vfs.f_blocks * vfs.f_frsize, vfs.f_bavail * vfs.f_frsize
            self.disk_val.set_text(f"{fmt_bytes(dt - df)}")
            self.disk_sub.set_text(f"used of {fmt_bytes(dt)} · {fmt_bytes(df)} free")
            self.disk_bar.set_value((dt - df) / dt if dt else 0)
        except OSError:
            pass
        try:
            secs = int(float(open("/proc/uptime").read().split()[0]))
        except (OSError, ValueError):
            secs = 0
        h, mnt = secs // 3600, secs % 3600 // 60
        self.up_val.set_text(f"{h}h {mnt:02d}m" if h else f"{mnt} min")
        load = os.getloadavg()
        self.up_sub.set_text(f"{nprocs} processes · load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")


def main():
    GLib.set_prgname("wisp-taskmanager")
    GLib.set_application_name("Task Manager")
    apply_css()
    win = TaskManager(sys.argv[1] if len(sys.argv) > 1 else None)
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
