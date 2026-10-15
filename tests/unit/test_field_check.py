"""bootc_installer/utils/field_check.py: one entry checked by fisherman.

The page shows the problem fisherman reports, in the words of the copy key
validate_<code>, and asks `ok` before enabling Next. A check that cannot run
blocks nothing: the install runs the same rules before it touches a disk.
"""

import unittest

from bootc_installer.utils import field_check


class FakeEntry:
    def __init__(self, text=""):
        self.text = text
        self.css = set()
        self.handlers = []

    def get_text(self):
        return self.text

    def connect(self, signal, fn):
        self.handlers.append(fn)

    def type(self, text):
        self.text = text
        for fn in self.handlers:
            fn(self)

    def add_css_class(self, c):
        self.css.add(c)

    def remove_css_class(self, c):
        self.css.discard(c)


class FakeLabel:
    def __init__(self):
        self.visible = None
        self.label = ""

    def set_visible(self, v):
        self.visible = v

    def set_label(self, t):
        self.label = t


class FakeLiveCheck:
    def __init__(self, on_result):
        self.on_result = on_result
        self.submitted = []

    def submit(self, recipe):
        self.submitted.append(recipe)


class FakeWindow:
    recipe = {"branding": {"name": "Example", "copy": {
        "validate_hostname_invalid_char": "No underscores, please."}}}


class TestFieldCheck(unittest.TestCase):
    def setUp(self):
        self.entry = FakeEntry()
        self.label = FakeLabel()
        self.changes = 0
        self.live = None

        def factory(on_result):
            self.live = FakeLiveCheck(on_result)
            return self.live

        def changed():
            self.changes += 1

        self.check = field_check.FieldCheck(
            FakeWindow(), self.entry, "hostname", lambda t: {"hostname": t.strip()},
            self.label, on_change=changed, live_check_factory=factory)

    def test_typing_submits_a_partial_recipe(self):
        self.entry.type(" my_pc ")
        self.assertEqual(self.live.submitted, [{"hostname": "my_pc"}])

    def test_a_problem_marks_the_entry_and_shows_the_copy(self):
        self.entry.type("my_pc")
        self.live.on_result([{"field": "hostname", "code": "hostname_invalid_char",
                              "message": "hostname contains '_'"}], None)
        self.assertFalse(self.check.ok)
        self.assertIn("error", self.entry.css)
        self.assertTrue(self.label.visible)
        self.assertEqual(self.label.label, "No underscores, please.")
        self.assertEqual(self.changes, 1)

    def test_the_neutral_copy_is_the_default(self):
        self.live.on_result([{"field": "hostname", "code": "hostname_label_hyphen",
                              "message": "m"}], None)
        self.assertEqual(self.label.label,
                         "A part of the computer name cannot start or end with a hyphen.")

    def test_an_unknown_code_shows_fishermans_message(self):
        self.live.on_result([{"field": "hostname", "code": "hostname_brand_new",
                              "message": "fisherman says no"}], None)
        self.assertEqual(self.label.label, "fisherman says no")

    def test_a_fix_clears_the_problem(self):
        self.live.on_result([{"field": "hostname", "code": "hostname_required",
                              "message": "m"}], None)
        self.live.on_result([], None)
        self.assertTrue(self.check.ok)
        self.assertNotIn("error", self.entry.css)
        self.assertFalse(self.label.visible)

    def test_another_fields_problem_is_not_this_ones(self):
        self.live.on_result([{"field": "user.username", "code": "username_reserved",
                              "message": "m"}], None)
        self.assertTrue(self.check.ok)

    def test_a_check_that_cannot_run_blocks_nothing(self):
        self.live.on_result(None, "cannot run /usr/local/bin/fisherman: not found")
        self.assertTrue(self.check.ok)
        self.assertFalse(self.label.visible)

    def test_the_command_is_unprivileged_partial_and_on_stdin(self):
        argv = field_check.validate_command()
        self.assertEqual(argv[-4:], ["validate", "--json", "--partial", "-"])
        self.assertNotIn("pkexec", argv)
        self.assertNotIn("sudo", argv)


if __name__ == "__main__":
    unittest.main()
