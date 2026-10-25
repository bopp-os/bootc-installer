# Install and use the installer

bootc-installer is a Flatpak.
It installs a [bootc](https://containers.github.io/bootc/) container image to a disk.

## Get the Flatpak

Use the production build for a real install.
This command removes an old copy, then installs the latest release:

```bash
curl -Lo installer.flatpak \
  https://github.com/tuna-os/bootc-installer/releases/latest/download/org.bootcinstaller.Installer.flatpak \
  && sudo flatpak uninstall -y org.bootcinstaller.Installer org.bootcos.Installer 2>/dev/null; sudo flatpak install --bundle -y installer.flatpak
```

The devel build follows the `dev` branch.
Use it to test new changes:

```bash
curl -Lo installer-devel.flatpak \
  https://github.com/tuna-os/bootc-installer/releases/download/latest-dev/org.bootcinstaller.Installer.Devel.flatpak \
  && sudo flatpak uninstall -y org.bootcinstaller.Installer.Devel 2>/dev/null; sudo flatpak install --bundle -y installer-devel.flatpak
```

The production release moves only when `dev` passes all checks.
Refer to [the release flow](../RELEASE.md).

## Start the installer

```bash
flatpak run org.bootcinstaller.Installer
```

On a live ISO, the installer starts by itself.

## The wizard, screen by screen

The images below come from CI.
Refer to [the GNOME walkthrough](../gui-walkthrough.md) for the full set.

| Screen | What you do |
|---|---|
| ![Welcome](../screenshots/01-welcome.png) | **Welcome**. Read what the installer will do. |
| ![Phone companion](../screenshots/02-qr_companion.png) | **Phone companion**. Scan the QR code to type your account data on a phone. This step is optional. |
| ![Install location](../screenshots/03-disk.png) | **Install location**. Select a disk. The installer does not write to the disk yet. |
| ![Encryption](../screenshots/04-encryption.png) | **Disk encryption**. Select LUKS with a passphrase, TPM2, or the two together. |
| ![Confirm](../screenshots/05-confirm.png) | **Confirm**. Make sure that the data is correct. After this screen, the installer writes to the disk. |
| ![Installing](../screenshots/06-progress.png) | **Installing**. Wait for the nine steps to complete. Open the log if you want to see more. |
| ![Recovery key](../screenshots/07-recovery-key.png) | **Recovery key**. Keep the key in a safe place, then confirm. This screen shows only after an encrypted install. |
| ![Done](../screenshots/08-done.png) | **Done**. Restart into the new system. |

Some screens show only for some images.
For example, the account screen shows only when the image needs a user account.

## Other frontends

The KDE, COSMIC, Niri and XFCE frontends use the same backend and the same screen contract.
Refer to [the walkthrough for all frontends](../walkthrough/README.md).
