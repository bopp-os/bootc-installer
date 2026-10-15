"""Unit tests for the pure-Python logic in defaults/slurp.py.

slurp.py has a GTK module-level import chain. We stub out all gi.repository
modules before importing so these tests run without a display or GResource.
"""

import os
import subprocess
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Stub out gi.repository before importing anything from the package ──────────

def _build_gi_stubs():
    """Inject lightweight gi stubs so slurp.py can be imported headlessly.

    Other unit test files (e.g. test_image_helpers.py) install MagicMock gi
    modules before this file is collected. MagicMock returns truthy for any
    attribute, so a simple hasattr("_stubbed") check is not enough. We always
    force-install our stubs and then reload slurp.py so its class definitions
    are evaluated with our stubs rather than MagicMocks.
    """
    gi_mod = types.ModuleType("gi")
    gi_mod._stubbed = True
    repo_mod = types.ModuleType("gi.repository")

    # A Template decorator that accepts @Gtk.Template(resource_path=...) and
    # returns the class unchanged. Also provides Template.Child() as a
    # class-level descriptor.
    class _Template:
        def __call__(self, *args, **kwargs):
            # @Gtk.Template(resource_path="...") → returns decorator
            return lambda cls: cls

        def Child(self, *args, **kwargs):
            return None

    _template_instance = _Template()

    # Minimal stub class that satisfies Gtk.Template, Adw.Bin, etc.
    class _Stub:
        pass

    from unittest.mock import MagicMock as _MagicMock
    stubs = {}
    for lib in ("Gtk", "Adw", "GLib", "Gio", "Gdk", "NM"):
        stub = types.ModuleType(f"gi.repository.{lib}")
        stub.Template = _template_instance
        stub.Bin = _Stub
        stub.Box = _Stub
        stub.PreferencesGroup = _Stub
        stub.SwitchRow = _Stub
        stub.Label = _Stub
        stub.Picture = _Stub
        stub.Spinner = _Stub
        stub.Orientation = type("Orientation", (), {"HORIZONTAL": 0, "VERTICAL": 1})
        stub.Align = type("Align", (), {"CENTER": 0, "FILL": 1, "START": 2})
        stub.Client = type("Client", (), {"new": staticmethod(lambda: None)})
        setattr(repo_mod, lib, stub)
        sys.modules[f"gi.repository.{lib}"] = stub
        stubs[lib] = stub

    # Adw needs Window for dialog_credits.BootcCreditsWindow(Adw.Window)
    stubs["Adw"].Window = _Stub
    stubs["Adw"].ActionRow = _Stub
    stubs["Adw"].ExpanderRow = _Stub

    # Gio needs these for progress.py GResource lookups and dbus calls
    class _ResourceLookupFlags:
        NONE = 0
    stubs["Gio"].ResourceLookupFlags = _ResourceLookupFlags
    stubs["Gio"].resources_lookup_data = _MagicMock()
    stubs["Gio"].bus_get_sync = _MagicMock()
    stubs["Gio"].BusType = types.SimpleNamespace(SYSTEM=0)
    stubs["Gio"].DBusCallFlags = types.SimpleNamespace(NONE=0)
    stubs["Gio"].File = _MagicMock()
    stubs["GObject"] = types.ModuleType("gi.repository.GObject")
    stubs["GObject"].Property = lambda *a, **kw: (lambda f: property(f))
    repo_mod.GObject = stubs["GObject"]
    sys.modules["gi.repository.GObject"] = stubs["GObject"]

    gi_mod.repository = repo_mod
    gi_mod.require_version = lambda *a, **kw: None
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repo_mod

    # Force-reload slurp and its dependencies so class bodies are evaluated
    # with our stubs (not MagicMocks from earlier test files).
    for mod_name in list(sys.modules):
        if "bootc_installer" in mod_name and (
            "slurp" in mod_name or "progress" in mod_name
        ):
            del sys.modules[mod_name]


_build_gi_stubs()

# Now import the helpers we want to test.
from bootc_installer.defaults import slurp
from bootc_installer.defaults.slurp import (
    BootcDefaultSlurp,
    _fmt_bytes,
)

# ── _fmt_bytes ─────────────────────────────────────────────────────────────────

class TestFmtBytes:
    @pytest.mark.parametrize("size,expected", [
        (0, "0.0 B"),
        (512, "512.0 B"),
        (1023, "1023.0 B"),
        (1024, "1.0 KB"),
        (2048, "2.0 KB"),
        (5 * 1024 ** 2, "5.0 MB"),
        (3 * 1024 ** 3, "3.0 GB"),
        (2 * 1024 ** 4, "2.0 TB"),
    ])
    def test_fmt_bytes(self, size, expected):
        assert _fmt_bytes(size) == expected


# ── BootcDefaultSlurp.should_show ───────────────────────────────────────────

class TestSlurpShouldShow:
    def _step(self):
        from types import SimpleNamespace
        return SimpleNamespace()

    def test_always_true(self):
        assert BootcDefaultSlurp.should_show(self._step(), {}) is True

    def test_true_with_populated_context(self):
        ctx = {"finals": [{"disk": "/dev/sda"}], "leaf_count": 2}
        assert BootcDefaultSlurp.should_show(self._step(), ctx) is True


# ── BootcDefaultSlurp.__get_disk ────────────────────────────────────────────

class TestSlurpGetDisk:
    def _get_disk(self, context):
        from types import SimpleNamespace
        step = SimpleNamespace()
        return BootcDefaultSlurp._BootcDefaultSlurp__get_disk(step, context)

    def test_auto_nested_dict(self):
        ctx = {"finals": [{"disk": {"auto": {"disk": "/dev/sda"}, "filesystem": "xfs"}}]}
        assert self._get_disk(ctx) == "/dev/sda"

    def test_plain_string(self):
        assert self._get_disk({"finals": [{"disk": "/dev/nvme0n1"}]}) == "/dev/nvme0n1"

    def test_empty_string_returns_none(self):
        assert self._get_disk({"finals": [{"disk": ""}]}) is None

    def test_no_finals_returns_none(self):
        assert self._get_disk({}) is None
        assert self._get_disk({"finals": []}) is None
        assert self._get_disk({"finals": [{}]}) is None

    def test_non_dict_finals_entry_skipped(self):
        ctx = {"finals": ["not-a-dict", {"disk": "/dev/sdb"}]}
        assert self._get_disk(ctx) == "/dev/sdb"

    def test_disk_dict_with_disk_key(self):
        ctx = {"finals": [{"disk": {"disk": "/dev/sdc"}}]}
        assert self._get_disk(ctx) == "/dev/sdc"


# ── BootcDefaultSlurp.get_finals ────────────────────────────────────────────

class TestSlurpGetFinals:
    def _get_finals(self, selection):
        from types import SimpleNamespace
        step = SimpleNamespace()
        step._BootcDefaultSlurp__selection = selection
        return BootcDefaultSlurp.get_finals(step)

    def test_empty_selection(self):
        assert self._get_finals({}) == {"slurp": None}

    def test_all_deselected(self):
        sel = {
            ("/dev/sda3", "Alice", "Documents"): False,
            ("/dev/sda3", "Alice", "Pictures"): False,
        }
        assert self._get_finals(sel) == {"slurp": None}

    def test_single_category_selected(self):
        sel = {
            ("/dev/sda3", "Alice", "Documents"): True,
            ("/dev/sda3", "Alice", "Pictures"): False,
        }
        result = self._get_finals(sel)
        assert result["slurp"] is not None
        assert result["slurp"]["sourcePartition"] == "/dev/sda3"
        assert result["slurp"]["users"][0]["name"] == "Alice"
        assert result["slurp"]["users"][0]["categories"] == ["Documents"]

    def test_multiple_categories_same_user(self):
        sel = {
            ("/dev/sda3", "Bob", "Documents"): True,
            ("/dev/sda3", "Bob", "Pictures"): True,
            ("/dev/sda3", "Bob", "Music"): False,
        }
        result = self._get_finals(sel)
        cats = sorted(result["slurp"]["users"][0]["categories"])
        assert cats == ["Documents", "Pictures"]

    def test_multiple_users_same_partition(self):
        sel = {
            ("/dev/sda3", "Alice", "Documents"): True,
            ("/dev/sda3", "Bob", "Pictures"): True,
        }
        result = self._get_finals(sel)
        assert result["slurp"] is not None
        names = {u["name"] for u in result["slurp"]["users"]}
        assert names == {"Alice", "Bob"}

    def test_source_partition_is_first_key(self):
        sel = {("/dev/nvme0n1p3", "Charlie", "Desktop"): True}
        result = self._get_finals(sel)
        assert result["slurp"]["sourcePartition"] == "/dev/nvme0n1p3"

    def test_users_with_no_selected_categories_omitted(self):
        sel = {
            ("/dev/sda3", "Alice", "Documents"): True,
            ("/dev/sda3", "Bob", "Pictures"): False,
        }
        result = self._get_finals(sel)
        names = [u["name"] for u in result["slurp"]["users"]]
        assert "Bob" not in names
        assert "Alice" in names


# ── BootcDefaultSlurp.__resolve_fisherman_path ──────────────────────────────

class TestResolveFishermanPath:
    def _resolve(self, step):
        return BootcDefaultSlurp._BootcDefaultSlurp__resolve_fisherman_path(step)

    def test_flatpak_host_path_already_present(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", True)
        monkeypatch.setattr(slurp, "_FISHERMAN_HOST_PATH", "/run/host/fisherman")
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/run/host/fisherman")
        assert self._resolve(SimpleNamespace()) == "/run/host/fisherman"

    def test_flatpak_stages_then_finds_host_path(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", True)
        monkeypatch.setattr(slurp, "_FISHERMAN_HOST_PATH", "/run/host/fisherman")
        calls = {"n": 0}

        def fake_exists(p):
            if p != "/run/host/fisherman":
                return False
            calls["n"] += 1
            return calls["n"] > 1  # missing, then present after staging

        monkeypatch.setattr(os.path, "exists", fake_exists)
        monkeypatch.setattr(slurp, "_stage_fisherman_on_host", lambda: True)
        assert self._resolve(SimpleNamespace()) == "/run/host/fisherman"

    def test_flatpak_falls_back_to_non_app_env_path(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", True)
        monkeypatch.setattr(slurp, "_FISHERMAN_HOST_PATH", "/run/host/fisherman")
        monkeypatch.setattr(slurp, "_stage_fisherman_on_host", lambda: False)
        monkeypatch.setenv("BOOTC_FISHERMAN_PATH", "/opt/fisherman")
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/opt/fisherman")
        assert self._resolve(SimpleNamespace()) == "/opt/fisherman"

    def test_flatpak_rejects_app_prefixed_env_path(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", True)
        monkeypatch.setattr(slurp, "_FISHERMAN_HOST_PATH", "/run/host/fisherman")
        monkeypatch.setattr(slurp, "_stage_fisherman_on_host", lambda: False)
        monkeypatch.setenv("BOOTC_FISHERMAN_PATH", "/app/bin/fisherman")
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/app/bin/fisherman")
        assert self._resolve(SimpleNamespace()) is None

    def test_flatpak_none_found(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", True)
        monkeypatch.setattr(slurp, "_FISHERMAN_HOST_PATH", "/run/host/fisherman")
        monkeypatch.setattr(slurp, "_stage_fisherman_on_host", lambda: False)
        monkeypatch.delenv("BOOTC_FISHERMAN_PATH", raising=False)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert self._resolve(SimpleNamespace()) is None

    def test_non_flatpak_env_path_wins(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", False)
        monkeypatch.setenv("BOOTC_FISHERMAN_PATH", "/opt/fisherman")
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/opt/fisherman")
        assert self._resolve(SimpleNamespace()) == "/opt/fisherman"

    def test_non_flatpak_falls_back_to_usr_local_bin(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", False)
        monkeypatch.delenv("BOOTC_FISHERMAN_PATH", raising=False)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/usr/local/bin/fisherman")
        assert self._resolve(SimpleNamespace()) == "/usr/local/bin/fisherman"

    def test_non_flatpak_falls_back_to_usr_bin(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", False)
        monkeypatch.delenv("BOOTC_FISHERMAN_PATH", raising=False)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/usr/bin/fisherman")
        assert self._resolve(SimpleNamespace()) == "/usr/bin/fisherman"

    def test_non_flatpak_none_found(self, monkeypatch):
        monkeypatch.setattr(slurp, "_IN_FLATPAK", False)
        monkeypatch.delenv("BOOTC_FISHERMAN_PATH", raising=False)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert self._resolve(SimpleNamespace()) is None


# ── BootcDefaultSlurp.__budget_limit_bytes / __selected_total_bytes /
#    __update_budget_warning ──────────────────────────────────────────────

class TestBudget:
    def _limit(self, step):
        return BootcDefaultSlurp._BootcDefaultSlurp__budget_limit_bytes(step)

    def _selected(self, step):
        return BootcDefaultSlurp._BootcDefaultSlurp__selected_total_bytes(step)

    def _update_warning(self, step):
        return BootcDefaultSlurp._BootcDefaultSlurp__update_budget_warning(step)

    def test_limit_uses_sysconf_minus_reserve(self, monkeypatch):
        page_size, pages = 4096, 1_000_000  # ~3.9 GB total
        monkeypatch.setattr(
            os, "sysconf",
            lambda name: page_size if name == "SC_PAGE_SIZE" else pages,
        )
        expected = max(0, page_size * pages - slurp._WARN_RESERVE_BYTES)
        assert self._limit(SimpleNamespace()) == expected

    def test_limit_never_negative(self, monkeypatch):
        monkeypatch.setattr(os, "sysconf", lambda name: 1)
        assert self._limit(SimpleNamespace()) == 0

    def test_limit_falls_back_when_sysconf_unavailable(self, monkeypatch):
        def raise_oserror(name):
            raise OSError("not supported")

        monkeypatch.setattr(os, "sysconf", raise_oserror)
        assert self._limit(SimpleNamespace()) == slurp._WARN_THRESHOLD_GB * 1024**3

    def test_selected_total_sums_only_selected_keys(self):
        step = SimpleNamespace()
        step._BootcDefaultSlurp__selection = {
            ("/dev/sda3", "Alice", "Documents"): True,
            ("/dev/sda3", "Alice", "Pictures"): False,
            ("/dev/sda3", "Bob", "Desktop"): True,
        }
        step._BootcDefaultSlurp__category_sizes = {
            ("/dev/sda3", "Alice", "Documents"): 100,
            ("/dev/sda3", "Alice", "Pictures"): 999,
            ("/dev/sda3", "Bob", "Desktop"): 50,
        }
        assert self._selected(step) == 150

    def test_selected_total_missing_size_defaults_zero(self):
        step = SimpleNamespace()
        step._BootcDefaultSlurp__selection = {("/dev/sda3", "Alice", "Documents"): True}
        step._BootcDefaultSlurp__category_sizes = {}
        assert self._selected(step) == 0

    def _warning_step(self, selected_bytes, limit_bytes):
        step = SimpleNamespace()
        step._BootcDefaultSlurp__selected_total_bytes = lambda: selected_bytes
        step._BootcDefaultSlurp__budget_limit_bytes = lambda: limit_bytes
        step.slurp_warning_label = MagicMock()
        return step

    def test_warning_shown_when_over_budget(self):
        step = self._warning_step(selected_bytes=10 * 1024**3, limit_bytes=5 * 1024**3)
        self._update_warning(step)
        step.slurp_warning_label.set_label.assert_called_once()
        step.slurp_warning_label.set_visible.assert_called_once_with(True)

    def test_warning_hidden_when_under_budget(self):
        step = self._warning_step(selected_bytes=1 * 1024**3, limit_bytes=5 * 1024**3)
        self._update_warning(step)
        step.slurp_warning_label.set_label.assert_not_called()
        step.slurp_warning_label.set_visible.assert_called_once_with(False)

    def test_warning_hidden_when_limit_is_zero(self):
        # budget_limit_bytes() == 0 means "no real limit known" — never warn.
        step = self._warning_step(selected_bytes=999, limit_bytes=0)
        self._update_warning(step)
        step.slurp_warning_label.set_visible.assert_called_once_with(False)


# ── BootcDefaultSlurp.__clear_other_partitions / __on_skip ──────────────────

class TestClearSelection:
    def _make_step(self, rows_and_selection):
        step = SimpleNamespace()
        step._BootcDefaultSlurp__rows = {}
        step._BootcDefaultSlurp__row_handlers = {}
        step._BootcDefaultSlurp__selection = {}
        for key, (row, handler_id, selected) in rows_and_selection.items():
            step._BootcDefaultSlurp__rows[key] = row
            step._BootcDefaultSlurp__row_handlers[key] = handler_id
            step._BootcDefaultSlurp__selection[key] = selected
        return step

    def test_clear_other_partitions_deselects_other_partitions_only(self):
        row_a = MagicMock()
        row_b = MagicMock()
        step = self._make_step({
            ("/dev/sda3", "Alice", "Documents"): (row_a, "h1", True),
            ("/dev/sdb1", "Alice", "Documents"): (row_b, "h2", True),
        })
        BootcDefaultSlurp._BootcDefaultSlurp__clear_other_partitions(step, "/dev/sda3")
        row_a.set_active.assert_not_called()
        row_b.handler_block.assert_called_once_with("h2")
        row_b.set_active.assert_called_once_with(False)
        row_b.handler_unblock.assert_called_once_with("h2")
        assert step._BootcDefaultSlurp__selection[("/dev/sdb1", "Alice", "Documents")] is False

    def test_clear_other_partitions_skips_unselected_rows(self):
        row_b = MagicMock()
        step = self._make_step({
            ("/dev/sdb1", "Alice", "Documents"): (row_b, "h2", False),
        })
        BootcDefaultSlurp._BootcDefaultSlurp__clear_other_partitions(step, "/dev/sda3")
        row_b.set_active.assert_not_called()

    def test_clear_other_partitions_handles_missing_handler_id(self):
        row_b = MagicMock()
        step = self._make_step({
            ("/dev/sdb1", "Alice", "Documents"): (row_b, None, True),
        })
        BootcDefaultSlurp._BootcDefaultSlurp__clear_other_partitions(step, "/dev/sda3")
        row_b.handler_block.assert_not_called()
        row_b.set_active.assert_called_once_with(False)
        row_b.handler_unblock.assert_not_called()

    def test_on_skip_deselects_everything_and_advances(self):
        row = MagicMock()
        step = self._make_step({
            ("/dev/sda3", "Alice", "Documents"): (row, "h1", True),
        })
        step.slurp_warning_label = MagicMock()
        step._BootcDefaultSlurp__window = MagicMock()
        BootcDefaultSlurp._BootcDefaultSlurp__on_skip(step, MagicMock())
        row.handler_block.assert_called_once_with("h1")
        row.set_active.assert_called_once_with(False)
        row.handler_unblock.assert_called_once_with("h1")
        assert step._BootcDefaultSlurp__selection[("/dev/sda3", "Alice", "Documents")] is False
        step.slurp_warning_label.set_visible.assert_called_once_with(False)
        step._BootcDefaultSlurp__window.next.assert_called_once_with(None)


# ── BootcDefaultSlurp.__run_scan / __on_scan_complete ───────────────────────

class TestRunScan:
    def _make_step(self):
        import functools

        step = SimpleNamespace()
        step._BootcDefaultSlurp__scan_disk = "/dev/sda"
        step._BootcDefaultSlurp__scan_inflight = True
        step._BootcDefaultSlurp__scan_result = None
        step._BootcDefaultSlurp__render_scan_result = MagicMock()
        # __run_scan reaches self.__on_scan_complete via GLib.idle_add — bind
        # the real unbound method so the callback actually updates `step`.
        step._BootcDefaultSlurp__on_scan_complete = functools.partial(
            BootcDefaultSlurp._BootcDefaultSlurp__on_scan_complete, step
        )
        return step

    def _run_scan(self, step, fisherman_path, disk, monkeypatch, run_result):
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: run_result)
        monkeypatch.setattr(slurp.GLib, "idle_add", lambda fn, *a: fn(*a), raising=False)
        monkeypatch.setattr(slurp, "_IN_FLATPAK", False)
        BootcDefaultSlurp._BootcDefaultSlurp__run_scan(step, fisherman_path, disk)

    def test_success_parses_json_stdout(self, monkeypatch):
        step = self._make_step()
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"disk": "/dev/sda", "partitions": [{"name": "p1"}]}', stderr="",
        )
        self._run_scan(step, "/usr/local/bin/fisherman", "/dev/sda", monkeypatch, result)
        assert step._BootcDefaultSlurp__scan_result == {
            "disk": "/dev/sda", "partitions": [{"name": "p1"}],
        }
        assert step._BootcDefaultSlurp__scan_inflight is False
        step._BootcDefaultSlurp__render_scan_result.assert_called_once()

    def test_nonzero_exit_yields_empty_partitions(self, monkeypatch):
        step = self._make_step()
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        self._run_scan(step, "/usr/local/bin/fisherman", "/dev/sda", monkeypatch, result)
        assert step._BootcDefaultSlurp__scan_result == {"disk": "/dev/sda", "partitions": []}

    def test_invalid_json_yields_empty_partitions(self, monkeypatch):
        step = self._make_step()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        self._run_scan(step, "/usr/local/bin/fisherman", "/dev/sda", monkeypatch, result)
        assert step._BootcDefaultSlurp__scan_result == {"disk": "/dev/sda", "partitions": []}

    def test_subprocess_exception_yields_empty_partitions(self, monkeypatch):
        step = self._make_step()

        def raise_timeout(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="fisherman", timeout=45)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        monkeypatch.setattr(slurp.GLib, "idle_add", lambda fn, *a: fn(*a), raising=False)
        monkeypatch.setattr(slurp, "_IN_FLATPAK", False)
        BootcDefaultSlurp._BootcDefaultSlurp__run_scan(step, "/usr/local/bin/fisherman", "/dev/sda")
        assert step._BootcDefaultSlurp__scan_result == {"disk": "/dev/sda", "partitions": []}

    def test_flatpak_wraps_command_with_flatpak_spawn(self, monkeypatch):
        step = self._make_step()
        captured_cmd = {}

        def fake_run(cmd, **kw):
            captured_cmd["cmd"] = cmd
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(slurp.GLib, "idle_add", lambda fn, *a: fn(*a), raising=False)
        monkeypatch.setattr(slurp, "_IN_FLATPAK", True)
        BootcDefaultSlurp._BootcDefaultSlurp__run_scan(step, "/usr/local/bin/fisherman", "/dev/sda")
        assert captured_cmd["cmd"][:3] == ["flatpak-spawn", "--host", "pkexec"]


class TestOnScanComplete:
    def _complete(self, step, disk, scan):
        return BootcDefaultSlurp._BootcDefaultSlurp__on_scan_complete(step, disk, scan)

    def test_stale_callback_for_different_disk_is_ignored(self):
        step = SimpleNamespace()
        step._BootcDefaultSlurp__scan_disk = "/dev/sda"  # user picked a new disk already
        step._BootcDefaultSlurp__scan_inflight = True
        step._BootcDefaultSlurp__scan_result = None
        step._BootcDefaultSlurp__render_scan_result = MagicMock()
        assert self._complete(step, "/dev/sdb", {"disk": "/dev/sdb"}) is False
        assert step._BootcDefaultSlurp__scan_inflight is True
        step._BootcDefaultSlurp__render_scan_result.assert_not_called()

    def test_fresh_callback_stores_result_and_renders(self):
        step = SimpleNamespace()
        step._BootcDefaultSlurp__scan_disk = "/dev/sda"
        step._BootcDefaultSlurp__scan_inflight = True
        step._BootcDefaultSlurp__scan_result = None
        step._BootcDefaultSlurp__render_scan_result = MagicMock()
        scan = {"disk": "/dev/sda", "partitions": []}
        assert self._complete(step, "/dev/sda", scan) is False
        assert step._BootcDefaultSlurp__scan_inflight is False
        assert step._BootcDefaultSlurp__scan_result == scan
        step._BootcDefaultSlurp__render_scan_result.assert_called_once()
