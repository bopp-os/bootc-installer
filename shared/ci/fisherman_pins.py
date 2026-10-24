#!/usr/bin/env python3
"""Move every fisherman pin in this repository to one commit, together.

fisherman is pinned in two kinds of place, and tests/unit/
test_shared_probe.py::TestFishermanPin requires them to agree:
  - the `fisherman` submodule gitlink, which GNOME builds from;
  - the fisherman git source in each frontend's Flatpak app manifest
    (frontends/<name>/flatpak/*.json), which the other frontends build from.

fisherman-bump.yml used to move only the gitlink, so every bump it opened
failed that test. This script moves all of them in one step and stages the
result.

A manifest is a Flatpak app manifest when its JSON is an object with
"modules" and an "app-id" or "id"; other JSON files there (cargo-sources.json)
are not looked at. In each one the fisherman source is found by its URL
(github.com/tuna-os/fisherman, any scheme, with or without .git), never by
module or frontend name, anywhere in the module tree. An app manifest with no
such source, or with more than one, is an error: nothing is written and the
script exits non-zero, so a bump never goes out with a pin silently left
behind.

The file is edited as text (only the commit value changes) so the diff is one
line per manifest, then parsed again to check the result.

    python3 shared/ci/fisherman_pins.py --commit <sha> [--repo .] [--no-stage]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

MANIFEST_GLOB = os.path.join("frontends", "*", "flatpak", "*.json")
SUBMODULE_PATH = "fisherman"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_FISHERMAN_URL_RE = re.compile(
    r"^(?:https?://|ssh://git@|git@)?github\.com[/:]tuna-os/fisherman(?:\.git)?/?$",
    re.IGNORECASE,
)


class PinError(Exception):
    """A manifest's fisherman pin cannot be moved safely."""


def is_fisherman_url(url):
    return isinstance(url, str) and bool(_FISHERMAN_URL_RE.match(url.strip()))


def is_app_manifest(data):
    return isinstance(data, dict) and isinstance(data.get("modules"), list) and (
        "app-id" in data or "id" in data)


def fisherman_sources(data):
    """Every git source in the module tree whose URL is tuna-os/fisherman."""
    found = []

    def walk(modules):
        for module in modules or []:
            if not isinstance(module, dict):
                continue  # a string module is a path to another file
            for source in module.get("sources") or []:
                if (isinstance(source, dict) and source.get("type") == "git"
                        and is_fisherman_url(source.get("url"))):
                    found.append(source)
            walk(module.get("modules"))

    walk(data.get("modules"))
    return found


def the_fisherman_source(data, name):
    sources = fisherman_sources(data)
    if len(sources) != 1:
        raise PinError(f"{name}: expected exactly one tuna-os/fisherman git source, "
                       f"found {len(sources)}")
    return sources[0]


def rewrite_manifest_text(text, commit, name="manifest"):
    """(new_text, old_commit) with the fisherman source pinned to `commit`."""
    data = json.loads(text)
    source = the_fisherman_source(data, name)
    old = source.get("commit")
    if not isinstance(old, str) or not _SHA_RE.fullmatch(old):
        raise PinError(f"{name}: the fisherman source has no full commit pin ({old!r})")
    if old == commit:
        return text, old
    pattern = re.compile(r'("commit"\s*:\s*")' + re.escape(old) + '"')
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise PinError(f"{name}: commit {old[:12]} appears {len(matches)} times; "
                       "cannot tell which one is fisherman's")
    new_text = pattern.sub(lambda m: m.group(1) + commit + '"', text)
    if the_fisherman_source(json.loads(new_text), name).get("commit") != commit:
        raise PinError(f"{name}: rewrite did not land on the fisherman source")
    return new_text, old


def app_manifests(repo):
    """Paths (relative to repo) of the Flatpak app manifests under frontends/."""
    out = []
    for path in sorted(glob.glob(os.path.join(repo, MANIFEST_GLOB))):
        with open(path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as e:
                raise PinError(f"{os.path.relpath(path, repo)}: not valid JSON: {e}") from e
        if is_app_manifest(data):
            out.append(os.path.relpath(path, repo))
    return out


def set_all_pins(repo, commit, stage=True):
    """Pin the gitlink and every app manifest to `commit`.

    Returns {path: old_commit} for each manifest. Every manifest is checked
    before any file is written, so an error leaves the tree untouched.
    """
    if not _SHA_RE.fullmatch(commit or ""):
        raise PinError(f"not a full commit sha: {commit!r}")
    manifests = app_manifests(repo)
    if not manifests:
        raise PinError(f"no Flatpak app manifest matches {MANIFEST_GLOB}")
    planned = {}
    for rel in manifests:
        with open(os.path.join(repo, rel), encoding="utf-8") as fh:
            text = fh.read()
        planned[rel] = rewrite_manifest_text(text, commit, rel)

    for rel, (new_text, _old) in planned.items():
        with open(os.path.join(repo, rel), "w", encoding="utf-8") as fh:
            fh.write(new_text)
    if stage:
        subprocess.run(["git", "-C", repo, "update-index", "--cacheinfo",
                        f"160000,{commit},{SUBMODULE_PATH}"], check=True)
        subprocess.run(["git", "-C", repo, "add", "--", *planned], check=True)
    return {rel: old for rel, (_text, old) in planned.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--commit", required=True, help="the fisherman commit to pin everywhere")
    p.add_argument("--repo", default=".", help="repository root (default: .)")
    p.add_argument("--no-stage", action="store_true",
                   help="rewrite the manifests only; leave the gitlink and index alone")
    args = p.parse_args(argv)
    try:
        moved = set_all_pins(args.repo, args.commit, stage=not args.no_stage)
    except PinError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    for rel, old in moved.items():
        print(f"{rel}: {old[:12]} -> {args.commit[:12]}")
    if not args.no_stage:
        print(f"{SUBMODULE_PATH} (gitlink) -> {args.commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
