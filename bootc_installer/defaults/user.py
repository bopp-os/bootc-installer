import re
import json
import logging
import os

from gi.repository import Adw, Gtk

from bootc_installer.utils.field_check import FieldCheck

logger = logging.getLogger("Installer::User")

_IN_FLATPAK = os.path.exists("/.flatpak-info")
_ETC = "/run/host/etc" if _IN_FLATPAK else "/etc"
_IMAGES_JSON = f"{_ETC}/bootc-installer/images.json"

# Groups added to every created user.
_DEFAULT_GROUPS = ["wheel", "docker", "incus-admin", "libvirt", "dialout"]


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-users.ui")
class BootcDefaultUsers(Adw.Bin):
    __gtype_name__ = "BootcDefaultUsers"

    btn_next           = Gtk.Template.Child()
    fullname_entry     = Gtk.Template.Child()
    username_entry     = Gtk.Template.Child()
    password_entry     = Gtk.Template.Child()
    password_confirmation = Gtk.Template.Child()
    password_strength_row = Gtk.Template.Child()
    password_strength_label = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__key = key
        self.__step = step
        self.delta = False

        # The username rule is fisherman's (`fisherman validate --json
        # --partial -`): it also refuses names the target already has, such
        # as root or wheel, which a pattern here never could. A username
        # fisherman refused used to fail in the configure step, after the OS
        # was on disk.
        self.username_message = Gtk.Label(xalign=0, wrap=True, margin_top=6)
        self.username_message.add_css_class("error")
        group = self.username_entry.get_ancestor(Adw.PreferencesGroup)
        if group is not None:
            group.add(self.username_message)
        self.username_check = FieldCheck(
            window, self.username_entry, "user.username",
            lambda text: {"user": {"username": text.strip()}},
            self.username_message, on_change=self.__update_btn_next)

        self.fullname_entry.connect("changed", self.__on_fullname_changed)
        self.username_entry.connect("changed", self.__on_field_changed)
        self.password_entry.connect("changed", self.__on_field_changed)
        self.password_confirmation.connect("changed", self.__on_field_changed)
        self.btn_next.connect("clicked", self.__window.next)

        # Pre-populate from QR Phone Companion if available
        companion_config = getattr(self.__window, "companion_config", None)
        if companion_config:
            logger.info("Pre-populating user credentials from Phone Companion.")
            if "fullname" in companion_config:
                self.fullname_entry.set_text(companion_config["fullname"])
            if "username" in companion_config:
                self.username_entry.set_text(companion_config["username"])
            if "password" in companion_config:
                self.password_entry.set_text(companion_config["password"])
                self.password_confirmation.set_text(companion_config["password"])

        self.__update_btn_next()

    def should_show(self, context: dict) -> bool:
        """Show this step only when the selected image requires user creation."""
        image_step = getattr(self.__window, "image_step", None)
        if image_step is None or context.get("leaf_count", 2) <= 1:
            # No usable image step: check sys_recipe["images"] first (handles removed
            # image-step cases), then fall back to images.json.
            sys_recipe = context.get("sys_recipe") or getattr(self.__window, "recipe", {})
            recipe_images = sys_recipe.get("images", [])
            if recipe_images:
                nuc = recipe_images[0].get("needs_user_creation", True)
                logger.info("should_show (recipe images): needs_user_creation=%s → show=%s", nuc, nuc)
                return nuc
            # Live ISO mode: read needs_user_creation from /etc/bootc-installer/images.json
            try:
                with open(_IMAGES_JSON) as f:
                    data = json.load(f)
                images = data.get("images", [data]) if "images" in data else [data]
                nuc = images[0].get("needs_user_creation", True)
                logger.info("should_show (live ISO): needs_user_creation=%s from images.json → show=%s", nuc, nuc)
                return nuc
            except Exception as e:
                logger.warning("should_show: image metadata unavailable (%s) — showing user step", e)
                return True
        nuc = image_step.selected_needs_user_creation
        logger.info("should_show: selected_needs_user_creation=%s → show=%s", nuc, nuc)
        return nuc

    def test_auto_advance(self):
        self.btn_next.emit("clicked")

    def get_finals(self):
        username = self.username_entry.get_text().strip()
        if not username:
            return {"user": {"username": "", "fullname": "", "password": "", "groups": []}}
        return {
            "user": {
                "username": username,
                "fullname": self.fullname_entry.get_text().strip(),
                "password": self.password_entry.get_text(),
                "groups": _DEFAULT_GROUPS,
            }
        }

    # ── Handlers ──────────────────────────────────────────────────────────────

    def __on_fullname_changed(self, entry):
        """Auto-suggest a username from the full name."""
        fullname = entry.get_text()
        current_username = self.username_entry.get_text()
        # Only auto-fill if the user hasn't typed a username yet.
        if current_username == "" or current_username == self.__suggested_username(
            self.__prev_fullname if hasattr(self, "_BootcDefaultUsers__prev_fullname") else ""
        ):
            suggested = self.__suggested_username(fullname)
            self.username_entry.set_text(suggested)
        self.__prev_fullname = fullname
        self.__on_field_changed(entry)

    def __suggested_username(self, fullname: str) -> str:
        """Derive a lowercase alphanumeric username from a full name."""
        name = fullname.lower().split()[0] if fullname.strip() else ""
        return re.sub(r"[^a-z0-9_-]", "", name)

    def __on_field_changed(self, *args):
        password = self.password_entry.get_text()
        confirm  = self.password_confirmation.get_text()

        # The password rules stay here: fisherman accepts any password,
        # including an empty one (VALIDATE.md, "Not fisherman rules").
        passwords_match = password == confirm and bool(password)
        if confirm and not passwords_match:
            self.password_confirmation.add_css_class("error")
        else:
            self.password_confirmation.remove_css_class("error")

        self.__update_password_strength(password)
        self.__update_btn_next()

    def __update_password_strength(self, password: str):
        """Show a simple password strength indicator."""
        if not password:
            self.password_strength_row.set_visible(False)
            return
        self.password_strength_row.set_visible(True)
        score = 0
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if re.search(r"[A-Z]", password):
            score += 1
        if re.search(r"[0-9]", password):
            score += 1
        if re.search(r"[^a-zA-Z0-9]", password):
            score += 1

        if score <= 1:
            label, color = "Weak", "error"
        elif score <= 2:
            label, color = "Fair", "warning"
        elif score <= 3:
            label, color = "Good", "success"
        else:
            label, color = "Strong", "success"

        self.password_strength_label.set_label(label)
        for cls in ("error", "warning", "success"):
            if cls == color:
                self.password_strength_label.add_css_class(cls)
            else:
                self.password_strength_label.remove_css_class(cls)

    def __update_btn_next(self):
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text()
        confirm  = self.password_confirmation.get_text()

        # A user page needs a user (the image has no other way to log in);
        # whether the name is acceptable is fisherman's answer.
        username_ok = bool(username) and self.username_check.ok
        passwords_match = password == confirm and bool(password)

        self.btn_next.set_sensitive(username_ok and passwords_match)
