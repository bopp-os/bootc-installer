#!/usr/bin/env python3
"""Judge the recipe a frontend handed to fisherman in the end-to-end job.

    check-recipe.py <frontend> [recipe.json]   (default /tmp/tuna-e2e/recipe.json)

Independent verdicts, all required:
  * the REAL fisherman accepts it (`fisherman validate --json -`, the same
    rules an install runs before it touches a disk), and each problem is
    reported with its stable code;
  * it conforms to shared/recipe/fisherman-recipe.schema.json, the contract
    the five frontends write against;
  * it targets the disk the job set up, so a frontend that picked the wrong
    device is caught here and not by a partitioned runner;
  * it leaves SELinux on (selinuxDisabled is not true);
  * for a frontend with a required account step (USER_STEP), it creates a
    user in wheel.
The recipe is then copied to e2e-recipe-<frontend>.json for the VM job.
"""
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL = "/usr/local/lib/tuna-e2e/fisherman.real"
# Frontends whose wizard has a required account step: their recipe must
# create a user, in wheel, or the installed system has nobody to log in as.
USER_STEP = {"niri"}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    frontend = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/tuna-e2e/recipe.json"
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} does not exist: the frontend never launched fisherman")
    with open(path) as fh:
        recipe = json.load(fh)
    print(f"recipe from {frontend}:")
    print(json.dumps(recipe, indent=2))

    failures = []

    # `validate --json -`: every problem, with its stable code, from the
    # rules the install runs before it touches a disk. The recipe goes on
    # stdin, the way the frontends hand it over.
    with open(path, "rb") as fh:
        r = subprocess.run([REAL, "validate", "--json", "-"], stdin=fh,
                           capture_output=True, text=True, check=False)
    print(f"fisherman validate --json -> exit {r.returncode}")
    try:
        verdict = json.loads(r.stdout)
    except ValueError:
        verdict = None
    if r.returncode not in (0, 1) or not isinstance(verdict, dict):
        failures.append(f"fisherman validate --json failed: {(r.stdout + r.stderr).strip()}")
    else:
        for problem in verdict.get("errors") or []:
            failures.append(f"fisherman: {problem.get('field') or '<recipe>'}: "
                            f"{problem.get('code')}: {problem.get('message')}")
        if verdict.get("valid"):
            print("fisherman validate: ok")

    try:
        import jsonschema
        with open(os.path.join(REPO, "shared", "recipe", "fisherman-recipe.schema.json")) as fh:
            schema = json.load(fh)
        errors = sorted(jsonschema.Draft7Validator(schema).iter_errors(recipe), key=str)
        for e in errors:
            failures.append(f"schema: {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}")
        if not errors:
            print("schema: ok")
    except ImportError:
        failures.append("python3-jsonschema is not installed; the schema was not checked")

    expected = ""
    try:
        with open("/tmp/tuna-e2e/loopdev") as fh:
            expected = fh.read().strip()
    except OSError:
        pass
    if expected and recipe.get("disk") != expected:
        failures.append(f"disk: frontend chose {recipe.get('disk')!r}, the e2e disk is {expected!r}")
    if not recipe.get("hostname"):
        failures.append("hostname is empty")
    if recipe.get("encryption", {}).get("type") not in ("none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"):
        failures.append(f"encryption type {recipe.get('encryption')!r}")
    # selinuxDisabled=true makes bootc add selinux=0 to the installed
    # system's kernel arguments. Four frontends once hardcoded it (#160).
    if recipe.get("selinuxDisabled") is True:
        failures.append("selinuxDisabled is true: the installed system would boot with selinux=0")

    if frontend in USER_STEP:
        user = recipe.get("user") or {}
        if not user.get("username"):
            failures.append("user: the account step produced no username")
        elif "wheel" not in (user.get("groups") or []):
            failures.append(f"user: {user.get('username')!r} is not in wheel: {user.get('groups')!r}")

    out = f"e2e-recipe-{frontend}.json"
    shutil.copyfile(path, out)
    print(f"kept as {out}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"OK: {frontend} produced a recipe the real fisherman accepts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
