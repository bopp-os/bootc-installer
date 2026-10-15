"""Host execution boundary for the privileged fisherman helper."""

import logging
import os
import shutil
import stat

logger = logging.getLogger("Installer::FishermanRunner")

IN_FLATPAK = os.path.exists("/.flatpak-info")


def default_stage_base() -> str:
    """Return the private user-owned base used for host-visible staging."""
    return (
        os.environ.get("HOME")
        or os.environ.get("XDG_RUNTIME_DIR")
        or f"/run/user/{os.getuid()}"
    )


STAGE_BASE = default_stage_base()
CACHE_DIR = os.path.join(STAGE_BASE, ".cache", "bootc-installer")
HOST_PATH = os.path.join(CACHE_DIR, "fisherman")
LOG_PATH = os.path.join(CACHE_DIR, "fisherman-output.log")


def build_argv(
    *,
    in_flatpak: bool = IN_FLATPAK,
    use_sudo: bool = False,
    host_path: str = HOST_PATH,
    log_path: str = LOG_PATH,
) -> list[str]:
    """Build the host-side command that runs fisherman and captures its output.

    fisherman reads the recipe from stdin (`fisherman -`, tuna-os/fisherman#276):
    the caller writes the JSON to the wrapper's stdin and closes it, so no
    recipe file ever holds the passphrase or the user password. bash, pkexec,
    sudo and flatpak-spawn all pass stdin through. stdout and stderr go to the
    log file, which the progress page tails.

    `use_sudo` is for live media outside a Flatpak, where the live user has
    passwordless sudo and may have no polkit agent. The caller decides it from
    fisherman's probe (`live.is_live`), never from /run/ostree-booted, which
    every installed ostree host has.
    """
    if in_flatpak:
        if os.environ.get("BOOTC_TEST"):
            binary = os.environ.get("BOOTC_FISHERMAN_PATH", host_path)
            command = f'sudo "{binary}" - >"{log_path}" 2>&1; exit $?'
        else:
            command = f'pkexec "{host_path}" - >"{log_path}" 2>&1; exit $?'
        return ["flatpak-spawn", "--host", "bash", "-c", command]
    escalate = "sudo" if use_sudo else "pkexec"
    command = f'{escalate} /usr/local/bin/fisherman - >"{log_path}" 2>&1; exit $?'
    return ["bash", "-c", command]


def fisherman_argv(
    *,
    in_flatpak: bool = IN_FLATPAK,
    host_path: str = HOST_PATH,
) -> list[str]:
    """The unprivileged way to reach fisherman, for `probe --json` and
    `validate --json`: the same binary the install runs, on the host, as the
    desktop user. In a Flatpak that is the staged copy, so the caller stages
    it first (stage_on_host)."""
    if in_flatpak:
        return ["flatpak-spawn", "--host", host_path]
    return ["/usr/local/bin/fisherman"]


def probe_argv(
    *,
    in_flatpak: bool = IN_FLATPAK,
    host_path: str = HOST_PATH,
) -> list[str]:
    """The unprivileged `fisherman probe --json` command (shared/probe/README.md).

    Never through pkexec or sudo: the probe needs no root.
    """
    return fisherman_argv(in_flatpak=in_flatpak, host_path=host_path) + ["probe", "--json"]


def path_is_private(path: str, check_mode: bool = True) -> bool:
    """Return whether a path is safe for staging a root-executed helper."""
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError as error:
        logger.error("cannot stat staging path %s: %s", path, error)
        return False

    if stat.S_ISLNK(path_stat.st_mode):
        logger.error("staging path %s is a symlink; refusing", path)
        return False
    if path_stat.st_uid != os.getuid():
        logger.error("staging path %s is owned by uid %d, not %d; refusing",
                     path, path_stat.st_uid, os.getuid())
        return False
    if check_mode and path_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        logger.error("staging path %s is group- or world-writable; refusing", path)
        return False
    return True


def stage_on_host(
    *,
    in_flatpak: bool = IN_FLATPAK,
    stage_base: str = STAGE_BASE,
    cache_dir: str = CACHE_DIR,
    host_path: str = HOST_PATH,
) -> bool:
    """Copy fisherman to a private host-visible location for pkexec."""
    if not in_flatpak:
        return True
    if not path_is_private(stage_base, check_mode=False):
        return False
    for path in (os.path.dirname(cache_dir), cache_dir, host_path):
        if not path_is_private(path):
            return False

    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    source = os.environ.get("BOOTC_FISHERMAN_PATH", "/app/bin/fisherman")
    try:
        shutil.copy2(source, host_path)
        os.chmod(host_path, stat.S_IRWXU)
        logger.info("Staged fisherman binary to %s", host_path)
        return True
    except OSError as error:
        logger.error("Failed to stage fisherman binary: %s", error)
        return False
