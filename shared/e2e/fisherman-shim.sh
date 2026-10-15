#!/bin/bash
# The fisherman every frontend launches in the end-to-end job.
#
# Installed at /usr/local/bin/fisherman, which is the path all five frontends
# run (sudo outside Flatpak, pkexec inside). It is NOT a fake backend: the
# recipe the frontend hands over is validated by the REAL fisherman built
# from the submodule (`fisherman validate`, the same Validate() the install
# path runs first), and the recipe is kept so a later job can run the real
# install against a loop disk in a VM. What this shim does not do is
# partition the runner it is on: after validating, it streams the progress
# events a real install emits, so the frontend's progress parsing, log
# persistence and done-page transition run against the real protocol.
#
# "The real protocol" was not true when this was written. The shim streamed
# nine "[n/9] Partitioning ..." lines, described in the comment below as
# "the step lines a real run prints". fisherman prints no such lines: it
# writes newline-delimited JSON to stdout and nothing else
# (shared/progress/README.md). Two frontends parsed the invented prefix, so
# their progress bars never moved on a real install — and this gate, the one
# check whose whole purpose is to drive each frontend's real backend path,
# fed them the invented format and passed.
#
# Layout (created by setup.sh):
#   /usr/local/lib/tuna-e2e/fisherman.real   the binary built from fisherman/
#   /tmp/tuna-e2e/                           1777; recipe.json lands here
#                                            (read from stdin for `fisherman -`)
#   /tmp/tuna-e2e/probe.json                 the `probe --json` answer
set -u
# Overridable only so tests/unit/test_e2e_shim.py can run the shim without
# root; the frontends reach it through sudo/pkexec, which reset the env.
REAL=${TUNA_E2E_REAL:-/usr/local/lib/tuna-e2e/fisherman.real}
DIR=${TUNA_E2E_DIR:-/tmp/tuna-e2e}

case "${1:-}" in
  probe)
    # The disk list every frontend renders (shared/probe/README.md). The
    # real probe would offer the runner's own disk and exclude the loop
    # disk, so setup.sh wrote the answer that offers only the loop disk.
    # Still checked against the real fisherman's argument rules.
    if [ "${2:-}" != "--json" ]; then
      exec "$REAL" "$@"
    fi
    exec cat "$DIR/probe.json"
    ;;
  validate|images|scan|--help|-h|"")
    # The real fisherman, stdin included: `validate --json --partial -` is
    # what the frontends run while the user types (fisherman/docs/VALIDATE.md).
    exec "$REAL" "$@"
    ;;
esac

mkdir -p "$DIR"
# Keep the recipe exactly as the frontend wrote it. Every frontend now pipes
# it on stdin (`fisherman -`, tuna-os/fisherman#276) and writes no file; a
# path argument is still accepted, as the real fisherman accepts one.
if [ "$1" = "-" ]; then
  cat > "$DIR/recipe.json"
  SOURCE=stdin
else
  cp "$1" "$DIR/recipe.json"
  SOURCE="$1"
fi
RECIPE="$DIR/recipe.json"
chmod 0644 "$RECIPE"
echo "[e2e] recipe received on $SOURCE ($(wc -c < "$RECIPE") bytes)"
if [ ! -s "$RECIPE" ]; then
  # What the real fisherman says to empty stdin, as its one event.
  printf '{"type":"error","message":"loading recipe: recipe is empty","elapsed_ms":0,"timestamp":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  exit 1
fi

if ! "$REAL" validate "$RECIPE"; then
  echo "[e2e] the real fisherman rejected this recipe" >&2
  exit 3
fi
echo "[e2e] fisherman validate: ok"

DISK=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["disk"])' "$RECIPE")
IMAGE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("image") or "(running system)")' "$RECIPE")
FS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("filesystem") or "xfs")' "$RECIPE")

# The events a real run emits: fisherman's stdout protocol, verbatim in shape
# (internal/progress/progress.go). Step names, weights and cumulative
# percentages are those of an uncached auto-layout install, the same profile
# shared/progress/dry-run-transcript.ndjson was generated from. total_steps
# is 8 here and is NOT a constant — fisherman computes it from the recipe.
#
# Like a current fisherman (tuna-os/fisherman#270), every step, substep and
# complete event carries overall_pct, the bar position fisherman computes
# (internal/progress/bar.go), and every step event its stable step_id. The
# overall_pct values below are what that Tracker emits for this exact stream:
# a unit test (tests/unit/test_e2e_shim.py) replays the shim's events through
# the reference parser with the field stripped and requires the same bar.
# Frontends show overall_pct and label the step from the copy key
# step_<step_id>; the e2e runners still require the bar to end at 100%.
#
# A frontend that shows a moving bar against this is parsing the protocol. A
# frontend that shows an empty one is not, which is the point of the gate.
TOTAL=8
step() { # step_name step_id cumulative_pct weight_pct overall_pct
  printf '{"type":"step","step":%d,"total_steps":%d,"step_name":"%s","step_id":"%s","cumulative_pct":%d,"weight_pct":%d,"overall_pct":%s,"elapsed_ms":%d,"timestamp":"%s"}\n' \
    "$N" "$TOTAL" "$1" "$2" "$3" "$4" "$5" "$((N * 200))" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  N=$((N + 1))
  sleep 0.2
}
substep() { # message overall_pct
  printf '{"type":"substep","message":"%s","overall_pct":%s,"elapsed_ms":0,"timestamp":"%s"}\n' \
    "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  sleep 0.2
}
N=1
step "Partitioning disk"            partition    0  0 0
substep "target disk: $DISK" 0
step "Formatting EFI partition"     format_efi   0  1 0
step "Formatting root filesystem"   format_root  1  0 1
substep "filesystem: $FS" 1
step "Mounting filesystem"          mount        1  0 1
step "Installing OS"                install_os   1 87 1
substep "image: $IMAGE" 1
substep "Pulling image: layer 18/71" 14.23
substep "Pulling image: layer 47/71" 35.55
substep "Pulling image: layer 71/71" 53.2
step "Copying system Flatpaks"      flatpaks    88 11 88
step "Configuring installed system" configure   99  0 99
step "Finalizing installation"      finalize    99  1 99
printf '{"type":"complete","message":"Installation complete!","boot_id":"0001","overall_pct":100,"elapsed_ms":0,"timestamp":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[e2e] install simulated; recipe kept at $DIR/recipe.json"
exit 0
