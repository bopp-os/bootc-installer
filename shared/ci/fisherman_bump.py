#!/usr/bin/env python3
"""Should the fisherman submodule pin move to fisherman `dev`'s HEAD?

fisherman/ is pinned to one commit of tuna-os/fisherman. A fix there reaches
the installers only when the pin moves. fisherman-bump.yml runs this on a
schedule and turns a "bump" answer into one pull request on a fixed branch.

The answer is "bump" only when all of these hold:
  - fisherman dev HEAD differs from the pinned commit;
  - HEAD is strictly ahead of the pin (never move the pin backwards or onto
    a diverged history);
  - CI on HEAD finished green: every commit status is `success`, every check
    run is completed with `success` or `skipped`, and at least one of them is
    a `success` (a commit no CI ran on proves nothing).
Otherwise it says why not ("current", "wait", "skip").

Writes key=value lines to $GITHUB_OUTPUT (or stdout) and, on a bump, the PR
body to --body. Run it locally from a checkout:

    python3 shared/ci/fisherman_bump.py --pinned "$(git rev-parse HEAD:fisherman)"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

UPSTREAM = "tuna-os/fisherman"
BRANCH = "dev"
GREEN_CHECKS = {"success", "skipped"}


# ---------------------------------------------------------------- pure logic


def ci_verdict(statuses, check_runs):
    """(ok, reason) for one commit's statuses and check runs.

    statuses: [{"context", "state"}], from /commits/{sha}/status. Only the
    latest status per context is there, so a re-run that went green counts.
    check_runs: [{"id", "name", "status", "conclusion"}].
    """
    # A commit carries one check run per workflow run, so a re-run or a
    # second firing of the same workflow repeats a name. The newest one (the
    # highest id) is the one that counts, as on the PR's checks tab.
    newest = {}
    for c in check_runs:
        name = c.get("name", "?")
        if name not in newest or c.get("id", 0) > newest[name].get("id", 0):
            newest[name] = c
    check_runs = list(newest.values())

    pending, red, green = [], [], 0
    for s in statuses:
        state = s.get("state")
        if state == "success":
            green += 1
        elif state == "pending":
            pending.append(s.get("context", "?"))
        else:
            red.append(f"{s.get('context', '?')} ({state})")
    for c in check_runs:
        name = c.get("name", "?")
        if c.get("status") != "completed":
            pending.append(name)
        elif c.get("conclusion") == "success":
            green += 1
        elif c.get("conclusion") not in GREEN_CHECKS:
            red.append(f"{name} ({c.get('conclusion')})")
    if red:
        return False, "CI not green: " + ", ".join(sorted(red))
    if pending:
        return False, "CI still running: " + ", ".join(sorted(set(pending)))
    if not green:
        return False, "no CI result recorded on this commit"
    return True, f"{green} check(s) green"


def decide(pinned, head, compare_status, ci_ok, ci_reason):
    """(action, reason). action: current | skip | wait | bump."""
    if pinned == head:
        return "current", f"fisherman is already pinned to {BRANCH} HEAD {head[:7]}"
    if compare_status != "ahead":
        return "skip", (
            f"{BRANCH} HEAD {head[:7]} is {compare_status} relative to the pin "
            f"{pinned[:7]}; refusing to move the pin anywhere but forward"
        )
    if not ci_ok:
        return "wait", f"{BRANCH} HEAD {head[:7]}: {ci_reason}"
    return "bump", f"{pinned[:7]}..{head[:7]}: {ci_reason}"


def title(pinned, head):
    return f"chore: update fisherman submodule ({pinned[:7]}..{head[:7]})"


def body(pinned, head, commits, ci_reason, token_kind, total=None):
    """Markdown body for the bump PR."""
    url = f"https://github.com/{UPSTREAM}"
    lines = [
        f"Moves the `fisherman` submodule from [`{pinned[:7]}`]({url}/commit/{pinned}) "
        f"to [`{head[:7]}`]({url}/commit/{head}), the current HEAD of "
        f"`{UPSTREAM}@{BRANCH}`. The fisherman source pin in each frontend "
        "Flatpak manifest (`frontends/*/flatpak/`) moves to the same commit.",
        "",
        f"CI on `{head[:7]}`: {ci_reason}. "
        f"Full diff: {url}/compare/{pinned[:12]}...{head[:12]}",
        "",
        f"### Commits ({total if total is not None else len(commits)})",
        "",
    ]
    for c in commits:
        sha = c["sha"]
        msg = (c.get("commit", {}).get("message") or "").splitlines()[0] if c.get("commit") else ""
        author = (c.get("author") or {}).get("login") or c.get("commit", {}).get("author", {}).get("name", "")
        # "(#123)" in a fisherman subject is a fisherman PR; bare, GitHub
        # would link it to this repository's #123. No @mention either: the
        # body is rewritten on every bump and would ping the authors each time.
        msg = re.sub(r"(?<![\w/])#(\d+)", rf"{UPSTREAM}#\1", msg)
        lines.append(f"- [`{sha[:7]}`]({url}/commit/{sha}) {msg}" + (f" (by {author})" if author else ""))
    if total is not None and total > len(commits):
        lines.append(f"- ... and {total - len(commits)} more; see the compare link above")
    lines += [
        "",
        "Opened by `fisherman-bump.yml`. It updates this PR in place as fisherman "
        "`dev` moves; it only ever bumps to a commit whose CI passed.",
    ]
    if token_kind != "bot":
        lines += [
            "",
            "> **CI does not start on its own for this PR.** It was pushed with the "
            "workflow's `GITHUB_TOKEN`, and GitHub does not trigger `push` or "
            "`pull_request` workflows for that token. The bump workflow dispatches "
            "Go Tests, Python Tests, Flatpak and End to end on this branch instead; "
            "their results show on the head commit. Anything else needs a close and "
            "reopen of this PR, or the `FISHERMAN_BUMP_TOKEN` secret (see the "
            "workflow header).",
        ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ I/O adapters


def gh_api(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def gh_api_all(path, key):
    items, page = [], 1
    sep = "&" if "?" in path else "?"
    while True:
        chunk = gh_api(f"{path}{sep}per_page=100&page={page}").get(key, [])
        items += chunk
        if len(chunk) < 100:
            return items
        page += 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--pinned", required=True, help="the commit fisherman/ is pinned to")
    p.add_argument("--body", help="write the PR body here on a bump")
    p.add_argument(
        "--token-kind",
        choices=("bot", "default"),
        default="default",
        help="'bot' when the PR is pushed with a token that triggers CI",
    )
    args = p.parse_args(argv)

    head = gh_api(f"repos/{UPSTREAM}/commits/{BRANCH}")["sha"]
    out = {"pinned": args.pinned, "head": head}
    if head == args.pinned:
        action, reason = decide(args.pinned, head, "identical", True, "")
    else:
        cmp = gh_api(f"repos/{UPSTREAM}/compare/{args.pinned}...{head}")
        statuses = gh_api(f"repos/{UPSTREAM}/commits/{head}/status").get("statuses", [])
        runs = gh_api_all(f"repos/{UPSTREAM}/commits/{head}/check-runs", "check_runs")
        ci_ok, ci_reason = ci_verdict(statuses, runs)
        action, reason = decide(args.pinned, head, cmp.get("status"), ci_ok, ci_reason)
        if action == "bump":
            out["title"] = title(args.pinned, head)
            if args.body:
                with open(args.body, "w", encoding="utf-8") as f:
                    f.write(
                        body(
                            args.pinned,
                            head,
                            cmp.get("commits", []),
                            ci_reason,
                            args.token_kind,
                            total=cmp.get("total_commits"),
                        )
                    )
    out["action"], out["reason"] = action, reason

    dest = os.environ.get("GITHUB_OUTPUT")
    text = "".join(f"{k}={v}\n" for k, v in out.items())
    if dest:
        with open(dest, "a", encoding="utf-8") as f:
            f.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
