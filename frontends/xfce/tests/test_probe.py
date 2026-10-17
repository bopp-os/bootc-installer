# test_probe.py - XFCE renders `fisherman probe --json` like every frontend
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The fixtures and the renderings every frontend must produce from them are
# shared/probe/fixtures/ in the monorepo (README.md there). GNOME, KDE,
# COSMIC and Niri test against the same files.

import json
import os

import pytest

from tuna_installer_xfce import core, fisherman_probe

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "shared", "probe", "fixtures")
NAMES = ("laptop", "container", "vm", "pure-live-oci")

pytestmark = pytest.mark.skipif(not os.path.isdir(FIXTURES),
                                reason="not inside the bootc-installer monorepo")


def _expected(name):
    with open(os.path.join(FIXTURES, name + ".expected.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def fixture(monkeypatch):
    def use(name):
        monkeypatch.setenv(fisherman_probe.FAKE_ENV, os.path.join(FIXTURES, name + ".json"))
        core.probe(refresh=True)
    yield use
    core._probe_cache.clear()


@pytest.mark.parametrize("name", NAMES)
def test_disk_list_matches_the_shared_rendering(fixture, name):
    fixture(name)
    disks, error = core.candidate_disks()
    assert error is None
    assert disks == _expected(name)["disks"]


@pytest.mark.parametrize("name", NAMES)
def test_tpm_and_requirements_match(fixture, name):
    fixture(name)
    want = _expected(name)
    assert core.has_tpm() is want["tpm_usable"]
    assert core.unmet_requirements() == want["unmet"]


def test_pure_live_fixture_is_a_live_install_of_the_running_image(fixture):
    fixture("pure-live-oci")
    want = _expected("pure-live-oci")
    assert core.is_live()
    assert core.live_image() == want["live_image"]
    assert want["live_image"] != ""
    assert core.offline_images() == set(want["offline_images"])
    # The live USB is the boot_disk, not a target: only the SSD shows.
    disks, error = core.candidate_disks()
    assert error is None
    assert [d["path"] for d in disks] == [d["path"] for d in want["disks"]]


def test_requirements_warning_lists_each_unmet_item(fixture):
    fixture("vm")
    text = core.requirements_warning()
    assert text.splitlines() == [core.BRANDING.text(k) for k in (
        "requirements_title", "requirements_ram", "requirements_cpu", "requirements_uefi")]
    fixture("laptop")
    assert core.requirements_warning() == ""


def test_probe_runs_once(fixture, monkeypatch):
    fixture("laptop")
    calls = []
    monkeypatch.setattr(fisherman_probe, "run", lambda argv: calls.append(argv))
    core.candidate_disks()
    core.has_tpm()
    core.unmet_requirements()
    assert calls == []


def test_a_failed_probe_offers_nothing_and_says_why(monkeypatch):
    def fail(argv):
        raise fisherman_probe.ProbeError("fisherman probe failed (exit 2): unknown command")

    monkeypatch.setattr(fisherman_probe, "run", fail)
    core.probe(refresh=True)
    try:
        disks, error = core.candidate_disks()
        assert disks == []
        assert "unknown command" in error
        assert core.has_tpm() is False
        assert core.requirements_warning() == ""
    finally:
        core._probe_cache.clear()


def test_probe_is_unprivileged_and_on_the_host():
    prefix = ["flatpak-spawn", "--host"] if core.IN_FLATPAK else []
    assert core.PROBE_ARGV == prefix + ["/usr/local/bin/fisherman", "probe", "--json"]
