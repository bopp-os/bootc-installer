# tuna-installer-xfce — Design

GTK3 (Python/PyGObject) frontend for XFCE. Shared flow/contract:
[tunaOS installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).

## Direction

XFCE's values are the design brief: light on resources, zero mystery,
works on the decade-old laptop this ISO is most likely being installed on.
This is the **plainest** frontend of the four — a classic `GtkAssistant`-shaped
wizard (own window implementation, since GtkAssistant's sidebar wastes space)
that would look at home next to Thunar. Restraint *is* the identity here;
one quiet signature and nothing else.

No libadwaita, no client-side decoration tricks, no animations beyond GTK
defaults. Respect the user's GTK theme (Greybird, Adwaita, whatever) — the
app must look native in all of them, so structural color comes from the theme,
never hex.

## Signature element: the trawl line

A single 3 px horizontal line under the header area spans the window: the
**trawl line**. Steps are knots (8 px circles) spaced evenly along it;
completed knots fill solid `--sonar`, the current knot is ringed, upcoming
knots are theme-border-colored. During install, the line itself fills
left-to-right with the 9 fisherman pipeline steps.

That's the entire brand budget. It costs one `GtkDrawingArea` and no CPU.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--sonar` | `#2EC4B6` | Knot fill, progress fill — the only brand hex |
| `--catch` | `#F4A259` | Install button `destructive`-adjacent styling |
| everything else | GTK theme colors | via style context, both light & dark |

## Type

System UI font throughout (no bundled fonts — resource frugality is the
brief). Monospace (`monospace` alias) for device names, image refs, and the
log view. Page titles: `<big><b>` markup, nothing more.

## Layout

```
┌────────────────────────────────────────────────────────┐
│ TunaOS Installer                              ─  □  ✕  │
├────────────────────────────────────────────────────────┤
│ ●───●───◉───○───○───○───○───○                          │  ← trawl line
│                                                        │
│  Where should TunaOS be installed?                     │
│                                                        │
│  ( ) Samsung SSD 990 PRO    1.0 TB    /dev/nvme0n1     │
│  (•) WD Blue                2.0 TB    /dev/sda         │
│                                                        │
│  ⚠  Everything on WD Blue (/dev/sda) will be erased.   │
│                                                        │
│                                                        │
│                              [ Back ]      [ Next ]    │
└────────────────────────────────────────────────────────┘
```

- 640×520 default, resizable, everything reachable at 800×600.
- Standard 12 px GNOME-2-era spacing, `GtkRadioButton` rows for disks
  (visible radios — XFCE users prefer explicit controls over selection
  highlights).
- Advanced options live behind a `GtkExpander` ("Advanced"), collapsed by
  default: filesystem choice and btrfs subvolumes.
- Progress page: `GtkProgressBar` (9 steps mapped), current-step label, and a
  *visible by default* mono `GtkTextView` log — XFCE users want to see the
  output, don't hide it.
- Back is hidden where it means nothing: on the welcome page, during the
  install and on the done page. The Back/Next bar disappears on the progress
  and done pages; the done page has its own **Close** and **Restart now**
  row, and Restart now stays insensitive until a recovery key, when there is
  one, is acknowledged.

## Copy

Plain, complete sentences, no jargon left unexplained: encryption options say
what they mean ("Passphrase — you'll type it at every boot", "TPM — unlocks
automatically on this hardware"). Buttons: Next / Back / Install / Close / Restart now (the welcome,
Install and Restart now labels are branding copy).

## Quality floor

Runs comfortably in 256 MB of GTK process memory. Full keyboard navigation
with visible focus. Works on X11 and Wayland. High-contrast themes: the trawl
line falls back to theme foreground color when the theme requests it.
