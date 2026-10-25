#!/usr/bin/env python3
"""Render every page of the GNOME (GTK4 / libadwaita) installer to PNG, plus an
animated walkthrough, and emit the parity report the shared installer matrix
consumes.

This is the GNOME frontend's counterpart to the harnesses the sibling
frontends already carry (frontends/*/tests/gui/capture-screens.py,
frontends/kde/tests/capture.cpp, frontends/cosmic/src/capture.rs). Same
contract, same output shape: ``NN-<page>.png`` per wizard page,
``walkthrough.gif``, and ``walkthrough-gnome.json`` for
``shared/walkthrough/aggregate.py``.

Runs headless under Xvfb with no desktop, no GPU and no real disks. The pages
are built against fixtures, driven through the real ``BootcWindow`` (the same
class the shipped Flatpak presents), and rendered through GTK's own renderer.
GTK4 has no offscreen backend, so a real X display is required:

    meson setup build -Dbuild-fisherman=false && ninja -C build
    BOOTC_RESOURCE=build/bootc_installer/bootc-installer.gresource \\
        xvfb-run -a python3 tests/gui/capture-screens.py [outdir]

Nothing here touches a disk. The disks come from the shared probe fixture,
the QR companion server never binds a port, and ``BootcProgress.start`` --
the one method that launches fisherman -- is replaced with a guard that fails
the capture if anything reaches it.
"""

import json
import os
import subprocess
import sys
import time
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "shared", "walkthrough"))

# ── environment, BEFORE any bootc_installer import ───────────────────────────

os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("GTK_A11Y", "none")
# BOOTC_DEMO makes the slurp (Windows data) step render its demo message
# instead of resolving a fisherman binary and scanning the disk.
os.environ.setdefault("BOOTC_DEMO", "1")
# The repo's own recipe, exactly as the Flatpak ships it. The captured
# branding therefore follows recipe.json (distro_name / welcome_title); a
# downstream ISO that overrides the recipe brands itself the same way.
os.environ.setdefault("BOOTC_CUSTOM_RECIPE", os.path.join(REPO, "recipe.json"))
# recipe.json carries no product strings, so branding still resolves from the
# host's os-release and an unpinned capture is BRANDED BY THE RUNNER -- on an
# ubuntu-24.04 box the wizard renders "Welcome to Ubuntu 24.04.4 LTS".
#
# Pin the whole branding object, not just the name. BOOTC_INSTALLER_PRODUCT_NAME
# (which screenshots-gnome.yml passes) covers `name` and nothing else, so the
# committed docs/screenshots/01-welcome.png reads "Welcome to TunaOS" under the
# runner's Ubuntu LOGO: os-release `LOGO=ubuntu-logo` was never overridden.
# setdefault, so a workflow pointing at a real product's file still wins.
os.environ.setdefault(
    "BOOTC_INSTALLER_BRANDING",
    os.path.join(REPO, "shared", "walkthrough", "capture-branding.json"))
# That branding names the app's own icon, which meson installs into the icon
# theme but a from-source run has never seen -- it would render as the broken
# -image glyph. data/ is laid out as a datadir (icons/hicolor/...), so putting
# it on XDG_DATA_DIRS makes the theme find it without installing anything.
os.environ["XDG_DATA_DIRS"] = os.pathsep.join([
    os.path.join(REPO, "data"),
    os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share",
])
# Disks, TPM and requirements come from `fisherman probe --json`
# (shared/probe/README.md). The capture reads the shared laptop fixture
# instead: four plausible disks, a usable TPM 2.0 (so the TPM row shows,
# which no CI runner could), every requirement met. Same fixture the other
# frontends' captures read.
#
# The fixture is a laptop booted from a live USB, and live media now comes
# from the probe (live.is_live): on live media GNOME drops the image page and
# installs the running image. This walkthrough shows the image page, so it
# reads the same laptop as an installed (not live) session.
if not os.environ.get("BOOTC_INSTALLER_FAKE_PROBE"):
    import json as _json
    import tempfile as _tempfile
    with open(os.path.join(REPO, "shared", "probe", "fixtures", "laptop.json"),
              encoding="utf-8") as _fh:
        _probe = _json.load(_fh)
    _probe["live"] = {"is_live": False, "live_image": ""}
    _fd, _path = _tempfile.mkstemp(prefix="gnome-capture-probe-", suffix=".json")
    with os.fdopen(_fd, "w", encoding="utf-8") as _fh:
        _json.dump(_probe, _fh)
    os.environ["BOOTC_INSTALLER_FAKE_PROBE"] = _path
# Skip the RAM / CPU / UEFI gate windows: this is a render of the wizard.
os.environ.setdefault("IGNORE_RAM", "1")
os.environ.setdefault("IGNORE_CPU", "1")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Graphene", "1.0")
try:
    gi.require_version("Vte", "3.91")
except ValueError:
    pass
import parity_report  # noqa: E402
from gi.repository import Adw, GdkPixbuf, Gio, GLib, Graphene, Gtk  # noqa: E402


def _find_gresource():
    candidates = [
        os.environ.get("BOOTC_RESOURCE", ""),
        os.path.join(REPO, "build", "bootc_installer", "bootc-installer.gresource"),
        os.path.join(REPO, "_build", "bootc_installer", "bootc-installer.gresource"),
        "/app/share/org.bootcinstaller.Installer/bootc-installer.gresource",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


_res = _find_gresource()
if not _res:
    sys.exit("bootc-installer.gresource not found: run meson setup build && "
             "ninja -C build, or set BOOTC_RESOURCE")
Gio.Resource.load(_res)._register()
Adw.init()

from bootc_installer.views import progress as progress_mod  # noqa: E402
from bootc_installer.widgets.page_header import BootcPageHeader  # noqa: E402,F401
from bootc_installer.windows.main_window import BootcWindow  # noqa: E402

# ── fixtures ─────────────────────────────────────────────────────────────────

def _refuse_to_install(*_args, **_kwargs):
    # SAFETY INTERLOCK. BootcProgress.start() is the only code path that
    # launches fisherman. The capture never confirms the install, so this
    # should be unreachable -- and if it is reached, failing loudly is the
    # right outcome, because the alternative is partitioning the runner.
    raise RuntimeError("capture reached BootcProgress.start(): refusing to install")


PATCHERS = [
    patch("bootc_installer.defaults.qr_companion.CompanionServer"),
    patch("bootc_installer.defaults.qr_companion.get_local_ip", return_value="192.0.2.10"),
    patch.object(progress_mod.BootcProgress, "start", _refuse_to_install),
]

CAPTIONS = {
    "welcome": "What the installer is about to do.",
    "qr_companion": "Optional phone companion for typing on a laptop keyboard.",
    "disk": "Choose the disk. Nothing is written yet.",
    "slurp": "Bring documents and settings over from an existing Windows install.",
    "encryption": "Full-disk encryption, with or without TPM2.",
    "user": "Your account and password.",
    "confirm": "The last screen before anything is written.",
    "progress": "The install, step by step.",
    "recovery-key": "The LUKS recovery key, shown once after an encrypted install.",
    "done": "Finished. Restart into the new system.",
}


def _pump(seconds=0.25):
    """Let GTK finish layout and drawing before the grab.

    Grabbing too early yields a valid PNG of a half-drawn window, which looks
    like a screenshot and is not one. Time-bounded rather than
    pending()-bounded because the frame clock schedules its own work.
    """
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


def _grab(widget, path):
    """Render the widget through GTK's own renderer into a PNG.

    GTK4 has no Gdk.pixbuf_get_from_window. The renderer that draws the
    window draws the same node tree into a texture, so the PNG is exactly what
    the compositor would have been handed.
    """
    native = widget.get_native()
    renderer = native.get_renderer() if native else None
    w, h = widget.get_width(), widget.get_height()
    if renderer is None or w == 0 or h == 0:
        return False
    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, w, h)
    node = snapshot.to_node()
    if node is None:
        return False
    texture = renderer.render_texture(node, Graphene.Rect().init(0, 0, w, h))
    texture.save_to_png(path)
    return True


def _page_text(widget, acc=None):
    """Every string the page actually put on screen.

    Read from the VISIBLE carousel page only: walking the whole window would
    credit every screen on every frame, the false-parity failure the screen
    spec warns about.

    Hidden widgets are skipped for the same reason, one level down. A page
    can hide a row on a runtime probe -- welcome.py hides the Bluetooth row
    when /sys/class/bluetooth has no adapter, which no runner does -- and
    without this the row's title and subtitle still landed in the text the
    parity report reads. The screenshot showed no Bluetooth row while
    walkthrough-gnome.json claimed "Connect Bluetooth Devices"; the report
    credited a screen for a row nobody can see.

    get_visible(), not get_mapped(): the offscreen render never maps
    anything, so get_mapped() would return False for the whole tree and the
    report would go empty. get_visible() is the property set_visible() sets,
    which is what these pages actually use.
    """
    acc = [] if acc is None else acc
    if not widget.get_visible():
        return acc
    if isinstance(widget, Gtk.Label):
        acc.append(widget.get_text() or "")
    elif isinstance(widget, Gtk.Button):
        acc.append(widget.get_label() or "")
    elif isinstance(widget, Gtk.Entry):
        acc.append(widget.get_placeholder_text() or "")
    elif isinstance(widget, Gtk.TextView):
        buf = widget.get_buffer()
        acc.append(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False) or "")
    if isinstance(widget, Adw.PreferencesRow):
        acc.append(widget.get_title() or "")
    if isinstance(widget, Adw.ActionRow):
        acc.append(widget.get_subtitle() or "")
    if isinstance(widget, Adw.PreferencesGroup):
        acc.append(widget.get_title() or "")
        acc.append(widget.get_description() or "")
    if isinstance(widget, Adw.StatusPage):
        acc.append(widget.get_title() or "")
        acc.append(widget.get_description() or "")
    child = widget.get_first_child()
    while child is not None:
        _page_text(child, acc)
        child = child.get_next_sibling()
    return acc


def _audit(path, name):
    """Read the pixels back: enough distinct colours and enough ink that the
    page really drew, not merely that a PNG exists."""
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
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
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    return {"name": name, "png": path, "w": w, "h": h, "colours": len(counts),
            "flat": max(counts.values()) / samples, "ink": dark / samples,
            "stddev": (var ** 0.5) / 255.0}


def _page_name(page):
    key = getattr(page, "_bootc_step_key", None)
    if key:
        return key
    return {"BootcConfirm": "confirm", "BootcProgress": "progress",
            "BootcRecoveryKey": "recovery-key", "BootcDone": "done"}.get(
        type(page).__name__, type(page).__name__.lower())


# The install screen, caught in flight: the shared dry-run transcript cut
# part-way through the image pull, so the bar sits mid-way rather than at
# either end. KDE, COSMIC, Niri and XFCE cut at the same line and render the
# same fraction.
TRANSCRIPT = os.path.join(REPO, "shared", "progress", "dry-run-transcript.ndjson")

# Seeding failures, reported alongside the pixel audit by main().
SEED_FAILURES = []


def _seed_progress(page):
    """Feed fisherman's own output through the parser a live install uses.

    This screen used to set the bar to 0.45 and write the labels by hand, so
    it showed nothing about whether this frontend can parse fisherman's JSON
    progress protocol (shared/progress/README.md): a parser regression would
    have left the screenshot unchanged. start_demo() is not an option either:
    it runs on timers and configures the install video, which a runner has no
    codec for.
    """
    with open(TRANSCRIPT, encoding="utf-8") as fh:
        lines = fh.readlines()
    cut = next(i for i, ln in enumerate(lines) if "47/71" in ln) + 1
    for line in lines[:cut]:
        page._BootcProgress__parse_progress_line(line.strip())

    # Did the transcript actually reach the bar?
    #
    # The pixel audit cannot answer this: it measures ink over the whole
    # frame, and this page has a title, labels and a substep line regardless.
    # A fraction of zero here means the parser stopped driving the bar.
    fraction = page.progressbar.get_fraction()
    print(f"    progress bar at {fraction:.1%}")
    if fraction <= 0.0:
        SEED_FAILURES.append(
            "progress: the bar is at 0% after the transcript -- "
            "__parse_progress_line is not driving it (shared/progress/README.md)")
    if not page.progressbar.get_visible():
        SEED_FAILURES.append("progress: the progress bar is not visible")


def _choose_disk(win):
    """Choose the fixture's first disk on the disk page, as a user does
    before Next, so the confirm page summarises a real choice.

    Without this the capture reached the confirm page with no disk chosen:
    the summary had no Target disk, Filesystem or erase warning, and the
    screenshot showed less than any other frontend's (docs/DESIGN-AUDIT.md).
    Only the partition recipe is set -- the "Use Entire Disk" button also
    opens a confirmation dialog, which has no place in a page render.
    """
    carousel = win.carousel
    for index in range(carousel.get_n_pages()):
        page = carousel.get_nth_page(index)
        if getattr(page, "_bootc_step_key", None) != "disk":
            continue
        disks = page._BootcDefaultDisk__disks.all_disks()
        if not disks:
            SEED_FAILURES.append("confirm: the disk page has no disks to choose")
            return
        page._set_auto_partition_recipe(disks[0])
        return
    SEED_FAILURES.append("confirm: no disk page in the carousel")


def _seed(win, page, name):
    """Put each page into the state a user would see it in."""
    if name == "confirm":
        _choose_disk(win)
        win.update_finals()
    elif name == "progress":
        _seed_progress(page)
    elif name == "recovery-key":
        page.set_recovery_key("mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf")
    elif name == "done":
        win.update_finals()
        page.set_result(True, None)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "docs", "screenshots")
    os.makedirs(out, exist_ok=True)
    for stale in os.listdir(out):
        if stale.endswith(".png") or stale == "walkthrough.gif":
            os.unlink(os.path.join(out, stale))

    for p in PATCHERS:
        p.start()

    app = Adw.Application(application_id="org.bootcinstaller.Installer.Capture",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    frames, findings = [], []

    def on_activate(_app):
        win = BootcWindow(application=app)
        win.set_default_size(1000, 700)
        win.present()
        _pump(1.0)
        carousel = win.carousel
        for index in range(carousel.get_n_pages()):
            page = carousel.get_nth_page(index)
            name = _page_name(page)
            _seed(win, page, name)
            carousel.scroll_to(page, False)
            _pump(0.6)
            path = os.path.join(out, f"{index + 1:02d}-{name}.png")
            if not _grab(win, path):
                print(f"  !! no render for {name}", file=sys.stderr)
                continue
            frames.append(path)
            finding = _audit(path, name)
            finding["text"] = " ".join(t for t in _page_text(page) if t)
            findings.append(finding)
        win.destroy()
        app.quit()

    app.connect("activate", on_activate)
    app.run([])
    for p in reversed(PATCHERS):
        p.stop()

    failures = list(SEED_FAILURES)
    for f in findings:
        print(f"  {f['name']:14s} {f['w']}x{f['h']}  colours {f['colours']:5d}  "
              f"largest-flat {f['flat']*100:5.1f}%  ink {f['ink']*100:5.1f}%")
        page_failures = []
        # Thresholds sit between "rendered" and "one flat fill", calibrated on
        # the same basis as the xfce harness: a window that never drew has a
        # handful of colours and one colour at ~100%.
        if f["colours"] < 60:
            page_failures.append(f"{f['name']}: only {f['colours']} distinct colours")
        if f["flat"] > 0.985:
            page_failures.append(f"{f['name']}: {f['flat']*100:.1f}% one flat colour")
        if f["ink"] < 0.003:
            page_failures.append(f"{f['name']}: {f['ink']*100:.2f}% ink, no text drawn")
        f["rendered"] = not page_failures
        failures.extend(page_failures)

    if not findings:
        failures.append("captured no pages")

    parity_report.write_report(
        out, "gnome", findings,
        harness="tests/gui/capture-screens.py (GTK4/libadwaita under Xvfb)")

    with open(os.path.join(out, "captions.json"), "w") as fh:
        json.dump({os.path.basename(f["png"]): CAPTIONS.get(f["name"], "")
                   for f in findings}, fh, indent=2)
        fh.write("\n")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    gif = os.path.join(out, "walkthrough.gif")
    has_magick = subprocess.run(["which", "magick"], capture_output=True, check=False).returncode == 0
    convert = "magick" if has_magick else "convert"
    subprocess.run([convert, "-delay", "240", "-loop", "0", *frames, gif], check=True)
    print(f"  wrote {len(frames)} screens + {os.path.basename(gif)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
