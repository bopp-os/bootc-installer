"""Pure construction helpers for the disk wizard's installer payload."""


def build_auto_partition_recipe(disk) -> dict:
    """Return the automatic-partition recipe for a selected disk."""
    return {
        "auto": {
            "disk": disk.disk,
            "pretty_size": disk.pretty_size,
            "size": disk.size,
            # For the confirm page only (Processor reads "disk"): the model
            # names the physical disk that is about to be erased.
            "model": getattr(disk, "model", "") or "",
            "vgs_to_remove": [],
            "pvs_to_remove": [],
        }
    }


def build_disk_finals(
    partition_recipe: dict | None,
    filesystem: str,
    hostname: str,
    *,
    virtual_disk: tuple[str, str | None] | None = None,
    var_disk: tuple[str, bool] | None = None,
) -> dict:
    """Build the disk step result without depending on GTK widget state."""
    disk = dict(partition_recipe) if partition_recipe else {}
    if "auto" in disk:
        disk["filesystem"] = filesystem
        disk["btrfsSubvolumes"] = filesystem == "btrfs"

    result = {"disk": disk, "hostname": hostname.strip()}
    if virtual_disk is not None:
        result["virtual_disk_img"], result["virtual_disk_loop"] = virtual_disk
    if var_disk is not None:
        result["var_disk"] = {
            "disk": var_disk[0],
            "keep_existing": var_disk[1],
        }
    return result


def apply_keep_files(disk_finals: dict, existing_install: dict | None, passphrase: str) -> dict:
    """Mark the disk step's auto layout as a keep-files reinstall over existing_install.

    The Processor turns the marks into fisherman's keepFiles and the unlock passphrase; the
    encryption step's own choice is then ignored (the container is kept as it is).
    """
    disk = disk_finals.get("disk") or {}
    if "auto" not in disk or not existing_install:
        return disk_finals
    disk["auto"]["keep_files"] = True
    disk["auto"]["keep_files_encrypted"] = bool(existing_install.get("encrypted"))
    disk["auto"]["keep_files_passphrase"] = passphrase if existing_install.get("encrypted") else ""
    return disk_finals
