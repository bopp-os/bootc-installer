"""Phone companion step: hand the account form to a phone over the LAN.

The page shows a QR code that opens the companion form served by
``CompanionServer`` (bootc_installer/utils/phone_companion.py). The URL in the
code carries the session token, so it is never put on screen as text: the page
shows only ``host:port`` and a button that copies the full link.

No product names here. Every line is neutral, so nothing needs the branding
resolver (shared/branding/README.md); add a ``copy`` key there before adding a
line that names the product.
"""

import io
import logging
from gettext import gettext as _
from urllib.parse import urlencode

from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from bootc_installer.utils.phone_companion import (
    CONFIG_RECEIVED_EVENT,
    CompanionServer,
    get_local_ip,
)

try:
    import segno
except ImportError:
    segno = None

logger = logging.getLogger("BootcInstaller::QrCompanion")

COMPANION_PORT = 8443

# Largest edge of the code on screen, in logical pixels. The real edge is the
# biggest whole multiple of the module count that fits, so every module is the
# same number of pixels wide.
QR_TARGET_SIZE = 240
# ISO/IEC 18004 asks for a four-module quiet zone; scanners struggle without it.
QR_QUIET_ZONE = 4
# The PNG is drawn at this multiple of the on-screen size, so a 2x display gets
# one texel per pixel and a 1x display an exact 2:1 reduction: module edges
# land on pixel edges either way, and the code stays sharp.
QR_OVERSAMPLE = 2

_CSS = """
.qr-card {
  background-color: #ffffff;
  border-radius: 18px;
  padding: 12px;
  box-shadow: 0 0 0 1px alpha(black, 0.08), 0 2px 8px alpha(black, 0.12);
}
.qr-step-number {
  min-width: 28px;
  min-height: 28px;
  border-radius: 999px;
  background-color: alpha(@accent_bg_color, 0.15);
  color: @accent_color;
  font-weight: bold;
}
"""
_css_installed = False


def _install_css():
    global _css_installed
    if _css_installed:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):  # GTK 4.12+
        provider.load_from_string(_CSS)
    else:
        provider.load_from_data(_CSS.encode(), -1)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_installed = True


def qr_geometry(modules, target=QR_TARGET_SIZE):
    """(pixels per module, edge in logical px) for a code `modules` wide,
    quiet zone included. Never below one pixel per module."""
    scale = max(1, target // modules)
    return scale, modules * scale


def render_qr_png(url, target=QR_TARGET_SIZE):
    """The QR code for `url` as PNG bytes and its on-screen edge, or None.

    Black modules on white with a four-module quiet zone: the polarity every
    phone camera reads. Rendered in memory, never to a file, because the URL
    holds the session token.
    """
    if segno is None:
        return None
    qr = segno.make_qr(url, error="m")
    modules = qr.symbol_size(scale=1, border=QR_QUIET_ZONE)[0]
    scale, edge = qr_geometry(modules, target)
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale * QR_OVERSAMPLE, border=QR_QUIET_ZONE,
            dark="#000000", light="#ffffff")
    return buf.getvalue(), edge


def companion_url(ip, port, token):
    return f"https://{ip}:{port}/?{urlencode({'token': token})}"


class BootcDefaultQrCompanion(Adw.Bin):
    __gtype_name__ = "BootcDefaultQrCompanion"

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__key = key
        self.__step = step
        self.__step_num = step["num"]
        self.delta = False
        self.__server = None
        self.__timeout_id = None
        self.__url = None

        # Add companion_config placeholder on window
        if not hasattr(self.__window, "companion_config"):
            self.__window.companion_config = None

        _install_css()

        # Two states: the companion itself, and the page shown when this
        # system cannot serve the form over HTTPS.
        self.state_stack = Gtk.Stack()
        self.state_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.state_stack.add_named(self.__build_companion_page(), "companion")
        self.state_stack.add_named(self.__build_unavailable_page(), "unavailable")
        self.state_stack.set_visible_child_name("companion")

        # Side by side when there is room, stacked when there is not.
        self.breakpoint_bin = Adw.BreakpointBin()
        self.breakpoint_bin.set_size_request(320, 360)
        self.breakpoint_bin.set_child(self.state_stack)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        narrow.add_setter(self.content_box, "orientation", Gtk.Orientation.VERTICAL)
        narrow.add_setter(self.side_box, "halign", Gtk.Align.CENTER)
        self.breakpoint_bin.add_breakpoint(narrow)
        self.set_child(self.breakpoint_bin)

        # Listen for page change events to start/stop the server
        self.__window.carousel.connect("page-changed", self.__on_page_changed)

    # ── layout ────────────────────────────────────────────────────────────

    def __build_companion_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_valign(Gtk.Align.CENTER)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        page.set_margin_start(16)
        page.set_margin_end(16)

        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.title_label = Gtk.Label(label=_("Set Up From Your Phone"))
        self.title_label.add_css_class("title-1")
        self.title_label.set_wrap(True)
        self.title_label.set_justify(Gtk.Justification.CENTER)
        heading.append(self.title_label)
        self.description_label = Gtk.Label(label=_(
            "Type your account details on your phone instead of this keyboard. "
            "Both devices need to be on the same network."))
        self.description_label.add_css_class("dim-label")
        self.description_label.set_wrap(True)
        self.description_label.set_justify(Gtk.Justification.CENTER)
        self.description_label.set_max_width_chars(52)
        heading.append(self.description_label)
        page.append(heading)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=36)
        self.content_box.set_halign(Gtk.Align.CENTER)

        # The code, on a white card whatever the colour scheme.
        self.qr_stack = Gtk.Stack()
        self.qr_stack.set_halign(Gtk.Align.CENTER)
        self.qr_stack.set_valign(Gtk.Align.CENTER)
        self.qr_card = Gtk.Box()
        self.qr_card.add_css_class("qr-card")
        self.qr_card.set_halign(Gtk.Align.CENTER)
        self.qr_card.set_valign(Gtk.Align.CENTER)
        self.qr_picture = Gtk.Picture()
        self.qr_picture.set_can_shrink(True)
        self.qr_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.qr_picture.set_size_request(QR_TARGET_SIZE, QR_TARGET_SIZE)
        self.qr_picture.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("QR code for the phone setup page")])
        # The picture's natural size is the oversampled PNG; the clamp holds
        # it to the on-screen edge and the aspect ratio sets the height.
        self.qr_clamp = Adw.Clamp(maximum_size=QR_TARGET_SIZE,
                                  tightening_threshold=QR_TARGET_SIZE)
        self.qr_clamp.set_child(self.qr_picture)
        self.qr_card.append(self.qr_clamp)
        self.qr_stack.add_named(self.qr_card, "code")

        # No QR library: the link is the only way in.
        nocode = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        nocode.add_css_class("card")
        nocode.set_size_request(QR_TARGET_SIZE, QR_TARGET_SIZE)
        nocode.set_valign(Gtk.Align.CENTER)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_vexpand(True)
        inner.set_margin_start(18)
        inner.set_margin_end(18)
        icon = Gtk.Image.new_from_icon_name("phone-symbolic")
        icon.set_pixel_size(48)
        icon.add_css_class("dim-label")
        inner.append(icon)
        self.nocode_label = Gtk.Label(label=_(
            "No QR code on this system. Copy the link and open it on your phone."))
        self.nocode_label.set_wrap(True)
        self.nocode_label.set_justify(Gtk.Justification.CENTER)
        self.nocode_label.set_max_width_chars(24)
        self.nocode_label.add_css_class("dim-label")
        inner.append(self.nocode_label)
        nocode.append(inner)
        self.qr_stack.add_named(nocode, "nocode")
        self.content_box.append(self.qr_stack)

        self.side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.side_box.set_valign(Gtk.Align.CENTER)
        self.side_box.set_halign(Gtk.Align.START)

        steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.step_labels = []
        for number, text in enumerate((
            _("Open the camera on your phone"),
            _("Point it at the code and open the link"),
            _("Fill in the form and send it. This screen moves on by itself."),
        ), start=1):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            badge = Gtk.Label(label=str(number))
            badge.add_css_class("qr-step-number")
            badge.set_valign(Gtk.Align.START)
            row.append(badge)
            label = Gtk.Label(label=text)
            label.set_wrap(True)
            label.set_xalign(0)
            label.set_max_width_chars(30)
            label.set_valign(Gtk.Align.CENTER)
            row.append(label)
            self.step_labels.append(label)
            steps.append(row)
        self.side_box.append(steps)

        waiting = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        spinner_cls = getattr(Adw, "Spinner", None)  # libadwaita 1.6+
        if spinner_cls is not None:
            self.spinner = spinner_cls()
        else:
            self.spinner = Gtk.Spinner()
            self.spinner.start()
        self.spinner.set_size_request(16, 16)
        waiting.append(self.spinner)
        self.waiting_label = Gtk.Label(label=_("Waiting for your phone…"))
        self.waiting_label.add_css_class("dim-label")
        waiting.append(self.waiting_label)
        self.side_box.append(waiting)

        # Fallback: the address only. The token-bearing URL goes to the
        # clipboard, never to a label.
        fallback = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cant_scan = Gtk.Label(label=_("Can't scan?"))
        cant_scan.add_css_class("dim-label")
        cant_scan.add_css_class("caption")
        fallback.append(cant_scan)
        self.address_label = Gtk.Label()
        self.address_label.add_css_class("monospace")
        self.address_label.add_css_class("caption")
        self.address_label.set_ellipsize(Pango.EllipsizeMode.END)
        fallback.append(self.address_label)
        self.copy_button = Gtk.Button(label=_("Copy link"))
        self.copy_button.add_css_class("flat")
        self.copy_button.add_css_class("caption")
        self.copy_button.set_sensitive(False)
        self.copy_button.connect("clicked", self.__on_copy_clicked)
        fallback.append(self.copy_button)
        self.side_box.append(fallback)

        self.content_box.append(self.side_box)
        page.append(self.content_box)

        self.btn_next = Gtk.Button(label=_("Skip"))
        self.btn_next.add_css_class("pill")
        self.btn_next.set_halign(Gtk.Align.CENTER)
        self.btn_next.set_tooltip_text(_("Enter your details on this computer instead"))
        self.btn_next.connect("clicked", self.__on_skip_clicked)
        page.append(self.btn_next)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        clamp = Adw.Clamp(maximum_size=760)
        clamp.set_child(page)
        scrolled.set_child(clamp)
        return scrolled

    def __build_unavailable_page(self):
        self.unavailable_page = Adw.StatusPage()
        self.unavailable_page.set_icon_name("phone-symbolic")
        self.unavailable_page.set_title(_("Phone Setup Unavailable"))
        self.unavailable_page.set_description(_(
            "This computer can't open a secure connection for your phone. "
            "Continue to enter your details here instead."))
        btn = Gtk.Button(label=_("Continue on This Computer"))
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", self.__on_skip_clicked)
        self.unavailable_button = btn
        self.unavailable_page.set_child(btn)
        return self.unavailable_page

    # ── step contract ─────────────────────────────────────────────────────

    @property
    def step_id(self):
        return self.__key

    def should_show(self, context: dict) -> bool:
        # Show this setup page if it is configured in the recipe
        return True

    def get_finals(self):
        # Feed Hostname and SSH Key to the recipe processor if provided
        companion_config = getattr(self.__window, "companion_config", None)
        if companion_config:
            finals = {}
            if "hostname" in companion_config:
                finals["hostname"] = companion_config["hostname"]
            return finals
        return {}

    def __on_page_changed(self, carousel, idx):
        # Check if we transitioned into this step page
        if int(idx) == self.__step_num - 1:
            self.__start_companion()
        else:
            self.__stop_companion()

    def test_auto_advance(self):
        """Simulate programmatic advance for UI integration tests."""
        self.__stop_companion()
        self.__window.next()

    # ── companion server ──────────────────────────────────────────────────

    def __show_unavailable(self):
        self.__url = None
        self.copy_button.set_sensitive(False)
        self.state_stack.set_visible_child_name("unavailable")

    def __show_code(self, url, host):
        self.__url = url
        self.address_label.set_text(host)
        self.copy_button.set_sensitive(True)
        self.state_stack.set_visible_child_name("companion")

        rendered = None
        try:
            rendered = render_qr_png(url)
        except ValueError as e:  # segno.DataOverflowError: too long to encode
            logger.error("Failed to render the QR code: %s", e)
        if rendered is None:
            if segno is None:
                logger.warning("segno is not available; offering the link only.")
            self.qr_stack.set_visible_child_name("nocode")
            return
        png, edge = rendered
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
        self.qr_picture.set_paintable(texture)
        self.qr_picture.set_size_request(edge, edge)
        self.qr_clamp.set_maximum_size(edge)
        self.qr_clamp.set_tightening_threshold(edge)
        self.qr_stack.set_visible_child_name("code")

    def __start_companion(self):
        if self.__server is not None:
            return

        logger.info("Initializing Phone Companion server...")
        self.__server = CompanionServer(port=COMPANION_PORT)
        if not self.__server.start():
            # No HTTPS, so no phone: the form carries the password (#185).
            self.__server = None
            self.__show_unavailable()
            return

        ip = get_local_ip()
        self.__show_code(companion_url(ip, COMPANION_PORT, self.__server.auth_token),
                         f"{ip}:{COMPANION_PORT}")

        # Start GLib polling loop to check for received config
        self.__timeout_id = GLib.timeout_add(500, self.__check_config_event)

    def __stop_companion(self):
        if self.__timeout_id:
            GLib.source_remove(self.__timeout_id)
            self.__timeout_id = None

        if self.__server:
            self.__server.stop()
            self.__server = None
            logger.info("Shut down Phone Companion server.")

    def __check_config_event(self):
        if CONFIG_RECEIVED_EVENT.is_set():
            logger.info("Received configuration from Phone Companion!")
            from bootc_installer.utils.phone_companion import GLOBAL_CONFIG

            # Save config to window state
            self.__window.companion_config = GLOBAL_CONFIG

            # Auto-advance to the next page
            GLib.idle_add(self.__window.next)

            self.__stop_companion()
            return False # Stop the polling loop

        return True # Continue polling

    def __on_copy_clicked(self, _btn):
        if not self.__url:
            return
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(self.__url)
        self.copy_button.set_label(_("Copied"))
        GLib.timeout_add_seconds(2, self.__reset_copy_label)

    def __reset_copy_label(self):
        self.copy_button.set_label(_("Copy link"))
        return False

    def __on_skip_clicked(self, btn):
        logger.info("Companion setup skipped by the user.")
        self.__stop_companion()
        self.__window.next()
