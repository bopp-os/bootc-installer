"""One entry checked by fisherman while the user types.

fisherman owns the hostname and username rules (`fisherman validate --json
--partial -`, shared/recipe/README.md). A FieldCheck sends the entry's text
as a partial recipe after a pause in the typing, off the UI thread, and
shows the problem fisherman reports under the entry, in the words of the
copy key `validate_<code>`. The page asks `ok` before it enables Next.

If fisherman cannot be asked, nothing is shown and nothing is blocked: the
install runs the same rules before it touches a disk.
"""

import logging

from bootc_installer.core import fisherman_validate
from bootc_installer.utils import copy as copy_text
from bootc_installer.utils import fisherman_runner

logger = logging.getLogger("Installer::FieldCheck")


def validate_command():
    """`fisherman validate --json --partial -`, unprivileged, on the host:
    the binary the probe already staged in a Flatpak."""
    return fisherman_validate.argv(fisherman_runner.fisherman_argv())


def _glib_live_check(on_result):
    from gi.repository import GLib
    return fisherman_validate.LiveCheck(
        validate_command(), on_result,
        timeout_add=GLib.timeout_add, source_remove=GLib.source_remove,
        idle_add=GLib.idle_add)


class FieldCheck:
    """Checks `entry` as the recipe field `field` ("hostname",
    "user.username").

    `partial(text)` builds the partial recipe for the entry's text.
    `message` is shown under the entry, hidden when there is no problem: a
    Gtk.Label, or a row (its title carries the text). `on_change()` is
    called whenever `ok` may have changed, so the page can update its
    buttons.
    """

    def __init__(self, window, entry, field, partial, message, on_change=None,
                 live_check_factory=_glib_live_check):
        self._window = window
        self._entry = entry
        self._field = field
        self._partial = partial
        self._message = message
        self._on_change = on_change or (lambda: None)
        self._problem = None
        self._check = live_check_factory(self._on_result)
        self._message.set_visible(False)
        entry.connect("changed", lambda *_: self.submit())

    @property
    def ok(self) -> bool:
        """No problem is known for this field."""
        return self._problem is None

    @property
    def problem(self):
        return self._problem

    def submit(self):
        self._check.submit(self._partial(self._entry.get_text()))

    def _set_message(self, text):
        if hasattr(self._message, "set_label"):
            self._message.set_label(text)
        else:
            self._message.set_title(text)

    def _on_result(self, problems, error):
        if error is not None:
            logger.warning("fisherman validate could not run: %s", error)
            problems = []
        mine = [p for p in problems if p.get("field") == self._field]
        self._problem = mine[0] if mine else None
        if self._problem is None:
            self._entry.remove_css_class("error")
            self._message.set_visible(False)
            self._set_message("")
        else:
            self._entry.add_css_class("error")
            self._set_message(fisherman_validate.render(
                self._problem, lambda key: copy_text.text(self._window, key)))
            self._message.set_visible(True)
        self._on_change()
