# processor.py
#
# Copyright 2024 BootcOS contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation at version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import os
import re

from bootc_installer.utils import branding
from bootc_installer.utils.sha512crypt import sha512_crypt

logger = logging.getLogger("Installer::Processor")


# A complete crypt(3) hash: $id$[rounds=N$]salt$hash, with the alphabet and
# lengths crypt uses. Only this is passed through unhashed. A bare "$"
# prefix is not enough: fisherman writes any "$"-prefixed password verbatim
# with `chpasswd -e`, so a user who typed "$uperSecret" got an account whose
# password field was that literal string, and could never log in.
_CRYPT_HASH_RE = re.compile(
    r"^\$(?:1|5|6)\$(?:rounds=\d+\$)?[./0-9A-Za-z]{1,16}\$[./0-9A-Za-z]{22,86}$"
    r"|^\$(?:y|gy|7)\$[./0-9A-Za-z]+\$[./0-9A-Za-z]+\$[./0-9A-Za-z]{43}$"
)


def _hash_user_password(password: str) -> str:
    """Hash a plaintext user password as a "$6$" crypt string.

    fisherman writes a "$"-prefixed password verbatim via `chpasswd -e`.
    Passing plaintext through forces fisherman to hash it itself via
    `chpasswd` without -e, which invokes the target's PAM stack to do so.
    On a composefs-native deploy fisherman only has `chpasswd --root <dir>`
    (no real chroot), so PAM module resolution fails against the target and
    the install aborts ("pam_chauthtok() failed", or plain "exit status 1"
    on EL10). Hashing here means fisherman never invokes PAM at all (#79).

    Hashed in plain Python (utils/sha512crypt.py): the flatpak's Python no
    longer has the `crypt` module, and an `openssl` CLI is not guaranteed.

    A complete crypt hash is returned unchanged, so a config that already
    carries one is not hashed twice. Empty input is returned unchanged:
    fisherman treats "" as "leave the account unset".
    """
    if not password or _CRYPT_HASH_RE.match(password):
        return password
    return sha512_crypt(password)


def _find_nvidia_imgref_for(imgref: str) -> str:
    """Search the image manifest for a nvidia_imgref associated with imgref.

    Walks the manifest tree (inherited from parent nodes) looking for the node
    whose imgref matches, then returns its nvidia_imgref field if present.
    Returns empty string if not found.
    """
    try:
        from bootc_installer.defaults.image import _MANIFEST
        tree = _MANIFEST.get("images", [])
    except Exception:
        return ""

    def _search(nodes, nvidia_ctx=""):
        for node in nodes:
            node_nvidia = node.get("nvidia_imgref", nvidia_ctx)
            if node.get("imgref") == imgref:
                return node_nvidia
            children = node.get("children", [])
            if children:
                result = _search(children, node_nvidia)
                if result:
                    return result
        return ""

    return _search(tree)


class Processor:
    @staticmethod
    def recipe_names_disk(recipe: dict) -> bool:
        """Whether the fisherman recipe names a target disk.

        The window checks this before starting fisherman: a recipe with an
        empty disk only fails inside fisherman, as "invalid recipe: disk is
        required", which a user cannot act on (#154).
        """
        try:
            return bool(str(recipe.get("disk") or "").strip())
        except AttributeError:
            return False

    @staticmethod
    def gen_install_recipe(log_path: str, finals: list, sys_recipe: dict) -> dict:
        """Generate a fisherman recipe JSON from the UI's collected finals.

        Args:
            log_path: path for the installation log (unused by fisherman, kept for API compat)
            finals: list of dicts collected from each installer step's get_finals()
            sys_recipe: the loaded system recipe (from /etc/bootcos-installer/recipe.json)

        Returns:
            The fisherman recipe. The caller hands it to fisherman on stdin
            (`fisherman -`); it is never written to a file, because it holds
            the LUKS passphrase and the user's password hash.
        """
        # Merge all finals dicts into one flat dict
        merged = {}
        for step_finals in finals:
            if isinstance(step_finals, dict):
                merged.update(step_finals)

        logger.info(f"Building fisherman recipe from finals: {list(merged.keys())}")

        # --- Disk ---
        # disk_info comes from BootcDefaultDisk.get_finals() as one of:
        #   Auto:   {"auto": {"disk": "/dev/vda", ...}}
        #   Manual: {"/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"}, "/dev/sda2": {...}, ...}
        disk_info = merged.get("disk", {})
        disk_device = ""
        filesystem = "xfs"
        btrfs_subvolumes = False
        custom_mounts = []

        is_manual = (
            isinstance(disk_info, dict)
            and disk_info
            and all(k.startswith("/dev/") for k in disk_info)
        )

        if is_manual:
            for partition, spec in disk_info.items():
                fstype = spec.get("fs", "unformatted") or "unformatted"
                mountpoint = spec.get("mp", "")
                if not mountpoint:
                    continue
                custom_mounts.append({
                    "partition": partition,
                    "target": mountpoint,
                    "fstype": fstype,
                })
            logger.info(f"Manual partition layout: {len(custom_mounts)} mounts")
        elif isinstance(disk_info, dict):
            if "auto" in disk_info:
                disk_device = disk_info["auto"].get("disk", "")
            elif "disk" in disk_info:
                disk_device = disk_info["disk"]
            elif "device" in disk_info:
                disk_device = disk_info["device"]
            fs = disk_info.get("filesystem", "xfs")
            if fs in ("xfs", "btrfs"):
                filesystem = fs
            if filesystem == "btrfs":
                btrfs_subvolumes = disk_info.get("btrfsSubvolumes", False)
        elif isinstance(disk_info, str):
            disk_device = disk_info

        logger.info(f"Selected disk: {disk_device}, filesystem: {filesystem}")

        # --- Encryption ---
        enc_info = merged.get("encryption", {})
        encryption_type = "none"
        encryption_passphrase = ""

        if isinstance(enc_info, dict):
            use_enc = enc_info.get("use_encryption", False)
            if use_enc:
                key = enc_info.get("encryption_key", "")
                explicit_type = enc_info.get("type", "")
                if explicit_type in ("luks-passphrase", "tpm2-luks-passphrase", "tpm2-luks"):
                    encryption_type = explicit_type
                    encryption_passphrase = key
                elif key:
                    encryption_type = "luks-passphrase"
                    encryption_passphrase = key
                else:
                    encryption_type = "tpm2-luks"

        # --- Image / OCI ref ---
        # In Flatpak mode: finals contain "selected_image" or "custom_image" from the UI.
        # In live ISO mode: the image step is skipped; recipe["imgref"] holds the remote
        # tracking ref and optional "local_imgref" holds the install source override.
        image = merged.get("custom_image", "") or merged.get("selected_image", "")
        if not image:
            image = sys_recipe.get("imgref", "")
        if not image:
            # Fall back to first default-marked image in the recipe images list
            for img in sys_recipe.get("images", []):
                if img.get("default", False):
                    image = img.get("imgref", "")
                    break
        if not image and sys_recipe.get("images"):
            image = sys_recipe["images"][0].get("imgref", "")
        if not image:
            logger.warning("No image/imgref found in finals or sys_recipe!")

        # target_imgref is always the remote registry reference written into the
        # installed system so that bootc upgrade tracks the correct upstream image.
        target_imgref = image

        # NVIDIA auto-detection: if the selected image has a nvidia_imgref in the
        # manifest, use the nvidia image as the install source (it's on the ISO)
        # and set targetImgref based on whether NVIDIA hardware is present.
        nvidia_imgref = merged.get("nvidia_imgref", "")
        if not nvidia_imgref:
            nvidia_imgref = _find_nvidia_imgref_for(image)
        if nvidia_imgref:
            from bootc_installer.core.system import Systeminfo
            if Systeminfo.has_nvidia_gpu():
                # NVIDIA present: install nvidia, track nvidia for updates
                image = nvidia_imgref
                target_imgref = nvidia_imgref
                logger.info(f"NVIDIA GPU detected: using {nvidia_imgref} for install and updates")
            else:
                # No NVIDIA: install nvidia (it's on the ISO), but track the base image
                # so bootc rebases to the lighter image on first update
                target_imgref = image  # base (non-nvidia) imgref
                image = nvidia_imgref  # install from the nvidia image on the ISO
                logger.info(
                    f"No NVIDIA GPU: installing {nvidia_imgref} (from ISO), "
                    f"tracking {target_imgref} for updates"
                )

        # local_imgref (live ISO only) is an optional install *source* override — e.g.
        # "containers-storage:ghcr.io/org/image:tag" for offline installs from a
        # pre-populated squashfs.  It is passed to fisherman as --source-imgref while
        # target_imgref (the remote ref) is passed as --target-imgref unchanged.
        local_imgref = sys_recipe.get("local_imgref", "")
        if local_imgref:
            logger.info(
                f"local_imgref override: install source={local_imgref}, "
                f"installed system tracks={target_imgref}"
            )
            image = local_imgref

        # --- Hostname ---
        # Use hardware-derived hostname if no explicit hostname was set by the user.
        hostname = merged.get("hostname", "")
        if not hostname:
            hostname = sys_recipe.get("hostname", "")
        if not hostname:
            from bootc_installer.core.system import Systeminfo
            hostname = Systeminfo.generate_hostname()

        # --- Flatpaks ---
        flatpaks = merged.get("flatpaks", [])

        # --- SELinux / unified storage / composefs / image type ---
        selinux_disabled = sys_recipe.get("selinuxDisabled", False)
        unified_storage = sys_recipe.get("unifiedStorage", True)
        composefs_backend = bool(merged.get("composefs_backend", False))
        image_type = merged.get("image_type", "bootc") or "bootc"
        bootloader = merged.get("bootloader", "") or ""
        image_filesystem = merged.get("image_filesystem", "") or ""
        flatpak_var_path = merged.get("flatpak_var_path", "") or ""

        # Live ISO mode or removed image step: image-level fields are missing
        # from merged. Check sys_recipe["images"] list first (handles dev mode
        # and dakota-style recipes where the image step is removed), then fall
        # back to /etc/bootc-installer/images.json on the host.
        if not image_filesystem:
            _recipe_images = sys_recipe.get("images", [])
            if _recipe_images:
                _img = _recipe_images[0]
                image_filesystem  = _img.get("filesystem", "") or ""
                composefs_backend = bool(_img.get("composefs", composefs_backend))
                bootloader        = _img.get("bootloader", bootloader) or bootloader
                flatpak_var_path  = _img.get("flatpak_var_path", flatpak_var_path) or flatpak_var_path
                logger.info("Recipe images fallback: filesystem=%s composefs=%s bootloader=%s",
                            image_filesystem, composefs_backend, bootloader)
            else:
                _in_flatpak = os.path.exists("/.flatpak-info")
                _etc = "/run/host/etc" if _in_flatpak else "/etc"
                _images_json = f"{_etc}/bootc-installer/images.json"
                try:
                    with open(_images_json) as _f:
                        _idata = json.load(_f)
                    _imgs = _idata.get("images", [_idata]) if "images" in _idata else [_idata]
                    _img = _imgs[0]
                    image_filesystem  = _img.get("filesystem", "") or ""
                    composefs_backend = bool(_img.get("composefs", composefs_backend))
                    bootloader        = _img.get("bootloader", bootloader) or bootloader
                    flatpak_var_path  = _img.get("flatpak_var_path", flatpak_var_path) or flatpak_var_path
                    logger.info("Live ISO fallback from images.json: filesystem=%s composefs=%s bootloader=%s",
                                image_filesystem, composefs_backend, bootloader)
                except Exception as _e:
                    logger.warning("Live ISO: could not read %s: %s", _images_json, _e)

        # Image-level filesystem requirement overrides the disk-step selection.
        if image_filesystem in ("xfs", "btrfs"):
            filesystem = image_filesystem
            if filesystem == "btrfs":
                btrfs_subvolumes = disk_info.get("btrfsSubvolumes", False) if isinstance(disk_info, dict) else False

        # --- User account ---
        user_info = merged.get("user", {})
        user_username = user_info.get("username", "")
        user_fullname = user_info.get("fullname", "")
        user_password = _hash_user_password(user_info.get("password", ""))
        user_groups   = user_info.get("groups", [])
        # A live-ISO builder may pin the supplementary groups in
        # /etc/bootc-installer/recipe.json (e.g. an image without
        # libvirt/docker): an explicit operator list wins over the UI
        # defaults, which target a generic image.
        sys_user = sys_recipe.get("user", {})
        if isinstance(sys_user, dict) and isinstance(sys_user.get("groups"), list):
            user_groups = sys_user["groups"]
            logger.info("User groups overridden from system recipe: %s", user_groups)

        # For non-composefs (ostree/bootcDirect) live ISO installs, fisherman
        # expects an empty "image" and populated "targetImgref" so that it invokes
        # bootc install directly against host storage without containerized scratch export.
        fisherman_image = image
        # When the live ISO recipe explicitly sets image="" for non-composefs (bootcDirect),
        # honor the empty image so fisherman invokes host-direct bootc install.
        if not composefs_backend and image_type == "bootc" and sys_recipe.get("image") == "":
            fisherman_image = ""

        # Build the fisherman recipe
        recipe = {
            "disk": disk_device,
            "filesystem": filesystem,
            "btrfsSubvolumes": btrfs_subvolumes,
            "encryption": {
                "type": encryption_type,
                "passphrase": encryption_passphrase,
            },
            "image": fisherman_image,
            "targetImgref": target_imgref,
            "selinuxDisabled": selinux_disabled,
            "unifiedStorage": unified_storage,
            "composeFsBackend": composefs_backend,
            "bootloader": bootloader,
            "hostname": hostname,
            # fisherman names the OEM paths and services after this
            # (/etc/<distroID>/oem/). It is the branding id, like every
            # other frontend; with nothing branded it is os-release's ID.
            "distroID": branding.resolve().id,
            "flatpaks": flatpaks,
            "user": {
                "username": user_username,
                "fullname": user_fullname,
                "password": user_password,
                "groups": user_groups,
            },
        }
        if custom_mounts:
            recipe["customMounts"] = custom_mounts
        if image_type and image_type != "bootc":
            recipe["imageType"] = image_type
        if flatpak_var_path:
            recipe["flatpakVarPath"] = flatpak_var_path
        if "slurp" in merged and merged["slurp"] is not None:
            recipe["slurp"] = merged["slurp"]
        # Easter egg: always attempt to rescue wallpapers from existing Windows installs
        recipe["slurpWallpapers"] = True
        # Offline image stores: only when the ISO's recipe names them. Left
        # out, fisherman exposes the stores it finds on the host itself
        # (tuna-os/fisherman#276); [] would turn that off.
        additional_stores = sys_recipe.get("additionalImageStores")
        if additional_stores:
            recipe["additionalImageStores"] = additional_stores
        var_disk = merged.get("var_disk")
        if var_disk and var_disk.get("disk"):
            recipe["varDisk"] = {
                "disk": var_disk["disk"],
                "keepExisting": bool(var_disk.get("keep_existing", False)),
            }

        logger.info(f"Generated fisherman recipe: disk={disk_device}, image={image}, encryption={encryption_type}")

        return recipe
