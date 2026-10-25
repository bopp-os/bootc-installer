"""The phone companion step, headless.

GTK is stubbed with recording widgets: every set_* call and constructor
keyword lands in the widget's props, so a test can read back everything the
page would put on screen. tests/ui/test_qr_companion_page.py covers the same
page against real GTK.
"""

import struct
import sys
import types
import zlib
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

TOKEN = "s3cr3t-token-do-not-show"

# Props that put text on screen.
TEXT_PROPS = ("label", "text", "markup", "title", "description", "tooltip_text")


class _W:
    """A widget stub that records what the page did to it."""

    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        self.props_ = dict(kwargs)
        self.children = []
        self.named = {}
        self.css = set()
        self.signals = {}
        _W.instances.append(self)

    @classmethod
    def new_from_icon_name(cls, name):
        return cls(icon_name=name)

    def append(self, child):
        self.children.append(child)

    def set_child(self, child):
        self.children = [child]

    def add_named(self, child, name):
        self.named[name] = child
        self.children.append(child)

    def add_css_class(self, name):
        self.css.add(name)

    def connect(self, signal, callback, *args):
        self.signals[signal] = callback

    def __getattr__(self, name):
        if name.startswith("set_"):
            key = name[4:]
            return lambda value, *a: self.props_.__setitem__(key, value)
        if name.startswith("get_"):
            key = name[4:]
            return lambda *a: self.props_.get(key)
        return lambda *a, **kw: None


def _gi_modules():
    gtk = types.ModuleType("gi.repository.Gtk")
    for widget in ("Box", "Label", "Button", "Image", "Picture", "Stack",
                   "ScrolledWindow", "Spinner"):
        setattr(gtk, widget, type(widget, (_W,), {}))
    for enum in ("Align", "Orientation", "Justification", "ContentFit",
                 "PolicyType", "StackTransitionType", "AccessibleProperty"):
        setattr(gtk, enum, MagicMock())
    gtk.CssProvider = MagicMock()
    gtk.StyleContext = MagicMock()
    gtk.STYLE_PROVIDER_PRIORITY_APPLICATION = 600

    adw = types.ModuleType("gi.repository.Adw")
    for widget in ("Bin", "StatusPage", "Clamp", "BreakpointBin", "Spinner"):
        setattr(adw, widget, type(widget, (_W,), {}))
    adw.Breakpoint = MagicMock()
    adw.BreakpointCondition = MagicMock()

    gdk, glib, pango = MagicMock(), MagicMock(), MagicMock()
    repo = types.ModuleType("gi.repository")
    repo.Gtk, repo.Adw, repo.Gdk, repo.GLib, repo.Pango = gtk, adw, gdk, glib, pango
    repo.Gio = MagicMock()
    gi = types.ModuleType("gi")
    gi.repository = repo
    gi.require_version = lambda *a, **kw: None
    return {
        "gi": gi, "gi.repository": repo, "gi.repository.Gtk": gtk,
        "gi.repository.Adw": adw, "gi.repository.Gdk": gdk,
        "gi.repository.GLib": glib, "gi.repository.Pango": pango,
        "gi.repository.Gio": repo.Gio,
    }


@pytest.fixture
def mod():
    _W.instances = []
    with patch.dict(sys.modules, _gi_modules()):
        sys.modules.pop("bootc_installer.defaults.qr_companion", None)
        import bootc_installer.defaults.qr_companion as qr
        yield qr
    sys.modules.pop("bootc_installer.defaults.qr_companion", None)


def _page(mod, start_ok=True):
    window = MagicMock()
    page = mod.BootcDefaultQrCompanion(window, {}, "qr_companion", {"num": 2})
    server = MagicMock()
    server.start.return_value = start_ok
    server.auth_token = TOKEN if start_ok else None
    with patch.object(mod, "CompanionServer", return_value=server), \
         patch.object(mod, "get_local_ip", return_value="192.0.2.10"):
        page._BootcDefaultQrCompanion__start_companion()
    return page, window


def _visible_strings():
    return [str(w.props_[k]) for w in _W.instances for k in TEXT_PROPS
            if w.props_.get(k)]


def _png_size(png):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


# ── step contract (unchanged) ────────────────────────────────────────────────

def test_qr_companion_step_lifecycle(mod):
    """Verify the GUI companion step parses contexts, skips, and resolves finals cleanly."""
    window_mock = MagicMock()
    step_widget = mod.BootcDefaultQrCompanion(window_mock, {}, "qr_companion", {"num": 2})

    assert step_widget.step_id == "qr_companion"
    assert step_widget.should_show({}) is True

    window_mock.companion_config = None
    assert step_widget.get_finals() == {}

    window_mock.companion_config = {
        "fullname": "John Doe",
        "username": "johndoe",
        "password": "mypassword",
        "hostname": "test-host",
        "sshkey": "ssh-rsa ABC"
    }
    assert step_widget.get_finals() == {"hostname": "test-host"}


# ── rendering ────────────────────────────────────────────────────────────────

def test_geometry_is_whole_pixels_per_module(mod):
    qr_geometry = mod.qr_geometry
    for modules in (29, 33, 41, 45, 57):
        scale, edge = qr_geometry(modules, 240)
        assert edge == modules * scale and edge <= 240
        assert (modules * (scale + 1)) > 240, "a larger whole scale would have fit"
    assert qr_geometry(400, 240) == (1, 400), "never below one pixel per module"


def test_qr_renders_black_on_white_png_in_memory(mod):
    segno = pytest.importorskip("segno")
    url = "https://192.0.2.10:8443/?token=" + TOKEN
    with patch.object(mod, "segno", segno):
        png, edge = mod.render_qr_png(url)
    w, h = _png_size(png)
    assert w == h == edge * mod.QR_OVERSAMPLE
    assert edge <= mod.QR_TARGET_SIZE

    # The modules: what segno encodes for the URL, at a whole scale, with a
    # four-module light border.
    qr = segno.make_qr(url, error="m")
    modules = qr.symbol_size(scale=1, border=mod.QR_QUIET_ZONE)[0]
    assert w % modules == 0
    px = w // modules

    # Decode the PNG's pixels without a dependency: segno writes 1-bit
    # greyscale or a 2-colour palette, one filter byte per scanline.
    chunks, i = {}, 8
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        kind = png[i + 4:i + 8]
        chunks.setdefault(kind, b"")
        chunks[kind] += png[i + 8:i + 8 + n]
        i += 12 + n
    depth, colour_type = chunks[b"IHDR"][8], chunks[b"IHDR"][9]
    assert depth == 1
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = (w + 7) // 8 + 1

    def lum(x, y):
        line = raw[y * stride:(y + 1) * stride]
        assert line[0] == 0, "unfiltered scanlines expected"
        bit = (line[1 + x // 8] >> (7 - x % 8)) & 1
        if colour_type == 3:
            r, g, b = chunks[b"PLTE"][bit * 3:bit * 3 + 3]
            return (r + g + b) // 3
        return 255 * bit

    assert lum(0, 0) == 255, "quiet zone must be white"
    q = mod.QR_QUIET_ZONE * px
    assert lum(q - 1, q - 1) == 255, "quiet zone is four modules wide"
    assert lum(q, q) == 0, "finder pattern corner must be black"
    assert lum(q + px * 3, q + px * 3) == 0, "finder pattern centre must be black"
    assert lum(q + px, q + px) == 255, "finder pattern ring gap must be white"


def test_render_returns_none_without_segno(mod):
    with patch.object(mod, "segno", None):
        assert mod.render_qr_png("https://example.invalid") is None


def test_page_shows_the_code_when_segno_is_present(mod):
    segno = pytest.importorskip("segno")
    with patch.object(mod, "segno", segno):
        page, _ = _page(mod)
    assert page.state_stack.props_["visible_child_name"] == "companion"
    assert page.qr_stack.props_["visible_child_name"] == "code"
    png = mod.Gdk.Texture.new_from_bytes.call_args[0][0]
    assert page.qr_picture.props_["paintable"] is mod.Gdk.Texture.new_from_bytes.return_value
    assert png is mod.GLib.Bytes.new.return_value
    _png_size(mod.GLib.Bytes.new.call_args[0][0])


def test_page_falls_back_to_the_link_without_segno(mod):
    with patch.object(mod, "segno", None):
        page, _ = _page(mod)
    assert page.state_stack.props_["visible_child_name"] == "companion"
    assert page.qr_stack.props_["visible_child_name"] == "nocode"
    assert page.address_label.props_["text"] == "192.0.2.10:8443"
    assert page.copy_button.props_["sensitive"] is True
    mod.Gdk.Texture.new_from_bytes.assert_not_called()


# ── the token stays off the screen ───────────────────────────────────────────

@pytest.mark.parametrize("has_segno", [True, False])
def test_token_never_reaches_a_visible_string(mod, has_segno):
    segno = pytest.importorskip("segno") if has_segno else None
    with patch.object(mod, "segno", segno):
        _page(mod)
    strings = _visible_strings()
    assert any("192.0.2.10:8443" == s for s in strings), "host:port is shown"
    for s in strings:
        assert TOKEN not in s, f"token on screen: {s!r}"
        assert "token=" not in s and "https://" not in s, f"full URL on screen: {s!r}"


def test_copy_link_puts_the_full_url_on_the_clipboard(mod):
    with patch.object(mod, "segno", None):
        page, _ = _page(mod)
    clipboard = mod.Gdk.Display.get_default.return_value.get_clipboard.return_value
    page.copy_button.signals["clicked"](page.copy_button)
    copied = clipboard.set.call_args[0][0]
    assert copied == f"https://192.0.2.10:8443/?token={TOKEN}"
    assert TOKEN not in page.copy_button.props_["label"]


def test_skip_is_not_the_suggested_action(mod):
    page, window = _page(mod)
    assert "suggested-action" not in page.btn_next.css
    page.btn_next.signals["clicked"](page.btn_next)
    window.next.assert_called_once()


def test_page_says_unavailable_when_the_server_cannot_use_https(mod):
    """#185: no certificate, no server, and the page says so instead of
    showing a link to nothing."""
    page, window = _page(mod, start_ok=False)
    assert page.state_stack.props_["visible_child_name"] == "unavailable"
    assert "Unavailable" in page.unavailable_page.props_["title"]
    assert page._BootcDefaultQrCompanion__server is None
    assert page.copy_button.props_["sensitive"] is False
    assert not page.address_label.props_.get("text")
    page.unavailable_button.signals["clicked"](page.unavailable_button)
    window.next.assert_called_once()


# ── shipping ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("manifest", [
    "org.bootcinstaller.Installer.json",
    "org.bootcinstaller.Installer.Devel.json",
])
def test_the_flatpak_ships_segno(manifest):
    """segno was imported optionally and shipped nowhere, so every user saw
    the fallback instead of a QR code. The Flatpak must carry it, pinned,
    and install it before the app."""
    import json
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / "flatpak" / manifest
    modules = json.loads(path.read_text())["modules"]
    names = [m["name"] for m in modules]
    assert "python3-segno" in names
    assert names.index("python3-segno") < names.index("bootc-installer")
    segno_mod = modules[names.index("python3-segno")]
    assert any("pip3 install" in c and "--no-index" in c
               for c in segno_mod["build-commands"])
    for src in segno_mod["sources"]:
        assert "/segno-" in src["url"] and len(src["sha256"]) == 64
