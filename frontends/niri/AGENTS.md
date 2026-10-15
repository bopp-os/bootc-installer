# AGENTS.md — agent guide for frontends/niri (formerly tuna-os/tuna-installer-niri)

> **Monorepo note.** This directory is one of five frontends in
> `tuna-os/bootc-installer`. Every path below is relative to THIS directory.
> Workflows referenced as `screenshots.yml` / `publish-flatpak.yml` / `ci.yml`
> are now `.github/workflows/screenshots-niri.yml`, `publish-flatpak-niri.yml`
> (plus `ci-niri.yml` for the niri Go backend) at the repository root, running with
> `working-directory: frontends/niri`. The shared recipe schema and screen
> contract live in `../../shared/`. Do not add a `.github/` here.

A **Quickshell/QML wizard with a Go backend** that drives the
[fisherman](https://github.com/tuna-os/fisherman) bootc install backend, for
the Niri scrollable-tiling Wayland compositor. Architecture is modelled on
[DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell).

Human docs: [`README.md`](README.md) (architecture, build, recipe),
[`DESIGN.md`](DESIGN.md) (interaction and visual spec),
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) (CI-generated).

## Two halves, one contract

| Path | What |
|---|---|
| `installer/` | the Go backend — **its own module**, with all the unit tests |
| `ui/` | the Quickshell QML wizard (`installer.qml`, `Theme.qml`, `qmldir`) |
| `tests/gui/` | headless capture (`capture-screens.py`) and `parity_report.py` |
| `tests/qml-stubs/` | a stub `Quickshell` QML module so the UI can be loaded without the real one |

The QML talks to the backend through its CLI, not a library:

```bash
cd installer
go build -o tuna-installer-niri .
./tuna-installer-niri discover-disks        # renders `fisherman probe --json` disks
./tuna-installer-niri install < recipe.json # pipes the recipe on to `fisherman -`
./tuna-installer-niri validate < page.json  # `fisherman validate --json --partial -`
quickshell ui/installer.qml                 # the frontend, needs Quickshell
```

So a change to the backend's **stdout shape** is a breaking change to the UI
even though nothing in `ui/` references a Go symbol.

## Checks

CI (`ci.yml`) runs everything with `working-directory: installer`, which is
why a root-level `go` command finds nothing:

```bash
cd installer
gofmt -l .        # must print nothing — CI fails on any unformatted file
go vet ./...
go build ./...
go test ./...
```

`.golangci.yml` config lives at the repo root. The Go tests are real and cover
the interesting parts — `offline_test.go`, `readiness_test.go`,
`branding_test.go` — so run them before pushing rather than relying on CI.

## The QML stub is load-bearing

`tests/qml-stubs/Quickshell/` exists so the wizard can be loaded in CI without
installing Quickshell itself. When you add a Quickshell API call to the UI, the
stub needs the matching shim or the screenshot job fails with a QML resolution
error that looks nothing like the real cause.

## Visual verification

`screenshots.yml` renders every screen headlessly from the real QML and emits
the parity report the shared installer matrix consumes. A UI change that breaks
capture breaks that cross-installer report, not just this repo's screenshots.
`DESIGN.md`'s "Quality floor" section is the standard those renders are held to
— the scrolling column strip is the signature element, so treat changes to it
as design changes, not layout tweaks.

## Disks, TPM and minimum requirements

These come from `fisherman probe --json`, not from this frontend.
`installer/probe.go` runs `/usr/local/bin/fisherman probe --json` without
privileges (prefixed with `flatpak-spawn --host` in a Flatpak).
`discover-disks` prints the eligible disks in the shape of
`shared/probe/fixtures/*.expected.json`. `detect` reports `hasTpm` and
`unmet`. Show the disks in fisherman's order, with `size_label` exactly as
given. Do not add a disk filter or a size formatter. If the probe fails,
`discover-disks` exits 1 with the reason on stderr, and the disk page shows
it. `go test -run TestProbe` renders the shared fixtures, and
`../../shared/probe/README.md` is the contract.

## The recipe, live media and validation

- `install` reads the recipe on stdin and pipes it on to `fisherman -`;
  nothing writes it to a file. It holds the LUKS passphrase.
- `detect` reports the probe's live media (`isLive`, `liveImage`) and
  offline images, and the embedded `encryption-choices.json`
  (`encryptionChoices`). The QML sends an empty `image` only when `isLive`,
  and never `additionalImageStores`: fisherman exposes the host's stores.
- The hostname, filesystem and encryption rules are fisherman's:
  `validate` hands the QML's partial recipe to
  `fisherman validate --json --partial -`. The QML shows a problem through
  the copy key `validate_<code>` and holds Continue and Install on it.
  Branch on `needs_passphrase` / `needs_tpm2`, never on the type's name.

`../../shared/recipe/README.md` is the contract.

## Sibling contract

The recipe JSON and the screen sequence are shared with the other frontends
(`tuna-installer-kde`, `-xfce`, `-cosmic`) via the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
A field added here has to exist there too, or the installers diverge. All the
real disk work belongs in fisherman — keep it there.

## Branding

Nothing in this tree names a product. the Go backend's `installer/branding.go`, reported under `detect`'s `branding` key and read by the QML resolves the product name,
the recipe's `distroID`, the hostname seed and the default image from a `branding.json`
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
