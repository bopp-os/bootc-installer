"""GTK integration tests for confirm.py and progress.py."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from bootc_installer.widgets.page_header import BootcPageHeader  # noqa: F401, E402
from bootc_installer.views.confirm import BootcConfirm  # noqa: E402
from bootc_installer.views.progress import BootcProgress  # noqa: E402


def _pump():
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def _branded_window():
    """A window whose recipe carries a resolved branding block (the shape the
    RecipeLoader produces), so the confirm view has copy to render."""
    return SimpleNamespace(recipe={"branding": {
        "name": "Marlin",
        "copy": {
            "confirm_button": "Onward",
            "confirm_subtitle": '"Hold fast." — Someone',
        },
        "confirm_quotes": {"pt_BR": ['"Segue em frente." — Alguém']},
    }})


class _DummyWindow:
    def __init__(self):
        self.results = []
        # progress.py __setup_fallback_panel reads window.recipe
        self.recipe = {}

    def set_installation_result(self, *args):
        self.results.append(args)


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_kwargs):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


class TestConfirmScreen:
    def test_update_renders_summary_rows_and_pt_br_quote(self):
        confirm = BootcConfirm(_branded_window())
        finals = [
            {"language": "pt_BR.UTF-8"},
            {"keyboard": [{"layout": "us", "variant": ""}, {"layout": "br", "variant": "abnt2"}]},
            {"timezone": {"region": "America", "zone": "Sao_Paulo"}},
            {"users": {"username": "jorge", "fullname": "Jorge Castro"}},
            {"disk": {"auto": {"disk": "/dev/nvme0n1", "pretty_size": "1 TB",
                               "model": "WD_BLACK SN850X"},
                      "filesystem": "btrfs"}},
            {"encryption": {"type": "tpm2-luks-passphrase"}},
            {"hostname": "legendary-box"},
            {"selected_image": "ghcr.io/example/marlin:latest", "pretty_name": "Marlin GTS"},
        ]

        with (
            patch("bootc_installer.core.system.Systeminfo.gpu_display_string", return_value="AMD Radeon"),
            patch("bootc_installer.core.system.Systeminfo.gpu_icon_name", return_value="video-display-symbolic"),
            patch("random.choice", return_value='"Segue em frente." — Alguém'),
        ):
            confirm.update(finals)

        def _row_key(widget):
            # Adw.EntryRow (hostname) has no get_subtitle; use get_text instead.
            subtitle = getattr(widget, 'get_text', None) or getattr(widget, 'get_subtitle', None)
            return (widget.get_title(), subtitle() if callable(subtitle) else "")
        rows = {_row_key(widget) for widget in confirm.active_widgets}
        assert confirm.page_header.subtitle == '"Segue em frente." — Alguém'
        assert confirm.btn_confirm.get_label() == "Onward"
        assert ("Language", "pt_BR.UTF-8") in rows
        assert ("Keyboard 1", "us") in rows
        assert ("Keyboard 2", "br+abnt2") in rows
        assert ("Timezone", "America Sao_Paulo") in rows
        assert ("Users", "jorge (Jorge Castro)") in rows
        # The model names the physical disk, the path says which device.
        assert ("Target disk", "WD_BLACK SN850X (/dev/nvme0n1, 1 TB)") in rows
        assert ("Filesystem", "Btrfs") in rows
        # The shared copy key, the same words the other four frontends use.
        assert ("Encryption", "TPM + passphrase") in rows
        assert ("Hostname", "legendary-box") in rows  # EntryRow, text via get_text
        assert ("Image", "Marlin GTS") in rows
        assert ("Graphics", "AMD Radeon") in rows
        # The facts every frontend's summary leads with come first, in the
        # order KDE, COSMIC and Niri list them; GNOME's extra steps follow.
        # (The untitled row after Hostname is its validation message.)
        titles = [widget.get_title() for widget in confirm.active_widgets]
        assert titles[:6] == ["Target disk", "Filesystem", "Encryption",
                              "Hostname", "", "Image"]
        # The erase warning is the branding contract's confirm_warning with
        # the chosen disk filled in, not a hardcoded GNOME string, in a row
        # of its own above the summary.
        assert confirm.group_warning.get_visible()
        assert confirm.row_warning.get_title() == \
            "Everything on /dev/nvme0n1 will be erased. This cannot be undone."

    def test_no_disk_no_warning_and_recipe_image(self):
        """No whole-disk erase, no warning; no image step, the recipe's image."""
        window = _branded_window()
        window.recipe["imgref"] = "registry.example/os:stable"
        confirm = BootcConfirm(window)
        with patch("bootc_installer.core.system.Systeminfo.gpu_display_string", return_value=""):
            confirm.update([{"hostname": "box"}])
        assert not confirm.group_warning.get_visible()
        rows = {(w.get_title(), w.get_subtitle()) for w in confirm.active_widgets
                if hasattr(w, "get_subtitle")}
        assert ("Image", "registry.example/os:stable") in rows

    def test_confirm_button_emits_signal_once_and_uses_confirm_subtitle(self):
        confirm = BootcConfirm(_branded_window())
        seen = []

        with patch("bootc_installer.core.system.Systeminfo.gpu_display_string", return_value=""):
            confirm.update([{"language": "en_US"}])

        confirm.connect("installation-confirmed", lambda *_args: seen.append("confirmed"))
        confirm.test_auto_advance()
        _pump()
        confirm.test_auto_advance()
        _pump()

        # No pt_BR quote for en_US: the copy's confirm_subtitle line.
        assert confirm.page_header.subtitle == '"Hold fast." — Someone'
        assert seen == ["confirmed"]


class TestProgressScreen:
    def _make_progress(self):
        window = _DummyWindow()
        with (
            patch("bootc_installer.views.progress.threading.Thread", _ImmediateThread),
            patch("bootc_installer.views.progress.GLib.timeout_add_seconds", return_value=1),
        ):
            progress = BootcProgress(window)
            _pump()
        return progress, window

    def test_progress_note_comes_from_the_contract(self):
        """GNOME used to show no do-not-power-off line at all."""
        progress, _window = self._make_progress()
        assert progress.progress_note.get_label() == "Do not power off the computer."
        assert progress.progress_note.get_visible()

    def test_media_and_console_toggles_preserve_selected_media_mode(self):
        progress, _window = self._make_progress()

        # Nothing plays before the install starts, so no pane is open and
        # the status is centred in the page instead of pushed to the bottom.
        assert not progress.console_box.get_visible()
        assert not progress.media_box.get_visible()
        assert progress.status_clamp.get_vexpand()

        progress.console_button.emit("clicked")
        _pump()
        assert progress.console_box.get_visible()
        assert progress.media_button.get_visible()
        assert not progress.console_button.get_visible()
        assert not progress.media_box.get_visible()
        # The log takes the height; the status sits under it.
        assert not progress.status_clamp.get_vexpand()

        progress.media_button.emit("clicked")
        _pump()
        assert not progress.console_box.get_visible()
        assert not progress.media_button.get_visible()
        assert progress.console_button.get_visible()
        assert progress.media_box.get_visible()
        assert not progress.status_clamp.get_vexpand()

    def test_progress_events_update_labels_percentage_eta_and_completion(self):
        progress, _window = self._make_progress()
        progress._BootcProgress__start_time = 100.0

        with patch("bootc_installer.views.progress.time.monotonic", return_value=220.0):
            progress._BootcProgress__update_elapsed_label()
            progress._BootcProgress__parse_progress_line(
                json.dumps(
                    {
                        "type": "step",
                        "step": 6,
                        "total_steps": 9,
                        "step_name": "Installing system image",
                        "cumulative_pct": 55,
                        "weight_pct": 22,
                    }
                )
            )
            progress._BootcProgress__parse_progress_line(
                json.dumps({"type": "substep", "message": "Pulling image: layer 5/10"})
            )

        assert progress.progressbar_text.get_label() == "Installing system image"
        # 55 + (5/10 of the pull) * 0.6 (the pull's share of the step) * 22.
        # The rest of the step is for the export and deploy phases after the
        # pull (#115; shared/progress/fraction-cases.json).
        assert progress.progress_percentage.get_label() == "61%"
        assert progress.progress_elapsed.get_label() == "2:00 elapsed"
        assert progress.progress_eta.get_label().startswith("~")
        assert "remaining" in progress.progress_eta.get_label()
        # substep widget shows friendly-mapped raw message
        assert progress.progress_substep.get_label() == "Downloading\u2026 (5 of 10 parts)"

        progress._BootcProgress__parse_progress_line(
            json.dumps({"type": "complete", "boot_id": "boot-123", "recovery_key": "rk-1"})
        )

        assert progress.progressbar_text.get_label() == "Installation complete!"
        assert progress.progress_percentage.get_label() == "100%"
        assert progress.progress_substep.get_label() == ""
        assert progress._BootcProgress__boot_id == "boot-123"
        assert progress._BootcProgress__recovery_key == "rk-1"

    def test_overall_pct_drives_the_bar_and_step_id_the_label(self):
        """fisherman's overall_pct is the bar and its step_id picks the copy
        line; the derivation would hold the bar through the Flatpak copy."""
        progress, window = self._make_progress()
        window.recipe = {"branding": {"name": "ExampleOS",
                                      "copy": {"step_flatpaks": "Adding apps for {name}…"}}}
        progress._BootcProgress__parse_progress_line(json.dumps({
            "type": "step", "step": 6, "total_steps": 8,
            "step_name": "Copying system Flatpaks", "step_id": "flatpaks",
            "cumulative_pct": 88, "weight_pct": 11, "overall_pct": 88,
        }))
        assert progress.progressbar_text.get_label() == "Adding apps for ExampleOS…"
        assert progress.progress_percentage.get_label() == "88%"
        progress._BootcProgress__parse_progress_line(json.dumps(
            {"type": "substep", "message": "Copying Flatpak data: 50%", "overall_pct": 93.5}))
        assert progress.progress_percentage.get_label() == "93%"
        assert progress.progressbar_text.get_label() == "Adding apps for ExampleOS…"

        # A step_id the copy does not know shows fisherman's step name.
        progress._BootcProgress__parse_progress_line(json.dumps({
            "type": "step", "step": 7, "total_steps": 8,
            "step_name": "Polishing the hull", "step_id": "polish_hull",
            "cumulative_pct": 99, "weight_pct": 0, "overall_pct": 99,
        }))
        assert progress.progressbar_text.get_label() == "Polishing the hull"
        assert progress.progress_percentage.get_label() == "99%"

    def test_demo_mode_completes_and_reports_success(self):
        progress, window = self._make_progress()

        def _run_now(_delay, callback, *args):
            callback(*args)
            return 1

        with patch("bootc_installer.views.progress.GLib.timeout_add", side_effect=_run_now):
            progress.start_demo()

        assert progress.progressbar_text.get_label() == "Installation complete!"
        assert progress.progress_percentage.get_label() == "100%"
        assert window.results == [(True, None, "")]
