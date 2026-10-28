"""Headless contract tests for the fisherman host execution boundary."""

import os
from unittest.mock import patch

import pytest

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


def test_native_path_prefers_the_packaged_binary():
    assert fisherman_runner.native_path(lambda p: p == "/usr/bin/fisherman") == "/usr/bin/fisherman"
    assert fisherman_runner.native_path(lambda p: False) == "/usr/local/bin/fisherman"


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


def test_flatpak_uses_persistent_app_cache_on_var_home():
    with patch.object(fisherman_runner, "IN_FLATPAK", True), patch.dict(
        os.environ, {"HOME": "/var/home/test", "XDG_CACHE_HOME": "/var/home/test/.var/app/app.id/cache"}, clear=True
    ):
        assert fisherman_runner.default_cache_dir() == "/var/home/test/.var/app/app.id/cache/bootc-installer"


def test_native_cache_location_is_unchanged():
    with patch.object(fisherman_runner, "IN_FLATPAK", False), patch.dict(
        os.environ, {"HOME": "/home/test", "XDG_CACHE_HOME": "/different"}, clear=True
    ):
        assert fisherman_runner.default_cache_dir() == "/home/test/.cache/bootc-installer"


@pytest.mark.parametrize("cache", ["", "relative"])
def test_missing_or_relative_flatpak_cache_is_rejected(cache):
    with patch.object(fisherman_runner, "IN_FLATPAK", True), patch.dict(
        os.environ, {"HOME": "/home/test", "XDG_CACHE_HOME": cache}, clear=True
    ), pytest.raises(ValueError, match="absolute path"):
        fisherman_runner.default_cache_dir()


def test_staging_requires_host_visible_identical_bytes(tmp_path):
    import hashlib
    import subprocess
    from types import SimpleNamespace

    source = tmp_path / "source"
    source.write_bytes(b"test helper bytes")
    cache = tmp_path / "cache" / "bootc-installer"
    target = cache / "fisherman"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with patch.dict(os.environ, {"BOOTC_FISHERMAN_PATH": str(source)}):
        for result, expected in [
            (SimpleNamespace(returncode=0, stdout=digest + "  " + str(target)), True),
            (SimpleNamespace(returncode=1, stdout=""), False),
            (SimpleNamespace(returncode=0, stdout="0" * 64 + "  " + str(target)), False),
        ]:
            with patch.object(fisherman_runner.subprocess, "run", return_value=result) as run:
                assert fisherman_runner.stage_on_host(
                    in_flatpak=True, stage_base=str(tmp_path), cache_dir=str(cache), host_path=str(target)
                ) is expected
                assert run.call_args.args[0] == ["flatpak-spawn", "--host", "sha256sum", "--", str(target)]
                assert target.stat().st_mode & 0o777 == 0o700
        for error in (OSError("portal unavailable"), subprocess.TimeoutExpired("portal", 10)):
            with patch.object(fisherman_runner.subprocess, "run", side_effect=error):
                assert not fisherman_runner.stage_on_host(
                    in_flatpak=True, stage_base=str(tmp_path), cache_dir=str(cache), host_path=str(target)
                )


@pytest.mark.parametrize("unsafe", ["symlink", "writable"])
def test_unsafe_staging_directory_is_rejected_before_host_call(tmp_path, unsafe):
    cache = tmp_path / "cache"
    if unsafe == "symlink":
        cache.symlink_to(tmp_path, target_is_directory=True)
    else:
        cache.mkdir(mode=0o777)
        cache.chmod(0o777)
    with patch.object(fisherman_runner.subprocess, "run") as run:
        assert not fisherman_runner.stage_on_host(
            in_flatpak=True, stage_base=str(tmp_path), cache_dir=str(cache), host_path=str(cache / "fisherman")
        )
        run.assert_not_called()
