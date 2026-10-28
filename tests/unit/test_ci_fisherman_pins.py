"""shared/ci/fisherman_pins.py: the bump moves every fisherman pin together.

TestFishermanPin (test_shared_probe.py) requires the submodule gitlink and
each frontend Flatpak manifest's fisherman source to name one commit.
fisherman-bump.yml used to move only the gitlink, so its PRs went red. These
tests run the rewrite in throwaway git repositories, with no network.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))
import fisherman_pins as fp  # noqa: E402

OLD = "a" * 40
NEW = "b" * 40
URL = "https://github.com/tuna-os/fisherman.git"


def manifest(app_id, sources, nested=False):
    """A Flatpak app manifest; `sources` go on the module that builds fisherman."""
    backend = {"name": "backend", "buildsystem": "simple", "sources": sources}
    modules = [{"name": "dep", "sources": [{"type": "archive", "url": "https://example.invalid/x.tgz"}]}]
    if nested:
        modules.append({"name": "outer", "modules": [backend]})
    else:
        modules.append(backend)
    modules.append({"name": "app", "sources": [{"type": "dir", "path": "../"}]})
    return {"app-id": app_id, "runtime": "r", "modules": modules}


def git_source(commit=OLD, url=URL):
    return {"type": "git", "url": url, "commit": commit}


def write(repo, rel, data):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    r = str(tmp_path)
    git(r, "init", "-q")
    git(r, "update-index", "--add", "--cacheinfo", f"160000,{OLD},fisherman")
    # Four frontends; names are arbitrary on purpose: the pin is found by URL.
    write(r, "frontends/alpha/flatpak/org.example.Alpha.json",
          manifest("org.example.Alpha", [git_source()]))
    write(r, "frontends/beta/flatpak/org.example.Beta.json",
          manifest("org.example.Beta", [git_source(url="https://github.com/tuna-os/fisherman")], nested=True))
    write(r, "frontends/gamma/flatpak/org.example.Gamma.json",
          manifest("org.example.Gamma", [git_source(url="git@github.com:tuna-os/fisherman.git")]))
    write(r, "frontends/delta/flatpak/org.example.Delta.json",
          manifest("org.example.Delta", [git_source()]))
    # Not an app manifest (cargo-sources.json is a list): never touched.
    write(r, "frontends/alpha/flatpak/cargo-sources.json",
          [{"type": "git", "url": URL, "commit": OLD}])
    return r


def pins(repo):
    gitlink = git(repo, "ls-files", "-s", "fisherman").split()[1]
    out = {"fisherman": gitlink}
    for rel in fp.app_manifests(repo):
        with open(os.path.join(repo, rel), encoding="utf-8") as fh:
            out[rel] = fp.the_fisherman_source(json.load(fh), rel)["commit"]
    return out


def test_all_five_pins_move_together(repo):
    assert set(pins(repo).values()) == {OLD}
    assert len(pins(repo)) == 5

    moved = fp.set_all_pins(repo, NEW)

    assert set(moved.values()) == {OLD} and len(moved) == 4
    assert set(pins(repo).values()) == {NEW}
    # Staged, so the workflow's `git commit` carries all five.
    staged = set(git(repo, "diff", "--cached", "--name-only").split())
    assert staged == {"fisherman", *moved}


def test_only_the_commit_line_changes(repo):
    rel = "frontends/alpha/flatpak/org.example.Alpha.json"
    with open(os.path.join(repo, rel), encoding="utf-8") as fh:
        before = fh.read()

    fp.set_all_pins(repo, NEW)

    with open(os.path.join(repo, rel), encoding="utf-8") as fh:
        after = fh.read()
    assert after == before.replace(OLD, NEW)


def test_non_app_json_is_left_alone(repo):
    rel = "frontends/alpha/flatpak/cargo-sources.json"
    with open(os.path.join(repo, rel), encoding="utf-8") as fh:
        before = fh.read()
    fp.set_all_pins(repo, NEW)
    with open(os.path.join(repo, rel), encoding="utf-8") as fh:
        assert fh.read() == before


def test_already_current_is_a_no_op(repo):
    fp.set_all_pins(repo, NEW)
    moved = fp.set_all_pins(repo, NEW)
    assert set(moved.values()) == {NEW}
    assert set(pins(repo).values()) == {NEW}


def _assert_untouched(repo):
    assert set(pins_or_raw(repo)) == {OLD}


def pins_or_raw(repo):
    """Every fisherman commit in the tree, without requiring exactly one per file."""
    found = [git(repo, "ls-files", "-s", "fisherman").split()[1]]
    for rel in fp.app_manifests(repo):
        with open(os.path.join(repo, rel), encoding="utf-8") as fh:
            found += [s["commit"] for s in fp.fisherman_sources(json.load(fh))]
    return found


def test_missing_fisherman_source_fails_and_writes_nothing(repo):
    write(repo, "frontends/epsilon/flatpak/org.example.Epsilon.json",
          manifest("org.example.Epsilon", [{"type": "git", "url": "https://github.com/other/repo.git", "commit": OLD}]))

    with pytest.raises(fp.PinError, match=r"Epsilon\.json: expected exactly one .* found 0"):
        fp.set_all_pins(repo, NEW)

    _assert_untouched(repo)


def test_duplicated_fisherman_source_fails_and_writes_nothing(repo):
    write(repo, "frontends/epsilon/flatpak/org.example.Epsilon.json",
          manifest("org.example.Epsilon", [git_source(), git_source()]))

    with pytest.raises(fp.PinError, match=r"Epsilon\.json: expected exactly one .* found 2"):
        fp.set_all_pins(repo, NEW)

    _assert_untouched(repo)


def test_ambiguous_commit_text_fails(repo):
    """The old sha also pins another source: the text edit cannot tell which."""
    data = manifest("org.example.Epsilon", [git_source()])
    data["modules"][0]["sources"] = [{"type": "git", "url": "https://github.com/other/x.git", "commit": OLD}]
    write(repo, "frontends/epsilon/flatpak/org.example.Epsilon.json", data)

    with pytest.raises(fp.PinError, match="appears 2 times"):
        fp.set_all_pins(repo, NEW)
    _assert_untouched(repo)


def test_unpinned_fisherman_source_fails():
    text = json.dumps(manifest("org.example.X", [{"type": "git", "url": URL, "branch": "dev"}]))
    with pytest.raises(fp.PinError, match="no full commit pin"):
        fp.rewrite_manifest_text(text, NEW, "x.json")


def test_rejects_a_short_or_bad_sha(repo):
    with pytest.raises(fp.PinError, match="not a full commit sha"):
        fp.set_all_pins(repo, "b" * 7)


def test_no_manifests_fails(tmp_path):
    with pytest.raises(fp.PinError, match="no Flatpak app manifest"):
        fp.set_all_pins(str(tmp_path), NEW, stage=False)


@pytest.mark.parametrize("url,ok", [
    ("https://github.com/tuna-os/fisherman.git", True),
    ("https://github.com/tuna-os/fisherman", True),
    ("https://github.com/tuna-os/fisherman/", True),
    ("git@github.com:tuna-os/fisherman.git", True),
    ("https://github.com/bopp-os/fisherman.git", True),
    ("https://github.com/tuna-os/fisherman-fork.git", False),
    ("https://github.com/someone/fisherman.git", False),
    ("https://gitlab.com/tuna-os/fisherman.git", False),
    (None, False),
])
def test_fisherman_url_matching(url, ok):
    assert fp.is_fisherman_url(url) is ok


def test_cli_reports_errors_without_a_traceback(repo, capsys):
    write(repo, "frontends/epsilon/flatpak/org.example.Epsilon.json",
          manifest("org.example.Epsilon", []))
    assert fp.main(["--repo", repo, "--commit", NEW]) == 1
    assert "::error::" in capsys.readouterr().err
    _assert_untouched(repo)


def test_real_manifests_each_have_exactly_one_fisherman_pin():
    """The checked-in frontends satisfy what the bump relies on."""
    manifests = fp.app_manifests(REPO)
    assert manifests, "no frontend Flatpak app manifests found"
    for rel in manifests:
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            text = fh.read()
        source = fp.the_fisherman_source(json.loads(text), rel)
        new_text, old = fp.rewrite_manifest_text(text, NEW, rel)
        assert old == source["commit"]
        assert new_text == text.replace(old, NEW)
