#!/usr/bin/env python3
"""End to end: the Niri wizard's recipe, through the real Go backend, into
fisherman.

The chain on a live ISO is QML -> `tuna-installer-niri install` (recipe on
stdin) -> `sudo /usr/local/bin/fisherman -` (recipe on stdin again).
Quickshell cannot run headless, so the QML is loaded under PyQt6 with the
stub modules from tests/qml-stubs, driven to Confirm, and its Install button
pressed (startInstall). The stub Process records what the QML wrote to the
backend's stdin instead of spawning it. That exact byte string is then piped
to the REAL backend binary, which pipes it on to fisherman
(shared/e2e/setup.sh's validating shim) and streams its output.

    python3 tests/e2e/run.py            # after: cd installer && go build -o tuna-installer-niri .
"""
import json
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
E2E_DIR = os.environ.get("TUNA_E2E_DIR", "/tmp/tuna-e2e")
BACKEND = os.environ.get("TUNA_BACKEND", os.path.join(REPO, "installer", "tuna-installer-niri"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The branding the backend and the QML resolve from (shared/branding): this
# frontend has no image chooser, so the image it installs is the branding's
# default_image; on a runner that is the canary shared/e2e later rewrites.
os.environ.setdefault("BOOTC_INSTALLER_BRANDING", os.path.join(REPO, "tests", "e2e", "branding.json"))
os.environ["QML2_IMPORT_PATH"] = os.path.join(REPO, "tests", "qml-stubs")
os.environ["QML_IMPORT_PATH"] = os.environ["QML2_IMPORT_PATH"]

from PyQt6.QtCore import (QEventLoop, QMetaObject, QObject, QTimer, QUrl,
                          Q_ARG, QVariant)
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine


# The account the e2e user types. The VM job installs it for real, so it is
# a valid name for fisherman (not reserved) and names no product.
ACCOUNT = {"username": "e2euser", "fullname": "E2E User",
           "userPassword": "e2e-password", "userPasswordConfirm": "e2e-password"}


def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    if not os.path.exists(BACKEND):
        sys.exit(f"FAIL: backend binary not built at {BACKEND}")
    with open(os.path.join(E2E_DIR, "loopdev")) as fh:
        disk = fh.read().strip()
    name = os.path.basename(disk)

    _app = QGuiApplication(sys.argv)  # must outlive the engine
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(os.path.join(REPO, "ui", "installer.qml")))
    if not engine.rootObjects():
        sys.exit("FAIL: installer.qml did not load")
    root = engine.rootObjects()[0]
    settle(400)

    # What the QML's own Process wrappers would have learned from the backend
    # on a real machine, from the real backend.
    facts = json.loads(subprocess.run([BACKEND, "detect"], capture_output=True, text=True, check=True).stdout)
    disks = json.loads(subprocess.run([BACKEND, "discover-disks"], capture_output=True, text=True, check=True).stdout)
    print(f"[e2e] backend detect: {facts}")
    print(f"[e2e] backend discover-disks: {disks}")
    chosen = next((d for d in disks if d.get("path") == disk), None)
    if chosen is None:
        sys.exit(f"FAIL: the backend did not list the e2e disk {name}: {disks}")

    # Drive the wizard the way a user would reach Install: pick the disk,
    # fill the account, walk to Confirm, press Install.
    root.setProperty("branding", facts.get("branding") or {})
    root.setProperty("isLive", facts.get("isLive") is True)
    root.setProperty("liveImage", facts.get("liveImage") or "")
    root.setProperty("encryptionChoices", facts.get("encryptionChoices") or [])
    root.setProperty("disks", disks)
    root.setProperty("selectedDisk", chosen)
    # The account page (required: this frontend has no image catalog). Its
    # Continue is held until these are set; advance() is the same call the
    # button and Enter make, so a page that will not let a user through
    # fails here rather than in the VM.
    root.setProperty("currentPage", 3)
    for prop, value in ACCOUNT.items():
        root.setProperty(prop, value)
    settle(500)  # the validate debounce, then the stub's answer
    if not root.property("accountReady"):
        sys.exit("FAIL: the filled account page holds Continue")
    QMetaObject.invokeMethod(root, "advance")
    settle(200)
    if root.property("currentPage") != 4:
        sys.exit(f"FAIL: Continue on the account page went to page "
                 f"{root.property('currentPage')}, not Confirm")
    QMetaObject.invokeMethod(root, "startInstall")
    settle(300)

    # The install Process's write(); the stub keeps it. The validate Process
    # writes too (the page's fields, for `fisherman validate --partial`), so
    # pick the one whose command is `install`.
    def _command(obj):
        cmd = obj.property("command")
        cmd = cmd.toVariant() if hasattr(cmd, "toVariant") else cmd
        return list(cmd or [])

    written = next((obj.property("written") for obj in root.findChildren(QObject)
                    if obj.property("written") and "install" in _command(obj)), None)
    if not written:
        sys.exit("FAIL: startInstall wrote nothing to the backend's stdin")
    recipe = json.loads(written)
    print("[e2e] recipe the QML wrote:\n" + json.dumps(recipe, indent=2))
    if recipe.get("disk") != disk:
        sys.exit(f"FAIL: QML chose {recipe.get('disk')!r}, expected {disk!r}")
    want_user = {"username": ACCOUNT["username"], "fullname": ACCOUNT["fullname"],
                 "password": ACCOUNT["userPassword"], "groups": ["wheel"]}
    if recipe.get("user") != want_user:
        sys.exit(f"FAIL: the recipe's user block is {recipe.get('user')!r}, "
                 f"expected {want_user!r}")

    print(f"[e2e] piping it to {BACKEND} install")
    r = subprocess.run([BACKEND, "install"], input=written, capture_output=True, text=True,
                       timeout=180, check=False)
    print(r.stdout)
    print(r.stderr, file=sys.stderr)
    if r.returncode != 0:
        sys.exit(f"FAIL: backend install exited {r.returncode}")
    # Feed the backend's real output through the QML's own appendLog(), the
    # function a live install calls, and check where the bar lands.
    #
    # This was `if "[9/9]" not in r.stdout`, matching a prefix fisherman has
    # never written — the shim invented it to satisfy this line, so the
    # assertion compared the harness with itself and passed while the QML
    # bar sat at zero for every real install.
    for line in r.stdout.splitlines():
        if line.strip():
            QMetaObject.invokeMethod(root, "appendLog", Q_ARG(QVariant, line))
    fraction = root.property("installFraction")
    steps = root.property("installSteps")
    print(f"[e2e] progress bar ended at {fraction:.0%} over {steps} steps")
    if '"type":"complete"' not in r.stdout:
        sys.exit("FAIL: the backend's output carried no completion event")
    if fraction != 1.0:
        sys.exit(f"FAIL: the progress bar ended at {fraction:.0%}, not 100% — "
                 "the QML is not parsing fisherman's progress protocol "
                 "(shared/progress/README.md)")
    # The last step carries step_id "finalize", so its caption is the copy
    # line step_finalize, not fisherman's raw step_name.
    with open(os.path.join(REPO, "installer", "copy-defaults.json"), encoding="utf-8") as fh:
        want = json.load(fh)["step_finalize"]
    label = root.property("installStepName")
    print(f"[e2e] last step label: {label!r}")
    if label != want:
        sys.exit(f"FAIL: the last step reads {label!r}, not the copy line {want!r} -- "
                 "the QML is not labelling steps by step_id")
    if not os.path.exists(os.path.join(E2E_DIR, "recipe.json")):
        sys.exit("FAIL: the shim recorded no recipe")
    print("OK: Niri's recipe went QML -> backend -> fisherman")
    return 0


if __name__ == "__main__":
    sys.exit(main())
