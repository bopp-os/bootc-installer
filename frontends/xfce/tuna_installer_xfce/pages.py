"""TunaOS installer for XFCE — classic GTK3 wizard. Design: ../DESIGN.md.
Flow and recipe contract: ../../INSTALLER-FRONTENDS.md."""

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from . import core, fisherman_validate, progress_parser
from .logo import product_logo

# The recipe's encryption types, in display order: fisherman's
# encryption-choices.json (core.ENCRYPTION_CHOICES), which
# tests/unit/test_encryption_choices.py holds to fisherman's own file. What
# each one is called is branding copy, never a literal here.
ENCRYPTION_TYPES = tuple(c["type"] for c in core.ENCRYPTION_CHOICES)


def live_check(on_result):
    """`fisherman validate --json --partial -` for one page: debounced, off
    the UI thread, answered on it (shared/recipe/README.md)."""
    return fisherman_validate.LiveCheck(
        core.VALIDATE_ARGV, on_result, timeout_add=GLib.timeout_add,
        source_remove=GLib.source_remove, idle_add=GLib.idle_add)


def problem_label():
    """The line under a field that shows fisherman's problem with it."""
    label = Gtk.Label(xalign=0)
    label.set_line_wrap(True)
    label.set_no_show_all(True)
    label.get_style_context().add_class("error")
    return label


def show_problem(label, problem):
    """Show `problem` (or nothing) in `label`: the copy key
    validate_<code>, or fisherman's message for a code with no copy."""
    if problem is None:
        label.set_text("")
        label.hide()
        return
    label.set_text(fisherman_validate.render(problem, core.BRANDING.text))
    label.show()


def encryption_text(enc_type, suffix):
    """The copy line for an encryption type; suffix is _label or _description
    (shared/branding/README.md, "Encryption choices")."""
    return core.BRANDING.text("encryption_" + enc_type.replace("-", "_") + suffix)


def _page_title(text):
    label = Gtk.Label(xalign=0)
    label.set_markup(f"<big><b>{GLib.markup_escape_text(text)}</b></big>")
    label.set_margin_bottom(12)
    return label


def _warn_row(text):
    box = Gtk.Box(spacing=8)
    box.pack_start(Gtk.Image.new_from_icon_name("dialog-warning", Gtk.IconSize.MENU), False, False, 0)
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.set_line_wrap(True)
    box.pack_start(lbl, True, True, 0)
    return box


class Page(Gtk.Box):
    """One wizard page: vertical box, 12px spacing, knows if it can advance."""

    title = ""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin=18)
        self.win = win
        if self.title:
            self.pack_start(_page_title(self.title), False, False, 0)

    def can_continue(self):
        return True

    def on_enter(self):
        pass


class WelcomePage(Page):
    # Flavour text is branding copy (shared/branding): the product's own
    # welcome line first, then what this assistant does.
    title = core.BRANDING.text("welcome_title")

    def __init__(self, win):
        super().__init__(win)
        self.logo = product_logo(core.BRANDING.logo, core.IN_FLATPAK)
        self.pack_start(self.logo, False, False, 0)
        self.reorder_child(self.logo, 0)
        subtitle = core.BRANDING.text("welcome_subtitle")
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0)
            sub.set_line_wrap(True)
            self.pack_start(sub, False, False, 0)
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_text(
            f"This assistant installs {core.PRODUCT_NAME} on this computer.\n\n"
            "You'll choose what to install and where; nothing is written to "
            "any disk until you confirm on the final step.")
        self.pack_start(body, False, False, 0)
        # fisherman's minimum requirements (RAM, CPU cores, UEFI). A warning,
        # not a gate: GNOME blocks, the other frontends warn and continue
        # (shared/probe/README.md).
        warning = core.requirements_warning()
        if warning:
            self.pack_start(_warn_row(warning), False, False, 0)


class SourcePage(Page):
    title = "What do you want to install?"

    def __init__(self, win):
        super().__init__(win)
        # Live media and the offline images are fisherman's facts (probe's
        # `live` and `offline`), read on the host.
        self.live = core.is_live()
        self.live_image = core.live_image()
        self.offline_refs = core.offline_images()
        _, _, self.catalog = core.load_catalog()
        self.leaves = [l for root in self.catalog for l in root.leaves()]

        self.radios = []
        group = None

        def add_radio(label_text, sub, payload, offline):
            nonlocal group
            radio = Gtk.RadioButton.new_with_label_from_widget(group, label_text)
            group = group or radio
            radio.payload = payload
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.pack_start(radio, False, False, 0)
            subline = Gtk.Label(xalign=0)
            tagged = f"{sub}   [available offline]".strip() if offline else sub
            subline.set_markup(
                f"<small><tt>{GLib.markup_escape_text(tagged)}</tt></small>")
            subline.set_margin_start(26)
            box.pack_start(subline, False, False, 0)
            self.listbox.pack_start(box, False, False, 4)
            self.radios.append(radio)

        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.listbox)
        self.pack_start(scroll, True, True, 0)

        if self.live:
            # The same row GNOME shows: welcome_install and its subtitle. The
            # "[available offline]" tag already says no download is needed.
            add_radio(core.BRANDING.text("welcome_install") + " (this system)",
                      core.BRANDING.text("welcome_install_subtitle"), {"live": True}, True)

        def sort_key(leaf):
            return (leaf.imgref not in self.offline_refs, leaf.name)

        for leaf in sorted(self.leaves, key=sort_key):
            add_radio(leaf.name, leaf.imgref, {"leaf": leaf},
                      leaf.imgref in self.offline_refs)
        if not self.radios:
            self.pack_start(_warn_row(
                "No image catalog found and this is not a live system. "
                "Check that fisherman's images.json is installed."), False, False, 0)
        self.listbox.show_all()

    def can_continue(self):
        return bool(self.radios)

    def selection(self):
        for r in self.radios:
            if r.get_active():
                return r.payload
        return None


def disk_label(disk):
    """One destination row: the title (model, else path), then the path,
    fisherman's size label and the bus, in the order every frontend uses."""
    bits = [disk["title"], disk["path"], disk["size_label"], disk["transport_label"]]
    return "    ".join(b for b in bits if b)


class DestinationPage(Page):
    title = f"Where should {core.PRODUCT_NAME} be installed?"

    def __init__(self, win):
        super().__init__(win)
        self.radios = []
        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pack_start(self.listbox, False, False, 0)
        self.warn = _warn_row("")
        self.warn_label = self.warn.get_children()[1]
        self.pack_end(self.warn, False, False, 0)

    def on_enter(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.radios = []
        group = None
        disks, error = core.candidate_disks()
        for disk in disks:
            radio = Gtk.RadioButton.new_with_label_from_widget(group, disk_label(disk))
            group = group or radio
            radio.disk = disk
            radio.connect("toggled", self._update_warning)
            self.listbox.pack_start(radio, False, False, 4)
            self.radios.append(radio)
        if not disks:
            self.listbox.pack_start(_warn_row(
                f"Could not detect disks: {error}" if error else
                "No disk of at least 50 GiB was found. Connect one to install to."),
                False, False, 4)
        self.listbox.show_all()
        self._update_warning()

    def _update_warning(self, *_):
        d = self.selected_disk()
        if d:
            self.warn_label.set_text(
                f"Everything on {d['title']} ({d['path']}) will be erased.")
        self.warn.set_visible(d is not None)

    def can_continue(self):
        return self.selected_disk() is not None

    def selected_disk(self):
        for r in self.radios:
            if r.get_active():
                return r.disk
        return None


FILESYSTEMS = ("xfs", "ext4", "btrfs", "zfs")


class SetupPage(Page):
    # "Disk encryption" is a keyword of the shared screen contract
    # (shared/walkthrough/parity_report.py). With the old title, "Filesystem
    # and encryption", this page matched nothing and the parity matrix showed
    # XFCE as the one frontend without an encryption screen it plainly has.
    title = "Disk encryption"

    def __init__(self, win):
        super().__init__(win)
        self.has_tpm = core.has_tpm()

        self.enc_radios = []
        group = None
        for value in ENCRYPTION_TYPES:
            if core.needs_tpm2(value) and not self.has_tpm:
                continue
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, encryption_text(value, "_label"))
            group = group or radio
            radio.value = value
            radio.connect("toggled", self._sync)
            self.pack_start(radio, False, False, 0)
            sub = Gtk.Label(xalign=0)
            sub.set_markup("<small>" + GLib.markup_escape_text(
                encryption_text(value, "_description")) + "</small>")
            sub.set_margin_start(26)
            self.pack_start(sub, False, False, 0)
            self.enc_radios.append(radio)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6, margin_top=6)
        self.pass1 = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        self.pass2 = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        for e in (self.pass1, self.pass2):
            e.connect("changed", self._sync)
        grid.attach(Gtk.Label(label="Passphrase", xalign=0), 0, 0, 1, 1)
        grid.attach(self.pass1, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Confirm", xalign=0), 0, 1, 1, 1)
        grid.attach(self.pass2, 1, 1, 1, 1)
        self.pass_grid = grid
        self.pack_start(grid, False, False, 0)
        # fisherman's answer for the encryption and filesystem choice: an
        # empty passphrase, or LUKS on ZFS (encryption.*, filesystem).
        self.problem = None
        self.problem_label = problem_label()
        self.pack_start(self.problem_label, False, False, 0)
        self.check = live_check(self._on_checked)
        # Checked from the first visit on: before it, the window has no
        # image selection to take the filesystem from.
        self._entered = False

        adv = Gtk.Expander(label="Advanced")
        advbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        self.fs_combo = Gtk.ComboBoxText()
        for fs in FILESYSTEMS:
            self.fs_combo.append(fs, fs)
        # Whether the person picked a filesystem. Until they do, the combo
        # follows the selected image's catalog default (on_enter), and that
        # default is what goes in the recipe.
        self._fs_chosen = False
        self._fs_syncing = False
        self._show_filesystem("xfs")
        self.fs_combo.connect("changed", self._on_fs_changed)
        fsrow = Gtk.Box(spacing=8)
        fsrow.pack_start(Gtk.Label(label="Filesystem", xalign=0), False, False, 0)
        fsrow.pack_start(self.fs_combo, False, False, 0)
        advbox.pack_start(fsrow, False, False, 0)
        self.subvol_check = Gtk.CheckButton(label="Create btrfs subvolumes (@, @home, @snapshots)")
        advbox.pack_start(self.subvol_check, False, False, 0)
        adv.add(advbox)
        self.pack_start(adv, False, False, 0)
        self._sync()

    def _sync(self, *_):
        self.pass_grid.set_sensitive(core.needs_passphrase(self.enc_type()))
        self.win.refresh_nav()
        if getattr(self, "check", None) is not None and self._entered:
            self.check.submit(self.partial_recipe())

    def partial_recipe(self):
        leaf = self.win.selected_leaf()
        enc = {"type": self.enc_type()}
        if core.needs_passphrase(enc["type"]):
            enc["passphrase"] = self.pass1.get_text()
        return {"filesystem": self.default_filesystem(leaf.filesystem if leaf else ""),
                "encryption": enc}

    def _on_checked(self, problems, error):
        problems = problems or []
        self.problem = next((p for p in problems if p.get("field", "").startswith(
            ("encryption", "filesystem"))), None)
        show_problem(self.problem_label, self.problem)
        self.win.refresh_nav()

    def enc_type(self):
        for r in self.enc_radios:
            if r.get_active():
                return r.value
        return "none"

    def can_continue(self):
        # The passphrase rule (not empty) is fisherman's; that the two
        # entries match is this page's.
        if self.problem is not None:
            return False
        if core.needs_passphrase(self.enc_type()):
            p1, p2 = self.pass1.get_text(), self.pass2.get_text()
            return bool(p1) and p1 == p2
        return True

    def _show_filesystem(self, fs):
        """Select fs in the combo without counting it as the person's pick."""
        if fs not in FILESYSTEMS and self.fs_combo.get_model() is not None:
            ids = [row[1] for row in self.fs_combo.get_model()]
            if fs not in ids:
                self.fs_combo.append(fs, fs)
        self._fs_syncing = True
        try:
            self.fs_combo.set_active_id(fs)
        finally:
            self._fs_syncing = False

    def _on_fs_changed(self, *_):
        if not self._fs_syncing:
            self._fs_chosen = True
            self._sync()

    def on_enter(self):
        if not self._fs_chosen:
            leaf = self.win.selected_leaf()
            self._show_filesystem((leaf.filesystem if leaf else "") or "xfs")
        self._entered = True
        self.check.submit(self.partial_recipe())

    def default_filesystem(self, leaf_default):
        # Catalog default wins unless the user touched Advanced. This used to
        # be `get_active_id() or leaf_default`, but the combo always had
        # "xfs" active, so the catalog default could never apply.
        if self._fs_chosen:
            return self.fs_combo.get_active_id() or leaf_default or "xfs"
        return leaf_default or "xfs"


class IdentityPage(Page):
    title = "Name this computer"

    def __init__(self, win):
        super().__init__(win)
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self.hostname = Gtk.Entry(text=core.BRANDING.default_hostname)
        grid.attach(Gtk.Label(label="Hostname", xalign=0), 0, 0, 1, 1)
        grid.attach(self.hostname, 1, 0, 1, 1)
        self.hostname_problem = problem_label()
        grid.attach(self.hostname_problem, 1, 1, 1, 1)
        self.pack_start(grid, False, False, 0)

        self.user_frame = Gtk.Frame(label="Your account", margin_top=8)
        ug = Gtk.Grid(column_spacing=12, row_spacing=6, margin=10)
        self.username = Gtk.Entry()
        self.fullname = Gtk.Entry()
        self.password = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        for i, (lbl, entry) in enumerate((("Username", self.username),
                                          ("Full name", self.fullname),
                                          ("Password", self.password))):
            ug.attach(Gtk.Label(label=lbl, xalign=0), 0, i * 2, 1, 1)
            ug.attach(entry, 1, i * 2, 1, 1)
            entry.connect("changed", lambda *_: win.refresh_nav())
        self.username_problem = problem_label()
        ug.attach(self.username_problem, 1, 1, 1, 1)
        self.user_frame.add(ug)
        self.pack_start(self.user_frame, False, False, 0)

        # The hostname and username rules are fisherman's
        # (`fisherman validate --json --partial -`). The hostname used to be
        # a single-label pattern here with no length limit, and the username
        # was not checked at all, so "root" failed after the OS was on disk.
        self.problems = {}
        self.check = live_check(self._on_checked)
        for entry in (self.hostname, self.username):
            entry.connect("changed", lambda *_: self.check.submit(self.partial_recipe()))

    def partial_recipe(self):
        partial = {"hostname": self.hostname.get_text()}
        if self.win.needs_user_creation():
            partial["user"] = {"username": self.username.get_text()}
        return partial

    def _on_checked(self, problems, error):
        problems = problems or []
        self.problems = {f: next((p for p in problems if p.get("field") == f), None)
                         for f in ("hostname", "user.username")}
        show_problem(self.hostname_problem, self.problems["hostname"])
        show_problem(self.username_problem, self.problems["user.username"])
        self.win.refresh_nav()

    def on_enter(self):
        self.user_frame.set_visible(self.win.needs_user_creation())
        self.check.submit(self.partial_recipe())

    def can_continue(self):
        if self.problems.get("hostname") is not None:
            return False
        if self.win.needs_user_creation():
            # A user is required for this image (needs_user_creation), and
            # the password rule is this page's; fisherman accepts any.
            return (bool(self.username.get_text()) and bool(self.password.get_text())
                    and self.problems.get("user.username") is None)
        return True


class ConfirmPage(Page):
    title = core.BRANDING.text("confirm_title")

    def __init__(self, win):
        super().__init__(win)
        # confirm_subtitle and confirm_body are the product's own lines
        # (a quote, a tagline); empty in the neutral defaults, so hidden.
        self.subtitle = Gtk.Label(xalign=0)
        self.subtitle.set_line_wrap(True)
        self.subtitle.set_no_show_all(True)
        self.pack_start(self.subtitle, False, False, 0)
        self.summary = Gtk.Label(xalign=0)
        self.summary.set_line_wrap(True)
        self.pack_start(self.summary, False, False, 0)
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.body.set_no_show_all(True)
        self.pack_start(self.body, False, False, 0)
        # confirm_warning names the disk that is about to be erased; on_enter
        # fills in the selected one's path, as KDE, COSMIC and Niri do.
        self.warn_label = _warn_row(core.BRANDING.text("confirm_warning", disk="the selected disk"))
        self.warn_text = self.warn_label.get_children()[1]
        self.pack_start(self.warn_label, False, False, 0)
        for widget, key in ((self.subtitle, "confirm_subtitle"), (self.body, "confirm_body")):
            line = core.BRANDING.text(key)
            widget.set_text(line)
            widget.set_visible(bool(line))

    def on_enter(self):
        r = self.win.build_recipe()
        disk = r.get("disk") or self.win.pages["destination"].selected_disk()["path"]
        # The same rows, in the same order, as KDE's confirm step.
        rows = [
            ("Target disk", disk),
            ("Filesystem", r["filesystem"]),
            ("Encryption", encryption_text(r["encryption"]["type"] or "none", "_label")),
            ("Hostname", r["hostname"]),
            ("Image", r.get("image") or self.win.pages["source"].live_image
             or "this live system"),
        ]
        if r.get("user", {}).get("username"):
            rows.append(("User", r["user"]["username"]))
        width = max(len(k) for k, _ in rows) + 2
        lines = [f"{k + ':':<{width}}{v}" for k, v in rows]
        self.summary.set_markup("<tt>" + GLib.markup_escape_text("\n".join(lines)) + "</tt>")
        self.warn_text.set_text(core.BRANDING.text("confirm_warning", disk=disk))


class ProgressPage(Page):
    title = core.BRANDING.text("progress_title")

    def __init__(self, win):
        super().__init__(win)
        self.steplabel = Gtk.Label(xalign=0)
        self.pack_start(self.steplabel, False, False, 0)
        self.bar = Gtk.ProgressBar(show_text=True)
        self.pack_start(self.bar, False, False, 0)
        # progress_note ("Do not power off the computer.") -- the one warning
        # that matters while the disk is being written. Empty hides it.
        self.note = Gtk.Label(label=core.BRANDING.text("progress_note"), xalign=0)
        self.note.get_style_context().add_class("dim-label")
        self.note.set_no_show_all(not self.note.get_text())
        self.pack_start(self.note, False, False, 0)
        # Multi-line parser context (current step, weight, seen substeps).
        self._progress = progress_parser.new_progress_state()
        # The one step label that names the product ("Installing {product}…")
        # must say what this build installs, not a hardcoded distro. The
        # parser defaults to a neutral "the OS" until told otherwise.
        progress_parser.set_product_name(core.PRODUCT_NAME)
        progress_parser.set_install_label(core.BRANDING.text("progress_title"))
        # fisherman names each step with a stable step_id; its label is the
        # copy key "step_<id>". An id the copy does not know reads "" and
        # the parser falls back to the step name.
        progress_parser.set_step_label_resolver(
            lambda step_id: core.BRANDING.text("step_" + step_id))
        # Log visible by default — XFCE users want the output (DESIGN.md).
        self.logview = Gtk.TextView(editable=False, monospace=True)
        self.logview.modify_font(Pango.FontDescription("monospace 9"))
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.add(self.logview)
        self.pack_start(scroll, True, True, 0)

    def on_enter(self):
        self.win.start_install(self)

    def append_log(self, text):
        buf = self.logview.get_buffer()
        for line in text.splitlines():
            # fisherman's protocol is machine-readable; this pane is not. The
            # raw line still goes to the log FILE (app.py) — that is what gets
            # pasted into bug reports — but a human reads this one.
            shown = progress_parser.render_event(line)
            if shown is None:
                shown = line
            buf.insert(buf.get_end_iter(), shown + "\n")
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self.logview.scroll_mark_onscreen(mark)
        # The bar is driven by fisherman's newline-delimited JSON progress
        # protocol (shared/progress/README.md), parsed by the shared parser.
        #
        # This used to be `re.search(r"\[(\d)/9\]", text)` against a
        # hardcoded nine-entry step table. fisherman has never written that
        # prefix — it emits JSON on stdout and nothing else — so the bar sat
        # at zero and the step label stayed empty for the whole of every real
        # install. The screenshot harness did not catch it because the dry-run
        # transcript in core.py was itself written in the "[n/9]" shape, so
        # the only thing the parser ever matched was the fixture written to
        # match the parser.
        #
        # The step COUNT was wrong too, independently: fisherman computes
        # total_steps (8, adjusted for manual layout, LUKS, TPM2 enrolment and
        # a separate /var disk — cmd/fisherman/main.go), so it is 9 only by
        # coincidence. The protocol carries cumulative_pct precisely so no
        # frontend has to model the pipeline; this reads it instead of
        # counting steps. Current fisherman goes further and sends the bar
        # itself as overall_pct, which the parser prefers; the cumulative_pct
        # derivation is the fallback for an older fisherman.
        for line in text.splitlines():
            update = progress_parser.apply_progress_event(line, self._progress)
            if update is None:
                continue
            if update["label"] is not None:
                # The step label sits directly under the page title, and for
                # the install step the branding's "progress_title" and the
                # parser's "Installing {product}…" are the same sentence — so
                # the screen said it twice, for the 87% of the install that
                # step covers. Blank rather than stale: repeating the previous
                # step's name would be a lie about what is running.
                dup = update["label"].rstrip("…. ") == self.title.rstrip("…. ")
                self.steplabel.set_text("" if dup else update["label"])
            if update["fraction"] is not None:
                frac = update["fraction"]
                self.bar.set_fraction(frac)
                self.win.trawl.set_fill(frac)

    def recovery_key(self):
        """The key fisherman emitted, or "" for a non-TPM install.

        The parser has tracked this all along (shared/progress/README.md);
        nothing read it, which is how it stayed a log line only.
        """
        return self._progress.get("recovery_key", "")

    def can_continue(self):
        return False  # navigation unlocked by install completion


class DonePage(Page):
    def __init__(self, win):
        super().__init__(win)
        self.logo = product_logo(core.BRANDING.logo, core.IN_FLATPAK)
        self.logo.hide()
        self.pack_start(self.logo, False, False, 0)
        self.headline = _page_title("")
        self.pack_start(self.headline, False, False, 0)
        self.body = Gtk.Label(xalign=0)
        self.body.set_line_wrap(True)
        self.pack_start(self.body, False, False, 0)
        # store_label -> store_url on every frontend when the branding sets a
        # store (docs/PARITY.md); hidden otherwise.
        self.store_btn = Gtk.LinkButton(uri=core.BRANDING.store_url,
                                        label=core.BRANDING.text("store_label"))
        self.store_btn.set_no_show_all(True)
        self.pack_start(self.store_btn, False, False, 0)
        # Recovery key (#129). fisherman emits it once, after TPM enrolment,
        # and for a tpm2-luks install it is the only way back into the disk
        # if the TPM state changes. Writing it to the log pane was the
        # mitigation; the log scrolls and nothing pauses, so a user could
        # reach this page and reboot having never seen it.
        #
        # This is a panel rather than the modal #129 suggested: a dialog is
        # dismissed and then the key is gone, while this keeps it on screen
        # for as long as it takes to write down. The gate is on the reboot
        # button, which is the action that ends the chance to read it.
        self.recovery_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.recovery_box.set_no_show_all(True)
        self.recovery_title = _page_title("")
        self.recovery_box.pack_start(self.recovery_title, False, False, 0)
        self.recovery_body = Gtk.Label(xalign=0)
        self.recovery_body.set_line_wrap(True)
        self.recovery_box.pack_start(self.recovery_body, False, False, 0)
        self.recovery_key_label = Gtk.Label(xalign=0, selectable=True)
        self.recovery_key_label.set_line_wrap(True)
        self.recovery_key_label.modify_font(Pango.FontDescription("monospace 11"))
        self.recovery_box.pack_start(self.recovery_key_label, False, False, 0)
        self.recovery_copy_btn = Gtk.Button(
            label=core.BRANDING.text("recovery_key_copy"))
        self.recovery_copy_btn.connect("clicked", self.__on_copy)
        self.recovery_box.pack_start(self.recovery_copy_btn, False, False, 0)
        self.recovery_ack = Gtk.CheckButton(
            label=core.BRANDING.text("recovery_key_ack"))
        self.recovery_ack.connect("toggled", self.__on_ack)
        self.recovery_box.pack_start(self.recovery_ack, False, False, 0)
        self.pack_start(self.recovery_box, False, False, 8)

        # The page's own action row, where the wizard's Back/Next bar sits on
        # every other page (the window hides that bar here): Close, and
        # Restart now -- held while a recovery key is unacknowledged.
        actions = Gtk.Box(spacing=8)
        self.reboot_btn = Gtk.Button(label=core.BRANDING.text("done_restart") or "Restart now")
        self.reboot_btn.get_style_context().add_class("suggested-action")
        self.reboot_btn.connect("clicked", lambda *_: core.host_run(["systemctl", "reboot"]))
        self.close_btn = Gtk.Button(label="Close")
        self.close_btn.connect("clicked", self.__on_close)
        actions.pack_end(self.reboot_btn, False, False, 0)
        actions.pack_end(self.close_btn, False, False, 0)
        self.pack_end(actions, False, False, 0)

    def __on_close(self, *_):
        top = self.get_toplevel()
        if isinstance(top, Gtk.Window):
            top.close()

    def __on_copy(self, *_):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self.recovery_key_label.get_text(), -1)

    def __on_ack(self, check):
        self.reboot_btn.set_sensitive(check.get_active())

    def show_recovery_key(self, key):
        """Reveal the panel and gate reboot behind the acknowledgement.

        No key means no panel and no gate: a non-TPM install must not be
        asked to tick a box about a key it was never given.
        """
        key = (key or "").strip()
        self.recovery_box.set_visible(bool(key))
        if not key:
            self.reboot_btn.set_sensitive(True)
            return
        self.recovery_title.set_markup("<big><b>" + GLib.markup_escape_text(
            core.BRANDING.text("recovery_key_title")) + "</b></big>")
        self.recovery_body.set_text(core.BRANDING.text("recovery_key_body"))
        self.recovery_key_label.set_text(key)
        self.recovery_ack.set_active(False)
        self.reboot_btn.set_sensitive(False)
        # show_all() is a no-op while no_show_all is set -- that flag exists
        # to stop the window's own show_all() revealing the panel on a
        # non-TPM install. Lift it for this one call, or the box appears with
        # none of its children in it: the capture drew an empty panel and the
        # key never reached the screen.
        self.recovery_box.set_no_show_all(False)
        self.recovery_box.show_all()
        self.recovery_box.set_no_show_all(True)

    def set_result(self, ok, log_tail, recovery_key=""):
        # A failed install never enrolled a TPM, so there is no key to show.
        self.show_recovery_key(recovery_key if ok else "")
        self.logo.set_visible(ok and self.logo.get_pixbuf() is not None)
        if ok:
            self.headline.set_markup("<big><b>" + GLib.markup_escape_text(
                core.BRANDING.text("done_title")) + "</b></big>")
            self.body.set_text(core.BRANDING.text("done_subtitle"))
            self.store_btn.set_visible(bool(core.BRANDING.store_url))
            self.reboot_btn.show()
        else:
            self.headline.set_markup("<big><b>" + GLib.markup_escape_text(
                core.BRANDING.text("done_failed_title")) + "</b></big>")
            self.body.set_text(
                "The last lines of the install log:\n\n" + log_tail +
                "\n\nFull log: " + core.install_log_path())
            self.reboot_btn.hide()


PAGE_ORDER = ["welcome", "source", "destination", "setup", "identity",
              "confirm", "progress", "done"]
