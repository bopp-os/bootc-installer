"""The phone companion page against real GTK.

The QR code is a Gdk.Texture made from in-memory PNG bytes, black on white
with a quiet zone; without segno the page falls back to the link; the
token-bearing URL never lands in a widget the user can read.
"""

from unittest.mock import MagicMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from bootc_installer.defaults import qr_companion as mod

TOKEN = "ui-test-token-must-stay-hidden"


def _page(start_ok=True, segno=mod.segno):
    page = mod.BootcDefaultQrCompanion(MagicMock(), {}, "qr_companion", {"num": 2})
    server = MagicMock()
    server.start.return_value = start_ok
    server.auth_token = TOKEN if start_ok else None
    with patch.object(mod, "CompanionServer", return_value=server), \
         patch.object(mod, "get_local_ip", return_value="192.0.2.10"), \
         patch.object(mod, "segno", segno), \
         patch.object(mod.GLib, "timeout_add", return_value=0):
        page._BootcDefaultQrCompanion__start_companion()
    return page


def _strings(widget, acc=None):
    """Every string any widget under `widget` carries, visible or not."""
    acc = [] if acc is None else acc
    if isinstance(widget, Gtk.Label):
        acc.append(widget.get_label() or "")
    if isinstance(widget, Gtk.Button):
        acc.append(widget.get_label() or "")
    if isinstance(widget, Adw.StatusPage):
        acc += [widget.get_title() or "", widget.get_description() or ""]
    acc.append(widget.get_tooltip_text() or "")
    child = widget.get_first_child()
    while child is not None:
        _strings(child, acc)
        child = child.get_next_sibling()
    return acc


def _pixel(texture, x, y):
    """(R, G, B) of one texel."""
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8)
    data, stride = downloader.download_bytes()
    buf = data.get_data()
    i = y * stride + x * 3
    return tuple(buf[i:i + 3])


@pytest.mark.skipif(mod.segno is None, reason="segno not installed")
def test_qr_is_a_crisp_black_on_white_texture():
    page = _page()
    assert page.state_stack.get_visible_child_name() == "companion"
    assert page.qr_stack.get_visible_child_name() == "code"
    texture = page.qr_picture.get_paintable()
    assert isinstance(texture, Gdk.Texture)

    url = f"https://192.0.2.10:8443/?token={TOKEN}"
    modules = mod.segno.make_qr(url, error="m").symbol_size(
        scale=1, border=mod.QR_QUIET_ZONE)[0]
    assert texture.get_width() == texture.get_height()
    assert texture.get_width() % modules == 0, "whole pixels per module"
    px = texture.get_width() // modules
    edge = texture.get_width() // mod.QR_OVERSAMPLE
    assert edge <= mod.QR_TARGET_SIZE
    assert page.qr_picture.get_size_request() == (edge, edge)

    q = mod.QR_QUIET_ZONE * px
    assert _pixel(texture, 0, 0) == (255, 255, 255), "quiet zone is white"
    assert _pixel(texture, q - 1, q - 1) == (255, 255, 255)
    assert _pixel(texture, q, q) == (0, 0, 0), "finder corner is black"
    assert _pixel(texture, q + 3 * px, q + 3 * px) == (0, 0, 0)


def test_without_segno_the_page_offers_the_link():
    page = _page(segno=None)
    assert page.state_stack.get_visible_child_name() == "companion"
    assert page.qr_stack.get_visible_child_name() == "nocode"
    assert page.qr_picture.get_paintable() is None
    assert page.address_label.get_text() == "192.0.2.10:8443"
    assert page.copy_button.get_sensitive()


@pytest.mark.parametrize("segno", [mod.segno, None])
def test_the_token_is_never_in_a_label(segno):
    page = _page(segno=segno)
    strings = _strings(page)
    assert "192.0.2.10:8443" in strings
    for s in strings:
        assert TOKEN not in s, f"token on screen: {s!r}"
        assert "token=" not in s, f"full URL on screen: {s!r}"


def test_copy_link_copies_the_full_url():
    page = _page(segno=None)
    with patch.object(mod.GLib, "timeout_add_seconds", return_value=0):
        page.copy_button.emit("clicked")
    clipboard = Gdk.Display.get_default().get_clipboard()
    got = {}
    loop = GLib.MainLoop()

    def done(cb, res):
        got["text"] = cb.read_text_finish(res)
        loop.quit()

    clipboard.read_text_async(None, done)
    GLib.timeout_add(2000, loop.quit)
    loop.run()
    assert got.get("text") == f"https://192.0.2.10:8443/?token={TOKEN}"


def test_skip_is_a_plain_button():
    page = _page()
    assert not page.btn_next.has_css_class("suggested-action")
    page.btn_next.emit("clicked")


def test_unavailable_is_a_status_page():
    page = _page(start_ok=False)
    assert page.state_stack.get_visible_child_name() == "unavailable"
    assert isinstance(page.state_stack.get_visible_child(), Adw.StatusPage)
    assert "Unavailable" in page.unavailable_page.get_title()
    assert not page.copy_button.get_sensitive()
