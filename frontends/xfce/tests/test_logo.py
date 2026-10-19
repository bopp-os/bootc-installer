"""Exercise real GTK3 decoding and visibility (run under Xvfb, like recovery tests)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tuna_installer_xfce import core, logo, pages

GdkPixbuf = logo.GdkPixbuf


def test_shared_logo_paths():
    fixture = Path(__file__).resolve().parents[3] / "shared/branding/fixtures/logo-paths.json"
    for case in json.loads(fixture.read_text())["cases"]:
        assert logo.logo_source(case["spec"], case["in_flatpak"]) == (case["kind"], case["value"])



@pytest.fixture
def artwork(tmp_path):
    path = tmp_path / "logo with spaces.png"
    pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 240, 120)
    pixels.fill(0x42AABBFF)
    pixels.savev(str(path), "png", [], [])
    return str(path)


def test_decodes_file_with_bounded_aspect_ratio(artwork):
    pixels = logo.load_logo(artwork, False)
    assert (pixels.get_width(), pixels.get_height()) == (96, 48)


def test_theme_icon():
    assert logo.load_logo("dialog-warning", False) is not None


@pytest.mark.parametrize("value", ["", "/missing/logo.svg", "missing-brand-icon-123456",
                                    "https://example.com/logo.png", "relative/logo.png",
                                    "resource:///missing/logo.svg"])
def test_invalid_logo_preserves_empty_layout(value):
    image = logo.product_logo(value, False)
    image.show_all()
    assert image.get_pixbuf() is None
    assert not image.get_visible()


def test_corrupt_file(tmp_path):
    path = tmp_path / "broken.png"
    path.write_text("not an image")
    assert logo.load_logo(str(path), False) is None


def test_welcome_and_done_use_logo_without_branding_failure(monkeypatch, artwork):
    monkeypatch.setattr(core, "BRANDING", replace(core.BRANDING, logo=artwork))
    monkeypatch.setattr(core, "requirements_warning", lambda: "")
    welcome = pages.WelcomePage(None)
    welcome.show_all()
    assert welcome.logo.get_visible()
    assert welcome.get_children()[0] is welcome.logo
    done = pages.DonePage(None)
    done.set_result(True, "")
    done.show_all()
    assert done.logo.get_visible()
    done.set_result(False, "test failure")
    done.show_all()
    assert not done.logo.get_visible()
    done.set_result(True, "")
    assert done.logo.get_visible()
