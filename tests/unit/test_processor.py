"""Unit tests for utils/processor.py — pure Python, no GTK required."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer.utils.processor import Processor

# A minimal system recipe (the bootc recipe.json, NOT the fisherman recipe).
_SYS_RECIPE = {}


def _load(recipe: dict) -> dict:
    """gen_install_recipe returns the recipe itself: it goes to fisherman on
    stdin, never to a file."""
    assert isinstance(recipe, dict)
    return recipe


# ── Auto-disk helpers ──────────────────────────────────────────────────────────

def _auto_finals(disk="/dev/vda", fs="xfs", image="ghcr.io/tuna-os/yellowfin:gnome",
                 hostname="testhost", encryption=None, user=None, flatpaks=None,
                 composefs=False, image_type="bootc", bootloader="", image_filesystem="",
                 flatpak_var_path=""):
    d = {
        "disk": {
            "auto": {"disk": disk, "pretty_size": "100 GB", "size": 100_000_000_000},
            "filesystem": fs,
            "btrfsSubvolumes": fs == "btrfs",
        },
        "selected_image": image,
        "hostname": hostname,
        "flatpaks": flatpaks or [],
        "composefs_backend": composefs,
        "image_type": image_type,
        "bootloader": bootloader,
        "image_filesystem": image_filesystem,
        "flatpak_var_path": flatpak_var_path,
    }
    if encryption:
        d["encryption"] = encryption
    else:
        d["encryption"] = {"use_encryption": False}
    if user:
        d["user"] = user
    return [d]


# ── Auto-disk tests ────────────────────────────────────────────────────────────

class TestAutoDisk:
    def test_basic_xfs(self, tmp_path):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/vda"
        assert r["filesystem"] == "xfs"
        assert "customMounts" not in r or r.get("customMounts") == []

    def test_non_composefs_live_iso_mode_emits_empty_image(self, tmp_path):
        sys_recipe = {
            "image": "",
            "local_imgref": "containers-storage:ghcr.io/projectbluefin/utah:testing",
            "imgref": "ghcr.io/projectbluefin/utah:testing",
        }
        path = Processor.gen_install_recipe("log", _auto_finals(image="ghcr.io/projectbluefin/utah:testing", composefs=False, image_type="bootc"), sys_recipe)
        r = _load(path)
        assert r["image"] == ""
        assert r["targetImgref"] == "ghcr.io/projectbluefin/utah:testing"
        assert r["composeFsBackend"] is False

    def test_composefs_live_iso_mode_keeps_local_imgref(self, tmp_path):
        sys_recipe = {
            "local_imgref": "containers-storage:ghcr.io/projectbluefin/dakota-nvidia:stable",
            "imgref": "ghcr.io/projectbluefin/dakota:stable",
        }
        path = Processor.gen_install_recipe("log", _auto_finals(image="ghcr.io/projectbluefin/dakota:stable", composefs=True, image_type="bootc"), sys_recipe)
        r = _load(path)
        assert r["image"] == "containers-storage:ghcr.io/projectbluefin/dakota-nvidia:stable"
        assert r["targetImgref"] == "ghcr.io/projectbluefin/dakota:stable"
        assert r["composeFsBackend"] is True

    def test_selects_disk(self, tmp_path):
        path = Processor.gen_install_recipe("log", _auto_finals(disk="/dev/nvme0n1"), _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/nvme0n1"

    def test_image_propagated(self):
        img = "ghcr.io/ublue-os/bluefin:stable"
        path = Processor.gen_install_recipe("log", _auto_finals(image=img), _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == img

    def test_target_imgref_no_docker_prefix(self):
        # Regression: targetImgref must be a bare reference, not docker://ghcr.io/...
        # If docker:// is prepended here, bootc stores it verbatim and subsequent
        # `bootc update` calls prepend it again → double prefix → broken updates.
        img = "ghcr.io/projectbluefin/dakota:latest"
        path = Processor.gen_install_recipe("log", _auto_finals(image=img), _SYS_RECIPE)
        r = _load(path)
        assert r["targetImgref"] == img
        assert not r["targetImgref"].startswith("docker://")

    def test_hostname_propagated(self):
        path = Processor.gen_install_recipe("log", _auto_finals(hostname="mybox"), _SYS_RECIPE)
        r = _load(path)
        assert r["hostname"] == "mybox"

    def test_flatpaks_propagated(self):
        flatpaks = ["org.mozilla.firefox", "org.gnome.Fractal"]
        path = Processor.gen_install_recipe("log", _auto_finals(flatpaks=flatpaks), _SYS_RECIPE)
        r = _load(path)
        assert r["flatpaks"] == flatpaks

    def test_fallback_hostname_from_sys_recipe(self):
        finals = [{"disk": {"auto": {"disk": "/dev/vda"}}, "selected_image": "ghcr.io/x:y",
                   "encryption": {"use_encryption": False}}]
        path = Processor.gen_install_recipe("log", finals, {"hostname": "fallback-host"})
        r = _load(path)
        assert r["hostname"] == "fallback-host"

    def test_fallback_hostname_default(self):
        """When no hostname is specified, a hardware-derived hostname is generated."""
        finals = [{"disk": {"auto": {"disk": "/dev/vda"}}, "selected_image": "ghcr.io/x:y",
                   "encryption": {"use_encryption": False}}]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        # Hardware-derived hostname: lowercase, contains hyphens, ends with 4-char hex suffix
        assert r["hostname"]  # non-empty
        assert r["hostname"] != "dakota"  # not the old hardcoded default
        import re
        assert re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", r["hostname"])


# ── Encryption tests ───────────────────────────────────────────────────────────

class TestEncryption:
    def test_no_encryption(self):
        path = Processor.gen_install_recipe(
            "log", _auto_finals(encryption={"use_encryption": False}), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "none"
        assert r["encryption"]["passphrase"] == ""

    def test_luks_passphrase(self):
        enc = {"use_encryption": True, "type": "luks-passphrase", "encryption_key": "s3cr3t"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "luks-passphrase"
        assert r["encryption"]["passphrase"] == "s3cr3t"

    def test_tpm2_luks(self):
        enc = {"use_encryption": True, "type": "tpm2-luks"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "tpm2-luks"

    def test_tpm2_luks_passphrase(self):
        enc = {"use_encryption": True, "type": "tpm2-luks-passphrase", "encryption_key": "pw"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "tpm2-luks-passphrase"
        assert r["encryption"]["passphrase"] == "pw"

    def test_key_without_explicit_type_defaults_to_luks_passphrase(self):
        enc = {"use_encryption": True, "encryption_key": "mykey"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "luks-passphrase"
        assert r["encryption"]["passphrase"] == "mykey"

    def test_no_key_and_no_type_defaults_to_tpm2(self):
        enc = {"use_encryption": True}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "tpm2-luks"


# ── Manual partitioning tests ──────────────────────────────────────────────────

class TestManualDisk:
    def _manual_finals(self, partitions: dict):
        return [{
            "disk": partitions,
            "selected_image": "ghcr.io/x:y",
            "hostname": "manualhost",
            "flatpaks": [],
            "encryption": {"use_encryption": False},
        }]

    def test_basic_manual_layout(self):
        partitions = {
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "ext4",  "mp": "/boot"},
            "/dev/sda3": {"fs": "xfs",   "mp": "/"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        assert "customMounts" in r
        mounts = {m["target"]: m for m in r["customMounts"]}
        assert mounts["/"]["partition"] == "/dev/sda3"
        assert mounts["/"]["fstype"] == "xfs"
        assert mounts["/boot/efi"]["partition"] == "/dev/sda1"
        assert mounts["/boot/efi"]["fstype"] == "fat32"
        assert mounts["/boot"]["partition"] == "/dev/sda2"
        assert mounts["/boot"]["fstype"] == "ext4"

    def test_manual_does_not_set_disk_field(self):
        partitions = {
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs",   "mp": "/"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        assert r.get("disk", "") == ""

    def test_unformatted_partition(self):
        partitions = {
            "/dev/sda1": {"fs": "unformatted", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs",         "mp": "/"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        mounts = {m["target"]: m for m in r["customMounts"]}
        assert mounts["/boot/efi"]["fstype"] == "unformatted"

    def test_swap_partition_included(self):
        partitions = {
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs",   "mp": "/"},
            "/dev/sda3": {"fs": "swap",  "mp": "swap"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        mounts = {m["target"]: m for m in r["customMounts"]}
        assert "swap" in mounts
        assert mounts["swap"]["partition"] == "/dev/sda3"

    def test_auto_takes_precedence_over_manual_check(self):
        """auto key means auto-partition, not manual."""
        finals = [{"disk": {"auto": {"disk": "/dev/sda"}}, "selected_image": "ghcr.io/x:y",
                   "hostname": "h", "encryption": {"use_encryption": False}}]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert "customMounts" not in r or not r.get("customMounts")
        assert r["disk"] == "/dev/sda"


# ── User spec tests ────────────────────────────────────────────────────────────

class TestSlurpSpec:
    def test_slurp_omitted_when_not_selected(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert "slurp" not in r

    def test_slurp_propagated(self):
        finals = _auto_finals()
        finals[0]["slurp"] = {
            "sourcePartition": "/dev/nvme0n1p3",
            "users": [
                {
                    "name": "JohnDoe",
                    "categories": ["Documents", "Pictures"],
                }
            ],
        }
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["slurp"] == finals[0]["slurp"]


class TestUserSpec:
    def test_user_propagated(self):
        user = {"username": "alice", "fullname": "Alice Smith", "password": "pass1",
                "groups": ["wheel"]}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["username"] == "alice"
        assert r["user"]["fullname"] == "Alice Smith"
        # Plaintext must never reach the recipe: fisherman would then hash it
        # itself via chpasswd's PAM path, which fails on composefs targets.
        assert r["user"]["password"] != "pass1"
        assert r["user"]["password"].startswith("$6$")
        assert r["user"]["groups"] == ["wheel"]

    def test_empty_user_when_not_provided(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["username"] == ""
        # No password requested: stays empty, not a hash of "" (fisherman
        # treats "" as "leave the account unset").
        assert r["user"]["password"] == ""

    def test_user_groups_default_empty(self):
        user = {"username": "bob", "password": "p"}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["groups"] == []

    def test_sys_recipe_groups_override_ui_groups(self):
        # An operator-pinned group list (e.g. an image without libvirt)
        # wins over the UI defaults.
        user = {"username": "bob", "password": "p",
                "groups": ["wheel", "docker", "incus-admin", "libvirt", "dialout"]}
        sys = {**_SYS_RECIPE, "user": {"groups": ["wheel", "dialout"]}}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), sys)
        r = _load(path)
        assert r["user"]["groups"] == ["wheel", "dialout"]

    def test_sys_recipe_without_groups_keeps_ui_groups(self):
        user = {"username": "bob", "password": "p", "groups": ["wheel"]}
        sys = {**_SYS_RECIPE, "user": {"username": "ignored"}}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), sys)
        r = _load(path)
        assert r["user"]["groups"] == ["wheel"]

    def test_already_hashed_password_passed_through(self):
        # A companion config may already supply a crypt(3) hash. Re-hashing
        # it would make the literal hash text the account's real password.
        prehashed = "$6$abcdsalt$" + "x" * 86
        user = {"username": "carol", "password": prehashed}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["password"] == prehashed


class TestHashUserPassword:
    """#79: the recipe carries a "$6$" hash, never the typed password."""

    def _verify(self, hashed, password):
        from bootc_installer.utils.sha512crypt import sha512_crypt
        parts = hashed.split("$")
        assert hashed.startswith("$6$") and len(parts) == 4, hashed
        assert sha512_crypt(password, parts[2]) == hashed

    def test_empty_password_untouched(self):
        from bootc_installer.utils.processor import _hash_user_password
        assert _hash_user_password("") == ""

    def test_plaintext_is_hashed_and_verifies(self):
        from bootc_installer.utils.processor import _hash_user_password
        self._verify(_hash_user_password("hunter2"), "hunter2")

    def test_a_typed_password_starting_with_dollar_is_hashed(self):
        """fisherman writes any "$"-prefixed value verbatim, so passing this
        through would leave an account nobody can log in to."""
        from bootc_installer.utils.processor import _hash_user_password
        for typed in ("$uperSecret", "$6$", "$6$salt$hash", "$y$j9T$salt$hash"):
            hashed = _hash_user_password(typed)
            assert hashed != typed
            self._verify(hashed, typed)

    def test_a_complete_crypt_hash_passes_through(self):
        from bootc_installer.utils.processor import _hash_user_password
        from bootc_installer.utils.sha512crypt import sha512_crypt
        for hashed in (sha512_crypt("x", "abcdsalt"),
                       "$6$rounds=10000$saltstringsaltst$OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHbbMCVNSnCM/UrjmM0Dp8vOuZeHBy/YTBmSK6H9qs/y3RnOaw5v.",
                       "$y$j9T$F5Jx5fExrKuPp53xLKQ..1$X3DX6M94c7o.9agCG9G317fhZg9SqC.5i5rd.RhAtQ7"):
            assert _hash_user_password(hashed) == hashed

    def test_newline_and_unicode_passwords_hash_in_full(self):
        from bootc_installer.utils.processor import _hash_user_password
        for pw in ("a\nb", "pässwörd 日本語 🙂"):
            self._verify(_hash_user_password(pw), pw)

    def test_two_calls_use_different_salts(self):
        from bootc_installer.utils.processor import _hash_user_password
        assert _hash_user_password("hunter2") != _hash_user_password("hunter2")

    def test_needs_neither_crypt_nor_openssl(self, monkeypatch):
        """The flatpak's Python (3.13+) has no `crypt`, and no openssl CLI is
        assumed."""
        import shutil
        monkeypatch.setitem(sys.modules, "crypt", None)
        monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
        from bootc_installer.utils.processor import _hash_user_password
        self._verify(_hash_user_password("hunter2"), "hunter2")


class TestSha512Crypt:
    """utils/sha512crypt.py against Drepper's published test vectors."""

    VECTORS = [
        ("Hello world!", "saltstring", None,
         "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"),
        ("Hello world!", "saltstringsaltstring", 10000,
         "$6$rounds=10000$saltstringsaltst$OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHbbMCVNSnCM/UrjmM0Dp8vOuZeHBy/YTBmSK6H9qs/y3RnOaw5v."),
        ("This is just a test", "toolongsaltstring", 5000,
         "$6$rounds=5000$toolongsaltstrin$lQ8jolhgVRVhY4b5pZKaysCLi0QBxGoNeKQzQ3glMhwllF7oGDZxUhx1yxdYcz/e1JSbq3y6JMxxl8audkUEm0"),
        ("a very much longer text to encrypt.  This one even stretches over morethan one line.",
         "anotherlongsaltstring", 1400,
         "$6$rounds=1400$anotherlongsalts$POfYwTEok97VWcjxIiSOjiykti.o/pQs.wPvMxQ6Fm7I6IoYN3CmLs66x9t0oSwbtEW7o7UmJEiDwGqd8p4ur1"),
        ("we have a short salt string but not a short password", "short", 77777,
         "$6$rounds=77777$short$WuQyW2YR.hBNpjjRhpYD/ifIw05xdfeEyQoMxIXbkvr0gge1a1x3yRULJ5CCaUeOxFmtlcGZelFl5CxtgfiAc0"),
        ("the minimum number is still observed", "roundstoolow", 10,
         "$6$rounds=1000$roundstoolow$kUMsbe306n21p9R.FRkW3IGn.S9NPN0x50YhH1xhLsPuWGsUSklZt58jaTfF4ZEQpyUNGc0dqbpBYYBaHHrsX."),
    ]

    @pytest.mark.parametrize("password,salt,rounds,want", VECTORS)
    def test_spec_vectors(self, password, salt, rounds, want):
        from bootc_installer.utils.sha512crypt import sha512_crypt
        assert sha512_crypt(password, salt, rounds) == want

    def test_matches_openssl_when_present(self):
        import shutil
        import subprocess as _subprocess
        if shutil.which("openssl") is None:
            pytest.skip("openssl not available")
        from bootc_installer.utils.sha512crypt import sha512_crypt
        for pw in ("correct horse", "$uperSecret", "pässwörd"):
            want = _subprocess.run(["openssl", "passwd", "-6", "-salt", "abcdefgh", "-stdin"],
                                   input=pw, capture_output=True, text=True, check=True).stdout.strip()
            assert sha512_crypt(pw, "abcdefgh") == want


class TestUnifiedStorage:
    def test_unified_storage_true_by_default(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r.get("unifiedStorage") is True

    def test_sys_recipe_can_disable_unified_storage(self):
        sys = {**_SYS_RECIPE, "unifiedStorage": False}
        path = Processor.gen_install_recipe("log", _auto_finals(), sys)
        r = _load(path)
        assert r.get("unifiedStorage") is False


# ── composefs + image_type tests ──────────────────────────────────────────────

class TestComposefs:
    def test_composefs_false_by_default(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r.get("composeFsBackend", False) is False

    def test_composefs_true_when_set(self):
        path = Processor.gen_install_recipe("log", _auto_finals(composefs=True), _SYS_RECIPE)
        r = _load(path)
        assert r["composeFsBackend"] is True

    def test_image_type_bootc_default(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        # bootc is the default — field may be omitted or set to "bootc"
        assert r.get("imageType", "bootc") == "bootc"

    def test_image_type_ostree(self):
        path = Processor.gen_install_recipe(
            "log", _auto_finals(image_type="ostree"), _SYS_RECIPE)
        r = _load(path)
        assert r.get("imageType") == "ostree"

    def test_bootloader_default_empty(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r.get("bootloader", "") == ""

    def test_bootloader_systemd_propagates(self):
        path = Processor.gen_install_recipe(
            "log", _auto_finals(bootloader="systemd"), _SYS_RECIPE)
        r = _load(path)
        assert r["bootloader"] == "systemd"

    def test_image_filesystem_overrides_disk_filesystem(self):
        # Even if disk step says xfs, if the image requires btrfs it wins.
        path = Processor.gen_install_recipe(
            "log", _auto_finals(fs="xfs", image_filesystem="btrfs"), _SYS_RECIPE)
        r = _load(path)
        assert r["filesystem"] == "btrfs"

    def test_image_filesystem_empty_does_not_override(self):
        path = Processor.gen_install_recipe(
            "log", _auto_finals(fs="xfs", image_filesystem=""), _SYS_RECIPE)
        r = _load(path)
        assert r["filesystem"] == "xfs"

    def test_disk_step_btrfs_selection(self):
        # When the disk step picks btrfs (user chose it from filesystem dropdown),
        # the recipe must reflect btrfs + subvolumes=True.
        path = Processor.gen_install_recipe(
            "log", _auto_finals(fs="btrfs"), _SYS_RECIPE)
        r = _load(path)
        assert r["filesystem"] == "btrfs"
        assert r["btrfsSubvolumes"] is True

    def test_disk_step_xfs_no_subvolumes(self):
        # XFS selection must never set btrfsSubvolumes=True.
        path = Processor.gen_install_recipe(
            "log", _auto_finals(fs="xfs"), _SYS_RECIPE)
        r = _load(path)
        assert r["filesystem"] == "xfs"
        assert r.get("btrfsSubvolumes", False) is False

    def test_dakota_recipe_fields(self):
        """Simulate a Dakota image selection producing the full expected recipe."""
        path = Processor.gen_install_recipe("log", _auto_finals(
            image="ghcr.io/projectbluefin/dakota:latest",
            composefs=True,
            bootloader="systemd",
            image_filesystem="btrfs",
            flatpak_var_path="state/os/default/var",
        ), _SYS_RECIPE)
        r = _load(path)
        assert r["composeFsBackend"] is True
        assert r["bootloader"] == "systemd"
        assert r["filesystem"] == "btrfs"
        assert r["flatpakVarPath"] == "state/os/default/var"

    def test_flatpak_var_path_absent_when_empty(self):
        """flatpakVarPath should be omitted from the recipe when not set."""
        path = Processor.gen_install_recipe("log", _auto_finals(
            flatpak_var_path="",
        ), _SYS_RECIPE)
        r = _load(path)
        assert "flatpakVarPath" not in r

    def test_flatpak_var_path_propagated(self):
        """flatpak_var_path from image metadata must appear in the recipe."""
        path = Processor.gen_install_recipe("log", _auto_finals(
            flatpak_var_path="state/os/default/var",
        ), _SYS_RECIPE)
        r = _load(path)
        assert r["flatpakVarPath"] == "state/os/default/var"


# ── Misc / edge cases ──────────────────────────────────────────────────────────

class TestMisc:
    def test_returns_the_recipe_not_a_path(self):
        recipe = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        assert isinstance(recipe, dict)

    def test_recipe_round_trips_as_json(self):
        recipe = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        assert json.loads(json.dumps(recipe)) == recipe

    def test_multiple_finals_dicts_merged(self):
        finals = [
            {"selected_image": "ghcr.io/x:y"},
            {"hostname": "mergedhost"},
            {"disk": {"auto": {"disk": "/dev/vda"}}},
            {"encryption": {"use_encryption": False}},
        ]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/x:y"
        assert r["hostname"] == "mergedhost"
        assert r["disk"] == "/dev/vda"

    def test_custom_image_url_overrides_selected(self):
        finals = [{
            "custom_image": "ghcr.io/custom/image:tag",
            "selected_image": "ghcr.io/x:y",
            "disk": {"auto": {"disk": "/dev/vda"}},
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/custom/image:tag"

    def test_sys_recipe_fallback_image(self):
        finals = [{"disk": {"auto": {"disk": "/dev/vda"}}, "hostname": "h",
                   "encryption": {"use_encryption": False}}]
        sys_recipe = {"imgref": "ghcr.io/sys/image:tag"}
        path = Processor.gen_install_recipe("log", finals, sys_recipe)
        r = _load(path)
        assert r["image"] == "ghcr.io/sys/image:tag"


class TestApplyIcon:
    """Regression tests for done.py apply_icon — no GTK required (uses mocks)."""

    @staticmethod
    def _get_apply_icon():
        """Import apply_icon with all gi dependencies stubbed out."""
        import sys
        import types
        from unittest.mock import MagicMock

        gi_stub = types.ModuleType("gi")
        repo_stub = types.ModuleType("gi.repository")
        gi_stub.repository = repo_stub
        gi_stub.require_version = lambda *a, **kw: None
        for name in ("Adw", "Gio", "GLib", "Gtk", "GObject"):
            setattr(repo_stub, name, MagicMock())

        mods_to_patch = {
            "gi": gi_stub,
            "gi.repository": repo_stub,
            "bootc_installer.widgets.page_header": MagicMock(),
        }
        with pytest.MonkeyPatch().context() as mp:
            for mod, stub in mods_to_patch.items():
                mp.setitem(sys.modules, mod, stub)
            # Remove cached module so we get a fresh import with stubs
            sys.modules.pop("bootc_installer.views.done", None)
            from bootc_installer.views.done import apply_icon
            # Keep module around so patching log works
            import bootc_installer.views.done as done_mod
        return apply_icon, done_mod

    def test_resource_uri_calls_set_from_resource(self):
        from unittest.mock import MagicMock
        apply_icon, _ = self._get_apply_icon()
        header = MagicMock()
        apply_icon(header, "resource:///org/bootcinstaller/Installer/images/dakota.png")
        header.set_from_resource.assert_called_once_with(
            "/org/bootcinstaller/Installer/images/dakota.png"
        )

    def test_icon_name_sets_icon_name(self):
        from unittest.mock import MagicMock
        apply_icon, _ = self._get_apply_icon()
        header = MagicMock()
        apply_icon(header, "object-select-symbolic")
        header.set_from_resource.assert_not_called()
        assert header.icon_name == "object-select-symbolic"

    def test_exception_is_logged_not_silenced(self):
        """apply_icon must log failures — not silently swallow them."""
        from unittest.mock import MagicMock, patch
        apply_icon, done_mod = self._get_apply_icon()
        header = MagicMock()
        header.set_from_resource.side_effect = Exception("resource not found")
        with patch.object(done_mod, "log") as mock_log:
            apply_icon(header, "resource:///org/bootcinstaller/Installer/images/missing.png")
            mock_log.warning.assert_called_once()


class TestVarDisk:
    """Tests for optional /var disk passthrough to recipe JSON."""

    def test_var_disk_absent_by_default(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert "varDisk" not in r

    def test_var_disk_format_fresh(self):
        finals = _auto_finals()
        finals[0]["var_disk"] = {"disk": "/dev/sdb", "keep_existing": False}
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["varDisk"] == {"disk": "/dev/sdb", "keepExisting": False}

    def test_var_disk_keep_existing(self):
        finals = _auto_finals()
        finals[0]["var_disk"] = {"disk": "/dev/sdb", "keep_existing": True}
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["varDisk"] == {"disk": "/dev/sdb", "keepExisting": True}

    def test_var_disk_empty_disk_omitted(self):
        finals = _auto_finals()
        finals[0]["var_disk"] = {"disk": "", "keep_existing": False}
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert "varDisk" not in r


# ── NVIDIA auto-detection tests ───────────────────────────────────────────────

class TestNvidiaAutoDetect:
    def test_nvidia_gpu_detected_uses_nvidia_image(self, monkeypatch):
        """When NVIDIA GPU is present, both image and targetImgref use nvidia."""
        monkeypatch.setattr(
            "bootc_installer.core.system.Systeminfo.has_nvidia_gpu",
            staticmethod(lambda: True),
        )
        finals = _auto_finals(image="ghcr.io/projectbluefin/dakota:latest")
        finals[0]["nvidia_imgref"] = "ghcr.io/projectbluefin/dakota-nvidia:latest"
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/projectbluefin/dakota-nvidia:latest"
        assert r["targetImgref"] == "ghcr.io/projectbluefin/dakota-nvidia:latest"

    def test_no_nvidia_gpu_installs_nvidia_tracks_base(self, monkeypatch):
        """Without NVIDIA GPU, install nvidia (on ISO) but track base for updates."""
        monkeypatch.setattr(
            "bootc_installer.core.system.Systeminfo.has_nvidia_gpu",
            staticmethod(lambda: False),
        )
        finals = _auto_finals(image="ghcr.io/projectbluefin/dakota:latest")
        finals[0]["nvidia_imgref"] = "ghcr.io/projectbluefin/dakota-nvidia:latest"
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/projectbluefin/dakota-nvidia:latest"
        assert r["targetImgref"] == "ghcr.io/projectbluefin/dakota:latest"

    def test_no_nvidia_imgref_skips_detection(self):
        """When nvidia_imgref is empty, no NVIDIA logic runs."""
        finals = _auto_finals(image="ghcr.io/tuna-os/yellowfin:gnome")
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/tuna-os/yellowfin:gnome"
        assert r["targetImgref"] == "ghcr.io/tuna-os/yellowfin:gnome"


# ── Hostname generation tests ─────────────────────────────────────────────────

class TestManualPartitionLayout:
    """Tests for manual partition mode (all keys start with /dev/)."""

    def _manual_finals(self, partitions, image="ghcr.io/t/img:latest", hostname="h"):
        return [{
            "disk": partitions,
            "selected_image": image,
            "hostname": hostname,
            "encryption": {"use_encryption": False},
        }]

    def test_custom_mounts_populated(self):
        finals = self._manual_finals({
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs", "mp": "/"},
        })
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert "customMounts" in r
        mounts = {m["partition"]: m for m in r["customMounts"]}
        assert mounts["/dev/sda1"]["target"] == "/boot/efi"
        assert mounts["/dev/sda2"]["fstype"] == "xfs"

    def test_partition_without_mountpoint_skipped(self):
        """Partitions with no mp= are silently skipped."""
        finals = self._manual_finals({
            "/dev/sda1": {"fs": "swap", "mp": ""},
            "/dev/sda2": {"fs": "xfs", "mp": "/"},
        })
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        mounts = r.get("customMounts", [])
        partitions = [m["partition"] for m in mounts]
        assert "/dev/sda1" not in partitions
        assert "/dev/sda2" in partitions

    def test_all_partitions_no_mountpoint_no_custom_mounts_key(self):
        """If every partition lacks a mountpoint, customMounts is omitted."""
        finals = self._manual_finals({
            "/dev/sda1": {"fs": "swap", "mp": ""},
        })
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert "customMounts" not in r


class TestDiskInfoVariants:
    """Tests for alternate disk_info shapes (dict with 'disk'/'device' key, plain string)."""

    def test_disk_key_in_dict(self):
        finals = [{
            "disk": {"disk": "/dev/nvme0n1", "filesystem": "xfs"},
            "selected_image": "ghcr.io/t/img:latest",
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/nvme0n1"

    def test_device_key_in_dict(self):
        finals = [{
            "disk": {"device": "/dev/sdb", "filesystem": "xfs"},
            "selected_image": "ghcr.io/t/img:latest",
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/sdb"

    def test_disk_as_plain_string(self):
        finals = [{
            "disk": "/dev/vda",
            "selected_image": "ghcr.io/t/img:latest",
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/vda"


class TestImageFallbackPaths:
    """Tests for image resolution from sys_recipe fallback paths."""

    def test_default_marked_image_used_when_no_selected(self):
        """When no image in finals, fall back to the default-marked entry in sys_recipe."""
        finals = [{
            "disk": {"auto": {"disk": "/dev/vda"}},
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        sys_recipe = {
            "images": [
                {"imgref": "ghcr.io/org/base:latest", "default": False},
                {"imgref": "ghcr.io/org/preferred:latest", "default": True},
            ]
        }
        path = Processor.gen_install_recipe("log", finals, sys_recipe)
        r = _load(path)
        assert r["image"] == "ghcr.io/org/preferred:latest"

    def test_first_image_used_when_none_default_marked(self):
        """If no entry is default-marked, use the first entry in sys_recipe images."""
        finals = [{
            "disk": {"auto": {"disk": "/dev/vda"}},
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        sys_recipe = {
            "images": [
                {"imgref": "ghcr.io/org/first:latest"},
                {"imgref": "ghcr.io/org/second:latest"},
            ]
        }
        path = Processor.gen_install_recipe("log", finals, sys_recipe)
        r = _load(path)
        assert r["image"] == "ghcr.io/org/first:latest"

    def test_local_imgref_overrides_install_source(self):
        """local_imgref in sys_recipe overrides the install image while target_imgref stays remote."""
        finals = _auto_finals(image="ghcr.io/org/image:latest")
        sys_recipe = {
            "imgref": "ghcr.io/org/image:latest",
            "local_imgref": "containers-storage:ghcr.io/org/image:latest",
        }
        path = Processor.gen_install_recipe("log", finals, sys_recipe)
        r = _load(path)
        assert r["image"] == "containers-storage:ghcr.io/org/image:latest"
        assert r["targetImgref"] == "ghcr.io/org/image:latest"

    def test_additional_image_stores_propagated(self):
        """additionalImageStores from sys_recipe passes through to the recipe."""
        finals = _auto_finals()
        sys_recipe = {"additionalImageStores": ["/run/media/iso/ostree/repo"]}
        path = Processor.gen_install_recipe("log", finals, sys_recipe)
        r = _load(path)
        assert r["additionalImageStores"] == ["/run/media/iso/ostree/repo"]

    def test_no_image_available_leaves_image_empty(self):
        """If finals and sys_recipe provide no image, recipe keeps empty image fields."""
        finals = [{
            "disk": {"auto": {"disk": "/dev/vda"}},
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        path = Processor.gen_install_recipe("log", finals, {})
        r = _load(path)
        assert r["image"] == ""
        assert r["targetImgref"] == ""
 
 
class TestHardwareHostname:
    def test_explicit_hostname_used(self):
        """User-provided hostname takes priority over hardware-derived."""
        finals = _auto_finals(hostname="my-workstation")
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["hostname"] == "my-workstation"

    def test_sys_recipe_hostname_used(self):
        """sys_recipe hostname used when no user hostname provided."""
        finals = _auto_finals(hostname="")
        path = Processor.gen_install_recipe("log", finals, {"hostname": "sys-host"})
        r = _load(path)
        assert r["hostname"] == "sys-host"

    def test_hardware_hostname_generated(self, monkeypatch):
        """When no hostname from user or sys_recipe, hardware hostname is used."""
        monkeypatch.setattr(
            "bootc_installer.core.system.Systeminfo.generate_hostname",
            staticmethod(lambda: "framework-13-a7c3"),
        )
        finals = _auto_finals(hostname="")
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["hostname"] == "framework-13-a7c3"


class TestFindNvidiaImgref:
    """Tests for _find_nvidia_imgref_for() — the manifest-walk helper."""

    def _inject_manifest(self, monkeypatch, manifest: dict):
        """Inject a fake _MANIFEST via sys.modules without importing the real image module."""
        import sys
        import types

        fake_image = types.ModuleType("bootc_installer.defaults.image")
        fake_image._MANIFEST = manifest
        monkeypatch.setitem(sys.modules, "bootc_installer.defaults.image", fake_image)

    def test_returns_empty_when_import_fails(self, monkeypatch):
        """If _MANIFEST cannot be imported, return empty string instead of crashing."""
        import sys
        import types

        # A module with no _MANIFEST attribute — accessing it raises AttributeError.
        broken = types.ModuleType("bootc_installer.defaults.image")
        monkeypatch.setitem(sys.modules, "bootc_installer.defaults.image", broken)

        from bootc_installer.utils.processor import _find_nvidia_imgref_for
        result = _find_nvidia_imgref_for("ghcr.io/org/anything:latest")
        assert result == ""

    def test_finds_direct_match(self, monkeypatch):
        """Returns nvidia_imgref when the imgref is a direct leaf node."""
        self._inject_manifest(monkeypatch, {
            "images": [
                {
                    "imgref": "ghcr.io/org/base:latest",
                    "nvidia_imgref": "ghcr.io/org/base-nvidia:latest",
                }
            ]
        })
        from bootc_installer.utils.processor import _find_nvidia_imgref_for
        result = _find_nvidia_imgref_for("ghcr.io/org/base:latest")
        assert result == "ghcr.io/org/base-nvidia:latest"

    def test_finds_nested_match(self, monkeypatch):
        """Returns inherited nvidia_imgref when imgref is inside a children list."""
        self._inject_manifest(monkeypatch, {
            "images": [
                {
                    "nvidia_imgref": "ghcr.io/org/group-nvidia:latest",
                    "children": [
                        {"imgref": "ghcr.io/org/child:latest"},
                    ],
                }
            ]
        })
        from bootc_installer.utils.processor import _find_nvidia_imgref_for
        result = _find_nvidia_imgref_for("ghcr.io/org/child:latest")
        assert result == "ghcr.io/org/group-nvidia:latest"

    def test_returns_empty_when_not_found(self, monkeypatch):
        """Returns empty string when imgref is absent from the manifest."""
        self._inject_manifest(monkeypatch, {
            "images": [{"imgref": "ghcr.io/org/other:latest"}]
        })
        from bootc_installer.utils.processor import _find_nvidia_imgref_for
        result = _find_nvidia_imgref_for("ghcr.io/org/missing:latest")
        assert result == ""


class TestNoRecipeFile:
    """The recipe holds the LUKS passphrase and the password hash; it goes to
    `fisherman -` on stdin and is never written to disk (fisherman#276)."""

    def test_no_file_is_written_in_or_out_of_a_flatpak(self, monkeypatch, tmp_path):
        import os as _os
        import tempfile as _tempfile
        import bootc_installer.utils.processor as proc_mod

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(_tempfile, "tempdir", str(tmp_path))
        for flatpak in (False, True):
            monkeypatch.setattr(_os.path, "exists", lambda p, f=flatpak: f and p == "/.flatpak-info")
            enc = {"use_encryption": True, "encryption_key": "s3cret"}
            recipe = proc_mod.Processor.gen_install_recipe(
                "log", _auto_finals(encryption=enc), _SYS_RECIPE)
            assert recipe["encryption"]["passphrase"] == "s3cret"
        assert list(tmp_path.rglob("*")) == []

    def test_the_module_cannot_write_a_temp_file(self):
        import bootc_installer.utils.processor as proc_mod
        assert not hasattr(proc_mod, "tempfile")


class TestAdditionalImageStores:
    """Left out, fisherman finds the host's offline stores itself; the
    frontend passes only what the ISO's recipe names."""

    def test_absent_unless_the_iso_recipe_names_stores(self):
        assert "additionalImageStores" not in _load(
            Processor.gen_install_recipe("log", _auto_finals(), {}))
        assert "additionalImageStores" not in _load(
            Processor.gen_install_recipe("log", _auto_finals(), {"additionalImageStores": []}))
        r = _load(Processor.gen_install_recipe(
            "log", _auto_finals(), {"additionalImageStores": ["/run/store"]}))
        assert r["additionalImageStores"] == ["/run/store"]


class TestLiveISOFallback:
    """Tests for the live-ISO images.json fallback in gen_install_recipe (lines 236-243)."""

    def test_filesystem_read_from_images_json(self, monkeypatch, tmp_path):
        """When merged has no image_filesystem and sys_recipe has no images key,
        gen_install_recipe reads /etc/bootc-installer/images.json for the filesystem."""
        import io
        import json as _json
        import bootc_installer.utils.processor as proc_mod

        images_json_content = _json.dumps({"images": [{"filesystem": "btrfs"}]})
        images_json_path = "/etc/bootc-installer/images.json"

        real_open = open

        def fake_open(path, *args, **kwargs):
            if path == images_json_path:
                return io.StringIO(images_json_content)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)
        # Ensure not in flatpak so path is /etc (not /run/host/etc)
        monkeypatch.setattr("os.path.exists", lambda p: False)

        # image_filesystem="" so the fallback branch is triggered
        finals = _auto_finals(image_filesystem="")
        path = proc_mod.Processor.gen_install_recipe("log", finals, {})
        r = _load(path)
        assert r["filesystem"] == "btrfs"

    def test_fallback_handles_missing_images_json(self, monkeypatch):
        """When images.json is absent, gen_install_recipe logs a warning and continues."""
        import bootc_installer.utils.processor as proc_mod

        monkeypatch.setattr("os.path.exists", lambda p: False)
        real_open = open

        def raise_for_images_json(path, *args, **kwargs):
            if "bootc-installer/images.json" in str(path):
                raise FileNotFoundError("no file")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", raise_for_images_json)

        finals = _auto_finals(image_filesystem="")
        # Should not raise — just log a warning
        path = proc_mod.Processor.gen_install_recipe("log", finals, {})
        assert path  # recipe file still written




class TestRecipeNamesDisk:
    """#154: the window refuses to start fisherman on a recipe with no disk."""

    def test_empty_disk_is_refused(self):
        for value in ("", "   ", None):
            assert not Processor.recipe_names_disk({"disk": value})

    def test_missing_disk_key_is_refused(self):
        assert not Processor.recipe_names_disk({})

    def test_unreadable_recipe_is_refused(self):
        assert not Processor.recipe_names_disk(None)
        assert not Processor.recipe_names_disk("not a recipe")

    def test_named_disk_is_accepted(self):
        assert Processor.recipe_names_disk({"disk": "/dev/nvme0n1"})

    def test_no_disk_finals_produce_a_refused_recipe(self):
        """The real path from #154: no partition recipe -> {"disk": {}} finals
        -> a generated recipe the guard must refuse."""
        finals = _auto_finals()
        assert finals[0]["disk"]["auto"]["disk"]  # a real disk, before the edit
        finals[0]["disk"] = {}
        recipe = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        assert recipe["disk"] == ""
        assert not Processor.recipe_names_disk(recipe)
        # and the same finals with the disk restored are accepted
        assert Processor.recipe_names_disk(Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE))


# ── distroID ───────────────────────────────────────────────────────────────────

class TestDistroID:
    """GNOME writes the branding id, like the other four frontends."""

    def test_distro_id_is_the_branding_id(self, monkeypatch, tmp_path):
        branding_file = tmp_path / "branding.json"
        branding_file.write_text(json.dumps({"id": "exampleos"}))
        monkeypatch.setenv("BOOTC_INSTALLER_BRANDING", str(branding_file))
        r = _load(Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE))
        assert r["distroID"] == "exampleos"

    def test_distro_id_follows_the_resolver(self, monkeypatch):
        from bootc_installer.utils import branding
        monkeypatch.setattr(branding, "resolve",
                            lambda *a, **k: branding.Branding(id="somedistro"))
        r = _load(Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE))
        assert r["distroID"] == "somedistro"
