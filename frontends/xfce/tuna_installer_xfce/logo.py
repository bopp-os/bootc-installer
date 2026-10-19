"""Optional product artwork for GTK3; keep the unbranded layout on failure."""

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402


def logo_path(value, in_flatpak):
    """Translate host /usr and /etc paths only inside a Flatpak."""
    if in_flatpak and value.startswith(("/usr/", "/etc/")):
        return "/run/host" + value
    return value


def logo_source(value, in_flatpak):
    """Classify portable file/theme sources, plus GTK resource compatibility."""
    if value.startswith("resource:///"):
        return "resource", value[len("resource://"):]
    if os.path.isabs(value):
        return "file", logo_path(value, in_flatpak)
    if value and "/" not in value and ":" not in value:
        return "theme", value
    return "none", ""


def load_logo(value, in_flatpak, size=96):
    """Decode a bounded logo; missing files/icons and invalid artwork are optional.

    Resources belong to the application, themed icons to its active theme, and
    absolute /usr or /etc files to the host when sandboxed. Never fetch URLs.
    """
    kind, value = logo_source(value, in_flatpak)
    try:
        if kind == "resource":
            return GdkPixbuf.Pixbuf.new_from_resource_at_scale(
                value, size, size, True)
        if kind == "file":
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(value, size, size, True)
        if kind == "theme":
            theme = Gtk.IconTheme.get_default()
            if theme is not None:
                return theme.load_icon(value, size, Gtk.IconLookupFlags.FORCE_SIZE)
    except GLib.Error:
        pass
    return None


def product_logo(value, in_flatpak):
    """A hidden empty image does not reserve space or show a broken-image icon."""
    image = Gtk.Image()
    image.set_no_show_all(True)
    image.set_halign(Gtk.Align.START)
    pixbuf = load_logo(value, in_flatpak)
    if pixbuf is not None:
        image.set_from_pixbuf(pixbuf)
        image.show()
    return image
