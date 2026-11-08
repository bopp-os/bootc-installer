# encryption.py
#
# Copyright 2024 mirkobrombin
#
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

from gettext import gettext as _

from gi.repository import Adw, Gtk

from bootc_installer.utils import copy as copy_text

@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-encryption.ui")
class BootcDefaultEncryption(Adw.Bin):
    __gtype_name__ = "BootcDefaultEncryption"

    btn_next = Gtk.Template.Child()
    page_header = Gtk.Template.Child()

    group_keep_encryption = Gtk.Template.Child()
    group_encryption_choice = Gtk.Template.Child()
    encryption_row = Gtk.Template.Child()
    use_encryption_switch = Gtk.Template.Child()
    tpm2_row = Gtk.Template.Child()
    tpm2_switch = Gtk.Template.Child()

    encryption_pass_entry = Gtk.Template.Child()
    encryption_pass_entry_confirm = Gtk.Template.Child()
    strength_label = Gtk.Template.Child()

    password_filled = False
    # Whether this machine has a TPM 2.0 (shared/tpm/README.md). Set once in
    # __init__; False until then so a half-built page never offers TPM.
    has_tpm2 = False

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        # This page is a switch plus a TPM switch, not the four-way choice
        # the other frontends show, so only the two choice descriptions it
        # can produce apply: the switch alone gives luks-passphrase, both
        # give tpm2-luks-passphrase. The words are the shared copy keys.
        self.encryption_row.set_subtitle(
            copy_text.encryption_text(window, "luks-passphrase", "_description"))
        self.tpm2_row.set_subtitle(
            copy_text.encryption_text(window, "tpm2-luks-passphrase", "_description"))

        self.btn_next.connect("clicked", self.__window.next)
        # The disk step may switch to "Keep my files" after this page was built: check on every page change.
        self.__window.carousel.connect("page-changed", lambda *_a: self.__update_keep_mode())
        self.use_encryption_switch.connect(
            "state-set", self.__on_encryption_switch_set)
        self.tpm2_switch.connect("state-set", self.__on_tpm2_switch_set)
        self.encryption_pass_entry.connect(
            "changed", self.__on_password_changed)
        self.encryption_pass_entry_confirm.connect(
            "changed", self.__on_password_changed
        )

        # Default: encryption ON, TPM2 ON if hardware present.
        #
        # Without a TPM 2.0 the TPM row is hidden, not merely switched off.
        # It used to stay visible and switchable on every machine, so a
        # person without a TPM (or with a TPM 1.2) could turn it on and get a
        # tpm2-luks-passphrase recipe that fails at enrolment, after the disk
        # has been partitioned. The other four frontends drop the TPM choices
        # on such a machine; this follows them. BOOTC_INSTALLER_FAKE_TPM
        # forces the row visible for screenshots.
        from bootc_installer.core.system import Systeminfo
        self.has_tpm2 = Systeminfo.has_tpm2()
        self.tpm2_row.set_visible(self.has_tpm2)
        self.use_encryption_switch.set_active(True)
        self.tpm2_switch.set_active(self.has_tpm2)

        self.__update_btn_next()

    def should_show(self, context: dict) -> bool:
        return True

    def test_auto_advance(self):
        # Ensure encryption is off — TPM2 won't work on virtual/loop disks
        self.use_encryption_switch.set_active(False)
        self.tpm2_switch.set_active(False)
        self.btn_next.emit("clicked")

    def get_finals(self):
        use_enc = self.use_encryption_switch.get_active()
        if not use_enc:
            return {"encryption": {"use_encryption": False, "encryption_key": ""}}
        passphrase = self.encryption_pass_entry.get_text()
        use_tpm2 = self.has_tpm2 and self.tpm2_switch.get_active()
        enc_type = "tpm2-luks-passphrase" if use_tpm2 else "luks-passphrase"
        return {
            "encryption": {
                "use_encryption": True,
                "type": enc_type,
                "encryption_key": passphrase,
            }
        }

    def __on_encryption_switch_set(self, state, user_data):
        if self.use_encryption_switch.get_active():
            self.page_header.icon_name = "changes-prevent-symbolic"
        else:
            self.page_header.icon_name = "changes-allow-symbolic"
            self.tpm2_switch.set_active(False)

        self.__update_btn_next()

    def __on_tpm2_switch_set(self, state, user_data):
        self.__update_btn_next()

    def __on_password_changed(self, *args):
        password = self.encryption_pass_entry.get_text()
        confirm = self.encryption_pass_entry_confirm.get_text()

        # Passphrase match validation
        if password and password == confirm:
            self.password_filled = True
            self.encryption_pass_entry_confirm.remove_css_class("error")
        else:
            self.password_filled = False
            if confirm:
                self.encryption_pass_entry_confirm.add_css_class("error")
            else:
                self.encryption_pass_entry_confirm.remove_css_class("error")

        # Real-time strength feedback
        if password:
            has_upper = any(c.isupper() for c in password)
            has_lower = any(c.islower() for c in password)
            has_digit = any(c.isdigit() for c in password)
            has_symbol = any(not c.isalnum() for c in password)
            variety = sum([has_upper, has_lower, has_digit, has_symbol])
            length = len(password)

            if length < 8 or variety < 2:
                self.strength_label.set_text(_("Weak \u2014 make it longer or more complex"))
                self.strength_label.remove_css_class("success")
                self.strength_label.remove_css_class("warning")
                self.strength_label.add_css_class("error")
            elif length < 12 or variety < 3:
                self.strength_label.set_text(_("Fair \u2014 consider making it longer"))
                self.strength_label.remove_css_class("error")
                self.strength_label.remove_css_class("success")
                self.strength_label.add_css_class("warning")
            else:
                self.strength_label.set_text(_("Strong passphrase"))
                self.strength_label.remove_css_class("error")
                self.strength_label.remove_css_class("warning")
                self.strength_label.add_css_class("success")
            self.strength_label.set_visible(True)
        else:
            self.strength_label.set_visible(False)

        self.__update_btn_next()

    def __keep_files(self) -> bool:
        try:
            window = self.__window
        except AttributeError:  # page built without a window (unit tests)
            return False
        return getattr(window, "keep_files_mode", False) is True

    def __update_keep_mode(self):
        keep = self.__keep_files()
        self.group_keep_encryption.set_visible(keep)
        self.group_encryption_choice.set_visible(not keep)
        self.__update_btn_next()

    def __update_btn_next(self):
        if self.__keep_files():
            # Nothing to choose: the disk step has the existing password.
            self.btn_next.set_sensitive(True)
            return
        use_enc = self.use_encryption_switch.get_active()
        rule = not use_enc or self.password_filled
        self.btn_next.set_sensitive(rule)
