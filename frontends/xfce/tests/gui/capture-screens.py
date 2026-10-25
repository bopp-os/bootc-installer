#!/usr/bin/env python3
"""Render every wizard page to PNG, plus an animated walkthrough, for
docs/gui-walkthrough.md and the README.

Runs headless under Xvfb with no desktop, no GPU and no real disks: the app's
pages are built against fixtures, driven through the real InstallerWindow, and
grabbed from the X server.

Nothing here touches a disk. The disks, TPM and requirements come from the
shared probe fixture (BOOTC_INSTALLER_FAKE_PROBE, shared/probe/README.md), so
the destination page shows a plausible machine that does not exist, and
core.host_run answers every other host query with nothing.

    xvfb-run -a python3 tests/gui/capture-screens.py [outdir]
"""

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

# SAFETY INTERLOCK — set before ANY tuna_installer_xfce import, and first
# because this is the one line whose absence costs a disk rather than a
# screenshot. ProgressPage.on_enter() calls win.start_install() with no
# confirmation in between, so navigating this wizard to the progress page runs
# fisherman as root. core.dry_run() makes that a no-op that plays a transcript
# instead; the full reasoning is in tuna_installer_xfce/core.py, and the check
# that this actually took effect is further down.
os.environ.setdefault("TUNA_INSTALLER_DRY_RUN", "1")

# ── fixtures, installed BEFORE the app imports anything ──────────────────────

CATALOG = {
    "default_image": "ghcr.io/tuna-os/bonito:latest",
    "fallback_flatpaks": [],
    "images": [
        {
            "name": "TunaOS", "registry": "ghcr.io/tuna-os/bonito",
            "desc": "The default TunaOS image.",
            "bootloader": "systemd", "filesystem": "btrfs", "composefs": True,
            "children": [
                {"name": "GNOME", "tag": "latest",
                 "subtitle": "The standard desktop",
                 "desc": "A clean GNOME desktop. The best-tested option."},
                {"name": "KDE Plasma", "tag": "kde",
                 "subtitle": "More to configure",
                 "desc": "KDE Plasma, for a more customisable desktop."},
            ],
        },
        {
            "name": "Bluefin", "registry": "ghcr.io/ublue-os/bluefin",
            "desc": "Universal Blue's developer image.",
            "bootloader": "grub2", "filesystem": "xfs",
            "children": [
                {"name": "Bluefin", "tag": "latest",
                 "subtitle": "Developer-focused",
                 "desc": "Tracks upstream Universal Blue closely."},
            ],
        },
    ],
}

_tmp = tempfile.mkdtemp(prefix="tuna-shots-")
_catalog_path = os.path.join(_tmp, "images.json")
with open(_catalog_path, "w") as fh:
    json.dump(CATALOG, fh)
os.environ["FISHERMAN_IMAGES_PATH"] = _catalog_path
os.environ.setdefault("XDG_RUNTIME_DIR", _tmp)
os.environ.setdefault("GTK_A11Y", "none")

# Product branding is resolved from the host's os-release, so an unpinned
# capture is BRANDED BY THE RUNNER: on a GitHub ubuntu-24.04 box the wizard
# renders "Welcome to Ubuntu 24.04.4 LTS", and the main-branch job commits
# those PNGs into docs/. Pin it so the committed walkthrough is stable and
# says the family name, exactly as it did before branding became dynamic.
# On a real Skipjack ISO the same attributes read "Skipjack" instead.
#
# This has to happen BEFORE tuna_installer_xfce.core is imported: core
# resolves the whole Branding object once at import and every copy key is
# formatted from it. Setting core.PRODUCT_NAME afterwards pinned only the
# one f-string that reads it, which is why the committed walkthrough said
# "Welcome to Ubuntu 24.04.5 LTS This assistant installs TunaOS" -- the
# runner's name and the pinned one, in the same sentence.
#
# Pin the whole object rather than BOOTC_INSTALLER_PRODUCT_NAME, which covers
# `name` alone and leaves os-release's LOGO and assets showing through.
# setdefault, so a workflow pointing at a real product's file still wins.
# REPO here is the frontend tree, not the monorepo root, so reach the shared
# file the same way tests/gui/parity_report.py does.
os.environ.setdefault("BOOTC_INSTALLER_BRANDING", os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "shared", "walkthrough", "capture-branding.json")))

# The hardware: fisherman's probe answer for a laptop (shared/probe/fixtures),
# the same fixture every frontend's capture reads. Its TPM 2.0 is usable, so
# the TPM encryption choices show: without one, which no CI runner has, the
# page renders two options and docs/PARITY.md -- read off these screenshots --
# once recorded this frontend as having no TPM support at all.
os.environ.setdefault("BOOTC_INSTALLER_FAKE_PROBE", os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "shared", "probe", "fixtures", "laptop.json")))

# SAFETY, and not a small one. ProgressPage.on_enter() calls
# win.start_install(), so simply navigating the wizard to the progress page
# LAUNCHES A REAL INSTALL — there is no confirmation between the two. A capture
# script that drove pages the obvious way would try to partition the runner's
# disk.
#
# This used to be `InstallerWindow.start_install = lambda self, page: None`,
# applied before any page was shown. That protected THIS script and nothing
# else: a monkeypatch in one test file is invisible to anything driving the
# real binary, which is exactly what the live-ISO walkthrough harness in
# tuna-os/tunaOS does over a QEMU keyboard with no ability to patch anything.
#
# The interlock now lives in the app (core.dry_run(), honoured as the first
# statement of start_install), so it protects every caller. It is read at CALL
# time, so import order cannot defeat it — but the assignment stays up here
# above every import anyway, because the cost of being wrong about this is a
# disk rather than a screenshot.

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from tuna_installer_xfce import core  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parity_report  # noqa: E402


class _Result:
    def __init__(self, stdout): self.returncode, self.stdout, self.stderr = 0, stdout, ""


def _fake_host_run(argv, **kwargs):
    """Every other host query in core goes through host_run. Anything returns
    empty rather than reaching the host."""
    return _Result("")


core.host_run = _fake_host_run
# The probe fixture is a laptop booted from a live USB. This walkthrough
# shows the catalog as an installed session sees it, as it always has: not
# live media, nothing offline (both are the probe's `live` and `offline`).
core.is_live = lambda: False
core.live_image = lambda: ""
core.offline_images = lambda: set()

from tuna_installer_xfce.app import PAGE_ORDER, InstallerWindow  # noqa: E402,F401

# Guard on the guard, in the spirit of tuna-installer-cosmic's
# TUNA_BLANK_SELFTEST. The whole safety of this script rests on one check in
# another module, and the failure mode if it silently stops being read is not a
# broken screenshot — it is a partitioned runner disk. So refuse to show a
# single page unless the interlock is demonstrably live.
#
# It has already earned its keep: on the first attempt this fired in CI (run
# 31271258293) because the env var was set HERE, below the `from
# tuna_installer_xfce import core` above, while core evaluated it at import
# time. The guard turned an ordering mistake into a failed job instead of an
# install. core.dry_run() is now read at call time so that ordering cannot
# matter, and the assignment moved to the top of the file so it does not
# matter twice.
if not core.dry_run():
    sys.exit(
        "refusing to run: core.dry_run() is False, so navigating to the "
        "progress page would start a REAL install. TUNA_INSTALLER_DRY_RUN is "
        "set at the top of this file; if core no longer honours it, fix the "
        "interlock rather than this check."
    )

CAPTIONS = {
    "welcome": "What the assistant is about to do.",
    "source": "Choose an image to install.",
    "destination": "Choose the disk. Nothing is written yet.",
    "setup": "Disk encryption; filesystem under Advanced.",
    "identity": "Your account and computer name.",
    "confirm": "The last screen before anything is written.",
    "progress": "The install, step by step.",
    "done": "Finished — restart into the new system.",
    "recovery": "A TPM install: the recovery key, and reboot held until it "
                "is acknowledged.",
}

# fisherman emits this once, after TPM enrolment, and it is the only way back
# into the disk if the TPM state changes (#129). No CI runner does a TPM
# install, so the event is synthesised here -- but it is fed through the SAME
# parser a real install goes through, not written into the widget. A capture
# that seeded the label directly would keep passing if the parse broke, which
# is the failure this harness has spent four PRs removing.
RECOVERY_EVENT = json.dumps({
    "type": "recovery_key",
    "key": "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf",
    "timestamp": "2026-01-01T00:00:00Z",
    "elapsed_ms": 1000,
})


# The install screen, caught in flight: the real dry-run transcript
# (tuna_installer_xfce/dry-run-transcript.ndjson) truncated part-way through
# the image pull, so the bar sits mid-way rather than at either end.
#
# This was nine hand-written "[n/9] " lines naming a specific image ref. Both
# were wrong: fisherman emits newline-delimited JSON and never that prefix
# (so the bar in the captured screenshot moved only because the fixture was
# written to match the frontend's own regex), and naming a product in a
# fixture puts that product's image ref in the rendered docs for every
# downstream that rebrands this installer.
def _fixture_log():
    lines = core.DRY_RUN_TRANSCRIPT
    cut = next(i for i, ln in enumerate(lines) if "47/71" in ln) + 1
    return "".join(lines[:cut])


FIXTURE_LOG = _fixture_log()


def _seed_progress(page):
    """Fill the progress screen with a believable install in flight.

    append_log() drives the step label and progress bar by parsing fisherman's
    JSON progress protocol (shared/progress/README.md), so feeding it the real
    transcript exercises the same code path a live install would — which is
    the whole point of capturing this screen.
    """
    for line in FIXTURE_LOG.splitlines(keepends=True):
        page.append_log(line)

    # Did the transcript actually reach the bar?
    #
    # The pixel audit cannot answer this: it measures ink over the whole
    # frame, and this page has a title and a log full of text regardless. The
    # KDE frontend shipped a progress bar that laid out at full width,
    # reported itself visible and opaque, painted nothing, and passed every
    # check in this repository including its own capture job — because a page
    # with a populated log looks populated either way.
    #
    # A fraction of zero here means append_log() stopped driving the bar,
    # which is the bug that had this frontend and Niri rendering an empty bar
    # for every real install while their fixtures, written in the same
    # invented shape, photographed one moving.
    fraction = page.bar.get_fraction()
    print(f"    progress bar at {fraction:.1%}")
    if fraction <= 0.0:
        sys.exit("FAIL: the progress bar is at 0% after the whole transcript "
                 "— append_log is not driving it (shared/progress/README.md)")
    if not page.bar.get_visible():
        sys.exit("FAIL: the progress bar is not visible")


def _drain():
    for _ in range(200):
        if not Gtk.events_pending():
            break
        Gtk.main_iteration_do(False)


class _Painter:
    """Counts the frames GTK actually paints into the window.

    GTK3 lays out and paints from the frame clock, which schedules each frame
    as a TIMED source paced to the refresh rate. Between "the page changed"
    and "the page was painted" there can be a stretch where
    Gtk.events_pending() is False -- nothing is due yet -- although the
    paint is still to come. The old _settle() stopped at the first such
    moment, so whenever a frame was still waiting on the clock the grab read
    the X server's copy of the PREVIOUS page: CI committed 02-source and
    03-destination, 05-identity and 06-confirm, 07-progress and 08-done as
    identical PNGs while the widget-tree text (read from the stack, not the
    pixels) credited every screen. Waiting for after-paint replaces the
    guess with the event that means the frame is on screen.
    """

    def __init__(self, window):
        self.count = 0
        window.get_frame_clock().connect("after-paint", self._tick)

    def _tick(self, *_):
        self.count += 1


def _settle(window, painter, frames=2, timeout_s=10):
    """Return once `frames` whole frames have been painted after the caller's
    changes, and the X server has them. False if that never happened.

    Two frames, not one: a page whose first layout wraps a label or adds rows
    queues another resize from inside the first frame. The wake-up timeout
    keeps the blocking iteration from sleeping forever if GTK decides there
    is nothing to draw.
    """
    _drain()
    target = painter.count + frames
    window.queue_draw()
    wake = GLib.timeout_add(20, lambda: True)
    deadline = GLib.get_monotonic_time() + timeout_s * 1_000_000
    try:
        while painter.count < target:
            if GLib.get_monotonic_time() > deadline:
                return False
            Gtk.main_iteration_do(True)
            if painter.count < target:
                window.queue_draw()
    finally:
        GLib.source_remove(wake)
    _drain()
    # The paint went over the X connection; make sure the server has done it
    # before reading its pixels back.
    window.get_display().sync()
    _drain()
    return True


def _grab(window):
    gdk_window = window.get_window()
    if gdk_window is None:
        return None
    width = gdk_window.get_width()
    height = gdk_window.get_height()
    return Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height)


def _page_text(widget, acc=None):
    """Every string the page actually put in its widget tree.

    This is what the parity report matches tunaOS's screen keywords against.
    Reading the tree rather than OCRing the PNG is the whole reason this can
    run on a GPU-less runner: no tesseract, no recognition error, and it costs
    nothing on top of a capture we already do.

    It is read from the VISIBLE page only — walking the whole window would
    collect all eight pages' text at once and credit every screen on every
    frame, which is precisely the false-parity failure tunaOS's spec file
    warns about in its comments.

    Hidden widgets are skipped for that same reason, one level down. Several
    widgets here are set_no_show_all(True) or hidden when their value is
    empty (the welcome subtitle, the done page's body and store button, the
    reboot button), and without this their text still reached the parity
    report — crediting a screen for a line nobody can see. The GNOME harness
    had the same hole, where it credited a Bluetooth row that only appears
    on a machine with an adapter.

    get_visible(), not get_mapped(): the offscreen render never maps
    anything, so get_mapped() would empty the report.
    """
    acc = [] if acc is None else acc
    if not widget.get_visible():
        return acc
    if isinstance(widget, Gtk.Label):
        acc.append(widget.get_text() or "")
    elif isinstance(widget, Gtk.Button):
        acc.append(widget.get_label() or "")
    elif isinstance(widget, Gtk.TextView):
        buf = widget.get_buffer()
        acc.append(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False) or "")
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            _page_text(child, acc)
    return acc


def _audit(pixbuf, name):
    """Read the pixels back.

    A capture rig that asserts its PNGs merely EXIST will happily publish blank
    pages — that is not hypothetical, it happened in bootc-installer-asahi and
    shipped a settings screen that was a title over an empty page. So measure
    what only holds when the UI really drew: enough non-background pixels, and
    enough distinct colours that it is not one flat fill.
    """
    data = pixbuf.get_pixels()
    stride, chans = pixbuf.get_rowstride(), pixbuf.get_n_channels()
    w, h = pixbuf.get_width(), pixbuf.get_height()
    counts, samples, dark = {}, 0, 0
    luma_sum = luma_sq = 0
    for y in range(0, h, 3):
        row = y * stride
        for x in range(0, w, 3):
            i = row + x * chans
            px = (data[i], data[i + 1], data[i + 2])
            counts[px] = counts.get(px, 0) + 1
            samples += 1
            luma = (30 * px[0] + 59 * px[1] + 11 * px[2]) // 100
            luma_sum += luma
            luma_sq += luma * luma
            if luma < 160:
                dark += 1
    bg = max(counts.values()) / samples
    # Grayscale stddev, normalised 0..1 — the same "is the screen blank"
    # measure tunaOS's VM walkthrough takes with ImageMagick, computed here
    # from the pixels we are already visiting. Reported, never gating: the
    # thresholds below are this repo's and stay exactly as calibrated.
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    return {"name": name, "w": w, "h": h, "colours": len(counts),
            "background": bg, "ink": dark / samples,
            "stddev": (var ** 0.5) / 255.0}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "docs", "screenshots")
    os.makedirs(out, exist_ok=True)

    # Drop the generated files before capturing anything. The workflow uploads
    # this directory on always(), because a failed capture is exactly when the
    # pictures are worth looking at — but on a fresh checkout the directory
    # already holds the committed copies from the last green run. Without this,
    # a page that never grabs leaves its old PNG in place (the loop below
    # continues past it), and walkthrough.gif is only rebuilt past the failure
    # gate at the end, so a failed run's artifact ships the previous run's
    # animation. Both then read as evidence about this run, which is how a
    # capture bug gets diagnosed against the wrong image.
    for stale in os.listdir(out):
        if stale.endswith(".png") or stale == "walkthrough.gif":
            os.unlink(os.path.join(out, stale))

    app = Gtk.Application(application_id="org.tunaos.installer.xfce.shots")
    frames, findings = [], []

    captured = []

    def capture(win, painter, name, filename, expect_back):
        """Wait for the page to be painted, grab it, and check that the frame
        is that page: a new picture, the right stack child, the right nav."""
        painted = _settle(win, painter)
        pixbuf = _grab(win)
        if pixbuf is None:
            print(f"  !! no window for {name}", file=sys.stderr)
            return None
        path = os.path.join(out, filename)
        pixbuf.savev(path, "png", [], [])
        frames.append(path)
        finding = _audit(pixbuf, name)
        finding["png"] = path
        visible = win.stack.get_visible_child()
        finding["text"] = " ".join(_page_text(visible)) if visible else ""
        fatal = []
        if not painted:
            fatal.append("GTK never painted this page")
        pixels = bytes(pixbuf.get_pixels())
        if captured and captured[-1] == pixels:
            # The defect this harness shipped: a grab that predates the paint
            # is a perfect copy of the previous frame, and every per-frame
            # check (ink, colours, widget text) still passes.
            fatal.append("pixel-identical to the previous frame -- the grab "
                         "did not wait for the paint")
        captured.append(pixels)
        page = PAGE_ORDER[win.index]
        if win.stack.get_visible_child_name() != page:
            fatal.append(f"stack shows {win.stack.get_visible_child_name()!r}")
        back = win.back_btn.get_visible() and win.nav.get_visible()
        if back != expect_back:
            fatal.append("Back is " + ("shown" if back else "hidden") +
                         " on this page")
        if fatal:
            finding["fatal"] = "; ".join(fatal)
        findings.append(finding)
        return finding

    def add_fatal(finding, problems):
        if problems:
            finding["fatal"] = "; ".join(
                ([finding["fatal"]] if finding.get("fatal") else []) + problems)

    def on_activate(_app):
        # No theme animations. The theme fades a button between its
        # insensitive and sensitive looks over ~200 ms, and a grab that waits
        # for the paint (rather than for nothing to be pending) lands inside
        # that fade: the confirm page's live Install button photographed
        # greyed out, as if it were held.
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        win = InstallerWindow(app)
        win.set_default_size(760, 560)
        win.show_all()
        _drain()
        painter = _Painter(win)
        for index, name in enumerate(PAGE_ORDER):
            # Drive the stack directly rather than through _enter(): _enter
            # fires on_enter() side effects, and on the progress page that is
            # the install itself. Nav state is refreshed explicitly instead.
            win.index = index
            win.stack.set_visible_child_name(name)
            win.trawl.set_step(index)
            if name == "progress":
                _seed_progress(win.pages["progress"])
            elif name == "done":
                # A finished install's bar is full; the seeded one stopped
                # part-way through the pull.
                win.trawl.set_fill(1.0)
                win.pages["done"].set_result(True, "")
            else:
                win.pages[name].on_enter()
            win.refresh_nav()
            finding = capture(win, painter, name, f"{index + 1:02d}-{name}.png",
                              expect_back=name not in ("welcome", "progress", "done"))
            if finding is None:
                continue
            problems = []
            if name == "confirm":
                text = finding["text"]
                disk = win.pages["destination"].selected_disk()["path"]
                for row in ("Target disk:", "Filesystem:", "Encryption:",
                            "Hostname:", "Image:"):
                    if row not in text:
                        problems.append(f"summary has no {row!r} row")
                if core.BRANDING.text("confirm_warning", disk=disk) not in text:
                    problems.append("the erase warning does not name " + disk)
            elif name == "done":
                done = win.pages["done"]
                if core.BRANDING.text("done_title") not in finding["text"]:
                    problems.append("done_title is not on the done page")
                if not (done.close_btn.get_visible() and done.reboot_btn.get_visible()):
                    problems.append("the done page lacks Close or Restart now")
                elif not done.reboot_btn.get_sensitive():
                    problems.append("Restart now is held with no recovery key")
            add_fatal(finding, problems)

        # The done page again, this time as a TPM install leaves it. The key
        # goes in through the progress page's parser, so this frame proves the
        # event is understood end to end rather than that a label can be set.
        win.pages["progress"].append_log(RECOVERY_EVENT + "\n")
        key = win.pages["progress"].recovery_key()
        if not key:
            print("  !! the parser did not yield a recovery key", file=sys.stderr)
            findings.append({"name": "recovery", "fatal":
                             "recovery_key event was not parsed"})
        else:
            win.index = PAGE_ORDER.index("done")
            win.stack.set_visible_child_name("done")
            win.pages["done"].set_result(True, "", key)
            win.refresh_nav()
            finding = capture(win, painter, "recovery",
                              f"{len(PAGE_ORDER) + 1:02d}-recovery.png",
                              expect_back=False)
            if finding is not None:
                # The point of the frame: the key itself must be on screen,
                # and reboot must still be held.
                if key not in finding["text"]:
                    add_fatal(finding, ["the recovery key is not in the rendered "
                                        "text; the panel did not draw"])
                elif win.pages["done"].reboot_btn.get_sensitive():
                    add_fatal(finding, ["reboot is live before the key was "
                                        "acknowledged"])

        win.destroy()
        app.quit()

    app.connect("activate", on_activate)
    app.run([])

    failures = []
    for f in findings:
        # A finding that never got as far as a pixel audit (the recovery frame
        # when the event did not parse) carries "fatal" and nothing else.
        if "colours" not in f:
            failures.append(f"{f['name']}: {f.get('fatal', 'not captured')}")
            f["rendered"] = False
            continue
        print(f"  {f['name']:12s} {f['w']}x{f['h']}  colours {f['colours']:5d}  "
              f"largest-flat {f['background']*100:5.1f}%  ink {f['ink']*100:5.1f}%")
        # A window that never drew is one flat colour: few distinct values and a
        # background occupying nearly everything.
        # Thresholds calibrated against MEASURED output, not guessed. The eight
        # real pages score:
        #     colours       196 - 303
        #     largest-flat  47.6% - 96.1%
        #     ink            0.6% -  3.5%
        # A window that never drew is one flat fill: a handful of colours and a
        # background at ~100%. The gaps below sit between those two worlds.
        #
        # The first version used 0.97 for largest-flat and failed a page that
        # had rendered perfectly — these are sparse wizard pages on a light
        # theme, so 96% background is normal, not broken. Guessing a threshold
        # and then reading the failure as a defect is how you end up "fixing"
        # working code.
        page_failures = []
        if f["colours"] < 60:
            page_failures.append(f"{f['name']}: only {f['colours']} distinct colours — did not render")
        if f["background"] > 0.985:
            page_failures.append(f"{f['name']}: {f['background']*100:.1f}% one flat colour — blank page")
        if f["ink"] < 0.003:
            page_failures.append(f"{f['name']}: {f['ink']*100:.2f}% ink — no text drawn")
        # Same verdict, same thresholds — just also recorded per page so the
        # parity report can say WHICH screen was blank instead of only how
        # many were.
        # A frame can render perfectly and still be wrong: the recovery frame
        # asserts the key is in the text and that reboot is still held, and
        # neither shows up in a pixel histogram.
        if f.get("fatal"):
            page_failures.append(f"{f['name']}: {f['fatal']}")
        f["rendered"] = not page_failures
        failures.extend(page_failures)

    # PAGE_ORDER plus the recovery frame, which is the done page in its other
    # state rather than a page of its own.
    expected_frames = len(PAGE_ORDER) + 1
    if len(findings) != expected_frames:
        failures.append(f"captured {len(findings)} of {expected_frames} frames")

    # Emitted before the failure gate on purpose: a frontend that renders a
    # blank page is exactly the case the parity matrix most needs a row for.
    # Bailing out here would leave that frontend reading "_pending_" forever,
    # which is how the last three defects survived.
    parity_report.write_report(
        out, "xfce", findings,
        harness="tests/gui/capture-screens.py (GTK3 under Xvfb)")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    gif = os.path.join(out, "walkthrough.gif")
    subprocess.run(["convert", "-delay", "240", "-loop", "0", *frames, gif], check=True)
    print(f"  wrote {len(frames)} screens + {os.path.basename(gif)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
