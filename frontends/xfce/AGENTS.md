# AGENTS.md — agent guide for frontends/xfce (formerly tuna-os/tuna-installer-xfce)

> **Monorepo note.** This directory is one of five frontends in
> `tuna-os/bootc-installer`. Every path below is relative to THIS directory.
> Workflows referenced as `screenshots.yml` / `publish-flatpak.yml` / `ci.yml`
> are now `.github/workflows/screenshots-xfce.yml`, `publish-flatpak-xfce.yml`
> (plus `ci-niri.yml` for the niri Go backend) at the repository root, running with
> `working-directory: frontends/xfce`. The shared recipe schema and screen
> contract live in `../../shared/`. Do not add a `.github/` here.

A **GTK3 / PyGObject wizard** that drives the
[fisherman](https://github.com/tuna-os/fisherman) bootc install backend.
Deliberately the plainest of the TunaOS installer frontends: no libadwaita, it
follows the system GTK theme, and per [`DESIGN.md`](DESIGN.md) the trawl line is
the entire brand budget.

Human docs: [`README.md`](README.md) (flow, offline behaviour, Flatpak),
[`DESIGN.md`](DESIGN.md), [`docs/gui-walkthrough.md`](docs/gui-walkthrough.md).

## Layout

| Path | Lines | What |
|---|---|---|
| `tuna_installer_xfce/app.py` | ~557 | the wizard: screens, navigation, GTK wiring |
| `tuna_installer_xfce/core.py` | ~400 | recipe construction, fisherman invocation, the probe's live and offline facts |
| `tuna_installer_xfce/trawlline.py` | ~70 | the one piece of brand |
| `tests/gui/` | | `capture-screens.py`, `parity_report.py` |

```bash
sudo dnf install -y python3-gobject gtk3   # Fedora
./tuna-installer-xfce
```

`core.py` is the part worth reading first — it is where the recipe is decided,
and it is GTK-free enough to reason about without a display.

## How it invokes fisherman — two different paths

This trips people up because it works one way in development and another when
packaged:

- **Outside Flatpak:** `sudo /usr/local/bin/fisherman -`
- **Inside Flatpak:** `flatpak-spawn --host bash -c 'pkexec
  /usr/local/bin/fisherman -; exit $?'`, which requires the
  polkit action for it to be installed **on the host** by the ISO build — not
  by this repo. The host bash is there so fisherman's parent is a process
  this frontend owns (fisherman cancels when its parent dies); the wrapper
  is started in its own process group (`app.spawn_fisherman`).

Either way the recipe goes to fisherman on stdin: `spawn_fisherman` writes
the JSON and closes the pipe. Nothing writes it to a file.

A change to how the backend is launched has to work in both, and the Flatpak
path can only really be exercised from a built Flatpak:

```bash
flatpak-builder --user --install --force-clean build \
  flatpak/org.tunaos.InstallerXfce.json
flatpak run org.tunaos.InstallerXfce
```

Runtime is `org.gnome.Platform` (it ships GTK3 + PyGObject).

## Disks, TPM and minimum requirements

These come from `fisherman probe --json`, not from this frontend. `core.probe()`
runs it one time, without privileges, as `/usr/local/bin/fisherman probe --json`
(prefixed with `flatpak-spawn --host` in a Flatpak). It reads the answer through
`tuna_installer_xfce/fisherman_probe.py`, a byte-identical copy of
`shared/probe/fisherman_probe.py`. Show the eligible disks in fisherman's order,
with `size_label` exactly as given. Do not add a disk filter or a size
formatter. If the probe fails, the destination page shows the reason and
offers no disk. `tests/test_probe.py` renders the shared fixtures, and
`../../shared/probe/README.md` is the contract. A capture sets
`BOOTC_INSTALLER_FAKE_PROBE` to a fixture file.

## Offline and live-ISO installs

Live media and the offline images are fisherman's facts: `core.is_live()`,
`core.live_image()` and `core.offline_images()` read the probe's `live` and
`offline` sections. On live media an **empty `image` means "install the
running system"**, which fisherman accepts only there. The recipe never
carries `additionalImageStores`: fisherman exposes the host's offline
stores itself. Do not look for either in this frontend; inside a Flatpak it
sees the runtime's `/etc` and `/usr`, not the host's
(`tests/unit/test_no_frontend_detection.py`).

## Validation is fisherman's

The identity page sends the hostname and username, and the encryption page
the encryption choice, passphrase and filesystem, to
`fisherman validate --json --partial -` (`fisherman_validate.LiveCheck`, a
byte-identical copy of `shared/recipe/fisherman_validate.py`). A problem
shows under the field, worded by the copy key `validate_<code>`, and holds
Next. The password and the passphrase confirmation are this frontend's
rules. Encryption choices come from `encryption-choices.json`; branch on
`core.needs_passphrase()` / `core.needs_tpm2()`, never on the type's name.

## Visual verification

`screenshots.yml` renders every screen headlessly from the real wizard and
emits the parity report the shared installer matrix consumes, so a UI change
that breaks capture breaks that cross-installer report too. `tests/test_core.py`
and `tests/test_readiness.py` are real GTK-free unit tests; the screenshot job
runs the whole `tests/` suite under `xvfb-run` before it captures.

The capture waits for GTK to paint each page (the frame clock's
`after-paint`, then an X sync) before grabbing it, with theme animations
off. Do not go back to "drain until no events are pending": GTK3 paints on
a timed source, so the grab then read the previous page, and CI committed
three pairs of identical frames that the widget-tree text still credited.
A frame that is pixel-identical to the one before it fails the job.

Navigation: Back is hidden on welcome, progress and done; the Back/Next bar
is hidden on progress and done, and the done page carries its own Close and
Restart now (`done_restart`), Restart held until a recovery key is
acknowledged (`tests/test_navigation.py`).

## Sibling contract

Recipe JSON and screen sequence are shared with `tuna-installer-kde`, `-niri`
and `-cosmic` through the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
A field added here must exist there too. All real disk work belongs in
fisherman — keep it there.

## Branding

Nothing in this tree names a product. `tuna_installer_xfce/branding.py`, a byte-identical copy of the shared resolver that `core.BRANDING` exposes, resolves the product name,
the recipe's `distroID`, the hostname seed from a `branding.json`
under `/etc/bootc-installer/` (host first), then `os-release`, then a
neutral "Linux"; the contract and the fixtures it is tested against are in
`shared/branding/` at the monorepo root. `BOOTC_INSTALLER_BRANDING` points
tests at a file, `BOOTC_INSTALLER_PRODUCT_NAME` overrides the name for the
screenshot harness.
Flavour text (welcome, confirm, progress and done lines, the Install button)
is branding copy too: every rebrandable line is a key of
`shared/branding/copy-defaults.json`, read through the same resolver, and
`docs/PARITY.md` records which keys this frontend renders. Add a new
user-facing line the product might want to own as a copy key, not a
literal.
