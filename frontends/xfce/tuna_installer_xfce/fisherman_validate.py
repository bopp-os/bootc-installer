"""Reader for `fisherman validate --json` and the encryption choices file,
per shared/recipe/README.md.

Canonical copy. The Python frontends (GNOME, XFCE) carry byte-identical
copies and tests/unit/test_shared_validate.py enforces that they match, the
same arrangement shared/probe/ uses. Edit this file and re-copy; never edit
a copy.

fisherman owns the recipe rules: hostname, username, filesystem, encryption
(fisherman/docs/VALIDATE.md). The install runs the same rules before it
touches a disk. A frontend asks fisherman while the user types, and shows
the answer through the copy key `validate_<code>`. It must not re-implement
a rule: that is how five frontends ended up with five hostname checks, and
a username like `Alice` failed only after the OS was on disk.

The recipe goes to fisherman on stdin (`-`), never on argv: a partial recipe
can hold the LUKS passphrase, and argv is world-readable in /proc.
"""

import json
import os
import subprocess
import threading

# The schema version this reader understands. fisherman bumps it only when a
# field is removed, renamed or changes meaning; new codes do not bump it.
PROTOCOL_VERSION = 1

# How long one check may take. It reads nothing from the machine in
# --partial mode, so this only bounds a hung flatpak-spawn.
TIMEOUT_SECONDS = 10

# A problem's copy key is this prefix plus its code (shared/branding).
COPY_PREFIX = "validate_"

# Where a frontend copy of encryption-choices.json sits: beside this module.
CHOICES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "encryption-choices.json")


class ValidateError(Exception):
    """fisherman could not be asked, or its answer was unreadable.

    This is not "the recipe is invalid". A frontend shows nothing and does
    not block: the install runs the same rules before it touches a disk.
    """


def argv(fisherman, partial=True):
    """The command for one check. `fisherman` is the frontend's own,
    unprivileged way of reaching fisherman (a list): the binary, prefixed
    with `flatpak-spawn --host` in a Flatpak. Never through pkexec or sudo."""
    return list(fisherman) + ["validate", "--json"] + (["--partial"] if partial else []) + ["-"]


def parse(text):
    """The validate result in `text`, or ValidateError."""
    try:
        result = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValidateError(f"fisherman validate printed invalid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ValidateError("fisherman validate did not print a JSON object")
    version = result.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise ValidateError(
            f"fisherman validate protocol_version {version!r} is not {PROTOCOL_VERSION}")
    if not isinstance(result.get("errors"), list):
        raise ValidateError("fisherman validate printed no errors list")
    return result


def run(command, recipe, timeout=TIMEOUT_SECONDS):
    """Write `recipe` (a dict) to `command`'s stdin and return the parsed
    result. Exit 0 is valid, 1 invalid; anything else is ValidateError."""
    try:
        proc = subprocess.run(command, input=json.dumps(recipe), capture_output=True,
                              text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ValidateError(f"cannot run {command[0]}: not found") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidateError(f"cannot run fisherman validate: {exc}") from exc
    if proc.returncode not in (0, 1):
        reason = (proc.stderr or "").strip().splitlines()
        detail = reason[0] if reason else "no message"
        raise ValidateError(f"fisherman validate failed (exit {proc.returncode}): {detail}")
    return parse(proc.stdout)


def problems(result, field=None):
    """The problems in `result`, in fisherman's order; only those for
    `field` (a JSON path such as "hostname" or "user.username") when given."""
    errors = [e for e in result.get("errors") or [] if isinstance(e, dict)]
    if field is None:
        return errors
    return [e for e in errors if e.get("field") == field]


def copy_key(code):
    """The branding copy key for a problem code."""
    return COPY_PREFIX + code


def render(problem, text):
    """The line a frontend shows for `problem`: the copy for its code, read
    through the frontend's resolver `text(key)`, or fisherman's English
    message for a code this build has no copy for (VALIDATE.md,
    "Compatibility")."""
    line = text(copy_key(problem.get("code", ""))) if problem.get("code") else ""
    return line or problem.get("message", "")


def load_choices(path=CHOICES_FILE):
    """The encryption choices, in display order (fisherman's
    data/encryption-choices.json, copied byte for byte)."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return [c for c in doc.get("choices") or [] if isinstance(c, dict) and c.get("type")]


def choice(enc_type, choices):
    """The choice for `enc_type` ("" is "none"), or None for a type
    fisherman does not accept."""
    enc_type = enc_type or "none"
    for c in choices:
        if c.get("type") == enc_type:
            return c
    return None


def needs_passphrase(enc_type, choices):
    return bool((choice(enc_type, choices) or {}).get("needs_passphrase"))


def needs_tpm2(enc_type, choices):
    return bool((choice(enc_type, choices) or {}).get("needs_tpm2"))


class LiveCheck:
    """Debounced, off-thread `validate --json --partial -` for one page.

    submit() a partial recipe each time a field changes. After `delay_ms`
    without a further change, fisherman is asked on a worker thread, and
    `on_result(problems, error)` is called back on the UI thread with
    either the problems (a list, empty when valid) or the reason the check
    could not run. An answer for anything but the latest submit is dropped.

    The toolkit's own scheduling is passed in, so this stays free of GTK:
    `timeout_add(ms, fn)` returns a source id, `source_remove(id)` cancels
    it, and `idle_add(fn, *args)` runs fn on the UI thread (all three are
    GLib's functions in the GTK frontends).
    """

    def __init__(self, command, on_result, *, timeout_add, source_remove, idle_add,
                 delay_ms=300, runner=None, start_thread=None):
        self._command = command
        self._on_result = on_result
        self._timeout_add = timeout_add
        self._source_remove = source_remove
        self._idle_add = idle_add
        self._delay_ms = delay_ms
        self._runner = runner or run
        self._start_thread = start_thread or (
            lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._timer = None
        self._seq = 0
        self.pending = False

    def submit(self, recipe):
        self._seq += 1
        seq = self._seq
        self.pending = True
        if self._timer is not None:
            self._source_remove(self._timer)
        self._timer = self._timeout_add(self._delay_ms, lambda: self._fire(seq, dict(recipe)))

    def _fire(self, seq, recipe):
        self._timer = None

        def work():
            try:
                answer = (problems(self._runner(self._command, recipe)), None)
            except ValidateError as exc:
                answer = (None, str(exc))
            self._idle_add(self._deliver, seq, answer)

        self._start_thread(work)
        return False

    def _deliver(self, seq, answer):
        if seq == self._seq:
            self.pending = False
            self._on_result(*answer)
        return False
