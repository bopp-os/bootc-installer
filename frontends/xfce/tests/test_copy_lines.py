"""Copy keys XFCE used to hardcode or drop (tests/unit/test_copy_coverage.py).

welcome_button, welcome_install_subtitle and progress_note were listed as
XFCE gaps: the Next button said "Next" on the welcome page, the live-system
row said "no download required", and the progress page had no warning at
all. Each is driven here through the real widget, not a string search.
"""

import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402


class _Win:
    class _Trawl:
        def set_fill(self, _f):
            pass

    def __init__(self):
        self.trawl = self._Trawl()

    def start_install(self, _page):
        pass


class _Page:
    def can_continue(self):
        return True


def _nav_label(step):
    win = types.SimpleNamespace(
        pages={name: _Page() for name in app.PAGE_ORDER},
        index=app.PAGE_ORDER.index(step),
        back_btn=Gtk.Button(), next_btn=Gtk.Button(),
    )
    app.InstallerWindow.refresh_nav(win)
    return win.next_btn.get_label()


def test_welcome_forward_button_is_branded():
    assert _nav_label("welcome") == core.BRANDING.text("welcome_button")


def test_install_button_is_still_branded():
    assert _nav_label("confirm") == core.BRANDING.text("confirm_button")


def test_structural_steps_keep_next():
    assert _nav_label("source") == "Next"


def test_progress_note_is_shown():
    page = pages.ProgressPage(_Win())
    assert page.note.get_text() == core.BRANDING.text("progress_note")
    assert page.note.get_text(), "the neutral default must not be empty"
    assert not page.note.get_no_show_all()


def test_live_row_carries_the_install_subtitle(monkeypatch):
    monkeypatch.setattr(core, "is_live", lambda: True)
    monkeypatch.setattr(core, "live_image", lambda: "ghcr.io/example/live:1")
    monkeypatch.setattr(core, "offline_images", lambda: set())
    monkeypatch.setattr(core, "load_catalog", lambda: (None, None, []))
    page = pages.SourcePage(_Win())
    texts = []

    def walk(widget):
        if isinstance(widget, Gtk.Label):
            texts.append(widget.get_text())
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                walk(child)

    walk(page.listbox)
    assert any(core.BRANDING.text("welcome_install_subtitle") in t for t in texts), texts
    assert not any("no download required" in t for t in texts)


def _feed(page, **event):
    import json
    page.append_log(json.dumps(event))


def test_overall_pct_drives_the_bar():
    page = pages.ProgressPage(_Win())
    _feed(page, type="step", step=6, total_steps=8, step_name="Copying system Flatpaks",
          step_id="flatpaks", cumulative_pct=88, weight_pct=11, overall_pct=88)
    # The derivation would hold the bar through the Flatpak copy.
    _feed(page, type="substep", message="Copying Flatpak data: 50%", overall_pct=93.5)
    assert abs(page.bar.get_fraction() - 0.935) < 1e-6


def test_without_overall_pct_the_bar_is_derived():
    page = pages.ProgressPage(_Win())
    _feed(page, type="step", step=5, total_steps=8, step_name="Installing OS",
          cumulative_pct=1, weight_pct=87)
    _feed(page, type="substep", message="Pulling image: layer 2/4")
    assert abs(page.bar.get_fraction() - (1 + 0.5 * 0.6 * 87) / 100) < 1e-6


def test_step_id_is_labelled_from_the_copy(monkeypatch):
    monkeypatch.setitem(core.BRANDING.copy, "step_flatpaks", "Adding apps")
    page = pages.ProgressPage(_Win())
    _feed(page, type="step", step=6, total_steps=8, step_name="Copying system Flatpaks",
          step_id="flatpaks", cumulative_pct=88, weight_pct=11, overall_pct=88)
    assert page.steplabel.get_text() == "Adding apps"


def test_an_unknown_step_id_shows_the_step_name():
    page = pages.ProgressPage(_Win())
    _feed(page, type="step", step=3, total_steps=8, step_name="Polishing the hull",
          step_id="polish_hull", cumulative_pct=1, weight_pct=0, overall_pct=1)
    assert page.steplabel.get_text() == "Polishing the hull"
