"""GNOME renders `fisherman probe --json` the way every frontend must.

The fixtures and their expected renderings are shared/probe/fixtures/; the
same files drive the XFCE, KDE, COSMIC and Niri tests, so the five disk lists
cannot drift apart again.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from bootc_installer.core import fisherman_probe  # noqa: E402
from bootc_installer.core.disks import DisksManager  # noqa: E402
from bootc_installer.core.system import Systeminfo  # noqa: E402
from bootc_installer.utils import fisherman_runner  # noqa: E402

FIXTURES = os.path.join(REPO, "shared", "probe", "fixtures")
NAMES = ("laptop", "container", "vm", "pure-live-oci")


def _fixture_path(name):
    return os.path.join(FIXTURES, name + ".json")


def _expected(name):
    with open(os.path.join(FIXTURES, name + ".expected.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _render(manager):
    return [
        {
            "path": d.disk,
            "title": d.display_name,
            "model": d.model,
            "size_label": d.pretty_size,
            "transport_label": d.transport_label,
            "removable": d.is_removable,
        }
        for d in manager.all_disks()
    ]


def _reset():
    Systeminfo._probe = None
    Systeminfo._probe_error = None
    Systeminfo._probed = False


class _ProbeIsolation(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)

    def _with_fixture(self, name):
        env = patch.dict(os.environ, {fisherman_probe.FAKE_ENV: _fixture_path(name)})
        env.start()
        self.addCleanup(env.stop)


class TestFixtures(_ProbeIsolation):
    def test_disk_list_matches_the_shared_rendering(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                _reset()
                self._with_fixture(name)
                self.assertEqual(_render(DisksManager()), _expected(name)["disks"])

    def test_tpm_and_requirements_match(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                _reset()
                self._with_fixture(name)
                want = _expected(name)
                self.assertEqual(Systeminfo.has_tpm2(), want["tpm_usable"])
                self.assertEqual(Systeminfo.unmet_requirements(), want["unmet"])
                self.assertEqual(Systeminfo.is_ram_enough(), "ram" not in want["unmet"])
                self.assertEqual(Systeminfo.is_cpu_enough(), "cpu" not in want["unmet"])
                self.assertEqual(Systeminfo.is_uefi(), "uefi" not in want["unmet"])

    def test_probe_runs_once(self):
        self._with_fixture("laptop")
        with patch.object(fisherman_probe, "run", wraps=fisherman_probe.run) as run:
            DisksManager()
            Systeminfo.has_tpm2()
            Systeminfo.is_ram_enough()
        self.assertEqual(run.call_count, 1)

    def test_get_disk(self):
        self._with_fixture("laptop")
        manager = DisksManager()
        self.assertEqual(manager.get_disk("/dev/sdc").display_name, "Extreme SSD")
        self.assertIsNone(manager.get_disk("/dev/sdb"))  # the live USB
    def test_pure_live_fixture_is_a_live_install_of_the_running_image(self):
        _reset()
        self._with_fixture("pure-live-oci")
        want = _expected("pure-live-oci")
        self.assertTrue(Systeminfo.is_live())
        self.assertEqual(Systeminfo.live_image(), want["live_image"])
        self.assertNotEqual(want["live_image"], "")
        self.assertEqual(Systeminfo.unmet_requirements(), [])
        # The live USB is the boot_disk, not a target: only the SSD shows.
        self.assertEqual([d.disk for d in DisksManager().all_disks()],
                         [d["path"] for d in want["disks"]])



class TestProbeFailure(_ProbeIsolation):
    def _fail(self, message="fisherman probe failed (exit 2): unknown command"):
        return patch.object(fisherman_probe, "run",
                            side_effect=fisherman_probe.ProbeError(message))

    def test_no_disks_and_the_reason(self):
        with patch.dict(os.environ, {}, clear=False), self._fail():
            os.environ.pop(fisherman_probe.FAKE_ENV, None)
            manager = DisksManager()
        self.assertEqual(manager.all_disks(), [])
        self.assertIn("unknown command", manager.error)

    def test_never_blocks_and_hides_tpm(self):
        with self._fail():
            self.assertTrue(Systeminfo.is_ram_enough())
            self.assertTrue(Systeminfo.is_cpu_enough())
            self.assertTrue(Systeminfo.is_uefi())
            self.assertFalse(Systeminfo.has_tpm2())

    def test_a_failed_stage_is_a_probe_error(self):
        with patch.object(fisherman_runner, "IN_FLATPAK", True), \
             patch.object(fisherman_runner, "stage_on_host", return_value=False), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop(fisherman_probe.FAKE_ENV, None)
            self.assertIsNone(Systeminfo.probe())
        self.assertIn("stage", Systeminfo._probe_error)


class TestProbeArgv(unittest.TestCase):
    def test_flatpak_runs_the_staged_binary_on_the_host_unprivileged(self):
        argv = fisherman_runner.probe_argv(in_flatpak=True, host_path="/home/u/.cache/f")
        self.assertEqual(argv, ["flatpak-spawn", "--host", "/home/u/.cache/f", "probe", "--json"])

    def test_host_runs_the_installed_binary_unprivileged(self):
        argv = fisherman_runner.probe_argv(in_flatpak=False)
        self.assertEqual(argv, ["/usr/local/bin/fisherman", "probe", "--json"])
        self.assertNotIn("pkexec", argv)
        self.assertNotIn("sudo", argv)


if __name__ == "__main__":
    unittest.main()
