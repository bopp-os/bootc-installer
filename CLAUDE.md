# CLAUDE.md

bootc-installer is the monorepo for every TunaOS / Bluefin bootc installer frontend. The GNOME frontend (GTK4/Libadwaita, Python) lives at the root; the KDE, COSMIC, Niri and XFCE frontends live under `frontends/<name>/`, each with its own `AGENTS.md` that is authoritative for that tree. All five drive the Go backend fisherman (a git submodule).

## Monorepo layout

| Path | What |
|---|---|
| `bootc_installer/`, `data/`, `flatpak/`, `tests/` | GNOME frontend (this file's original subject) |
| `frontends/kde|cosmic|niri|xfce/` | the other frontends, imported with history from `tuna-os/tuna-installer-*`; read their `AGENTS.md` first |
| `shared/recipe/` | canonical recipe schema (KDE keeps a byte-identical copy; a unit test enforces it) |
| `shared/branding/` | product identity contract: `branding.json` first, `os-release` second, neutral last; one resolver per language, all tested against `fixtures/` |
| `shared/walkthrough/` | screen contract + parity report + `aggregate.py` that builds `docs/walkthrough/` |
| `fisherman/` | backend submodule |

Workflows live only in the root `.github/workflows/`; per-frontend ones are named `<thing>-<frontend>.yml` and use `working-directory: frontends/<name>`.

## Release flow (read docs/RELEASE.md before touching CI)

`dev` → every check green + soak → `promote.yml` fast-forwards `prod` → `release.yml` cuts the GitHub release and publishes all five Flatpaks to the one package `ghcr.io/tuna-os/bootc-installer:<frontend>` (`publish-oci.yml`). Nothing on `dev` reaches `/releases/latest/` or the Flatpak remote. `prod` is never pushed by hand. The checks include `e2e.yml` (`shared/e2e/`): every frontend drives its real backend path and the recipe it produced is installed and booted in a VM.

## Build commands

```bash
# Build and install Flatpak locally (~10 min first time, cached after)
flatpak run org.flatpak.Builder --force-clean --user --install _build flatpak/org.bootcinstaller.Installer.json

# fisherman (Go submodule)
cd fisherman/fisherman
go build ./cmd/fisherman/    # compile check
go vet ./...                  # lint
```

## Two-component architecture

### fisherman (Go, `fisherman/fisherman/`)
Root-level CLI that reads a JSON recipe and executes a 9-step disk install pipeline. Emits newline-delimited JSON progress to stdout.

**Critical design constraints:**
- The partition layout follows the selected boot stack:
  - **systemd-boot / Dakota:** 2-partition GPT (EFI + root). The root partition is tagged with the architecture-specific Linux root GUID for GPT auto-discovery.
  - **GRUB2 / Bluefin:** 3-partition GPT (EFI + ext4 `/boot` + root), even when the root is unencrypted. The separate ext4 `/boot` is required because GRUB cannot read modern XFS features (`nrext64`, `exchange`, `rmapbt`), and `bootupctl` inside bwrap needs the `/boot` UUID from a raw block device.
- Scratch space is `/var/fisherman-tmp` (disk-backed, bind-mounted to `/var/tmp`). Do NOT change to `/run/*` — `/run` is tmpfs and too small.
- `--skip-finalize` is passed to bootc so step 9 can manually finalize (fstrim → remount ro → fsfreeze/thaw), because `bootc install finalize` is a no-op upstream.

### bootc-installer (Python, `bootc_installer/`)
GTK4/Adwaita GUI that collects user choices, builds a recipe, and pipes it to fisherman on stdin (`fisherman -`).

**Flatpak sandbox constraints:**
- fisherman runs on the **host** via `flatpak-spawn --host pkexec <path>`.
- Reboot must use `flatpak-spawn --host systemctl reboot`.
- In Flatpak, fisherman is staged to `$XDG_CACHE_HOME/bootc-installer/fisherman` (the persistent application cache) and its SHA256 is verified through the host portal before execution. Native execution still uses `/usr/local/bin/fisherman`. Do not derive a Flatpak staging path from `HOME/.cache`: `/var/home` may be private to one sandbox even with `--filesystem=host`.

## fisherman submodule workflow

fisherman is a separate repo (`tuna-os/fisherman`). Changes must be committed and pushed **separately**, then the parent repo's submodule pointer updated:

```bash
cd fisherman/fisherman && git add -A && git commit -m "..." && git push
cd ~/src/bootc-installer
git add fisherman && git commit -m "chore: update fisherman submodule (...)" && git push
```

CI checks out submodules recursively — always verify CI passes after both pushes.

## Screenshot walkthroughs

Every frontend has a headless capture job (`screenshots-<name>.yml`) that renders each page, audits the pixels, and emits `walkthrough-<name>.json` against the shared screen contract. `walkthrough.yml` folds them into `docs/walkthrough/README.md`. GNOME: `xvfb-run -a python3 tests/gui/capture-screens.py docs/screenshots` after a meson build.

The two GTK frontends can also be rendered in a real browser and driven with
Playwright — `shared/browser/run.sh gnome|xfce`, wired up as
`browser-walkthrough.yml`. This is GTK's own Broadway backend, so the widgets
are real; it clicks and types where the Xvfb harnesses can only look. It does
not replace them: Broadway ships text as textures, so there is no
accessibility tree and no text assertions. COSMIC, KDE and Niri have no
browser backend at all — `shared/browser/README.md` records what each one
would take, with the failing build output for COSMIC.

## Known issues

- **UI freeze during blob download**: `__on_vte_contents_changed` in `progress.py` scrapes the entire VTE buffer on every character change.
- **TPM2 enrolment:** Fixed in fisherman v0.2.0-34 — recovery key now emitted and shown in GUI.

## Don'ts

- **Don't remove the dedicated ext4 `/boot` partition from the GRUB2 layout.** It is required for GRUB2 images; systemd-boot images intentionally use the 2-partition layout described above.
- **Don't use `/run/*` for scratch space.** Always use `/var/fisherman-tmp`.
- **Don't skip the submodule push.** Changes in `fisherman/` must be pushed before updating the parent pointer, or CI breaks.
- **Don't write the recipe to a file.** Every frontend pipes it to `fisherman -` on stdin through its wrapper (`bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'`, with `flatpak-spawn --host` in front in a Flatpak) and closes stdin; the recipe holds the LUKS passphrase. Leave `additionalImageStores` out unless the ISO's recipe names stores (fisherman finds the host's), take live media from `fisherman probe --json`, and check fields with `fisherman validate --json --partial -`. See `shared/recipe/README.md`.
- **Don't push to `prod` or cut releases from `dev`.** `promote.yml` owns `prod`; `release.yml` owns tags and the Flatpak remote. Rolling release tags (`latest-stable`) are banned by ruleset history.
- **Don't add a `.github/` under `frontends/<name>/`.** Workflows only run from the root.
- **Don't hardcode a product.** No "TunaOS", "Bluefin", image ref, hostname, URL, vendor, quote, tagline, store or artwork in any frontend: read `shared/branding/README.md` and go through that frontend's branding resolver (`copy` keys for every rebrandable line, `assets` for artwork). The screenshot workflows set `BOOTC_INSTALLER_PRODUCT_NAME` for the docs; the bundled GNOME `recipe.json` carries no product strings; Bluefin's live in `shared/branding/examples/bluefin/`, which the live ISO ships. `docs/PARITY.md` says what each frontend renders.

## References
- `fisherman/data/images.json` — recursive distro image catalog
- `flatpak/org.bootcinstaller.Installer.json` — Flatpak manifest
- Recipe JSON fields: `disk`, `filesystem`, `encryption`, `image`, `targetImgref`, `hostname`, `flatpaks[]`
