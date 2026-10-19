"""Logo specs shared by the GNOME welcome, catalog and completion views.

Host /usr and /etc are mounted below /run/host in Flatpak. Never prefix
/app (the application's assets), already-mapped paths or icon names.
"""

import os


def resolve_icon(icon_spec, *, in_flatpak=None):
    """Return (resource|file|theme, value), or None for an empty spec."""
    if not isinstance(icon_spec, str) or not icon_spec:
        return None
    if icon_spec.startswith("resource://"):
        return "resource", icon_spec[len("resource://"):]
    if icon_spec.startswith("/"):
        if in_flatpak is None:
            in_flatpak = os.path.exists("/.flatpak-info")
        if in_flatpak and icon_spec.startswith(("/usr/", "/etc/")):
            icon_spec = "/run/host" + icon_spec
        return "file", icon_spec
    if "/" in icon_spec or ":" in icon_spec:
        return None  # not a theme name; never fetch a remote or relative URL
    return "theme", icon_spec


def set_image_icon(image, icon_spec):
    """Apply a spec to a Gtk.Image (also used by BootcPageHeader)."""
    resolved = resolve_icon(icon_spec)
    if resolved is None:
        return
    kind, value = resolved
    if kind == "resource":
        image.set_from_resource(value)
    elif kind == "file":
        image.set_from_file(value)
    else:
        image.set_from_icon_name(value)
