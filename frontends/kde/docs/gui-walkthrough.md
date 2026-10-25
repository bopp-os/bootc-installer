# GUI walkthrough

Every image below is rendered in CI from the **real** QML — the same
`src/qml/Wizard.qml` and the same seven step modules under `modules/` that the
shipped installer loads. Only `src/main.cpp` is swapped, for
`tests/capture.cpp`. Nothing about the UI is mocked or redrawn.

The capture runs on the Qt `offscreen` platform plugin with the software
scenegraph, inside a Fedora container that carries the KF6 runtime (Kirigami,
Kirigami Addons, `org.kde.desktop` Qt Quick Controls style). See
[`.github/workflows/screenshots-kde.yml`](../.github/workflows/screenshots.yml).

<p align="center">
  <img src="screenshots/walkthrough.gif" alt="The TunaOS KDE installer, step by step" width="720">
</p>

## The steps

| | |
|---|---|
| ![Welcome](screenshots/01-welcome.png) | **Welcome** — what the wizard is about to do. |
| ![Target disk](screenshots/02-disk.png) | **Target disk** — the disks `fisherman probe --json` offers, one FormCard radio per disk: the model (the path when unknown), then the path, fisherman's size label and the bus. Re-probed every time the step becomes current, so hotplugged media appear. |
| ![Disk encryption](screenshots/03-encryption.png) | **Disk encryption** — `none`, `luks-passphrase`, and (only when fisherman reports a usable TPM 2.0) `tpm2-luks` and `tpm2-luks-passphrase`. The passphrase fields appear only for the options that take one. |
| ![User account](screenshots/04-account.png) | **User account** — username, optional full name and the password typed twice: the recipe's `user` block, in group `wheel`. Next is held until both are filled, the passwords match and `fisherman validate --json --partial -` has no problem with the username (shown under the field in the `validate_username_*` copy). The capture asserts Next is held before the second typing and released after it. |
| ![Confirm](screenshots/05-confirm.png) | **Confirm** — the recipe as it will be written (including the username, never the password), and the only button in the app that starts an install. |
| ![Installing](screenshots/06-progress.png) | **Installing** — live `fisherman` output. No Back, no Next: the wizard advances itself when the process exits. |
| ![Finished](screenshots/07-done.png) | **Finished** — success or failure, with the exit code, under the branding artwork. |
| ![Recovery key](screenshots/08-recovery.png) | **Recovery key** — after a TPM enrolment: the key in a monospace, selectable field with a copy button, and Restart held until "I have saved my recovery key" is ticked. |

Every step's header shows "Step N of 7 · name" and one dot per step.

## What the capture checks

Existence checks are not enough. A sibling repository published a blank page
while its "the PNGs exist and are non-empty" assertion passed. So
`tests/capture.cpp` reads its own pixels back and fails the build when a screen
did not really render:

- **distinct colours** — a screen that never painted collapses to a handful.
- **ink** — the fraction of sampled pixels far enough (Manhattan distance > 40)
  from the image's own dominant colour to be drawn content. Measuring against
  the image's own background rather than a fixed luma keeps this correct under
  a dark colour scheme.
- **row and column spread** — the fraction of sampled rows, and of sampled
  columns, that contain any ink. This is what actually discriminates. Density
  alone does not: the welcome and finished steps are hero pages — one icon, a
  heading, a line of prose — and legitimately score around 1% ink, while a form
  step with a FormCard behind it scores 30%. A blank screen scores zero on all
  four.
- **visible step text** — the strings the current step actually put in its item
  tree. Independent of every pixel ratio above, and the one signal that does
  not move with the container's fonts.

Measured on the six real screens at 1000×700 (CI run 33658389834), and the
thresholds sit below these with margin (see the table at the top of `tests/capture.cpp`):

| step | class | colours | ink | rows | cols |
|---|---|---|---|---|---|
| 01-welcome | hero | 198 | 0.90% | 9.0% | 45.2% |
| 02-disk | card | 280 | 21.97% | 42.7% | 53.9% |
| 03-encryption | card | 217 | 26.86% | 53.8% | 53.9% |
| 04-confirm | card | 207 | 30.12% | 56.8% | 53.9% |
| 05-progress | card | 244 | 15.34% | 100.0% | 100.0% |
| 06-done | hero | 153 | 0.47% | 7.0% | 38.0% |

### Why the row floor is per-class

The spread floors are **per screen class**, and that is the point rather than a
concession. A single global row floor turned out to measure the container
image's font metrics as much as it measured rendering (#57).

When the workflow moved to `fedora:45`, the three card steps did not move at
all, while both hero pages roughly halved — welcome 23.2% → 9.0%, done 15.5% →
7.0% — taking ink and colour count down with them and leaving columns nearly
untouched. That is the signature of a smaller `Kirigami.Units.gridUnit`, which
is derived from font metrics: a hero page sizes its icon, its spacings and its
wrapped prose off it, so the entire column scales with the font. A card step
barely moves, because its row coverage comes from the card background painting
the rect rather than from text. The done page was rendering perfectly and the
check called it blank.

So the two classes are not measuring the same quantity and cannot share a
floor. Splitting them **tightens** the check where it can bite — the card floor
rises from 8% to 20%, against a sparsest measured 42.7% — and only relaxes it
on the class where the number tracked the font. The semantic text assertion
backs both up: a page that drew nothing carries no text whatever the fonts do.

Every run prints these numbers and the class each floor was applied under, so a
drift is visible in the log before it is a mystery. The capture also clears the output directory before rendering: a run
that dies on the first screen must not leave the previous run's images there
for the artifact upload to publish as its own.

The screenshot artifact is uploaded with `if: always()` — it is needed
precisely when the capture fails.

## Why this cannot start an install

The harness drives navigation through `Wizard.goToStep()`, which moves the
visible step and calls the target module's `onPageActivated()`. The only
`onPageActivated()` in the tree is the disk step's, and it re-runs the
read-only `fisherman probe --json` and nothing else. `InstallerController.startInstall()` — the sole path to a
privileged `fisherman` process — has exactly one caller, the Install button's
`onClicked` in `Wizard.qml`, which the harness never presses.

Worth stating explicitly: the sibling XFCE installer *does* kick off an install
from its page-enter hook, so "drive the steps" is not automatically harmless
across this family of frontends.
