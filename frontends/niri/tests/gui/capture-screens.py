#!/usr/bin/env python3
"""Render every wizard page of ui/installer.qml to PNG, plus an animated
walkthrough, for docs/gui-walkthrough.md and the README.

The installer normally runs under Quickshell on a Wayland compositor, which is
why it has been effectively impossible to look at. This loads the SAME,
UNMODIFIED installer.qml under a plain Qt Quick runtime by supplying local stub
implementations of the two Quickshell modules it imports (tests/qml-stubs).

Nothing is spawned: the stubbed Process serves canned backend output. That is a
safety property, not a convenience — the real backend runs fisherman, which
partitions a disk.

    QT_QPA_PLATFORM=offscreen python3 tests/gui/capture-screens.py [outdir]
"""

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Qt Quick's scene graph wants a GL context; the software backend renders the
# same tree on the CPU, which is what a container with no DRM device needs.
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["QML2_IMPORT_PATH"] = os.path.join(REPO, "tests", "qml-stubs")
os.environ["QML_IMPORT_PATH"] = os.environ["QML2_IMPORT_PATH"]

from PyQt6.QtCore import (QUrl, QTimer, QEventLoop, QMetaObject, Q_ARG,  # noqa: E402
                          QVariant, QPointF, QRect, QRectF, QSizeF)
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402
from PyQt6.QtQuick import QQuickWindow  # noqa: E402
from PyQt6 import sip  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parity_report  # noqa: E402

PAGES = [
    ("01-welcome", 0, "What the installer is about to do."),
    ("02-disk", 1, "Choose the target disk."),
    ("03-encryption", 2, "Encryption choice."),
    ("04-confirm", 3, "The last screen before anything is written."),
    ("05-progress", 4, "The install, with live log."),
    ("06-done", 5, "Finished."),
    ("07-recovery", 5, "A TPM install: the recovery key, and restart held "
                       "until it is acknowledged."),
]

# fisherman emits this once, after TPM enrolment, and for a tpm2-luks install
# it is the only way back into the disk if the TPM state changes (#129). No CI
# runner does a TPM install, so it is synthesised -- but it goes in through
# appendLog(), the function a real install calls, so this frame exercises the
# parse rather than a property assignment that would keep passing if the parse
# broke.
RECOVERY_EVENT = json.dumps({
    "type": "recovery_key",
    "key": "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf",
    "timestamp": "2026-01-01T00:00:00Z",
    "elapsed_ms": 1000,
})

# The install screen, caught in flight: fisherman's real newline-delimited
# JSON transcript (shared/progress/), truncated part-way through the image
# pull so the bar sits mid-way rather than at either end.
#
# This was seven hand-written "[n/9] " lines naming a specific image ref, and
# it was assigned straight to the `installLog` property — so the capture
# painted text into the log pane and never called appendLog() at all. The bar
# and the step caption were therefore never exercised by this harness in
# either direction, while docs/PARITY.md credited this frontend with a
# working progress bar. (fisherman does not emit that prefix, so the parser
# it was feeding could not have matched it anyway.)
#
# Naming a product in a fixture was the second problem: it put that product's
# image ref into the rendered docs for everyone who rebrands this installer.
_TRANSCRIPT = os.path.join(REPO, "..", "..", "shared", "progress",
                           "dry-run-transcript.ndjson")
_PROBE_EXPECTED = os.path.join(REPO, "..", "..", "shared", "probe", "fixtures",
                               "laptop.expected.json")


def fixture_lines():
    """Transcript lines up to the middle of the image pull."""
    with open(os.path.normpath(_TRANSCRIPT), encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    cut = next(i for i, ln in enumerate(lines) if "47/71" in ln) + 1
    return lines[:cut]



def find_item(root, name):
    """The QQuickItem with this objectName, searched down the VISUAL tree.

    findChild() walks the QObject tree, which does not reach items a QML
    component parents visually rather than by ownership — the sibling KDE
    harness reported its progress bar missing on a screen that was rendering
    beside it for exactly that reason. childItems() is what "on the screen"
    means.
    """
    if root is None:
        return None
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = find_item(child, name)
        if found is not None:
            return found
    return None


def assert_progress_bar_drawn(window, image, out=sys.stderr):
    """Is the progress bar's filled part actually on the screen?

    The pixel audit cannot answer this and was never meant to: it measures ink
    over the whole frame, and the install screen supplies plenty from the log
    text alone. The KDE frontend shipped a bar that laid out at full width,
    reported itself visible and opaque, and painted nothing — and passed every
    check in this repository, its capture job included, because a page with a
    populated log looks populated either way.

    This frontend is the one whose harness used to set `installLog` directly
    instead of calling appendLog(), so its bar was never exercised here at
    all. That is fixed; this stops it coming back.
    """
    fill = find_item(window.contentItem(), "installProgressFill")
    if fill is None:
        print("FAIL: no item named installProgressFill in the visual tree",
              file=out)
        return False

    track = fill.parentItem()
    share = fill.width() / track.width() if track and track.width() > 0 else 0.0
    print(f"    bar fill: {fill.width():.0f}x{fill.height():.0f} "
          f"({share:.1%} of track) visible={fill.isVisible()} "
          f"opacity={fill.opacity():.2f}", file=out)

    if fill.width() <= 0 or fill.height() <= 0 or not fill.isVisible():
        print("FAIL: the progress bar's fill has no drawable geometry", file=out)
        return False

    scale = image.width() / window.width()
    top_left = fill.mapToScene(QPointF(0, 0)) * scale
    rect = QRectF(top_left,
                  QSizeF(fill.width() * scale, fill.height() * scale)).toRect()
    rect = rect.intersected(QRect(0, 0, image.width(), image.height()))
    if rect.isEmpty():
        print("FAIL: the progress bar's fill maps to no pixels", file=out)
        return False

    background = image.pixel(2, 2)
    ink = sum(
        1
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
        if image.pixel(x, y) != background
    )
    if ink == 0:
        print(f"FAIL: the progress bar's fill covers {rect.width()}x"
              f"{rect.height()} pixels and every one is the page background "
              "— it is laid out but not painted", file=out)
        return False
    return True


def settle(ms=250):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def audit(image, name):
    """Read the pixels back.

    A capture that only checks its PNGs exist will publish blank pages: the
    files are present, non-empty, and empty. Qt Quick makes that especially
    easy — grab before the first frame and you get a valid image of nothing.
    """
    w, h = image.width(), image.height()
    counts, samples, ink = {}, 0, 0
    luma_sum = luma_sq = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = image.pixel(x, y) & 0xFFFFFF
            counts[c] = counts.get(c, 0) + 1
            samples += 1
            r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
            luma = (30 * r + 59 * g + 11 * b) // 100
            luma_sum += luma
            luma_sq += luma * luma
            if luma > 60:
                ink += 1  # the theme is near-black, so "ink" is the LIGHT pixels
    # Grayscale stddev, normalised 0..1 — the same "is the screen blank"
    # measure tunaOS's VM walkthrough takes with ImageMagick, computed from
    # the pixels we already visit. Reported only; the thresholds below are
    # this repo's and are unchanged.
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    return {"name": name, "w": w, "h": h, "colours": len(counts),
            "flat": max(counts.values()) / samples, "ink": ink / samples,
            "stddev": (var ** 0.5) / 255.0}


def page_text(item, acc=None):
    """Every string the CURRENTLY VISIBLE page put in the QML scene.

    This is what the parity report matches tunaOS's screen keywords against.
    Reading the scene graph instead of OCRing the PNG is what lets this run
    with no tesseract and no GPU, and it cannot misread a glyph.

    Visibility is the whole trick. `installer.qml` builds all six pages up
    front inside a StackLayout, so a naive walk of the tree collects every
    page's text on every frame and credits every screen everywhere — the
    exact false-parity failure tunaOS's spec file warns about. QQuickItem's
    `visible` is EFFECTIVE visibility (a child of a hidden page reports
    False), so pruning on it isolates one page.
    """
    acc = [] if acc is None else acc
    for child in item.childItems():
        if not child.isVisible():
            continue
        text = child.property("text")
        if isinstance(text, str) and text.strip():
            acc.append(text)
        page_text(child, acc)
    return acc


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "docs", "screenshots")
    os.makedirs(out, exist_ok=True)

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(os.path.join(REPO, "ui", "installer.qml")))
    if not engine.rootObjects():
        print("FAIL: installer.qml did not load — see QML errors above", file=sys.stderr)
        return 1

    root = engine.rootObjects()[0]
    # PyQt wraps the root as a bare QWindow because it has no binding for
    # QQuickApplicationWindow. The cast is what exposes grabWindow().
    window = sip.cast(root, QQuickWindow)
    settle(500)

    # The disks every frontend's capture shows: shared/probe/fixtures/laptop,
    # as fisherman's probe renders it (shared/probe/README.md) -- the exact
    # shape the backend's discover-disks prints, which installer/probe_test.go
    # pins against the same file. The pages are set directly, so the QML's
    # own discover-disks call never runs here.
    with open(_PROBE_EXPECTED, encoding="utf-8") as fh:
        probed = json.load(fh)
    root.setProperty("disks", probed["disks"])
    root.setProperty("disksProbed", True)
    root.setProperty("selectedDisk", probed["disks"][0])
    root.setProperty("hasTpm", probed["tpm_usable"])
    root.setProperty("unmet", probed["unmet"])
    # The encryption choices the backend's `detect` reports: its embedded
    # copy of fisherman's encryption-choices.json.
    with open(os.path.join(REPO, "installer", "encryption-choices.json"), encoding="utf-8") as fh:
        root.setProperty("encryptionChoices", json.load(fh)["choices"])

    frames, findings = [], []
    for name, page, _caption in PAGES:
        root.setProperty("currentPage", page)
        if page == 4:
            # Through appendLog(), the function a real install calls — so the
            # bar, the step caption and the log rendering are all the live
            # code path. Assigning installLog directly, as this used to, is
            # how a screen can be "captured" without running any of it.
            for line in fixture_lines():
                QMetaObject.invokeMethod(root, "appendLog",
                                         Q_ARG(QVariant, line))
            # The fill has `Behavior on width { NumberAnimation }`, so it
            # arrives at its final width over a few hundred milliseconds.
            # Grabbing on the usual 300ms settle can catch it part-way and
            # photograph a bar narrower than the install really is.
            settle(700)
        if page == 5:
            root.setProperty("installSuccess", True)
        if name == "07-recovery":
            QMetaObject.invokeMethod(root, "appendLog",
                                     Q_ARG(QVariant, RECOVERY_EVENT))
            if not root.property("recoveryKey"):
                print("  !! the recovery_key event did not parse",
                      file=sys.stderr)
                sys.exit(1)
        settle(300)
        image = window.grabWindow()
        path = os.path.join(out, f"{name}.png")
        image.save(path)
        frames.append(path)

        # The install screen is the one with a progress bar, and a bar that
        # lays out but paints nothing is invisible to the pixel audit. Fail
        # rather than publish a documentation image of a bar that is not
        # there.
        if page == 4 and not assert_progress_bar_drawn(window, image):
            sys.exit(1)
        finding = audit(image, name)
        finding["png"] = path
        finding["text"] = " ".join(page_text(window.contentItem()))

        # The recovery frame is the one screen where a correct-looking render
        # can still be wrong: the panel can draw without the key in it, and
        # Restart can be live before the acknowledgement. Neither shows up in
        # a pixel histogram.
        if name == "07-recovery":
            key = root.property("recoveryKey")
            if key not in finding["text"]:
                print("  !! the recovery key is not in the rendered text — "
                      "the panel did not draw (#129)", file=sys.stderr)
                sys.exit(1)
            # The key alone is not enough. On the first run of this frame
            # every LABEL was empty -- installer.qml keeps its own copy of
            # the contract defaults and had not been given the recovery
            # keys -- and the check still passed, because the key is set
            # from the event rather than from the copy table. Assert on a
            # contract-sourced string too, or this frame photographs a
            # panel of blank buttons and calls it covered.
            # Read from the canonical contract, not from the QML: that is
            # what makes this catch drift between installer.qml's own copy
            # table and shared/branding/copy-defaults.json.
            # REPO is frontends/niri; the contract lives two levels up.
            contract_path = os.path.join(
                os.path.dirname(os.path.dirname(REPO)),
                "shared", "branding", "copy-defaults.json")
            if not os.path.exists(contract_path):
                print("  .. shared/branding is absent; this tree is checked "
                      "out without the monorepo, so the copy-table check is "
                      "skipped", file=sys.stderr)
                findings.append(finding)
                continue
            with open(contract_path) as fh:
                contract = json.load(fh)
            for key in ("recovery_key_title", "recovery_key_ack",
                        "recovery_key_copy"):
                want = contract[key]
                if want not in finding["text"]:
                    print(f"  !! {key} is not in the rendered text. The copy "
                          "table in installer.qml is a hand-written duplicate "
                          "of copy-defaults.json and nothing enforces it; a "
                          "key added to the contract and not to that table "
                          "renders as an empty string (#129).",
                          file=sys.stderr)
                    sys.exit(1)
            restart = find_item(window.contentItem(), "doneRestartButton")
            if restart is None:
                print("  !! no doneRestartButton in the visual tree",
                      file=sys.stderr)
                sys.exit(1)
            if restart.property("enabled"):
                print("  !! Restart is live before the recovery key was "
                      "acknowledged (#129)", file=sys.stderr)
                sys.exit(1)

        findings.append(finding)

    # Runtime regression for the same portable file-logo contract as every
    # frontend. PNG avoids depending on a platform's optional SVG plugin.
    from PyQt6.QtGui import QColor, QImage
    logo_path = os.path.join(out, "fixture logo #1.png")
    logo = QImage(32, 32, QImage.Format.Format_ARGB32)
    logo.fill(QColor("#13b97d"))
    assert logo.save(logo_path)
    root.setProperty("branding", {
        "name": "Example Fork", "logoKind": "file",
        "logoValue": QUrl.fromLocalFile(os.path.abspath(logo_path)).toString(),
    })
    root.setProperty("recoveryKey", "")
    for page, name in [(0, "welcomeBrandingLogo"), (5, "doneBrandingLogo")]:
        root.setProperty("currentPage", page)
        root.setProperty("installSuccess", True)
        settle(300)
        item = find_item(window.contentItem(), name)
        assert item is not None and item.property("visible"), name + " failed to decode"
        image = window.grabWindow()
        image.save(os.path.join(out, "branding-" + str(page) + ".png"))
        assert any(image.pixelColor(x, y).name() == "#13b97d"
                   for y in range(image.height()) for x in range(image.width())), "logo pixels missing"
    root.setProperty("installSuccess", False)
    settle(100)
    assert not find_item(window.contentItem(), "doneBrandingLogo").property("visible")
    root.setProperty("branding", {"name": "Example Fork", "logoKind": "file",
                                  "logoValue": "file:///nonexistent/branding-logo.png"})
    root.setProperty("currentPage", 0)
    settle(100)
    assert not find_item(window.contentItem(), "welcomeBrandingLogo").property("visible")

    failures = []
    for f in findings:
        print(f"  {f['name']:14s} {f['w']}x{f['h']}  colours {f['colours']:5d}  "
              f"largest-flat {f['flat']*100:5.1f}%  ink {f['ink']*100:5.1f}%")
        page_failures = []
        if f["colours"] < 20:
            page_failures.append(f"{f['name']}: {f['colours']} colours — did not render")
        if f["flat"] > 0.995:
            page_failures.append(f"{f['name']}: {f['flat']*100:.1f}% one flat colour — blank")
        if f["ink"] < 0.002:
            page_failures.append(f"{f['name']}: {f['ink']*100:.2f}% lit pixels — nothing drawn")
        # Same verdict, same thresholds — recorded per page as well, so the
        # parity report can name WHICH screen was blank rather than only how
        # many were.
        f["rendered"] = not page_failures
        failures.extend(page_failures)

    # Emitted before the failure gate on purpose: a frontend that renders a
    # blank page is exactly the case tunaOS's parity matrix most needs a row
    # for. Bailing out first would leave niri reading "_GPU_" forever, which
    # is how the last crop of defects survived unseen.
    parity_report.write_report(
        out, "niri", findings,
        harness="tests/gui/capture-screens.py (QML via PyQt6, offscreen)")

    if failures:
        for m in failures:
            print(f"FAIL: {m}", file=sys.stderr)
        return 1

    gif = os.path.join(out, "walkthrough.gif")
    subprocess.run(["convert", "-delay", "240", "-loop", "0", *frames, gif], check=True)
    print(f"  wrote {len(frames)} screens + {os.path.basename(gif)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
