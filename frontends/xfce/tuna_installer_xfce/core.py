"""Backend plumbing shared by every page: catalog, disks, live and offline
facts, recipe emission, validation and fisherman invocation. See
../INSTALLER-FRONTENDS.md."""

import json
import os
import shlex
import subprocess

from tuna_installer_xfce import branding, fisherman_probe, fisherman_validate

IN_FLATPAK = os.path.exists("/.flatpak-info")

# Dry run: the wizard behaves normally but NEVER launches fisherman.
#
# This exists because reaching the progress page is not a neutral act here.
# ProgressPage.on_enter() calls win.start_install(), so merely NAVIGATING to
# that page partitions a disk — there is no confirmation between the two. Any
# harness that drives this wizard the obvious way destroys the machine it runs
# on, and tests/gui/capture-screens.py has been working around exactly that by
# monkeypatching InstallerWindow.start_install to a no-op before showing a
# single page.
#
# A monkeypatch in one test script is not a safety property. It protects only
# the callers that remember to apply it, and it is invisible to anything
# driving the real binary — which is precisely what the live-ISO walkthrough
# harness in tuna-os/tunaOS does, over a QEMU keyboard, with no ability to
# patch anything. The interlock has to live in the app.
#
# So it does, and it follows the siblings: tuna-installer-cosmic refuses
# Message::StartInstall outright while TUNA_CAPTURE_DIR is set
# (src/capture.rs), and tuna-installer-kde drives its progress page through
# loadDemoState() rather than a real install. This is the same idea with the
# env var named for what it does rather than for the harness that wanted it.
#
# It is deliberately NOT just a refusal. A harness that reaches the progress
# page and sees nothing cannot tell "install suppressed" from "install
# crashed", and the `install` and `done` screens are two of the six in the
# tunaOS screen contract that no frontend has ever been credited with
# reaching. Under a dry run the progress page plays a representative fisherman
# transcript and completes, so those screens can finally be measured without a
# disk anywhere near it.
# Read at CALL time, not import time, and deliberately so.
#
# This was a module-level constant on the first attempt and the capture job
# caught it immediately: capture-screens.py imports core near the top to stub
# host_run, then set the env var further down, so the constant had already been
# evaluated as False and the guard refused to run. An import-time read makes
# the interlock depend on module import ORDER, which is an invisible property
# no caller can see and every new caller can get wrong — a poor foundation for
# the one check standing between a test harness and a partitioned disk.
def dry_run():
    return os.environ.get("TUNA_INSTALLER_DRY_RUN", "") not in ("", "0")


# Hardware facts -- the disks that may be installed to, TPM 2.0, and the
# RAM/CPU/UEFI requirements -- are fisherman's: `fisherman probe --json`,
# run once, unprivileged, on the host (shared/probe/README.md). This frontend
# used to run its own lsblk with its own filter (it offered zram), format
# sizes in SI "GB", and probed the TPM itself. None of that is here now.
#
# There is no fallback scan when the probe fails: the destination page shows
# the reason instead and offers no disk.
FISHERMAN_PATH = "/usr/local/bin/fisherman"
# fisherman, unprivileged, on the host: for `probe --json` and
# `validate --json`. Never through pkexec or sudo.
FISHERMAN_UNPRIVILEGED = (["flatpak-spawn", "--host"] if IN_FLATPAK else []) + [FISHERMAN_PATH]
PROBE_ARGV = FISHERMAN_UNPRIVILEGED + ["probe", "--json"]
# `fisherman validate --json --partial -`: a page's fields as a partial
# recipe on stdin (shared/recipe/README.md). fisherman owns the hostname,
# username, filesystem and encryption rules.
VALIDATE_ARGV = fisherman_validate.argv(FISHERMAN_UNPRIVILEGED)

# The encryption types in display order, with needs_passphrase and
# needs_tpm2: a byte-identical copy of fisherman's
# data/encryption-choices.json (tests/unit/test_encryption_choices.py).
ENCRYPTION_CHOICES = fisherman_validate.load_choices()


def needs_passphrase(enc_type):
    return fisherman_validate.needs_passphrase(enc_type, ENCRYPTION_CHOICES)


def needs_tpm2(enc_type):
    return fisherman_validate.needs_tpm2(enc_type, ENCRYPTION_CHOICES)

_probe_cache = {}


def probe(refresh=False):
    """(result, error): the probe result, or None and the reason it failed."""
    if refresh or "answer" not in _probe_cache:
        try:
            _probe_cache["answer"] = (fisherman_probe.run(PROBE_ARGV), None)
        except fisherman_probe.ProbeError as exc:
            _probe_cache["answer"] = (None, str(exc))
    return _probe_cache["answer"]


def has_tpm():
    """fisherman's tpm.usable; False when the probe failed.

    BOOTC_INSTALLER_FAKE_TPM is honoured by fisherman itself, and a capture
    can point BOOTC_INSTALLER_FAKE_PROBE at a fixture with a usable TPM.
    """
    result, _ = probe()
    return fisherman_probe.tpm_usable(result) if result else False


def is_live():
    """Whether the host booted from live media: fisherman's live.is_live.

    Only then may the recipe leave `image` empty, which installs the running
    system; fisherman rejects an empty image anywhere else. This frontend
    used to ask `bootc status` and read /proc/cmdline itself, inside its
    Flatpak sandbox. False when the probe failed."""
    result, _ = probe()
    return fisherman_probe.is_live(result) if result else False


def live_image():
    """The booted image on live media (live.live_image); "" otherwise or
    when bootc could not name it."""
    result, _ = probe()
    return fisherman_probe.live_image(result) if result else ""


def offline_images():
    """Image refs in the host's offline stores (probe's offline.images), for
    the "[available offline]" tag. fisherman exposes those stores to the
    install itself when the recipe leaves additionalImageStores out."""
    result, _ = probe()
    return set(fisherman_probe.offline_images(result)) if result else set()


def unmet_requirements():
    """fisherman's system.unmet ("ram", "cpu", "uefi"); empty when the probe
    failed, so a failed probe never warns."""
    result, _ = probe()
    return fisherman_probe.unmet_requirements(result) if result else []


def requirements_warning():
    """The welcome page's warning text, or "" when every requirement is met."""
    unmet = unmet_requirements()
    if not unmet:
        return ""
    keys = {"ram": "requirements_ram", "cpu": "requirements_cpu",
            "uefi": "requirements_uefi"}
    lines = [BRANDING.text("requirements_title")]
    lines += [BRANDING.text(keys[item]) for item in unmet if item in keys]
    return "\n".join(line for line in lines if line)


# A representative fisherman transcript for the dry run, in fisherman's real
# wire format: newline-delimited JSON on stdout, one event per line
# (shared/progress/README.md). ProgressPage.append_log parses it with exactly
# the parser a real install goes through, so the dry run exercises the real
# code path rather than a private one.
#
# It used to be nine hand-written "[n/9] Partitioning /dev/vda" lines,
# described in this comment as "fisherman's own prefix format". It is not:
# fisherman has never written that prefix, and the step COUNT is not fixed at
# nine either (cmd/fisherman/main.go computes total_steps from the recipe).
# The transcript matched the frontend's own regex rather than the backend, so
# the screenshot harness photographed a moving bar that no real install could
# produce.
#
# This file is generated from fisherman's own progress emitter and weight
# profile, not written by hand, so the percentages are the ones a real
# uncached auto-layout install emits. `timestamp` and `elapsed_ms` are frozen
# to keep the fixture stable; nothing in the parser reads either.
_TRANSCRIPT_PATH = os.path.join(os.path.dirname(__file__), "dry-run-transcript.ndjson")


def _load_dry_run_transcript():
    """The dry-run transcript as a list of lines, each ending in a newline."""
    with open(_TRANSCRIPT_PATH, encoding="utf-8") as fh:
        return [line for line in fh.read().splitlines(keepends=True) if line.strip()]


DRY_RUN_TRANSCRIPT = _load_dry_run_transcript()

# Flatpak runtimes ship no pkexec; escalate host-side. The live ISO symlinks
# the flatpak-bundled fisherman to /usr/local/bin and installs the polkit
# policy for it (tunaOS customize-live.sh).
#
# Under Flatpak, pkexec runs inside a host-side bash rather than straight
# from `flatpak-spawn --host pkexec ...`. fisherman runs as root, so this
# process can never signal it; fisherman cancels itself when its PARENT dies
# (tuna-os/fisherman#267). Launched directly, that parent was the host's
# flatpak-session-helper, which nothing here can kill. With the wrapper it is
# this bash. The wrapper does no redirection: stdout and stderr still come
# back through flatpak-spawn's pipes, as before.
#
# `-`: fisherman reads the recipe from stdin (tuna-os/fisherman#276). The
# app writes the JSON to the wrapper's stdin and closes it, so no file ever
# holds the passphrase or the user password. bash, pkexec, sudo and
# flatpak-spawn all pass stdin through.
FISHERMAN_WRAPPER_SCRIPT = 'pkexec /usr/local/bin/fisherman -; exit $?'
FISHERMAN_CMD = (
    ["flatpak-spawn", "--host", "bash", "-c", FISHERMAN_WRAPPER_SCRIPT]
    if IN_FLATPAK
    else ["sudo", "/usr/local/bin/fisherman", "-"]
)

IMAGES_JSON_PATHS = [
    os.environ.get("FISHERMAN_IMAGES_PATH", ""),
    os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                 "tuna-installer/images.json"),
    "/etc/tuna-installer/images.json",
    "/app/share/fisherman/data/images.json",
    "/usr/share/fisherman/data/images.json",
]


# --- product branding --------------------------------------------------------
#
# Nothing here names a product. shared/branding/README.md (monorepo) is the
# contract: a branding.json under /etc/bootc-installer (host first, since this
# ships as a Flatpak) names the product, seeds the hostname and the recipe's
# distroID; keys it does not set come from os-release; the last resort is a
# neutral "Linux". tuna_installer_xfce/branding.py is a byte-identical copy of
# the shared resolver.


def resolve_branding():
    """Resolve once per call; the module-level BRANDING is the cached answer."""
    return branding.resolve()


# Resolved once at import: the files do not change under a running installer,
# and every page title needs the same answer.
BRANDING = resolve_branding()
PRODUCT_NAME = BRANDING.name


def host_run(argv, **kwargs):
    """Run a command on the host, crossing the sandbox boundary if needed."""
    if IN_FLATPAK:
        argv = ["flatpak-spawn", "--host"] + argv
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


# --- image catalog -----------------------------------------------------------

class ImageNode:
    """One entry of images.json with root->leaf field inheritance resolved.

    Current images.json uses registry+tag; older files use imgref. Handle both.
    """

    def __init__(self, raw, parent=None):
        self.name = raw.get("name", "")
        self.desc = raw.get("desc", "")
        self.subtitle = raw.get("subtitle", "")
        p = parent
        self.registry = raw.get("registry") or (p.registry if p else "")
        tag = raw.get("tag", "")
        self.imgref = raw.get("imgref") or (f"{self.registry}:{tag}" if self.registry and tag else "")
        self.flatpaks = raw.get("flatpaks") or (p.flatpaks if p else "")
        self.bootloader = raw.get("bootloader") or (p.bootloader if p else "")
        self.filesystem = raw.get("filesystem") or (p.filesystem if p else "")
        self.composefs = raw.get("composefs", p.composefs if p else False)
        self.needs_user_creation = raw.get(
            "needs_user_creation", p.needs_user_creation if p else True)
        self.children = [ImageNode(c, self) for c in raw.get("children", [])]

    def is_leaf(self):
        return bool(self.imgref) and not self.children

    def leaves(self):
        if self.is_leaf():
            yield self
        for c in self.children:
            yield from c.leaves()


def load_catalog():
    """Return (default_image, fallback_flatpaks, [ImageNode]) or Nones."""
    for path in IMAGES_JSON_PATHS:
        if path and os.path.exists(path):
            with open(path) as f:
                raw = json.load(f)
            nodes = [ImageNode(n) for n in raw.get("images", [])]
            return raw.get("default_image", ""), raw.get("fallback_flatpaks", []), nodes
    return "", [], []


# --- disks --------------------------------------------------------------------

def candidate_disks():
    """(disks, error): the disks fisherman offers, in its order, rendered per
    shared/probe/README.md -- title (model, else path), size_label verbatim."""
    result, error = probe()
    if result is None:
        return [], error
    return fisherman_probe.render_disks(result), None


# --- recipe -------------------------------------------------------------------

def build_recipe(*, disk, filesystem, btrfs_subvolumes=False,
                 encryption_type="none", passphrase="", image="",
                 hostname="", bootloader="", composefs=False, flatpaks="",
                 needs_user=True, username="", fullname="",
                 password="", branding=None):
    """Assemble the fisherman recipe from already-resolved values.

    This is the contract with the install backend — the same document the KDE,
    COSMIC and Niri forks each build their own way (tuna-os/tunaOS#1197) — so
    it is the one piece of this frontend most worth being able to test without
    a display. It used to live in `InstallerWindow.build_recipe`, reading
    `Gtk.Entry.get_text()` and `Gtk.CheckButton.get_active()` inline, which
    made every conditional below reachable only by constructing a GTK window.

    Callers pass plain values; the widget layer stays responsible for reading
    them off the pages. The conditionals are the ones that were in the method,
    unchanged:

      * `btrfsSubvolumes` is only meaningful on btrfs, and is False elsewhere
        regardless of what the Advanced checkbox says.
      * The passphrase is only emitted for an encryption type that takes one
        (`needs_passphrase` in encryption-choices.json), so a stale entry
        left in the box cannot leak into a recipe for an unencrypted install.
      * `bootloader`, `composeFsBackend` and `flatpaks` are catalog-leaf
        properties: absent keys mean "let fisherman decide", which is not the
        same as an empty value.
      * A `@`-prefixed flatpaks field is a catalog reference, not a package
        list, and is not passed through.
      * The user block is omitted entirely when the image creates its own
        first user, or when no username was typed.
    """
    recipe = {
        "disk": disk,
        "filesystem": filesystem,
        "btrfsSubvolumes": filesystem == "btrfs" and btrfs_subvolumes,
        "encryption": {"type": encryption_type},
        "image": image,
        # True makes bootc boot the installed system with selinux=0.
        "selinuxDisabled": False,
        "hostname": hostname,
        # The branding's id, never a literal: see resolve_branding().
        "distroID": (branding or BRANDING).id,
    }
    if needs_passphrase(encryption_type):
        recipe["encryption"]["passphrase"] = passphrase
    if bootloader:
        recipe["bootloader"] = bootloader
    if composefs:
        recipe["composeFsBackend"] = True
    if flatpaks and not flatpaks.startswith("@"):
        recipe["flatpaks"] = flatpaks.split()
    if needs_user and username:
        recipe["user"] = {
            "username": username,
            "fullname": fullname,
            "password": password,
            "groups": ["wheel"],
        }
    return recipe


def recipe_stdin(recipe):
    """The bytes the app writes to fisherman's stdin (`fisherman -`)."""
    return json.dumps(recipe).encode("utf-8")


def fisherman_argv(in_flatpak=None):
    """The argv that runs fisherman with privileges, the recipe on stdin."""
    if in_flatpak is None:
        return list(FISHERMAN_CMD)
    if in_flatpak:
        return ["flatpak-spawn", "--host", "bash", "-c", FISHERMAN_WRAPPER_SCRIPT]
    return ["sudo", "/usr/local/bin/fisherman", "-"]


def fisherman_shell():
    return " ".join(shlex.quote(a) for a in fisherman_argv())


# --- install log --------------------------------------------------------------
#
# InstallerWindow used to keep fisherman's output only in `self._log_tail`, an
# in-memory list capped at the last 15 lines and shown on the Done page when an
# install fails. Close the app (or lose the display, as happens over a QEMU
# serial console) before reading it and the only record of what fisherman did
# is gone — the same gap already found and fixed in tuna-installer-kde,
# -cosmic, -niri and bootc-installer-asahi's frontends. Persist the full
# transcript to disk so it survives past the wizard process.

INSTALL_LOG_DIR_NAME = "tuna-installer"
INSTALL_LOG_FILE_NAME = "install.log"


def install_log_path():
    """Path to the persistent install log; ensures its directory exists."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    log_dir = os.path.join(base, INSTALL_LOG_DIR_NAME)
    os.makedirs(log_dir, mode=0o700, exist_ok=True)
    return os.path.join(log_dir, INSTALL_LOG_FILE_NAME)


def open_install_log():
    """Open the persistent install log for appending, creating it 0600."""
    path = install_log_path()
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    return os.fdopen(fd, "a")
