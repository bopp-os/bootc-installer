# AGENTS.md — agent guide for frontends/kde (formerly tuna-os/tuna-installer-kde)

> **Monorepo note.** This directory is one of five frontends in
> `tuna-os/bootc-installer`. Every path below is relative to THIS directory.
> Workflows referenced as `screenshots.yml` / `publish-flatpak.yml` / `ci.yml`
> are now `.github/workflows/screenshots-kde.yml`, `publish-flatpak-kde.yml`
> (plus `ci-niri.yml` for the niri Go backend) at the repository root, running with
> `working-directory: frontends/kde`. The shared recipe schema and screen
> contract live in `../../shared/`. Do not add a `.github/` here.

A **thin Qt 6 / Kirigami wizard** that drives the
[fisherman](https://github.com/tuna-os/fisherman) bootc install backend. The
UI collects choices, writes a recipe JSON, and streams `fisherman`'s output.
All the disk work lives in fisherman — keep it there.

Human docs: [`README.md`](README.md) (build, tests, recipe),
[`DESIGN.md`](DESIGN.md) (architecture and the backend boundary),
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) (capture contract),
[`runbooks/`](runbooks/).

## Build and test

```bash
# Fedora deps — Kirigami and Kirigami Addons are QML-only; nothing links KF6,
# they resolve at runtime from the QML import path.
sudo dnf install -y cmake gcc-c++ ninja-build \
    qt6-qtbase-devel qt6-qtdeclarative-devel \
    kf6-kirigami kf6-kirigami-addons kf6-qqc2-desktop-style breeze-icons

cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build
./build/tuna-installer-kde

# Backend unit tests (CTest / QtTest)
cmake -B build -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build build && ctest --test-dir build --output-on-failure

# Offscreen screenshot harness
cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_CAPTURE=ON
cmake --build build && ./build/tuna-installer-capture
```

`biome.json` lints and formats **JSON only** (`**/*.json`) — there is no
JavaScript toolchain here despite appearances.

## The module contract

Each wizard step is a self-contained module at
`modules/<name>/contents/ui/main.qml` whose root is a
`TunaComponents.SetupModule` exposing `nextEnabled` and `contentItem`.
`src/qml/Wizard.qml` drives them with hand-rolled slide animations rather than
a `SwipeView`. `src/components/setupmodule.h` is deliberately a near-copy of
KDE KISS's `SetupModule`, so the shape is upstream's — follow it when adding a
step rather than inventing a new one.

Steps: welcome → disk → encryption → account → confirm → progress → done.
The account step writes the recipe's `user` block (groups `["wheel"]`)
and is required: there is no image catalog here to say an image creates
its own first user.

### QML gotchas already paid for

- **`contentItem` must be a plain `Item`, not a `ScrollView`,** for short
  steps. Inside a `ScrollView` the content item collapses to its implicit
  height, so centring stops centring — the first CI render came out jammed
  against the top with the lower half empty.
- **No hardcoded pixel metrics.** Use `Kirigami.Units` throughout, and
  Kirigami Addons `FormCard` for form layout. No forced Fusion style.

## Backend boundary — treat as a safety rule

`InstallerController` (`src/installercontroller.cpp`) owns recipe state and the
install process. Three rules from [`DESIGN.md`](DESIGN.md) are safety
properties, not preferences:

- **The recipe can contain a LUKS passphrase.** It must never be logged,
  retained or written to a file. The controller runs `fisherman -` and
  writes the JSON to the process's stdin, then closes it
  (`../../shared/recipe/README.md`).
- **The confirmation screen is the destructive-action boundary.** Back
  navigation is disabled once `fisherman` starts.
- **The progress module advances to "finished" only after the process exits** —
  not on a parsed progress line.

The recipe schema is shared with the other frontends
(`fisherman-recipe.schema.json`, and the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md)).
A field added here must exist there too, or the sibling installers diverge.
Encryption types come from `encryption-choices.json`, a byte-identical
copy of fisherman's file compiled into `recipe.cpp`; branch on
`Recipe::needsPassphrase()` / `needsTpm2()`, never on the type's name. On
live media (the probe's `live.is_live`, `InstallerController.isLive`)
`image` is left out and fisherman installs the running system. Never fill
`additionalImageStores`: fisherman exposes the host's offline stores.

## Validation is fisherman's

The hostname, username, filesystem and encryption rules are `fisherman
validate --json --partial -` (`src/validate.{h,cpp}`). The controller
sends those fields on stdin 300 ms after a change (the username, never
the user's password) and exposes `hostnameProblem`, `encryptionProblem`
and `usernameProblem`, worded by the copy key `validate_<code>`. The
encryption and account steps show their problem and hold Next on it; the
confirm step shows the hostname's. Only the passphrase and password
confirmations (and requiring an account) are rules of this frontend. Do not add a rule of your own to `Recipe::validationError()`.

## Disks, TPM and minimum requirements

These come from `fisherman probe --json`, not from this frontend. `src/probe.cpp`
runs `/usr/local/bin/fisherman probe --json` without privileges (prefixed with
`flatpak-spawn --host` in a Flatpak). `InstallerController` reads TPM and the
requirements from it at startup. `DiskModel` runs the probe again each time the
disk step opens. Show the eligible disks in fisherman's order, with
`size_label` exactly as given. Do not add a disk filter or a size formatter. If
the probe fails, the disk step shows the reason. `test_backend`
(`probeFixtures`) renders the shared fixtures, and
`../../shared/probe/README.md` is the contract. The capture sets
`BOOTC_INSTALLER_FAKE_PROBE` to `shared/probe/fixtures/laptop.json`.

## Visual verification

`screenshots.yml` builds the real QML modules with `tests/capture.cpp`, renders
every step offscreen, and checks the pixels for meaningful content. It also
emits `docs/screenshots/walkthrough-kde.json`, the parity report the shared
installer matrix consumes — so a UI change that breaks capture breaks the
cross-installer report, not just this repo's screenshots.

## Branding

Nothing in this tree names a product. `src/branding.{h,cpp}` (`InstallerController` reads it once at startup) resolves the product name,
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
