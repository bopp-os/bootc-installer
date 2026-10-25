# How an install works

The installer has two parts:

| Part | Language | Job |
|---|---|---|
| `bootc_installer/` | Python, GTK4 and libadwaita | The wizard. It collects your choices and writes a JSON recipe. |
| `fisherman/` | Go | The backend. It reads the recipe and writes the OS to the disk. It runs as root. |

`fisherman` is a git submodule.
Its source is in [tuna-os/fisherman](https://github.com/tuna-os/fisherman).

## Two boot stacks

| Stack | Images | Bootloader | Root file system | Layout |
|---|---|---|---|---|
| **systemd-boot** | [Dakota](https://github.com/projectbluefin/dakota) | systemd-boot and UKI | btrfs and composefs | 2 partitions: EFI and root |
| **GRUB2** | Bluefin, Bluefin-LTS, Bazzite | GRUB2 | XFS or btrfs | 3 partitions: EFI, `/boot` and root |

The installer selects the stack from two recipe fields: `bootloader` and `composeFsBackend`.
You do not have to do more steps.

### Dakota

Dakota is the next Project Bluefin variant.
It uses a sealed image.
The installer does these steps differently for Dakota:

- It uses systemd-boot with a UKI (Unified Kernel Image).
- It gives `--composefs-backend` to bootc.
- It formats the root partition as btrfs.
- It makes 2 partitions: an EFI partition of 1 GiB in FAT32, and a root partition.
- It sets the GPT type of the root partition to the GUID for an x86-64 Linux root. Thus systemd-boot finds the root with no more configuration.
- It does not make a user account. Dakota has its own setup at first boot.

The recipe fields for Dakota are `"bootloader": "systemd"` and `"composeFsBackend": true`.

## The nine install steps

fisherman does these steps from the recipe:

1. **Partition.** The layout comes from the boot stack:
   - systemd-boot: 2 GPT partitions, EFI (1 GiB FAT32) and root. systemd-boot can read the EFI partition in FAT32, so there is no `/boot` partition.
   - GRUB2: 3 GPT partitions, EFI (FAT32), `/boot` (ext4) and root. GRUB cannot read new XFS features (`nrext64`, `exchange`, `rmapbt`). Also, `bootupctl` must find the `/boot` UUID on a raw block device, not on a LUKS mapper device.
2. **Format.** fisherman formats the EFI partition with `mkfs.fat -F32`. For GRUB2 images, it also formats `/boot` with `mkfs.ext4`.
3. **Encrypt.** This step is optional. fisherman runs `cryptsetup luksFormat` and `luksOpen`.
4. **Format root.** fisherman runs `mkfs.xfs` or `mkfs.btrfs`. With btrfs, it can also make named subvolumes.
5. **Mount.** fisherman mounts all partitions under `/mnt/fisherman-target`.
6. **Install with bootc.** fisherman runs `bootc install to-filesystem --skip-finalize` in a privileged podman container. The `--skip-finalize` flag keeps the target writable for the next steps.
7. **Post-install.** fisherman sets the hostname and copies the Flatpaks. It also does the first-boot tasks below.
8. **Windows data.** fisherman does this step only when the recipe asks for it. This installer never asks. Windows data migration is the job of [wootc](https://github.com/tuna-os/wootc).
9. **Finalize.** fisherman runs `fstrim`, mounts the root read-only, then runs `fsfreeze` and `fsthaw`. This does the work of `bootc install finalize`, which does nothing upstream at this time.

> **Scratch space:** fisherman keeps OCI blobs in `/var/fisherman-tmp` while it pulls an image.
> This directory is on the disk, and fisherman bind-mounts it to `/var/tmp`.
> Do not move the scratch space to `/run`. `/run` is a tmpfs with a limit of about half the RAM, and large images do not fit.

## Encryption

| Mode | What you get |
|---|---|
| `none` | No encryption. |
| `luks-passphrase` | LUKS2 with your passphrase. |
| `tpm2-luks` | LUKS2. The TPM2 unlocks the disk at boot, so there is no passphrase prompt. |
| `tpm2-luks-passphrase` | LUKS2. The TPM2 unlocks the disk, and a passphrase is the fallback. The installer shows a recovery key, and you must confirm it before you continue. |

## Fast first boot

fisherman does these tasks during each install.
You do not have to do anything.

| Task | What it does |
|---|---|
| **Bluetooth** | Copies `/var/lib/bluetooth` to the new OS. Paired devices connect again at first boot. |
| **Wi-Fi** | Copies the NetworkManager `.nmconnection` files. Saved networks connect again at first boot. |
| **Audio names** | Adds WirePlumber rules that give ALSA devices names that people can read. The rules also hide S/PDIF and Pro Audio sinks. |
| **Live audio** | Applies the same audio rules to the live session immediately. |
| **OEM hardware** | Finds ASUS, Framework and TUXEDO hardware. Then it adds the correct brew packages for first boot. |
| **Caches** | Makes the font, icon, pixbuf, GIO, ldconfig, man-db and Flatpak caches before first boot. Without this step, first boot is 30 seconds slower or more. |
| **Printers** | Enables `cups-browsed`, `avahi-daemon` and `ipp-usb`. USB printers and AirPrint work immediately. |

## Windows data

This installer does not copy data from Windows.
It erases the whole target disk.
To keep Windows and move your files into the new system, use [wootc](https://github.com/tuna-os/wootc).

## Phone companion

The installer starts a local HTTPS server on port 8443 with a self-signed certificate.
It shows a QR code.
When you scan the code, your phone opens a form.
Type your account data and settings there.
The phone sends the data as JSON, and the installer adds it to the recipe.

## Video during the install

The progress screen plays an AV1 or VP9 video.
A distribution can put its own video at `/etc/bootc-installer/install-video.webm`.
The installer first makes sure that GStreamer has the codecs.
If the codecs are not available, it shows a static progress screen.

## Offline install from a live ISO

The file `/etc/bootc-installer/live-iso-mode` tells the installer that it runs on a live ISO.
Then the installer does not pull from the network.
It gives fisherman the OCI image in the containers-storage of the ISO through `additionalImageStores`.
Refer to [Live ISO](../live-iso.md) to build an ISO of this type.
