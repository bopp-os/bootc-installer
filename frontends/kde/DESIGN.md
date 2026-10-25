# tuna-installer-kde design

This repository provides a Qt 6 and Kirigami frontend for the `fisherman`
bootc installer. The shared recipe and screen requirements live in the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
This document describes how the KDE frontend implements that contract.

## Architecture

`src/qml/Main.qml` creates a `Kirigami.AbstractApplicationWindow` and hosts the
step runner in `src/qml/Wizard.qml`. The wizard follows KDE KISS's modular
pattern: each screen is a `SetupModule` under
`modules/<name>/contents/ui/main.qml`. A module exposes its content and whether
the user may continue; the wizard owns navigation, headings, and the shared
Back and Next buttons.

The seven modules are:

1. `welcome`
2. `disk`
3. `encryption`
4. `account`
5. `confirm`
6. `progress`
7. `done`

The wizard uses slide transitions between modules instead of `SwipeView`,
matching KISS's behaviour during window resizing. Do not put backend work in a
page-activation hook. Activation may refresh harmless page data, such as the
disk list, but installation starts only when the user selects Install on the
confirmation screen.

## Backend boundary

`InstallerController` exposes recipe state and the installation process to
QML. It writes the selected values to a temporary recipe, launches the
privileged `fisherman` command, streams output to the progress module, and
removes the recipe when the process exits. The recipe can contain a disk
encryption passphrase, so it must not be logged or retained.

The confirmation screen is the destructive-action boundary. Back navigation
is disabled after `fisherman` starts, and the progress module advances to the
finished screen only after the process exits.

## Plasma integration

Use Kirigami, Kirigami Addons, Qt Quick Controls, and `Kirigami.Units` for
layout and sizing. Controls use the Plasma `org.kde.desktop` style and Breeze
theme roles so system colours, fonts, icons, dark mode, and accent preferences
continue to work. Avoid fixed pixel geometry, custom palettes, and application
font overrides.

Use active, direct copy. State the destructive consequence plainly, keep the
Install label exclusive to the confirmation action, and present failures with
the process exit status or actionable backend output.

## Accessibility and interaction

- Preserve a complete keyboard navigation order.
- Never bind Escape or page activation to a destructive action.
- Keep paired passphrase fields and their reveal controls accessible.
- Expose validation before enabling Next or Install.
- Keep focus and warning states visible in both light and dark themes.

## Visual verification

The screenshot workflow builds the real QML modules with `tests/capture.cpp`,
renders every step offscreen, and checks the resulting pixels for meaningful
content. It also produces `docs/screenshots/walkthrough-kde.json`, the parity
report consumed by the shared installer matrix. See
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) for the capture contract,
current screenshots, and safety rationale.
