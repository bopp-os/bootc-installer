"""Headless contract tests for the fisherman host execution boundary."""

import os
from unittest.mock import patch

from bootc_installer.utils import fisherman_runner


def test_native_argv_uses_pkexec_and_reads_the_recipe_from_stdin():
    argv = fisherman_runner.build_argv(
        in_flatpak=False,
        use_sudo=False,
        log_path="/tmp/fisherman.log",
    )

    assert argv == ["bash", "-c",
                    'pkexec /usr/local/bin/fisherman - >"/tmp/fisherman.log" 2>&1; exit $?']


def test_live_media_argv_uses_sudo():
    argv = fisherman_runner.build_argv(in_flatpak=False, use_sudo=True, log_path="/l")
    assert argv[-1].startswith("sudo /usr/local/bin/fisherman - ")


def test_the_unprivileged_command_is_the_install_binary():
    assert fisherman_runner.fisherman_argv(in_flatpak=False) == ["/usr/local/bin/fisherman"]
    assert fisherman_runner.fisherman_argv(in_flatpak=True, host_path="/p/f") == [
        "flatpak-spawn", "--host", "/p/f"]
    assert fisherman_runner.probe_argv(in_flatpak=False)[-2:] == ["probe", "--json"]


def test_no_live_detection_from_ostree_booted():
    assert not hasattr(fisherman_runner, "LIVE_ISO")


def test_flatpak_argv_runs_redirect_on_host():
    with patch.dict(os.environ, {}, clear=True):
        argv = fisherman_runner.build_argv(
            in_flatpak=True,
            host_path="/private/fisherman",
            log_path="/private/fisherman.log",
        )

    assert argv[:3] == ["flatpak-spawn", "--host", "bash"]
    command = argv[argv.index("-c") + 1]
    assert 'pkexec "/private/fisherman" - ' in command
    assert '>"/private/fisherman.log"' in command


def test_native_staging_is_a_noop():
    assert fisherman_runner.stage_on_host(in_flatpak=False)
