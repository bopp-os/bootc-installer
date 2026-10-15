# dialog.py
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

import re
from gettext import gettext as _

from bootc_installer.utils import copy as copy_text
from bootc_installer.utils.field_check import FieldCheck

from gi.repository import Adw, GObject, Gtk


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-choice.ui")
class BootcChoiceEntry(Adw.ActionRow):
    __gtype_name__ = "BootcChoiceEntry"

    img_choice = Gtk.Template.Child()

    def __init__(self, title, subtitle, icon_name, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.img_choice.set_from_icon_name(icon_name)


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-choice-expander.ui")
class BootcChoiceExpanderEntry(Adw.ExpanderRow):
    __gtype_name__ = "BootcChoiceExpanderEntry"

    img_choice = Gtk.Template.Child()

    def __init__(self, title, subtitle, icon_name, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.img_choice.set_from_icon_name(icon_name)




@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/confirm.ui")
class BootcConfirm(Adw.Bin):
    __gtype_name__ = "BootcConfirm"
    __gsignals__ = {
        "installation-confirmed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    group_changes = Gtk.Template.Child()
    btn_confirm = Gtk.Template.Child()
    lbl_body = Gtk.Template.Child()
    page_header = Gtk.Template.Child()


    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.delta = False
        self._hostname_entry_row = None
        self._hostname_check = None

    def update(self, finals):
        self._hostname_entry_row = None  # reset on every update
        self._hostname_check = None
        try:
            for widget in self.active_widgets:
                self.group_changes.remove(widget)
        except AttributeError:
            pass
        self.active_widgets = []

        selected_language = None

        for final in finals:
            for key, value in final.items():
                if key == "language":
                    selected_language = value
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Language"), value, "preferences-desktop-locale-symbolic"
                        )
                    )
                elif key == "keyboard":
                    self.process_keyboards(value)
                elif key == "timezone":
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Timezone"),
                            f"{value['region']} {value['zone']}",
                            "preferences-system-time-symbolic",
                        )
                    )
                elif key == "users":
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Users"),
                            f"{value['username']} ({value['fullname']})",
                            "system-users-symbolic",
                        )
                    )
                elif key == "disk":
                    if "auto" in value:
                        self.active_widgets.append(
                            BootcChoiceEntry(
                                _("Disk"),
                                f"{value['auto']['disk']} ({value['auto']['pretty_size']})",
                                "drive-harddisk-system-symbolic",
                            )
                        )
                        # Destructive action warning: the branding
                        # contract's confirm_warning, with {disk} filled in.
                        # Plain text, not markup -- the line can come from a
                        # product's branding file.
                        warning = Adw.ActionRow()
                        warning.set_use_markup(False)
                        warning.set_title(
                            copy_text.text(self.__window, "confirm_warning",
                                           disk=value["auto"]["disk"])
                            or _("All data on this disk will be erased. This cannot be undone."))
                        warning.set_title_lines(0)
                        warning.add_css_class("error")
                        self.active_widgets.append(warning)
                    else:
                        disks = {}
                        # block, device_block
                        for part, info in value.items():
                            part_disk = re.match(
                                "^/dev/[a-zA-Z]+([0-9]+[a-z][0-9]+)?",
                                part,
                                re.MULTILINE,
                            )[0]
                            if part_disk not in disks:
                                disks[part_disk] = BootcChoiceExpanderEntry(
                                    _("Disk"),
                                    part_disk,
                                    "drive-harddisk-system-symbolic",
                                )
                                self.active_widgets.append(disks[part_disk])

                            disks[part_disk].add_row(
                                BootcChoiceEntry(
                                    part,
                                    f"{info['fs']} {info['mp']} ({info['pretty_size']})",
                                    "drive-harddisk-system-symbolic",
                                )
                            )
                elif key == "encryption":
                    enc_type = value.get("type", "none") if isinstance(value, dict) else str(value)
                    # Branding copy, the same words every frontend uses;
                    # a type outside the contract shows as itself.
                    label = copy_text.encryption_text(self.__window, enc_type, "_label") or enc_type
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Encryption"),
                            label,
                            "channel-secure-symbolic",
                        )
                    )
                elif key == "hostname":
                    entry_row = Adw.EntryRow()
                    entry_row.set_title(_("Hostname"))
                    entry_row.set_text(value or "")
                    entry_row.set_show_apply_button(False)
                    self._hostname_entry_row = entry_row
                    self.active_widgets.append(entry_row)
                    # An edit here is the hostname that gets installed, so
                    # fisherman checks it as the disk page's field is.
                    # A row of its own, under the entry, like the summary.
                    message = Adw.ActionRow()
                    message.set_use_markup(False)
                    message.set_title_lines(0)
                    message.add_css_class("error")
                    self.active_widgets.append(message)
                    self._hostname_check = FieldCheck(
                        self.__window, entry_row, "hostname",
                        lambda text: {"hostname": text.strip()},
                        message, on_change=self.__update_confirm_button)
                elif key == "selected_image":
                    pn = final.get("pretty_name") or value
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Image"),
                            pn,
                            "application-x-appliance-symbolic",
                        )
                    )
                elif key == "custom_image":
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Image"),
                            value,
                            "image-missing-symbolic"
                        )
                    )

        # Hardware-detected GPU badge (always shown if a GPU is found)
        from bootc_installer.core.system import Systeminfo
        gpu_label = Systeminfo.gpu_display_string()
        if gpu_label:
            gpu_icon = Systeminfo.gpu_icon_name()
            self.active_widgets.append(
                BootcChoiceEntry(
                    _("Graphics"),
                    gpu_label,
                    gpu_icon,
                )
            )

        # Flavour text from the branding contract (shared/branding): a
        # locale-specific quote when the product ships one for the selected
        # language, else its confirm_subtitle; the body line and the button
        # label likewise. Nothing here names a product.
        self.page_header.title = copy_text.text(self.__window, "confirm_title")
        self.page_header.subtitle = copy_text.confirm_subtitle(self.__window, selected_language or "")
        body = copy_text.text(self.__window, "confirm_body")
        self.lbl_body.set_label(body)
        self.lbl_body.set_visible(bool(body))
        self.btn_confirm.set_label(copy_text.text(self.__window, "confirm_button") or _("Install"))

        for widget in self.active_widgets:
            self.group_changes.add(widget)
        self.__update_confirm_button()

        self._btn_confirm_signal = self.btn_confirm.connect(
            "clicked", self.__on_confirm
        )

    def __update_confirm_button(self):
        self.btn_confirm.set_sensitive(
            self._hostname_check is None or self._hostname_check.ok)

    def test_auto_advance(self):
        self.btn_confirm.emit("clicked")

    def get_hostname_override(self):
        """Return the hostname the user typed on the confirm screen, or None.

        Returns None if the confirm screen was never shown a hostname field
        (e.g. the disk step is hidden or no hostname was in finals).
        """
        if self._hostname_entry_row is None:
            return None
        text = self._hostname_entry_row.get_text().strip()
        return text if text else None

    def __on_confirm(self, widget):
        self.emit("installation-confirmed")
        self.btn_confirm.disconnect(self._btn_confirm_signal)

    def process_keyboards(self, selected_keyboards):
        keyboard_index = ""
        if len(selected_keyboards) > 1:
           keyboard_index = 0 
        for i in selected_keyboards:
            value = i["layout"]
            if i["variant"] != "":
                value = f"{i['layout']}+{i['variant']}"
            if len(selected_keyboards) > 1:
                keyboard_index += 1
            self.active_widgets.append(
                BootcChoiceEntry(
                    _(f"Keyboard {keyboard_index}"), value,"input-keyboard-symbolic"
                )
            )
