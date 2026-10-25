# Build, test and release

Read the [contribution guide](../../CONTRIBUTING.md) before you open a pull request.
Open all pull requests against the `dev` branch.

## Get the source

`fisherman` is a git submodule.
Clone with `--recurse-submodules`, or the build fails:

```bash
git clone --recurse-submodules https://github.com/tuna-os/bootc-installer
cd bootc-installer
```

## Dependencies

- meson and ninja
- libadwaita-1-dev
- gettext and desktop-file-utils
- libgnome-desktop-4-dev
- python3-requests
- Go 1.22 or later, for fisherman

## Build

### Flatpak

We recommend the Flatpak build:

```bash
git submodule update --init --recursive
flatpak run org.flatpak.Builder --force-clean --user --install _build flatpak/org.bootcinstaller.Installer.json
flatpak run org.bootcinstaller.Installer
```

### Meson

Use Meson for development:

```bash
git submodule update --init --recursive
meson setup build
ninja -C build
sudo ninja -C build install
bootc-installer
```

## Demo mode

For work on the UI, use the launcher script:

```bash
./run-dev.sh
```

The script sets `BOOTC_DEMO=1`.
In demo mode, the wizard does not start fisherman and does not write to a disk.

To open one screen directly, set `BOOTC_PREVIEW_SCREEN`:

```bash
BOOTC_PREVIEW_SCREEN=confirm ./run-dev.sh
BOOTC_PREVIEW_SCREEN=progress ./run-dev.sh
```

With `BOOTC_DEMO=1`, the `progress` screen starts the demo install immediately.

## Tests

```bash
pytest tests/unit/ -q                           # Unit tests, no display
xvfb-run -a pytest tests/ui/ -q                 # UI tests
python3 -m ruff check bootc_installer/ tests/   # Lint
./QUALIFY_SOFTWARE.sh                           # All software checks
```

CI fails if the unit test coverage is less than the value of `--cov-fail-under` in `.github/workflows/python-test.yml`.
Do not make that value lower.

### Install tests in a VM

These tests need root and QEMU.
They erase the disk in the VM:

```bash
sudo FISHERMAN_BIN=/path/to/fisherman pytest tests/integration/test_e2e_install.py -v -s
sudo FISHERMAN_BIN=/path/to/fisherman BOOT_VERIFY=1 pytest tests/integration/test_e2e_install.py -v -s
```

### Tests on real hardware

Some features need lab hardware before a release:

- TPM2
- Boot prompts on a physical machine
- The recovery key and the passphrase fallback
- The offline ISO

Refer to [the release qualification runbook](../../.github/CI_CD_GUIDE.md#release-qualification-runbook).
It tells you which checks CI does, and which checks need hardware.

## Screenshots

CI makes the screenshots again after each change.
To make them on your computer, run:

```bash
just capture       # The GNOME screens, into docs/screenshots/
just walkthrough   # The page for all frontends, into docs/walkthrough/
```

Refer to [the GNOME walkthrough](../gui-walkthrough.md) for what the capture checks.

## Release

A change goes from `dev` to `prod` when all checks pass and 30 minutes go by.
Then CI makes the release.
Refer to [the release flow](../RELEASE.md).
