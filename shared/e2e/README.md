# End-to-end gate

`.github/workflows/e2e.yml` proves the installers work, not only that they
render. `promote.yml` requires every job here, so nothing reaches `prod`
until all five frontends have produced a recipe that the real fisherman
installed and booted.

## Layer 1: the frontend drives its real backend path

| Job | What runs |
|---|---|
| `E2E (gnome)` | `tests/e2e/run_gnome.py`: the wizard from Welcome to Done under Xvfb, `BootcProgress.start()` launches fisherman through `pkexec` |
| `E2E (xfce)` | `frontends/xfce/tests/e2e/run.py`: the wizard from Welcome to Done under Xvfb, `start_install()` launches `sudo /usr/local/bin/fisherman -` and pipes the recipe |
| `E2E (niri)` | `frontends/niri/tests/e2e/run.py`: the QML writes its recipe to the stub Process, the same bytes go to the real Go backend on stdin, which launches fisherman |
| `E2E (kde)` | `frontends/kde/tests/e2e.cpp`: `InstallerController::startInstall()` launches `fisherman -` and writes the recipe to its stdin, waits for `installCompleted` |
| `E2E (cosmic)` | the ignored test `e2e_install_path_reaches_fisherman`: `TunaInstaller::stream_fisherman()` launches `fisherman -` and writes the recipe to its stdin |

`setup.sh` prepares the runner:

- builds the real fisherman from the submodule to `/usr/local/lib/tuna-e2e/fisherman.real`;
- installs `fisherman-shim.sh` at `/usr/local/bin/fisherman`, the path all frontends run. Every frontend runs `fisherman -` and pipes the recipe on stdin. The shim keeps what it reads, runs the real `fisherman validate` on it, then streams fisherman's real progress protocol — newline-delimited JSON, `total_steps` computed from the recipe (`shared/progress/README.md`). It used to stream nine invented `[n/9] ` lines, which is how two frontends could parse a format fisherman never emits and still pass this gate. It never partitions the runner;
- creates a loop disk and writes `/tmp/tuna-e2e/probe.json`, which offers that disk and nothing else. The shim prints this file for `fisherman probe --json`, which every frontend reads its disk list from (`shared/probe/README.md`). The real probe would exclude the loop disk, because it is a loop device and smaller than 50 GiB. It would also offer the runner's own disk;
- puts `fake-bin/` first on `PATH`: `bootc` (fails), `pkexec` (`sudo -n`, there is no polkit agent). Live media is the probe's answer (`live.is_live` is false in `probe.json`), so no frontend sends an empty image. The shim hands `fisherman validate --json --partial -`, which the frontends run while the user types, to the real fisherman, stdin included.

`check-recipe.py` then judges the recipe the frontend handed over: the real
fisherman accepts it (`fisherman validate --json -`, each problem reported
with its code), it conforms to `shared/recipe/fisherman-recipe.schema.json`,
and it targets the disk the job set up.

## Layer 2: the recipe is installed and booted

`E2E (install <frontend>)` downloads that recipe and runs `vm-install.sh`:
fisherman's own bootcrew tooling installs it onto a loop disk, enables SSH
in the result, verifies the layout and boots it in QEMU until `bootc status`
answers over SSH. Only `disk` and `image` are rewritten (the loop device and
the SSH-enabled canary that matches the recipe's boot stack).

The SSH-enable step is fisherman's `scripts/enable-ssh-installed.sh` and
needs the submodule at `7c3c738` or later: that revision writes root's
`authorized_keys` into the stateroot `var/` the guest mounts (older ones
wrote it into the deployment's own `var/`, which the guest never sees, so
sshd rejected every probe) and adds an `sshd_config.d` drop-in. The BLS
entries are then patched like fisherman's `bootcrew-ci-test` does
(`console=ttyS0` so the serial log in the artifact shows the boot,
`enforcing=0` because the injected files carry no SELinux labels). The
artifact `e2e-install-<frontend>` holds the rewritten recipe, the install
log and the boot log.

## Run it locally

```bash
bash shared/e2e/setup.sh                       # needs go, sudo, losetup
export PATH=$PWD/shared/e2e/fake-bin:$PATH
xvfb-run -a python3 tests/e2e/run_gnome.py     # after a meson build
python3 shared/e2e/check-recipe.py gnome
```
