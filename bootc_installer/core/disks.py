"""Disks for the wizard.

Which disks may be installed to, their size labels and models come from
`fisherman probe --json` (shared/probe/README.md), through Systeminfo.probe().
Nothing here filters or formats a disk: fisherman decides. What remains below
is partition-level detail the probe does not report (the manual partition
picker, the Windows-data scan).
"""

import json
import logging
import os
import subprocess

from . import fisherman_probe

logger = logging.getLogger("Installer::Disks")


class Diskutils:
    @staticmethod
    def pretty_size(size: int) -> str:
        """fisherman's size rule, for sizes the probe does not report."""
        return fisherman_probe.format_size(size)

    @staticmethod
    def separate_device_and_partn(part_dev: str) -> tuple[str, str | None]:
        info_json = subprocess.check_output(
            # An argument list, never a shell string: part_dev can come from
            # a recipe, and "/dev/sda1; rm -rf /" in a shell string is
            # a command (#163).
            ["lsblk", "--json", "-o", "NAME,PKNAME,PARTN", part_dev],
        ).decode("utf-8")
        info_multiple = json.loads(info_json)["blockdevices"]

        if len(info_multiple) > 1:
            raise ValueError(f"{part_dev} returned more than one device")
        info = info_multiple[0]

        if info["partn"] is None:
            # part_dev is actually a device, not a partition
            return "/dev/" + info["name"], None

        return "/dev/" + info["pkname"], str(info["partn"])

    @staticmethod
    def fetch_lvm_pvs() -> list[list[str]]:
        try:
            output_json = subprocess.check_output(
                ["sudo", "pvs", "--reportformat=json"], stderr=subprocess.DEVNULL
            ).decode("utf-8")
            output_pvs = json.loads(output_json)["report"][0]["pv"]
            pv_with_vgs = []
            for pv_output in output_pvs:
                pv_name = pv_output["pv_name"]
                vg_name = pv_output["vg_name"] if pv_output["vg_name"] != "" else None
                pv_with_vgs.append([pv_name, vg_name])
            return pv_with_vgs
        except Exception as e:
            logger.warning(f"Could not enumerate LVM PVs (safe to ignore in Flatpak): {e}")
            return []


class Disk:
    """One eligible disk from the probe. Read-only; the probe is the source."""

    def __init__(self, probed: dict):
        self.__probed = probed
        self.__partitions = None

    @property
    def disk(self) -> str:
        return self.__probed.get("path", "")

    @property
    def name(self) -> str:
        return os.path.basename(self.disk)

    @property
    def size(self) -> int:
        return int(self.__probed.get("size_bytes") or 0)

    @property
    def pretty_size(self) -> str:
        return self.__probed.get("size_label", "")

    @property
    def model(self) -> str:
        return self.__probed.get("model", "")

    @property
    def transport_label(self) -> str:
        return self.__probed.get("transport_label", "")

    @property
    def display_name(self) -> str:
        return fisherman_probe.disk_title(self.__probed)

    @property
    def is_removable(self) -> bool:
        return bool(self.__probed.get("removable"))

    @property
    def block(self):
        return f"/sys/block/{self.name}"

    @property
    def partitions(self):
        if self.__partitions is None:
            self.update_partitions()
        return self.__partitions

    def update_partitions(self):
        try:
            entries = os.listdir(self.block)
        except OSError:
            entries = []
        self.__partitions = [Partition(self.name, p) for p in entries if p.startswith(self.name)]

    def get_partition(self, mountpoint: str):
        for partition in self.partitions:
            if partition.mountpoint == mountpoint:
                return partition


class Partition:
    def __init__(self, disk: str, partition: str):
        self.__disk = disk
        self.__partition = partition
        self.__mountpoint = self.__get_mountpoint()
        self.__size = self.__get_size()
        self.__fs_type = self.__get_fs_type()
        self.__uuid = self.__get_uuid()
        self.__label = self.__get_label()

    def __get_mountpoint(self):
        try:
            return (
                subprocess.check_output(["findmnt", "-n", "-o", "TARGET", self.partition])
                .decode("utf-8")
                .strip()
            )
        except subprocess.CalledProcessError:
            return None

    def __get_size(self):
        return int(open(f"{self.block}/size").read().strip()) * 512

    def __get_fs_type(self):
        try:
            return (
                subprocess.check_output(["lsblk", "-d", "-n", "-o", "FSTYPE", self.partition])
                .decode("utf-8")
                .strip()
            )
        except subprocess.CalledProcessError:
            return None

    def __get_uuid(self):
        try:
            return (
                subprocess.check_output(["lsblk", "-d", "-n", "-o", "UUID", self.partition])
                .decode("utf-8")
                .strip()
            )
        except subprocess.CalledProcessError:
            return None

    def __get_label(self):
        try:
            return (
                subprocess.check_output(["findmnt", "-n", "-o", "LABEL", self.partition])
                .decode("utf-8")
                .strip()
            )
        except subprocess.CalledProcessError:
            return None

    @property
    def partition(self):
        return f"/dev/{self.__partition}"

    @property
    def block(self):
        return f"/sys/block/{self.__disk}/{self.__partition}"

    @property
    def mountpoint(self):
        return self.__mountpoint

    @property
    def size(self):
        return self.__size

    @property
    def pretty_size(self):
        return Diskutils.pretty_size(self.size)

    @property
    def fs_type(self):
        return self.__fs_type

    @property
    def uuid(self):
        return self.__uuid

    @property
    def label(self):
        return self.__label

    def __lt__(self, other):
        return self.partition < other.partition

    def __eq__(self, other):
        if not other:
            return False
        return self.uuid == other.uuid and self.fs_type == other.fs_type


class DisksManager:
    """The disks fisherman offers, in fisherman's order.

    No filter here: zram, the live USB, optical drives and too-small disks
    are already excluded by the probe, and removable disks are offered
    (shared/probe/README.md). When the probe failed there are no disks and
    `error` says why; there is no fallback scan.
    """

    def __init__(self, probe_result=None):
        if probe_result is None:
            from bootc_installer.core.system import Systeminfo

            probe_result = Systeminfo.probe()
            self.__error = Systeminfo.probe_error() if probe_result is None else None
        else:
            self.__error = None
        self.__disks = [
            Disk(d) for d in fisherman_probe.eligible_disks(probe_result or {})
        ]

    @property
    def error(self) -> str | None:
        return self.__error

    def all_disks(self):
        return list(self.__disks)

    def get_disk(self, path: str):
        for disk in self.__disks:
            if disk.disk == path:
                return disk
        return None
