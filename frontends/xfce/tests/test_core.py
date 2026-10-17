# test_core.py - Unit tests for tuna_installer_xfce.core (backend plumbing)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# core.py is the shared backend (catalog, disks, live and offline facts,
# recipe emission, fisherman invocation) and is pure stdlib — no GTK import — so
# these tests run headlessly in plain pytest.

import json
import os
import subprocess

from tuna_installer_xfce import core


# ─── dry_run interlock ───────────────────────────────────────────────────────

class TestDryRun:
    def test_unset_is_false(self, monkeypatch):
        monkeypatch.delenv("TUNA_INSTALLER_DRY_RUN", raising=False)
        assert core.dry_run() is False

    def test_empty_is_false(self, monkeypatch):
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "")
        assert core.dry_run() is False

    def test_zero_is_false(self, monkeypatch):
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "0")
        assert core.dry_run() is False

    def test_nonzero_is_true(self, monkeypatch):
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
        assert core.dry_run() is True


# ─── product name resolution ─────────────────────────────────────────────────
# The resolver itself is tested against the shared fixtures in
# tests/test_branding.py; here only core's use of it.

class TestBranding:
    def test_product_name_is_the_branding_name(self):
        assert core.PRODUCT_NAME == core.BRANDING.name

    def test_resolve_branding_reads_env_file(self, tmp_path, monkeypatch):
        f = tmp_path / "branding.json"
        f.write_text('{"name": "Alpha", "id": "alpha"}')
        monkeypatch.setenv("BOOTC_INSTALLER_BRANDING", str(f))
        b = core.resolve_branding()
        assert (b.name, b.id) == ("Alpha", "alpha")

    def test_nothing_readable_is_neutral(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOTC_INSTALLER_BRANDING", str(tmp_path / "missing"))
        monkeypatch.setattr(core.branding, "OS_RELEASE_PATHS", [str(tmp_path / "missing")])
        b = core.resolve_branding()
        assert b.name == "Linux"
        assert "tuna" not in b.name.lower() and "bluefin" not in b.name.lower()


# ─── live media and offline images: fisherman's facts ────────────────────────

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "probe", "fixtures")


def _probe_from(monkeypatch, name):
    monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", os.path.join(FIXTURES, name + ".json"))
    core.probe(refresh=True)


class TestLiveAndOffline:
    """probe's `live` and `offline` sections, read through the shared reader
    (shared/probe/README.md). No bootc status, /proc/cmdline, store list or
    podman here: inside a Flatpak they saw the runtime, not the host."""

    def teardown_method(self):
        core._probe_cache.clear()

    def test_live_laptop(self, monkeypatch):
        _probe_from(monkeypatch, "laptop")
        expected = json.load(open(os.path.join(FIXTURES, "laptop.expected.json")))
        assert core.is_live()
        assert core.live_image() == expected["live_image"]
        assert core.offline_images() == set(expected["offline_images"])

    def test_pure_live_oci_installs_the_running_image(self, monkeypatch):
        _probe_from(monkeypatch, "pure-live-oci")
        expected = json.load(open(os.path.join(FIXTURES, "pure-live-oci.expected.json")))
        assert core.is_live()
        assert core.live_image() == expected["live_image"]
        assert expected["live_image"] != ""
        assert core.offline_images() == set(expected["offline_images"])


    def test_installed_container_is_not_live(self, monkeypatch):
        _probe_from(monkeypatch, "container")
        assert not core.is_live()
        assert core.live_image() == ""
        assert core.offline_images() == set()

    def test_a_failed_probe_is_not_live(self, monkeypatch):
        monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", "/nonexistent/probe.json")
        core.probe(refresh=True)
        assert not core.is_live()
        assert core.offline_images() == set()

    def test_no_detection_of_its_own(self):
        src = open(core.__file__).read()
        for gone in ("live_iso_image", "offline_stores", '"podman"', "rd.live.image",
                     "/run/ostree-live", "TUNA_OFFLINE_STORES"):
            assert gone not in src, gone


class TestImageNode:
    def test_parent_child_field_inheritance(self):
        raw_parent = {
            "name": "Desktop",
            "registry": "ghcr.io/tuna-os",
            "bootloader": "systemd-boot",
            "filesystem": "btrfs",
            "children": [
                {
                    "name": "XFCE",
                    "tag": "xfce",
                }
            ],
        }
        parent = core.ImageNode(raw_parent)
        assert len(parent.children) == 1
        child = parent.children[0]

        assert child.name == "XFCE"
        assert child.registry == "ghcr.io/tuna-os"
        assert child.imgref == "ghcr.io/tuna-os:xfce"
        assert child.bootloader == "systemd-boot"
        assert child.filesystem == "btrfs"
        assert child.is_leaf() is True

        leaves = list(parent.leaves())
        assert len(leaves) == 1
        assert leaves[0].name == "XFCE"


class TestLoadCatalog:
    def test_loads_images_json_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "images.json"
        cfg.write_text(json.dumps({
            "default_image": "ghcr.io/tuna-os/xfce:latest",
            "fallback_flatpaks": ["org.gnome.Loupe"],
            "images": [{"name": "XFCE", "imgref": "ghcr.io/tuna-os/xfce:latest"}]
        }))
        monkeypatch.setattr(core, "IMAGES_JSON_PATHS", [str(cfg)])
        default_img, fallbacks, nodes = core.load_catalog()
        assert default_img == "ghcr.io/tuna-os/xfce:latest"
        assert fallbacks == ["org.gnome.Loupe"]
        assert len(nodes) == 1
        assert nodes[0].name == "XFCE"


# Disks, sizes and the TPM come from `fisherman probe --json` now: see
# tests/test_probe.py.


# ─── recipe building ─────────────────────────────────────────────────────────
#
# These cover the conditionals that used to sit inside
# InstallerWindow.build_recipe, where reaching them meant constructing a GTK
# window. The recipe is the contract with fisherman, so the interesting cases
# are the ones where a key must be ABSENT — an empty value and a missing key
# do not mean the same thing to the backend.

MINIMAL = dict(disk="/dev/vda", filesystem="xfs")


class TestBuildRecipe:
    def test_minimal_recipe_has_the_fixed_fields(self):
        r = core.build_recipe(**MINIMAL, hostname="reef")
        assert r["disk"] == "/dev/vda"
        assert r["filesystem"] == "xfs"
        assert r["hostname"] == "reef"
        assert r["distroID"] == core.BRANDING.id
        assert r["selinuxDisabled"] is False
        assert r["encryption"] == {"type": "none"}

    def test_optional_keys_are_absent_not_empty(self):
        r = core.build_recipe(**MINIMAL)
        for key in ("bootloader", "composeFsBackend", "flatpaks",
                    "additionalImageStores", "user"):
            assert key not in r, f"{key} must be omitted, not emitted empty"

    # --- btrfs subvolumes ---

    def test_subvolumes_honoured_on_btrfs(self):
        r = core.build_recipe(disk="/dev/vda", filesystem="btrfs",
                              btrfs_subvolumes=True)
        assert r["btrfsSubvolumes"] is True

    def test_subvolumes_ignored_off_btrfs(self):
        """The Advanced checkbox keeps its state when the filesystem changes."""
        r = core.build_recipe(disk="/dev/vda", filesystem="xfs",
                              btrfs_subvolumes=True)
        assert r["btrfsSubvolumes"] is False

    # --- encryption ---

    def test_passphrase_emitted_for_a_passphrase_type(self):
        r = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                              passphrase="hunter2")
        assert r["encryption"] == {"type": "luks-passphrase",
                                   "passphrase": "hunter2"}

    def test_passphrase_never_leaks_into_an_unencrypted_recipe(self):
        """A stale entry in the box must not reach the backend."""
        r = core.build_recipe(**MINIMAL, encryption_type="none",
                              passphrase="left-over")
        assert "passphrase" not in r["encryption"]

    def test_tpm_only_takes_no_passphrase(self):
        """`tpm2-luks` unlocks from the TPM alone — see ENCRYPTION_TYPES."""
        r = core.build_recipe(**MINIMAL, encryption_type="tpm2-luks",
                              passphrase="left-over")
        assert r["encryption"] == {"type": "tpm2-luks"}

    def test_tpm_plus_passphrase_carries_the_fallback(self):
        """`tpm2-luks-passphrase` is TPM unlock with a passphrase fallback, so
        the passphrase must survive. This is why the check is a substring test
        and not equality against 'luks-passphrase'."""
        r = core.build_recipe(**MINIMAL, encryption_type="tpm2-luks-passphrase",
                              passphrase="fallback")
        assert r["encryption"] == {"type": "tpm2-luks-passphrase",
                                   "passphrase": "fallback"}

    # --- catalog leaf properties ---

    def test_bootloader_and_composefs_passed_through(self):
        r = core.build_recipe(**MINIMAL, bootloader="systemd-boot",
                              composefs=True)
        assert r["bootloader"] == "systemd-boot"
        assert r["composeFsBackend"] is True

    def test_flatpaks_split_into_a_list(self):
        r = core.build_recipe(**MINIMAL, flatpaks="org.gnome.Loupe org.gnome.Calculator")
        assert r["flatpaks"] == ["org.gnome.Loupe", "org.gnome.Calculator"]

    def test_catalog_reference_is_not_a_package_list(self):
        """A leading @ names another catalog entry — passing it verbatim would
        ask fisherman to install a flatpak called '@desktop'."""
        r = core.build_recipe(**MINIMAL, flatpaks="@desktop")
        assert "flatpaks" not in r

    # --- offline stores ---

    def test_stores_are_left_to_fisherman(self):
        """Absent, fisherman exposes the host's offline stores itself."""
        r = core.build_recipe(**MINIMAL)
        assert "additionalImageStores" not in r

    # --- user block ---

    def test_user_block_built_when_the_image_needs_one(self):
        r = core.build_recipe(**MINIMAL, needs_user=True, username="jo",
                              fullname="Jo Fish", password="pw")
        assert r["user"] == {"username": "jo", "fullname": "Jo Fish",
                             "password": "pw", "groups": ["wheel"]}

    def test_no_user_block_when_the_image_creates_its_own(self):
        """The image runs its own first-boot setup; a second user would be
        created behind the user's back."""
        r = core.build_recipe(**MINIMAL, needs_user=False, username="jo",
                              password="pw")
        assert "user" not in r

    def test_no_user_block_without_a_username(self):
        r = core.build_recipe(**MINIMAL, needs_user=True, username="",
                              password="pw")
        assert "user" not in r

    # --- round trip ---

    def test_recipe_survives_the_stdin_encoding(self):
        built = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                                  passphrase="pw", needs_user=True, username="jo")
        assert json.loads(core.recipe_stdin(built)) == built


# ─── fisherman invocation: the recipe on stdin ──────────────────────────────

class TestFisherman:
    def test_nothing_writes_a_recipe_file(self):
        assert not hasattr(core, "write_recipe")
        assert not hasattr(core, "recipe_dir")
        assert "tempfile" not in open(core.__file__).read()

    def test_argv_uses_sudo_outside_flatpak_and_reads_stdin(self):
        assert core.fisherman_argv(in_flatpak=False) == [
            "sudo", "/usr/local/bin/fisherman", "-"]

    def test_shell_line(self):
        assert core.fisherman_shell() == "sudo /usr/local/bin/fisherman -"

    def test_flatpak_argv_runs_pkexec_inside_a_host_bash(self):
        # Not `flatpak-spawn --host pkexec ...`: then fisherman's parent is
        # the host's flatpak-session-helper and it cannot be cancelled.
        argv = core.fisherman_argv(in_flatpak=True)
        assert argv == ["flatpak-spawn", "--host", "bash", "-c",
                        "pkexec /usr/local/bin/fisherman -; exit $?"]

    def test_flatpak_wrapper_passes_stdin_stdout_stderr_and_status_through(self, tmp_path):
        """Run the wrapper's bash for real, with pkexec stubbed: the recipe
        written to the wrapper's stdin is what fisherman reads."""
        stub = tmp_path / "bin"
        stub.mkdir()
        (stub / "pkexec").write_text(
            '#!/bin/sh\n'
            'printf \'{"type":"step","argv":"%s|%s"}\\n\' "$1" "$2"\n'
            'cat > "$RECIPE_OUT"\n'
            'echo "to stderr" >&2\n'
            'exit 7\n')
        (stub / "pkexec").chmod(0o755)
        argv = core.fisherman_argv(in_flatpak=True)
        assert argv[:2] == ["flatpak-spawn", "--host"]
        out = tmp_path / "recipe-read"
        env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}", RECIPE_OUT=str(out))
        recipe = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                                   passphrase="pw")
        done = subprocess.run(argv[2:], env=env, cwd=tmp_path, input=core.recipe_stdin(recipe),
                              capture_output=True)
        assert done.returncode == 7
        assert done.stdout == b'{"type":"step","argv":"/usr/local/bin/fisherman|-"}\n'
        assert done.stderr == b"to stderr\n"
        assert json.loads(out.read_text()) == recipe
        assert list(tmp_path.glob("*.json")) == []


# ─── validation and encryption choices: fisherman's ────────────────────────

class TestValidateAndChoices:
    def test_validate_argv_is_partial_on_stdin_and_unprivileged(self):
        assert core.VALIDATE_ARGV[-4:] == ["validate", "--json", "--partial", "-"]
        assert "sudo" not in core.VALIDATE_ARGV and "pkexec" not in core.VALIDATE_ARGV

    def test_choices_come_from_the_file(self):
        assert [c["type"] for c in core.ENCRYPTION_CHOICES] == [
            "none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"]
        assert core.needs_passphrase("tpm2-luks-passphrase")
        assert not core.needs_passphrase("tpm2-luks")
        assert core.needs_tpm2("tpm2-luks") and not core.needs_tpm2("luks-passphrase")


# ─── install log ─────────────────────────────────────────────────────────────

class TestInstallLog:
    def test_path_under_xdg_state_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert core.install_log_path() == str(tmp_path / "tuna-installer" / "install.log")

    def test_falls_back_to_local_state_without_xdg_state_home(self, monkeypatch):
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        path = core.install_log_path()
        assert path == os.path.join(
            os.path.expanduser("~"), ".local", "state", "tuna-installer", "install.log")

    def test_creates_private_directory(self, tmp_path, monkeypatch):
        import stat
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        core.install_log_path()
        mode = stat.S_IMODE(os.stat(tmp_path / "tuna-installer").st_mode)
        assert mode == 0o700

    def test_open_install_log_creates_0600_file(self, tmp_path, monkeypatch):
        import stat
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        f = core.open_install_log()
        try:
            f.write("hello\n")
            f.flush()
            path = core.install_log_path()
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o600, f"install log must be 0600, got {oct(mode)}"
        finally:
            f.close()

    def test_open_install_log_appends_across_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        f1 = core.open_install_log()
        f1.write("first\n")
        f1.close()
        f2 = core.open_install_log()
        f2.write("second\n")
        f2.close()
        assert open(core.install_log_path()).read() == "first\nsecond\n"


class TestHostRun:
    def test_host_run_flatpak(self, monkeypatch):
        monkeypatch.setattr(core, "IN_FLATPAK", True)
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        core.host_run(["echo", "hi"])
        assert calls == [["flatpak-spawn", "--host", "echo", "hi"]]


class TestLoadCatalogFallback:
    def test_missing_file_returns_defaults(self, monkeypatch):
        monkeypatch.setattr(core, "IMAGES_JSON_PATHS", ["/path/that/does/not/exist.json"])
        default_img, fallbacks, nodes = core.load_catalog()
        assert default_img == ""
        assert fallbacks == []
        assert nodes == []


