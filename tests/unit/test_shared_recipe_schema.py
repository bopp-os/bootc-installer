"""The recipe schema is the contract every frontend writes against.

shared/recipe/fisherman-recipe.schema.json is the canonical copy. The KDE
frontend still installs its own copy from frontends/kde/ (its Flatpak builds
from that directory alone, so it cannot reach shared/ at build time). Until
that build reads the shared file, the two must stay byte-identical, or the
"shared" schema is a lie.
"""

import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = REPO / "shared" / "recipe" / "fisherman-recipe.schema.json"
KDE = REPO / "frontends" / "kde" / "fisherman-recipe.schema.json"


class SharedRecipeSchemaTests(unittest.TestCase):
    def test_shared_schema_is_valid_json_schema(self):
        doc = json.loads(SHARED.read_text())
        self.assertIn("$schema", doc)
        self.assertIn("properties", doc)
        for field in ("disk", "encryption", "image"):
            self.assertIn(field, doc["properties"], f"schema lost the '{field}' field")

    def test_schema_covers_every_fisherman_recipe_field(self):
        """Every top-level `json:"..."` tag on fisherman's Recipe struct is a
        schema property. The schema used to list 13 of the backend's 26
        fields, so a frontend validating against it could not express what
        GNOME already writes (user, slurp, varDisk, customMounts...)."""
        recipe_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "recipe.go"
        if not recipe_go.exists():
            self.skipTest("fisherman submodule not checked out")
        src = recipe_go.read_text()
        start = src.index("type Recipe struct {")
        end = src.index("\n}", start)
        tags = re.findall(r'`json:"([A-Za-z0-9]+)', src[start:end])
        self.assertTrue(tags, "could not read fisherman's Recipe struct")
        props = json.loads(SHARED.read_text())["properties"]
        missing = sorted(set(tags) - set(props))
        self.assertEqual(missing, [], f"fisherman recipe fields absent from the shared schema: {missing}")

    def _switch_cases(self, src, expr):
        """The string literals of the first `case` clause of `switch <expr> {`
        in fisherman's rules: the values its rule accepts."""
        start = src.index(f"switch {expr} {{")
        clause = src[start:src.index(":", src.index("case", start))]
        return set(re.findall(r'"([^"]*)"', clause))

    def test_enums_match_what_fisherman_accepts(self):
        """A schema enum narrower than fisherman's rules rejects recipes
        fisherman installs: GNOME writes bootloader "" when the image
        metadata names none, and fisherman then picks the image's default.
        The rules live in internal/recipe/rules.go since fisherman#277, the
        one rule set the install and `validate --json` share."""
        rules_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "rules.go"
        choices = REPO / "fisherman" / "data" / "encryption-choices.json"
        if not rules_go.exists() or not choices.exists():
            self.skipTest("fisherman submodule not checked out")
        src = rules_go.read_text()
        props = json.loads(SHARED.read_text())["properties"]
        filesystems = src[src.index("var Filesystems = []string{"):]
        filesystems = filesystems[:filesystems.index("}")]
        # "" is accepted as "none" (LookupEncryption).
        enc_types = {c["type"] for c in json.loads(choices.read_text())["choices"]} | {""}
        cases = {
            "bootloader": (self._switch_cases(src, "b"), props["bootloader"]["enum"]),
            "encryption.type": (enc_types, props["encryption"]["properties"]["type"]["enum"]),
            "filesystem": (set(re.findall(r'"([^"]*)"', filesystems)),
                           props["filesystem"]["enum"]),
        }
        for field, (accepted, enum) in cases.items():
            with self.subTest(field=field):
                self.assertTrue(accepted, f"could not read fisherman's {field} rule")
                self.assertEqual(sorted(enum), sorted(accepted),
                                 f"schema enum for {field} differs from fisherman's rules")

    def test_hostname_and_username_patterns_follow_fishermans_rules(self):
        """The schema's patterns accept what fisherman's CheckHostname and
        CheckUsername accept, on the cases fisherman/docs/VALIDATE.md names.
        (Reserved usernames are a list, not a pattern: the schema cannot
        express them, `fisherman validate --json` reports them.)"""
        props = json.loads(SHARED.read_text())["properties"]
        host = props["hostname"]
        user = props["user"]["properties"]["username"]["pattern"]
        accepted = ["my-pc", "MyPC", "pc.example.com", "a", "a" * 63, "a." * 31 + "ab"]
        rejected = ["", "my_pc", "-router", "router-", "a..b", ".a", "a.", "a" * 64,
                    "a" * 63 + "." + "b"]
        for h in accepted:
            with self.subTest(hostname=h):
                self.assertRegex(h, host["pattern"])
                self.assertLessEqual(len(h), host["maxLength"])
        for h in rejected:
            with self.subTest(hostname=h):
                ok = re.fullmatch(host["pattern"], h) and len(h) <= host["maxLength"]
                self.assertFalse(ok, f"{h!r} should be rejected")
        for u in ["", "alice", "_svc", "a-b_c9", "a" * 32]:
            self.assertRegex(u, user)
        for u in ["Alice", "1abc", "a b", "a" * 33, "al.ice"]:
            self.assertIsNone(re.fullmatch(user, u), u)

    def test_kde_copy_matches_shared(self):
        self.assertEqual(
            KDE.read_bytes(), SHARED.read_bytes(),
            "frontends/kde/fisherman-recipe.schema.json has diverged from "
            "shared/recipe/fisherman-recipe.schema.json; change the shared copy "
            "and copy it over, not the other way round",
        )


if __name__ == "__main__":
    unittest.main()
