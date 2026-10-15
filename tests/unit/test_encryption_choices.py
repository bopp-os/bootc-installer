"""Every frontend offers the same encryption choices, in the same order, in
the same words.

The ids and their order are the `encryption.type` enum of
shared/recipe/fisherman-recipe.schema.json. The words are branding copy
(`encryption_<type>_label` / `_description` in
shared/branding/copy-defaults.json). Each frontend keeps only the list of
ids its page iterates, because its own logic branches on them (TPM gating,
the passphrase field); this test holds each list to the schema.

Before the copy keys existed, each frontend carried its own table of ids,
labels and descriptions. The four encryption pages happened to agree, but
the confirm pages did not: KDE said "None" and "Passphrase (LUKS)", GNOME
"Encrypted with passphrase", and COSMIC, Niri and Xfce printed the raw id.
"""

import json
import re
import unittest

from tests.unit.test_copy_coverage import (
    BEGIN, COMMENT_MARKERS, END, REPO, encryption_key, encryption_types,
    sources_for, strip_comments,
)

# Where each frontend's encryption page gets its ids: (file, the text that
# opens the list). Every quoted string between it and the closing bracket
# is an id, in display order.
# Empty since every frontend with a list reads fisherman's file instead
# (LOADS_THE_FILE); kept so a frontend that brings a literal list back is
# held to the order.
CHOICE_LISTS = {}
CLOSERS = {"(": ")", "[": "]", "{": "}"}

# The frontends that read their copy of encryption-choices.json instead of
# keeping a list: (file, the text that shows it reads the copy). Their order
# and their passphrase / TPM logic are then the file's.
LOADS_THE_FILE = {
    "kde": [("frontends/kde/CMakeLists.txt", 'encryption-choices.json" TUNA_ENCRYPTION_CHOICES_JSON'),
            ("frontends/kde/src/recipe.cpp", '#include "encryption_choices.h"')],
    "xfce": [("frontends/xfce/tuna_installer_xfce/core.py",
              "fisherman_validate.load_choices()")],
    "cosmic": [("frontends/cosmic/src/validate.rs", 'include_str!("encryption-choices.json")'),
               ("frontends/cosmic/src/main.rs", "validate::choices()")],
    "niri": [("frontends/niri/installer/validate.go", "//go:embed encryption-choices.json"),
             ("frontends/niri/installer/main.go", '"encryptionChoices": encryptionChoices()'),
             ("frontends/niri/ui/installer.qml", "root.encryptionChoices = facts.encryptionChoices")],
}
# What logic on the type's name looked like before the file had
# needs_passphrase and needs_tpm2.
NAME_LOGIC = re.compile(
    r"""["']passphrase["']\s+in\b|contains\(\s*"passphrase"|endsWith\(\s*(?:QLatin1String\()?"passphrase"|"""
    r"""HasSuffix\([^)]*"passphrase"|startswith\(\s*["']tpm2|startsWith\(\s*(?:QLatin1String\()?"tpm2"|"""
    r"""HasPrefix\([^)]*["]tpm2""" + '"')

# The defaults' distinctive words, and the confirm-page labels that drifted
# from them. "Passphrase" and "TPM" alone are left out: every frontend
# labels its passphrase field "Passphrase", which is not a choice label.
NOT_IN_FRONTEND_SOURCE = (
    "No encryption",
    "TPM + passphrase",
    "Anyone with the disk can read your files.",
    "You'll type it at every boot.",
    "Unlocks automatically on this hardware.",
    "Automatic unlock, passphrase as fallback.",
    "Passphrase (LUKS)",
    "Encrypted with passphrase",
    "Hardware-backed encryption",
    "Hardware-backed + passphrase fallback",
)

# How the confirm pages printed the raw recipe id.
RAW_ID_ON_CONFIRM = {
    "xfce": "{r['encryption']['type']}",
    "niri": "StyledText { text: root.encType;",
    "cosmic": "recipe.encryption.enc_type.clone()",
}


def choice_list(frontend):
    path, opener = CHOICE_LISTS[frontend]
    text = (REPO / path).read_text()
    start = text.index(opener) + len(opener)
    body = text[start:text.index(CLOSERS[opener[-1]], start)]
    return re.findall(r'"([^"]*)"', body)


def frontend_code(frontend):
    """Each source file of a frontend, comments, generated tables and Rust
    test modules removed: a test asserting the default words is not a
    frontend carrying its own."""
    for path in sources_for(frontend):
        text = path.read_text(errors="replace")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            text = head + rest.split(END, 1)[1]
        if path.suffix == ".rs":
            text = text.split("#[cfg(test)]", 1)[0]
        yield path, strip_comments(text, COMMENT_MARKERS[path.suffix])


# fisherman's table of encryption types (data/encryption-choices.json,
# generated from recipe.EncryptionChoices), copied byte for byte. The
# frontends that build from their own directory carry a further copy each.
CHOICES = REPO / "shared" / "recipe" / "encryption-choices.json"
CHOICES_UPSTREAM = REPO / "fisherman" / "data" / "encryption-choices.json"
CHOICES_COPIES = {
    "kde": REPO / "frontends" / "kde" / "encryption-choices.json",
    "cosmic": REPO / "frontends" / "cosmic" / "src" / "encryption-choices.json",
    "niri": REPO / "frontends" / "niri" / "installer" / "encryption-choices.json",
    "xfce": REPO / "frontends" / "xfce" / "tuna_installer_xfce" / "encryption-choices.json",
}


def choice_types():
    return [c["type"] for c in json.loads(CHOICES.read_text())["choices"]]


class TheChoicesFileIsFishermans(unittest.TestCase):
    def test_shared_copy_is_byte_identical_to_the_submodule(self):
        if not CHOICES_UPSTREAM.exists():
            self.skipTest("fisherman submodule not checked out")
        self.assertEqual(
            CHOICES.read_bytes(), CHOICES_UPSTREAM.read_bytes(),
            "shared/recipe/encryption-choices.json drifted from fisherman's "
            "data/encryption-choices.json; copy it again after a submodule bump")

    def test_frontend_copies_are_byte_identical(self):
        for frontend, path in CHOICES_COPIES.items():
            with self.subTest(frontend=frontend):
                self.assertEqual(path.read_bytes(), CHOICES.read_bytes(),
                                 f"{path.relative_to(REPO)} drifted from {CHOICES.relative_to(REPO)}")

    def test_the_file_is_the_schema_enum_in_order(self):
        self.assertEqual(choice_types(), encryption_types())

    def test_every_choice_names_its_copy_key(self):
        for c in json.loads(CHOICES.read_text())["choices"]:
            self.assertEqual(c["copy_key"], encryption_key(c["type"], ""))


class EveryFrontendOffersTheSchemaTypes(unittest.TestCase):
    def test_the_schema_lists_the_four_types(self):
        self.assertEqual(encryption_types(),
                         ["none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"])

    def test_each_list_is_the_schema_enum_in_order(self):
        for frontend in CHOICE_LISTS:
            with self.subTest(frontend=frontend):
                self.assertEqual(choice_list(frontend), encryption_types())

    def test_every_type_has_copy(self):
        from tests.unit.test_copy_coverage import contract_keys
        keys = contract_keys()
        for enc_type in encryption_types():
            for suffix in ("_label", "_description"):
                key = encryption_key(enc_type, suffix)
                self.assertTrue(keys.get(key, "").strip(), f"{key} missing or empty")

    def test_kde_module_iterates_the_controller_list(self):
        # The QML used to hold four hand-written radio rows. It now repeats
        # over InstallerController.encryptionTypes, i.e. recipe.cpp's list.
        qml = (REPO / "frontends/kde/modules/encryption/contents/ui/main.qml").read_text()
        code = strip_comments(qml, "//")
        self.assertIn("model: InstallerController.encryptionTypes", code)
        for enc_type in encryption_types():
            self.assertNotIn(f'"{enc_type}"', code)

    def test_every_type_shaped_literal_is_a_schema_type(self):
        # COSMIC once wrote "luks", which fisherman rejects, so the install
        # never started. Every "luks-..." or "tpm2-luks..." literal in a
        # frontend must be one of the schema's types. (Bare "luks" is left
        # out: GNOME's done page searches the log for it.)
        allowed = set(encryption_types())
        pattern = re.compile(r'"(luks-[a-z0-9-]+|tpm2-luks[a-z0-9-]*)"')
        for frontend in ("gnome", *LOADS_THE_FILE, *CHOICE_LISTS):
            for path, code in frontend_code(frontend):
                for literal in pattern.findall(code):
                    self.assertIn(literal, allowed, f"{path.relative_to(REPO)}: {literal!r}")


class NoFrontendCarriesItsOwnWords(unittest.TestCase):
    def test_no_choice_label_or_description_is_hardcoded(self):
        for frontend in ("gnome", *LOADS_THE_FILE, *CHOICE_LISTS):
            for path, code in frontend_code(frontend):
                for line in NOT_IN_FRONTEND_SOURCE:
                    for quoted in (f'"{line}"', f"'{line}'"):
                        self.assertFalse(
                            quoted in code,
                            f"{path.relative_to(REPO)} hardcodes {line!r}; read the "
                            "encryption_* copy key instead",
                        )

    def test_no_confirm_page_prints_the_raw_id(self):
        for frontend, raw in RAW_ID_ON_CONFIRM.items():
            with self.subTest(frontend=frontend):
                code = "\n".join(c for _, c in frontend_code(frontend))
                self.assertFalse(raw in code, f"{frontend} prints {raw}")


class FrontendsReadTheFile(unittest.TestCase):
    def test_each_reads_its_copy(self):
        for frontend, markers in LOADS_THE_FILE.items():
            for path, marker in markers:
                with self.subTest(frontend=frontend, path=path):
                    self.assertIn(marker, (REPO / path).read_text())

    def test_no_frontend_that_reads_the_file_keeps_a_list(self):
        for frontend in LOADS_THE_FILE:
            for path, code in frontend_code(frontend):
                with self.subTest(path=str(path.relative_to(REPO))):
                    self.assertNotIn('"tpm2-luks-passphrase"', code)

    def test_no_frontend_decides_by_the_types_name(self):
        """needs_passphrase and needs_tpm2 come from the file. A frontend
        that tests the name for "passphrase" or "tpm2" re-implements them."""
        for frontend in LOADS_THE_FILE:
            for path, code in frontend_code(frontend):
                with self.subTest(path=str(path.relative_to(REPO))):
                    self.assertIsNone(NAME_LOGIC.search(code))


class TheParserReadsRealLists(unittest.TestCase):
    """Guards the guard: an opener that no longer matches raises, and one
    that matched the wrong bracket would return the wrong count."""

    def test_each_list_has_four_entries(self):
        for frontend in CHOICE_LISTS:
            with self.subTest(frontend=frontend):
                self.assertEqual(len(choice_list(frontend)), 4)


if __name__ == "__main__":
    unittest.main()
