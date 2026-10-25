"""Application composition and install-process orchestration."""

import os
import signal

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import core, readiness
from .pages import (
    PAGE_ORDER,
    ConfirmPage,
    DestinationPage,
    DonePage,
    IdentityPage,
    ProgressPage,
    SetupPage,
    SourcePage,
    WelcomePage,
)
from .trawlline import TrawlLine


def spawn_fisherman(argv, stdin_data=b""):
    """Start the fisherman wrapper as the leader of its own process group,
    and hand it the recipe on stdin.

    The wrapper (flatpak-spawn, or sudo) is the only process in the install
    this user can signal; fisherman runs as root and cancels when its parent
    dies (tuna-os/fisherman#267). The contract every frontend follows is
    "kill your wrapper's process group", which needs the wrapper in a group
    of its own rather than the installer's. This frontend has no cancel UI,
    so nothing signals it yet.

    fisherman reads the recipe from stdin (`fisherman -`, #276) until EOF:
    `stdin_data` is written and the pipe closed here. A recipe is a few KiB,
    well under a pipe's buffer, so this does not wait for the polkit prompt.
    No file ever holds the passphrase or the user password.

    Returns (pid, stdout_fd, stderr_fd); the caller reaps the pid.
    """
    flags = GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.DO_NOT_REAP_CHILD
    pid, stdin_fd, out, err = GLib.spawn_async(
        argv, flags=flags, child_setup=os.setpgrp,
        standard_input=True, standard_output=True, standard_error=True)
    try:
        view = memoryview(stdin_data)
        while view:
            written = os.write(stdin_fd, view)
            view = view[written:]
    except OSError:
        # The wrapper is already gone; its exit status says why.
        pass
    finally:
        os.close(stdin_fd)
    return pid, out, err


class InstallerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=f"{core.PRODUCT_NAME} Installer",
                         default_width=640, default_height=520)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        self.trawl = TrawlLine(len(PAGE_ORDER))
        outer.pack_start(self.trawl, False, False, 6)

        self.stack = Gtk.Stack()
        outer.pack_start(self.stack, True, True, 0)

        nav = Gtk.Box(spacing=8, margin=12)
        self.back_btn = Gtk.Button(label="Back")
        self.next_btn = Gtk.Button(label="Next")
        self.back_btn.connect("clicked", lambda *_: self.go(-1))
        self.next_btn.connect("clicked", lambda *_: self.go(+1))
        nav.pack_end(self.next_btn, False, False, 0)
        nav.pack_end(self.back_btn, False, False, 0)
        outer.pack_end(nav, False, False, 0)
        # The wizard's own Back/Next bar. Hidden on the progress and done
        # pages: mid-install there is nowhere to go, and the done page has
        # its own Close and Restart now row (DonePage).
        self.nav = nav

        self.pages = {
            "welcome": WelcomePage(self), "source": SourcePage(self),
            "destination": DestinationPage(self), "setup": SetupPage(self),
            "identity": IdentityPage(self), "confirm": ConfirmPage(self),
            "progress": ProgressPage(self), "done": DonePage(self),
        }
        for name in PAGE_ORDER:
            self.stack.add_named(self.pages[name], name)
        self.index = 0
        self._log_tail = []
        self._install_log = None
        self.show_all()
        self._enter(0)

    def go(self, delta):
        self._enter(self.index + delta)

    def _enter(self, i):
        self.index = max(0, min(len(PAGE_ORDER) - 1, i))
        name = PAGE_ORDER[self.index]
        page = self.pages[name]
        self.stack.set_visible_child_name(name)
        self.trawl.set_step(self.index)
        page.on_enter()
        self.refresh_nav()

    def refresh_nav(self):
        if not getattr(self, "pages", None):
            return
        name = PAGE_ORDER[self.index]
        page = self.pages[name]
        # Back is hidden, not just greyed out, where it has no meaning: the
        # welcome page has nothing behind it, an install cannot be backed out
        # of, and the done page is the end. The other frontends hide it the
        # same way.
        terminal = name in ("progress", "done")
        self.back_btn.set_visible(self.index > 0 and not terminal)
        self.back_btn.set_sensitive(self.index > 0 and not terminal)
        self.next_btn.set_visible(not terminal)
        nav = getattr(self, "nav", None)
        if nav is not None:
            nav.set_visible(not terminal)
        self.next_btn.set_sensitive(page.can_continue())
        # Branding copy on the two buttons that carry a product's voice:
        # leaving the welcome page and starting the install.
        branded = {"welcome": "welcome_button", "confirm": "confirm_button"}.get(name)
        self.next_btn.set_label(core.BRANDING.text(branded) if branded else "Next")
        ctx = self.next_btn.get_style_context()
        if name == "confirm":
            ctx.add_class("destructive-action")
        else:
            ctx.remove_class("destructive-action")

    def selected_leaf(self):
        sel = self.pages["source"].selection() or {}
        return sel.get("leaf")

    def needs_user_creation(self):
        leaf = self.selected_leaf()
        return leaf.needs_user_creation if leaf else True

    def build_recipe(self):
        """Read page widgets and adapt their values to the core recipe API."""
        setup = self.pages["setup"]
        leaf = self.selected_leaf()
        disk = self.pages["destination"].selected_disk()
        identity = self.pages["identity"]
        return core.build_recipe(
            disk=disk["path"],
            filesystem=setup.default_filesystem(leaf.filesystem if leaf else ""),
            btrfs_subvolumes=setup.subvol_check.get_active(),
            encryption_type=setup.enc_type(),
            passphrase=setup.pass1.get_text(),
            image=leaf.imgref if leaf else "",
            hostname=identity.hostname.get_text(),
            bootloader=leaf.bootloader if leaf else "",
            composefs=leaf.composefs if leaf else False,
            flatpaks=leaf.flatpaks if leaf else "",
            needs_user=self.needs_user_creation(),
            username=identity.username.get_text(),
            fullname=identity.fullname.get_text(),
            password=identity.password.get_text(),
        )

    def start_install(self, progress_page):
        if core.dry_run():
            self._start_dry_run(progress_page)
            return

        recipe = self.build_recipe()
        argv = core.fisherman_argv()
        self._log_tail = []
        self._install_log = core.open_install_log()
        self._install_log.write(
            f"=== install started: {core.fisherman_shell()} (recipe on stdin) ===\n")
        self._install_log.flush()
        pid, out, err = spawn_fisherman(argv, core.recipe_stdin(recipe))
        for fd in (out, err):
            channel = GLib.IOChannel.unix_new(fd)
            channel.set_flags(GLib.IOFlags.NONBLOCK)
            GLib.io_add_watch(channel, GLib.IO_IN | GLib.IO_HUP,
                              self._on_output, progress_page)
        GLib.child_watch_add(pid, self._on_exit)

    def _start_dry_run(self, progress_page):
        """Play a fisherman transcript through the real progress page."""
        self._log_tail = []
        lines = list(core.DRY_RUN_TRANSCRIPT)

        def pump():
            if not lines:
                self.pages["done"].set_result(
                    True, "".join(self._log_tail),
                    progress_page.recovery_key())
                self._enter(PAGE_ORDER.index("done"))
                return False
            text = lines.pop(0)
            self._log_tail = (self._log_tail + [text])[-15:]
            progress_page.append_log(text)
            return True

        GLib.timeout_add(400, pump)

    def _on_output(self, channel, cond, page):
        if cond & GLib.IO_IN:
            _status, text, _length, _term = channel.read_line()
            if text:
                self._log_tail = (self._log_tail + [text])[-15:]
                if self._install_log:
                    self._install_log.write(text)
                    self._install_log.flush()
                page.append_log(text)
        return not (cond & GLib.IO_HUP)

    def _on_exit(self, pid, status, *_):
        GLib.spawn_close_pid(pid)
        ok = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
        if self._install_log:
            outcome = "ok" if ok else f"failed (status {status})"
            self._install_log.write(f"=== fisherman exited: {outcome} ===\n")
            self._install_log.close()
            self._install_log = None
        self.pages["done"].set_result(
            ok, "".join(self._log_tail),
            self.pages["progress"].recovery_key())
        self._enter(PAGE_ORDER.index("done"))


APP_ID = "org.tunaos.InstallerXfce"


class InstallerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or InstallerWindow(self)
        readiness.arm(win, APP_ID, page_getter=lambda: PAGE_ORDER[win.index])
        win.present()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    InstallerApp().run()
