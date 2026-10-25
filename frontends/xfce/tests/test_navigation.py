"""Where the wizard's buttons show, and what the confirm and done pages say.

The CI walkthrough showed Back on the welcome page (nothing behind it),
during the install (which cannot be backed out of) and on the done page
(the end). The other frontends hide it on all three, and the done page
offers Close and Restart now instead.
"""

import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402


class _Page:
    def can_continue(self):
        return True


def _nav(step):
    win = types.SimpleNamespace(
        pages={name: _Page() for name in app.PAGE_ORDER},
        index=app.PAGE_ORDER.index(step),
        back_btn=Gtk.Button(), next_btn=Gtk.Button(), nav=Gtk.Box(),
    )
    app.InstallerWindow.refresh_nav(win)
    return win


def test_no_back_on_welcome():
    win = _nav("welcome")
    assert not win.back_btn.get_visible()
    assert win.next_btn.get_visible()


def test_back_on_the_steps_in_between():
    for step in ("source", "destination", "setup", "identity", "confirm"):
        win = _nav(step)
        assert win.back_btn.get_visible(), step
        assert win.back_btn.get_sensitive(), step


def test_no_nav_bar_while_installing_or_when_done():
    for step in ("progress", "done"):
        win = _nav(step)
        assert not win.back_btn.get_visible(), step
        assert not win.next_btn.get_visible(), step
        assert not win.nav.get_visible(), step


class _Win:
    class _Trawl:
        def set_fill(self, _f):
            pass

    def __init__(self):
        self.trawl = self._Trawl()


def test_done_page_says_installed_and_offers_close_and_restart():
    done = pages.DonePage(_Win())
    done.set_result(True, "")
    assert core.BRANDING.text("done_title") in done.headline.get_text()
    assert done.body.get_text() == core.BRANDING.text("done_subtitle")
    assert done.close_btn.get_label() == "Close"
    assert done.reboot_btn.get_label() == core.BRANDING.text("done_restart")
    assert done.reboot_btn.get_sensitive()


def test_failed_install_offers_close_but_not_restart():
    done = pages.DonePage(_Win())
    done.show_all()
    done.set_result(False, "tail")
    assert done.close_btn.get_visible()
    assert not done.reboot_btn.get_visible()


class _ConfirmWin:
    """What ConfirmPage.on_enter reads from the window."""

    def __init__(self):
        self.pages = {
            "destination": types.SimpleNamespace(
                selected_disk=lambda: {"path": "/dev/vdz", "title": "Disk"}),
            "source": types.SimpleNamespace(live_image=""),
        }

    def build_recipe(self):
        return {"disk": "/dev/vdz", "filesystem": "btrfs",
                "encryption": {"type": "none"}, "hostname": "box",
                "image": "registry.example/os:1"}


def test_confirm_summary_rows_and_erase_warning_name_the_disk():
    confirm = pages.ConfirmPage(_ConfirmWin())
    confirm.on_enter()
    text = confirm.summary.get_text()
    for row in ("Target disk:", "Filesystem:", "Encryption:", "Hostname:", "Image:"):
        assert row in text, row
    assert "/dev/vdz" in text and "registry.example/os:1" in text
    assert confirm.warn_text.get_text() == core.BRANDING.text(
        "confirm_warning", disk="/dev/vdz")
