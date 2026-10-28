"""No frontend looks for live media or offline stores itself, or writes the
recipe to a file (ROADMAP.md, Consolidation plan F3).

fisherman answers both on the host: `fisherman probe --json` reports
`live` and `offline`, and an install whose recipe leaves
additionalImageStores out exposes the host's stores itself
(fisherman#276). Four frontends used to search for the stores inside their
Flatpak sandbox, where the host's /etc and /usr are not visible, and GNOME
treated every ostree host as live media because it read /run/ostree-booted.
And every frontend wrote the recipe, LUKS passphrase included, to a
temporary file; fisherman now reads it on stdin (`fisherman -`).

The scan reads each frontend's own code with comments (and Rust test
modules) removed, the way tests/unit/test_shared_probe.py does for lsblk.
"""

import re
import unittest

from tests.unit.test_copy_coverage import COMMENT_MARKERS, REPO, sources_for, strip_comments

FRONTENDS = ("gnome", "kde", "cosmic", "niri", "xfce")

# What a frontend's own detection looked like.
DETECTION = {
    "live media": re.compile(
        r'["\'](?:/run/ostree-booted|/run/ostree-live|/run/initramfs/live)["\']'
        r'|rd\.live\.image|live-iso-mode'
        r'|["\']bootc["\']\s*,\s*["\']status["\']'),
    "offline stores": re.compile(
        r'TUNA_OFFLINE_STORES|/etc/tuna-installer/offline-stores|oci-store'
        r'|["\']podman["\']'),
    "a recipe file": re.compile(
        r'\b(?:write_recipe|writeRecipe|recipe_dir|recipeDir|cleanup_recipe_file|m_recipePath)\b'),
}

# How each frontend hands the recipe over: the fisherman command reads `-`.
STDIN_COMMAND = {
    "gnome": ("bootc_installer/utils/fisherman_runner.py", "{NATIVE_PATH} -"),
    "kde": ("frontends/kde/src/offline.cpp", 'pkexec /usr/local/bin/fisherman -; exit $?'),
    "cosmic": ("frontends/cosmic/src/offline.rs", "pkexec /usr/local/bin/fisherman -; exit $?"),
    "niri": ("frontends/niri/installer/offline.go", "pkexec /usr/local/bin/fisherman -; exit $?"),
    "xfce": ("frontends/xfce/tuna_installer_xfce/core.py", "pkexec /usr/local/bin/fisherman -; exit $?"),
}


def frontend_files(frontend):
    """(path, code) for a frontend's own sources, comments removed."""
    paths = list(sources_for(frontend))
    if frontend == "niri":
        paths += [p for p in (REPO / "frontends/niri/installer").glob("*.go")
                  if not p.name.endswith("_test.go")]
    for path in paths:
        text = path.read_text(errors="replace")
        if path.suffix == ".rs":
            text = text.split("#[cfg(test)]", 1)[0]
        marker = COMMENT_MARKERS.get(path.suffix, "//")
        yield path, strip_comments(text, marker)


class NoFrontendDetectsItself(unittest.TestCase):
    def test_no_frontend_looks_for_live_media_offline_stores_or_writes_a_recipe(self):
        for frontend in FRONTENDS:
            for path, code in frontend_files(frontend):
                for what, pattern in DETECTION.items():
                    with self.subTest(frontend=frontend, what=what):
                        found = pattern.search(code)
                        self.assertIsNone(
                            found,
                            f"{path.relative_to(REPO)} looks for {what} itself "
                            f"({found.group(0) if found else ''!r}); read fisherman's probe, "
                            "leave additionalImageStores out, and pipe the recipe to `fisherman -` "
                            "(shared/recipe/README.md)")

    def test_every_frontend_pipes_the_recipe_to_fisherman_dash(self):
        for frontend, (path, needle) in STDIN_COMMAND.items():
            with self.subTest(frontend=frontend):
                self.assertIn(needle, (REPO / path).read_text())

    def test_the_scan_sees_code(self):
        """Guards the guard: the patterns match what used to be there."""
        old = {
            "live media": 'os.path.exists("/run/ostree-booted")',
            "offline stores": 'host_run(["podman", "images"])',
            "a recipe file": "path = core.write_recipe(recipe)",
        }
        for what, sample in old.items():
            self.assertIsNotNone(DETECTION[what].search(sample), what)
        self.assertIsNotNone(DETECTION["live media"].search('runHost("bootc", "status", "--json")'))
        for frontend in FRONTENDS:
            self.assertGreater(len(list(frontend_files(frontend))), 2, frontend)


if __name__ == "__main__":
    unittest.main()
