"""Keep my files: the disk step's marks (disk_plan.apply_keep_files) and the probe's existing_install."""

from bootc_installer.core.disks import Disk
from bootc_installer.defaults.disk_plan import apply_keep_files, build_disk_finals

EXISTING = {"root": "/dev/nvme0n1p2", "encrypted": True, "efi": "/dev/nvme0n1p1"}


def _auto():
    return {"auto": {"disk": "/dev/nvme0n1", "pretty_size": "1 TB", "size": 1, "vgs_to_remove": [], "pvs_to_remove": []}}


def test_marks_the_auto_layout():
    finals = apply_keep_files(build_disk_finals(_auto(), "xfs", "deck"), EXISTING, "pw")
    auto = finals["disk"]["auto"]
    assert auto["keep_files"] is True
    assert auto["keep_files_encrypted"] is True
    assert auto["keep_files_passphrase"] == "pw"


def test_plain_install_carries_no_password():
    finals = apply_keep_files(build_disk_finals(_auto(), "xfs", "deck"), dict(EXISTING, encrypted=False), "typed")
    assert finals["disk"]["auto"]["keep_files_passphrase"] == ""


def test_nothing_to_keep_changes_nothing():
    finals = build_disk_finals(_auto(), "xfs", "deck")
    assert "keep_files" not in apply_keep_files(finals, None, "pw")["disk"]["auto"]
    manual = build_disk_finals({"/dev/sda1": {"fs": "ext4", "mp": "/"}}, "xfs", "deck")
    assert apply_keep_files(manual, EXISTING, "pw") == manual


def test_disk_exposes_the_probed_install():
    assert Disk({"path": "/dev/nvme0n1", "existing_install": EXISTING}).existing_install == EXISTING
    assert Disk({"path": "/dev/sda"}).existing_install is None
    assert Disk({"path": "/dev/sda", "existing_install": {"root": ""}}).existing_install is None
