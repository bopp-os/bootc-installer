# welcome.py
#
# Copyright 2024 mirkobrombin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import os
import pathlib
import subprocess

from gi.repository import Adw, GLib, Gtk

from bootc_installer.views.done import apply_icon
from bootc_installer.windows.dialog_recovery import BootcRecoveryDialog
from bootc_installer.windows.dialog_poweroff import BootcPoweroffDialog

_IN_FLATPAK = os.path.exists("/.flatpak-info")


logger = logging.getLogger("Installer::Welcome")


def _needs_bluetooth_pairing() -> bool:
    """Return True if a Bluetooth adapter exists but no wired HID is present."""
    bt_adapters = list(pathlib.Path("/sys/class/bluetooth").glob("hci*"))
    if not bt_adapters:
        return False

    input_path = pathlib.Path("/sys/class/input")
    for dev in input_path.glob("event*"):
        device_path = dev / "device"
        if not device_path.exists():
            continue

        phys_file = device_path / "phys"
        if not phys_file.exists():
            continue

        try:
            phys = phys_file.read_text().strip()
        except OSError:
            continue

        if "usb" not in phys.lower():
            continue

        cap_file = device_path / "capabilities" / "ev"
        if not cap_file.exists():
            continue

        try:
            caps = int(cap_file.read_text().strip(), 16)
        except (OSError, ValueError):
            continue

        if caps & 0x2 or caps & 0x4:
            return False

    return True


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-welcome.ui")
class BootcDefaultWelcome(Adw.Bin):
    __gtype_name__ = "BootcDefaultWelcome"

    page_header = Gtk.Template.Child()
    row_install = Gtk.Template.Child()
    row_bluetooth = Gtk.Template.Child()
    row_recovery = Gtk.Template.Child()
    row_poweroff = Gtk.Template.Child()
    btn_credits = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        fallback_logo = self.__distro_info.get("logo", "org.bootcinstaller.Installer")
        icon_spec = fallback_logo or self.__distro_info.get("default_image_icon")

        apply_icon(self.page_header, icon_spec)
        welcome_title = self.__distro_info.get("welcome_title") or "bootc Installer"
        self.page_header.title = welcome_title

        # The install row's title is hardcoded to "Install Bluefin" in
        # default-welcome.blp and was never set at runtime, so every downstream
        # that rebrands this installer still offered to install Bluefin —
        # directly beneath a correctly branded welcome title, because
        # welcome_title above IS driven by the recipe.
        #
        # "name", not "distro_name": builder.py's distro_info property maps
        # recipe["distro_name"] onto the key "name". Reading "distro_name" here
        # would silently always miss and render the fallback, which is
        # indistinguishable from having no recipe at all.
        #
        # Same source and same fallback as done.py's "{} is installed".
        from bootc_installer.utils import copy as copy_text
        distro_name = self.__distro_info.get("name") or copy_text.product_name(self.__window)
        self.row_install.set_title(copy_text.text(self.__window, "welcome_install", name=distro_name))
        install_subtitle = copy_text.text(self.__window, "welcome_install_subtitle", name=distro_name)
        if install_subtitle:
            self.row_install.set_subtitle(install_subtitle)
        welcome_subtitle = self.__distro_info.get("welcome_subtitle", "")
        self.page_header.subtitle = welcome_subtitle

        try:
            self.row_bluetooth.set_visible(_needs_bluetooth_pairing())
        except Exception:
            self.row_bluetooth.set_visible(False)

        # signals
        self.row_install.connect("activated", self.__install)
        self.row_bluetooth.connect("activated", self.__on_bluetooth_clicked)
        self.row_recovery.connect("activated", self.__on_recovery_clicked)
        self.row_poweroff.connect("activated", self.__on_poweroff_clicked)
        self.btn_credits.connect("clicked", self.__on_credits_clicked)

        # Install is the primary action, so it should be what has focus when
        # the screen appears — Enter starts the install rather than doing
        # whatever happens to be first in tab order.
        #
        # Without this the welcome screen opens with focus nowhere in
        # particular, and Tab walks install -> bluetooth -> recovery ->
        # poweroff -> credits. TunaOS's screenshot harness, which drives the
        # installer blind with tab/Enter, reached Credits and opened the modal;
        # every subsequent keystroke went to the dialog and the run never left
        # the welcome screen (tunaOS installer-smoke run 31183217981).
        #
        # A keyboard user hits the same edge more mildly: on a wizard whose
        # entire purpose is one action, Enter should perform it.
        #
        # Deferred to an idle callback because the row is not realised yet at
        # __init__ time and grab_focus() on an unrealised widget is a no-op.
        GLib.idle_add(self.__focus_primary_action)

    def __focus_primary_action(self):
        """Put focus on Install once the row exists. Runs once."""
        try:
            self.row_install.grab_focus()
        except Exception as e:  # never let focus cost us the screen
            logger.debug("Could not focus the install row: %s", e)
        return GLib.SOURCE_REMOVE

    def should_show(self, context: dict) -> bool:
        return True

    def test_auto_advance(self):
        self.row_install.emit("activated")

    def get_finals(self):
        return {}

    def __on_bluetooth_clicked(self, row):
        commands = [
            ["gnome-control-center", "bluetooth"],
            ["gnome-bluetooth-panel"],
            ["blueman-manager"],
        ]

        for command in commands:
            if _IN_FLATPAK:
                command = ["flatpak-spawn", "--host"] + command
            try:
                subprocess.Popen(command)
                return
            except FileNotFoundError:
                continue
            except Exception:
                return

    def __on_recovery_clicked(self, row):
        BootcRecoveryDialog(self.__window).show()

    def __on_poweroff_clicked(self, row):
        BootcPoweroffDialog(self.__window).show()

    def __on_credits_clicked(self, button):
        from bootc_installer.windows.dialog_credits import BootcCreditsWindow
        BootcCreditsWindow(self.__window).show()

    def __install(self, _):
        if self.__window.install_mode == 1:
            self.__window.rebuild_ui(0)
        self.__window.next()
