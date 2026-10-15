# Hardware facts: `fisherman probe --json`

Every frontend gets its disk list, TPM presence and minimum-requirements
check from one command: `fisherman probe --json`. fisherman owns the schema
and the rules: [`fisherman/docs/PROBE.md`](../../fisherman/docs/PROBE.md).
This file says how a frontend runs the command and what it shows.

Before this, each frontend parsed `lsblk` itself. There were five disk
filters, and three frontends offered zram or the live USB as install targets.
Sizes appeared in three different units. Niri never showed the disk model.
Only GNOME checked RAM, CPU and UEFI. The rules are now in fisherman, and a
frontend only shows the result.

## Run it

The probe needs no root, and it writes nothing. Run it as the desktop user.
Do not run it through `pkexec` or `sudo`.

| Frontend | Command |
|---|---|
| GNOME, Flatpak | `flatpak-spawn --host ~/.cache/bootc-installer/fisherman probe --json` (the binary that the install stages) |
| GNOME, host | `/usr/local/bin/fisherman probe --json` |
| KDE, COSMIC, Niri, XFCE | `/usr/local/bin/fisherman probe --json`, prefixed with `flatpak-spawn --host` in a Flatpak |

Each frontend runs the same fisherman binary that it runs for the install.
The probe runs on the host, so `lsblk` sees the host's mounts and the
`boot_disk` rule can find the live USB.

Run the probe one time, when the wizard starts. Use that result for the disk
page, the encryption page and the requirements check. KDE, COSMIC and Niri
run the probe again each time the disk page opens, so they also show a disk
that you connect later.

## What a frontend shows

`fixtures/<name>.expected.json` shows what a frontend must render from `fixtures/<name>.json`:
the disks, `tpm_usable`, `unmet`, `live_image` and `offline_images`.
Each frontend's tests load the fixture through that frontend's own reader,
and must produce the same list.

- **Disks:** show only `eligible: true` disks, in the order that fisherman
  gives. Do not filter, sort or hide more disks. An unknown `excluded_reason`
  means that the disk is not eligible.
- **Name:** use `model`. If `model` is empty, use `path`. Do not use
  `vendor`, because it can be a PCI ID such as `0x1af4`.
- **Size:** use `size_label` exactly as fisherman gives it, for example
  `465.8 GiB`. The unit is binary (1 GiB = 2^30 bytes), and the label says so. Do not format `size_bytes` yourself. GNOME's partition picker shows
  partition sizes, which the probe does not report. For those sizes,
  `format_size` in `fisherman_probe.py` applies the same rule, and a test
  checks it against every label in the fixtures.
- **Bus:** `transport_label` (`NVMe`, `SATA`, `USB`, ...), where the
  frontend has space for it.
- **Removable disks:** offer the `removable: true` disks too. fisherman
  already removes the live USB (`boot_disk`), so a frontend must not hide
  removable disks.
- **No eligible disks:** say so on the disk page. Do not skip the page.
- **Minimum size:** fisherman removes disks smaller than 50 GiB
  (`too_small`). Frontends do not apply a minimum of their own.
- **TPM:** offer the `tpm2-luks` encryption types only when `tpm.usable`
  is true.
- **Live media:** `live.is_live` says whether the host booted from live
  media. Only then may the recipe leave `image` empty, which means "install
  the running image". Show `live.live_image` as that image. fisherman
  rejects an empty `image` on any other host (`image_required`). Do not
  look for live media in the frontend: inside a Flatpak it sees the
  runtime, not the host, and `/run/ostree-booted` is on every installed
  ostree host too.
- **Offline images:** `offline.images` lists the image refs in the host's
  offline stores. Use it for an "available offline" tag. Do not pass
  `offline.stores` in the recipe: when `additionalImageStores` is absent,
  fisherman exposes those stores itself (`shared/recipe/README.md`).
- **Requirements:** `system.unmet` lists `ram`, `cpu` and `uefi` in that
  order. If the list is not empty, show the `requirements_title` copy and one
  `requirements_<id>` line for each item (`shared/branding/copy-defaults.json`).
  GNOME blocks with a separate window for each item, as it did before, and
  `IGNORE_RAM` and `IGNORE_CPU` still override it. The other four frontends
  show a warning on the welcome page and let the user continue.

## When the probe fails

The probe can fail. For example, an older fisherman that has no probe
command exits non-zero with "unknown command". Or the binary is missing. There is no
fallback disk scan. A frontend shows the reason on the disk page and offers
no disks, so the user cannot install. The frontend hides the TPM choices.
It skips the requirements check and shows no warning.

A fallback scan would mean five `lsblk` parsers again, with five filters and
five size formats. They would run only on the machines where the probe
failed, which are the hardest to debug. The
fisherman that a frontend ships with always has the probe, because the
submodule pin is a revision that has it. A frontend that runs an older
fisherman is packaged incorrectly. The error message says so, and a fallback
would hide it.

## Readers

| Frontend | Reader | Test against the fixtures |
|---|---|---|
| GNOME | `bootc_installer/core/fisherman_probe.py` (copy), used by `core/system.py` and `core/disks.py` | `tests/unit/test_probe_frontend.py` |
| XFCE | `tuna_installer_xfce/fisherman_probe.py` (copy), used by `core.py` | `tests/test_probe.py` |
| KDE | `src/probe.{h,cpp}` | `tests/test_backend.cpp` (`probeFixtures`) |
| COSMIC | `src/probe.rs` | `cargo test probe` |
| Niri | `installer/probe.go`, sent to the QML by `discover-disks` and `detect` | `go test -run TestProbe` |

`fisherman_probe.py` is canonical. The Python frontends keep byte-identical
copies of it, and `tests/unit/test_shared_probe.py` checks that they match.
That test also checks the fixtures against the Go structs in
`fisherman/fisherman/internal/probe`. It also checks that `laptop.json` is
byte-identical to fisherman's own golden output.

## Fixtures

| File | What it is |
|---|---|
| `laptop.json` | fisherman's golden output (`internal/probe/testdata/golden/probe.json`): a laptop booted from a live USB, with every exclusion rule |
| `container.json` | a real `fisherman probe --json` run in a CI container: no eligible disk, no TPM, BIOS boot |
| `vm.json` | hand-built to the schema: a BIOS VM with one disk that has no model, and every requirement unmet |
| `*.expected.json` | what every frontend renders from the fixture of the same name |

## Test seam

`BOOTC_INSTALLER_FAKE_PROBE=<file>` makes every frontend read probe output
from that file and run no process. The screenshot harnesses use
`fixtures/laptop.json`. The end-to-end job does not use this variable: its
fisherman shim answers `probe --json` itself (`shared/e2e/README.md`).
