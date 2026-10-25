# CI/CD Guide — bootc-installer monorepo

Reference for every workflow in this repository, the promotion/release flow,
and the release qualification runbook. The narrative version of the release
flow is [`docs/RELEASE.md`](../docs/RELEASE.md); this page is the index.

---

## Branches

```
feature/xyz ──PR──▶ dev ──promote.yml (all checks green + soak)──▶ prod ──▶ release.yml
```

- All PRs target `dev`. Merge queue is enabled on `dev`.
- `prod` is a fast-forward of `dev`, moved only by `promote.yml`. Never push
  to it by hand and never open a PR against it.
- Bots push `[skip ci]` commits to `dev` (refreshed screenshots, refreshed
  walkthrough). Promotion skips those when picking a candidate.

---

## Workflows

### Validation (run on PRs and pushes to `dev`)

| Workflow | Job names (as the promotion gate sees them) | Scope |
|---|---|---|
| `python-test.yml` | `Unit Tests (no display)`, `UI Integration Tests (offscreen GTK)` | GNOME frontend. Coverage gate `--cov-fail-under` is a ratchet; never lower it. |
| `go-test.yml` | `Unit Tests` | fisherman submodule: vet, tests, 20% coverage floor, race detector. |
| `flatpak.yml` | `Build (production)`, `Build (production, aarch64)`, `Build (devel)` | GNOME Flatpak bundles, kept as artifacts. On a `dev` push also refreshes the `latest-dev` **pre-release**. Also `workflow_call`, used by `release.yml`. |
| `flatpak-frontends.yml` | `kde / publish`, `cosmic / publish`, … | Build-only (`publish: false`) Flatpak of each imported frontend whose tree changed, x86_64. |
| `screenshots-gnome.yml` | `Screenshots (gnome)` | Renders every GNOME page under Xvfb, pixel audit, parity report. Commits to `docs/screenshots/` on `dev`. |
| `screenshots-kde.yml` | `Screenshots (kde)` | Same for `frontends/kde` (Fedora container, KF6). |
| `screenshots-cosmic.yml` | `Screenshots (cosmic)` | Same for `frontends/cosmic` (lavapipe). Only job that compiles the crate. |
| `screenshots-niri.yml` | `Screenshots (niri)` | Same for `frontends/niri` (PyQt6 offscreen, Quickshell stubs). |
| `screenshots-xfce.yml` | `Screenshots (xfce)` | Same for `frontends/xfce` (GTK3 under Xvfb), plus its pytest suite. |
| `ci-niri.yml` | `Go backend (niri)` | gofmt / vet / build / test for `frontends/niri/installer`. |
| `cargo-sources-cosmic.yml` | `cargo-sources matches Cargo.lock (cosmic)` | Offline cargo vendoring stays in sync with `Cargo.lock`. |
| `e2e.yml` | `E2E (gnome)`, `E2E (kde)`, `E2E (cosmic)`, `E2E (niri)`, `E2E (xfce)`, `E2E (install <frontend>)` | The gate that proves the installers work: each frontend drives its real backend launch path to Done against the real fisherman's validation, then the recipe it produced is installed onto a loop disk and booted in QEMU. See `shared/e2e/README.md`. |
| `validate-flatpak.yml` | `validate` | GNOME manifests are well-formed with required fields. |
| `actionlint.yml` | `actionlint` | Workflow syntax. |
| `ste.yml` | `ste` | Simplified Technical English over every `.md`, budget in `.ste-budget` (a ratchet; the monorepo budget is the sum of the five repos'). |
| `nightly.yml` | — | Weekly test sweep of `dev` and `prod`. |
| `drop-bot-review-requests.yml` | — | Stops CODEOWNERS review requests on bot PRs. |

### Documentation

| Workflow | What |
|---|---|
| `walkthrough.yml` | After any screenshot job on `dev` (and daily): downloads the latest green `gui-screenshots-<frontend>` artifact of every frontend, runs `shared/walkthrough/aggregate.py`, commits `docs/walkthrough/`. |

### Promotion and release

| Workflow | Trigger | What |
|---|---|---|
| `promote.yml` | completion of any validation workflow on `dev`; hourly catch-up; manual | Gate: candidate is newest non-`[skip ci]` `dev` commit, descends from `prod`, older than `SOAK_MINUTES` (the job sleeps out the remainder), every check run complete and green, every `REQUIRED_CHECKS` name present. Then fast-forwards `prod` and dispatches `release.yml`. |
| `release.yml` | dispatch on `prod` (from promote); `v*` tag push; manual on `prod` | Builds GNOME bundles via `flatpak.yml`, cuts the `vYYYY.MM.DD-<sha>` release marked `--latest`, verifies the `/releases/latest/download/` URLs, then publishes each changed frontend's Flatpak. |
| `publish-flatpak.yml` | `workflow_call` from release; manual | GNOME → tuna-os Flatpak remote via `tuna-os/.github` reusable workflow. |
| `publish-flatpak-{kde,cosmic,niri,xfce}.yml` | `workflow_call` from release / frontends validation; manual | Same for each imported frontend. |

Names matter: `promote.yml` lists workflow *names* in its `workflow_run`
trigger and job *names* in `REQUIRED_CHECKS`. Renaming a job or workflow
means updating both.

---

## Release process

There is no manual release step. A `dev` commit that passes every check and
sits for the soak window is promoted and released automatically. See
[`docs/RELEASE.md`](../docs/RELEASE.md) for the escape hatches (`force`,
promoting a specific sha, hotfix tags, rollback, pausing).

Release assets:

| Asset | Contents |
|---|---|
| `org.bootcinstaller.Installer.flatpak` | GNOME, production app id, x86_64 |
| `org.bootcinstaller.Installer-aarch64.flatpak` | GNOME, production app id, aarch64 (absent if that build failed) |
| `org.bootcinstaller.Installer.Devel.flatpak` | GNOME, devel app id, x86_64 |

The other four frontends are distributed through the tuna-os Flatpak remote
(`https://tunaos.org/flatpak/index/static`), not as release assets.

---

## Release qualification runbook

### Software-only (automated in CI; reproducible locally)

```bash
./QUALIFY_SOFTWARE.sh     # GNOME: manifests, unit + UI tests, fisherman tests, both Flatpaks
just capture              # GNOME screenshot walkthrough, as screenshots-gnome.yml runs it
just walkthrough          # cross-frontend parity page from the committed captures
```

All of it must be green before `promote.yml` will move `prod`; running it
locally is for diagnosing a red `dev`, not a step in releasing.

### Hardware-only checks (manual, not gated in CI)

| Check | How to test |
|-------|-------------|
| TPM2 LUKS enrolment | Install with `tpm2-luks` on real hardware; verify no password prompt on reboot |
| Recovery key display | Install with `tpm2-luks-passphrase`; confirm key shown and copyable in GUI |
| Passphrase fallback | Install with `luks-passphrase`; verify passphrase prompt on reboot |
| GRUB boot (XFS root) | Install with `filesystem=xfs`; verify GRUB loads from ext4 `/boot` |
| systemd-boot (btrfs/composefs) | Install with `composeFsBackend=true`; verify `bootctl status` clean |
| Offline ISO | Boot from live ISO with embedded OCI; verify install completes without internet |
| Post-reboot WiFi | Install on machine with saved WiFi; verify auto-reconnect after reboot |

The VM install matrix for the backend lives in `tuna-os/fisherman`
(`bootcrew-vm.yml`); the live-ISO smoke test for every frontend lives in
`tuna-os/tunaOS` (`installer-smoke.yml`).
