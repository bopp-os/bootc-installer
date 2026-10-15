"""Reader for `fisherman probe --json`, per shared/probe/README.md.

Canonical copy. The Python frontends (GNOME, XFCE) carry byte-identical
copies and tests/unit/test_shared_probe.py enforces that they match, the
same arrangement shared/progress/ uses. Edit this file and re-copy; never
edit a copy.

fisherman decides which disks may be installed to, how big they are, whether
a TPM 2.0 is usable and whether the machine meets the minimum requirements.
This module only runs the command and reads its answer. It must not filter,
sort, re-format or second-guess any of it: that is how five frontends ended
up with five disk filters and three size units.
"""

import json
import os
import subprocess

# The schema version this reader understands. fisherman bumps it only when a
# field is removed, renamed or changes meaning; added fields are ignored.
PROTOCOL_VERSION = 1

# Test and screenshot seam: a path to a file holding probe output. When set,
# no process is run. Every frontend honours the same variable.
FAKE_ENV = "BOOTC_INSTALLER_FAKE_PROBE"

# How long the probe may take. It runs lsblk and `bootc status`; a hung host
# helper must not hang the wizard.
TIMEOUT_SECONDS = 30


class ProbeError(Exception):
    """The probe could not be run, failed, or printed something unreadable.

    There is deliberately no fallback disk scan behind this: the message is
    shown to the user instead (shared/probe/README.md, "When the probe
    fails").
    """


def parse(text):
    """The probe result in `text`, or ProbeError."""
    try:
        result = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ProbeError(f"fisherman probe printed invalid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ProbeError("fisherman probe did not print a JSON object")
    version = result.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise ProbeError(
            f"fisherman probe protocol_version {version!r} is not {PROTOCOL_VERSION}")
    return result


def run(argv, environ=None, timeout=TIMEOUT_SECONDS):
    """Run `argv` (which ends in `probe --json`) and return the parsed result.

    `argv` is the frontend's own way of reaching fisherman, unprivileged:
    `flatpak-spawn --host <fisherman> probe --json` in a Flatpak, the
    fisherman path itself outside one. Never through pkexec or sudo.
    """
    env = os.environ if environ is None else environ
    fake = env.get(FAKE_ENV, "")
    if fake:
        try:
            with open(fake, encoding="utf-8") as fh:
                return parse(fh.read())
        except OSError as exc:
            raise ProbeError(f"{FAKE_ENV}={fake}: {exc.strerror}") from exc
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ProbeError(f"cannot run {argv[0]}: not found") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"cannot run fisherman probe: {exc}") from exc
    if proc.returncode != 0:
        reason = (proc.stderr or "").strip().splitlines()
        detail = reason[0] if reason else "no message"
        raise ProbeError(f"fisherman probe failed (exit {proc.returncode}): {detail}")
    return parse(proc.stdout)


def eligible_disks(result):
    """The disks fisherman says may be installed to, in fisherman's order.

    An unknown `excluded_reason`, or a missing `eligible`, means not eligible.
    """
    return [d for d in result.get("disks") or [] if d.get("eligible") is True]


def disk_title(disk):
    """The disk's display name: its model, or its device path when unknown."""
    return disk.get("model") or disk.get("path", "")


def render_disks(result):
    """What every frontend shows per disk, as tests/unit/test_shared_probe.py
    and each frontend's own test compare it against the fixture's
    `*.expected.json`."""
    return [
        {
            "path": d.get("path", ""),
            "title": disk_title(d),
            "model": d.get("model", ""),
            "size_label": d.get("size_label", ""),
            "transport_label": d.get("transport_label", ""),
            "removable": bool(d.get("removable")),
        }
        for d in eligible_disks(result)
    ]


def tpm_usable(result):
    """Whether a TPM 2.0 is usable, so the tpm2-luks choices may be offered."""
    return bool((result.get("tpm") or {}).get("usable"))


def unmet_requirements(result):
    """Which minimum requirements this machine misses: "ram", "cpu", "uefi"."""
    return list((result.get("system") or {}).get("unmet") or [])


def is_uefi(result):
    return bool((result.get("system") or {}).get("uefi"))


def is_live(result):
    """Whether the host booted from live media (probe's live.is_live). Only
    then may a recipe leave `image` empty: fisherman installs the running
    image, and rejects an empty image anywhere else (image_required)."""
    return bool((result.get("live") or {}).get("is_live"))


def live_image(result):
    """The booted image ref when live; "" otherwise or when bootc could not
    say. What a frontend shows as the image of a live install."""
    if not is_live(result):
        return ""
    return (result.get("live") or {}).get("live_image") or ""


def offline_images(result):
    """Image refs present in the host's offline stores (offline.images), for
    an "available offline" tag. The stores themselves are fisherman's: a
    recipe that leaves additionalImageStores out gets them."""
    return list((result.get("offline") or {}).get("images") or [])


def format_size(nbytes):
    """fisherman's size rule (binary units, labelled honestly), for the rare
    size fisherman does not report itself, such as a partition. A disk's size
    is always its `size_label`; never format one here."""
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    value = float(nbytes)
    i = 0
    while value >= 1024 and i < len(units) - 1:
        value /= 1024
        i += 1
    if i == 0:
        return f"{int(nbytes)} B"
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text} {units[i]}"
