# tuna-installer-niri — Design

Quickshell QML frontend running fullscreen on the Niri scrollable-tiling
Wayland compositor. The shared flow and contract are defined in the
[installer frontend specification](https://github.com/tuna-os/tunaOS/blob/main/docs/INSTALLER-FRONTENDS.md).

## Direction

The installer is the session (kiosk), and the desktop it installs ships
[DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell) (DMS)
as its shell. So the installer looks like a DMS surface: the same Material 3
tokens, the same components, the same motion. A user who lands on the
installed desktop sees the thing they just used, one step further in.

There is no bespoke look here. Everything visual is a token or a component
taken from DMS's `dank-qml-common` (`Style.qml`, `DankButton`, `DankCard`,
`DankListItem`, `DankTextField`, `StyledText`). When DMS changes, the
installer follows it; this page records which parts are borrowed, not a
palette of its own.

## Tokens (`ui/Theme.qml`)

Mirrors DMS `Style` for a dark Material 3 scheme.

| Group | Values |
|---|---|
| Surfaces | `surface #141218`, `surfaceContainer #211F26`, `surfaceContainerHigh #2B2930`, `surfaceContainerHighest #36343B` |
| Accent | `primary #D0BCFF` on `primaryText #381E72`, `primaryContainer #4F378B`, `secondary #CCC2DC` |
| Signals | `error #F2B8B5`, `warning #FFB74D`, `success #81C995` |
| Text | `surfaceText #E6E1E5`, secondary and disabled as 70 % / 38 % of it |
| Radii | `cornerRadiusS 8`, `cornerRadius 12`, `cornerRadiusL 16`, `cornerRadiusXL 24` |
| Sizes | `buttonHeightS 40`, `buttonHeightM 56`, `listItemHeight 56` |
| Spacing | `spacingXS 4` … `spacingXXL 32` |
| Motion | `shortDuration 150`, `mediumDuration 250`, standard easing; `pressScale 0.96` |

Dark only, like the live-session shell it fronts. A future light scheme is a
second token set, not a rewrite.

## Type

- Body/UI: **Google Sans Flex** (DMS's `Fonts.sans`), falling back to Inter
  and the system sans. 14 px medium, 16 px large, 28 px page titles.
- Data (device names, sizes, image refs, log): **Fira Code** (DMS's
  `Fonts.mono`), falling back to JetBrains Mono and the system mono. Data is
  the protagonist in an installer; mono keeps every value scannable.

The fonts are not bundled in the Flatpak; the fallbacks render the same
layout on a runner or a plain runtime, so screenshots do not depend on them.

## Layout

```
  Step 3 of 7 · Encryption                            ● ● ━━ ● ● ● ●
  ┌──────────────────────────────────────────────────────────────┐
  │  Disk encryption                                             │
  │  Encryption protects your files if the disk is lost…         │
  │  ┌──────────────────────────────────────────────────────┐    │
  │  │ No encryption   Anyone with the disk can read…    ◉  │    │  grouped
  │  │ Passphrase      You'll type it at every boot.     ○  │    │  DankListItem
  │  │ TPM             Unlocks automatically…            ○  │    │
  │  └──────────────────────────────────────────────────────┘    │
  │                                                              │
  │  (Back)                                          (Continue)  │
  └──────────────────────────────────────────────────────────────┘
   Enter  Continue    Shift+Enter  Back    Tab  Next field
```

- **Top bar**: "Step n of 7 · name" on the left, the DMS step dots on the
  right (the active one stretched to a pill).
- **Pages** are a single column of DMS components: choices are grouped
  `DankListItem` lists with the Material radio, text entry is a filled
  `DankTextField`, the confirm summary is a `DankCard`.
- **Buttons** are `DankButton`: pill at rest, squarer while pressed, a state
  layer on hover, tonal for Back and Close, the error tone for the one
  action that erases a disk.
- **Progress** is a determinate bar fed by fisherman's `[n/9]` step markers
  plus the current line beneath it; the raw log scrolls under that.
- **Hint bar**: the live keybindings of the focused context, DMS keycap
  style, always visible. Keyboard is primary: `Tab`/arrows within a page,
  `Enter` advances, `Shift+Enter` goes back.

## Copy

Every line comes from the branding contract (`shared/branding`) through the
Go `detect` output; nothing product-specific is written in QML. Warnings
spell out the device.

## Quality floor

Every interactive element reachable and operable by keyboard alone. Hint bar
always reflects the actual bindings of the focused context. Focus ring is
the `primary` outline on the focused component and nothing else glows. All
animation gated on a reduced-motion setting (env `TUNA_REDUCED_MOTION=1`).
Screenshots (`tests/gui/capture-screens.py`) are held to this page: a
component that is not a DMS component is a design change, not a tweak.
