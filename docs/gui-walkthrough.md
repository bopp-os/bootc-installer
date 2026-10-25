# GNOME installer walkthrough

CI renders every image below from the real GTK4 / libadwaita wizard with
`tests/gui/capture-screens.py`. The script uses the same `BootcWindow` that
the Flatpak presents. It drives the wizard page by page under Xvfb against
fixtures (two canned disks, no network, the repository's own `recipe.json`).
The UI has no mocks, and nothing touches a disk. See `.github/workflows/screenshots-gnome.yml`.

The cross-frontend view, with the KDE, COSMIC, Niri and XFCE installers side
by side and the parity matrix on top, is [`walkthrough/`](walkthrough/README.md).

<p align="center">
  <img src="screenshots/walkthrough.gif" alt="The GNOME installer, screen by screen" width="720">
</p>

## The pages

| | |
|---|---|
| ![Welcome](screenshots/01-welcome.png) | **Welcome**: what the installer is about to do, with power-off and credits. |
| ![Phone companion](screenshots/02-qr_companion.png) | **Phone companion**: optional QR pairing so the rest of the wizard can be typed from a phone. |
| ![Install location](screenshots/03-disk.png) | **Install location**: whole disks only, plus the virtual-disk option for VMs. Nothing is written yet. |
| ![Encryption](screenshots/04-encryption.png) | **Disk encryption**: LUKS with a passphrase, TPM2, or both. |
| ![Confirm](screenshots/05-confirm.png) | **Confirm**: the last screen before anything is written. |
| ![Installing](screenshots/06-progress.png) | **Installing**: fisherman's nine steps, with the log one click away. |
| ![Recovery key](screenshots/07-recovery-key.png) | **Recovery key**: shown once after an encrypted install and must be acknowledged. |
| ![Done](screenshots/08-done.png) | **Done**: restart into the new system. |

The user-account page is part of the wizard but not of this capture. The
repository's `recipe.json` targets an image with `needs_user_creation: false`.
Thus the wizard skips the page, exactly as it would on that ISO.

## What the capture checks

A PNG that exists is not a screenshot that rendered. The job audits each
frame from its own pixels (distinct colours, share of the largest flat
colour, ink fraction). The job fails when a page did not draw. The job also
compares the visible widget text of each page with the shared screen contract in
`shared/walkthrough/parity_report.py`, and writes the result to
`screenshots/walkthrough-gnome.json` for the aggregator.

Run it locally:

```bash
meson setup build -Dbuild-fisherman=false && ninja -C build
BOOTC_RESOURCE=build/bootc_installer/bootc-installer.gresource \
  xvfb-run -a -s "-screen 0 1400x1000x24" python3 tests/gui/capture-screens.py docs/screenshots
```
