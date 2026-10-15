"""shared/recipe/fisherman_validate.py: the reader every Python frontend uses
for `fisherman validate --json` and the encryption choices file.

1. The GNOME and XFCE copies are byte-identical to the canonical one.
2. The reader parses every golden answer fisherman's own tests pin
   (fisherman/cmd/fisherman/testdata/validate/*.golden).
3. The partial recipe goes to fisherman on stdin, and argv ends in `-`:
   a partial recipe can hold the LUKS passphrase, and argv is
   world-readable in /proc.
4. LiveCheck debounces, runs off the UI thread, and drops stale answers.
5. Every problem code fisherman can report has a `validate_<code>` copy key.
"""

import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "shared" / "recipe"))

import fisherman_validate as fv  # noqa: E402

CANONICAL = REPO / "shared" / "recipe" / "fisherman_validate.py"
COPIES = [
    REPO / "bootc_installer" / "core" / "fisherman_validate.py",
    REPO / "frontends" / "xfce" / "tuna_installer_xfce" / "fisherman_validate.py",
]
GOLDEN = REPO / "fisherman" / "fisherman" / "cmd" / "fisherman" / "testdata" / "validate"
RULES_GO = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "rules.go"
COPY_DEFAULTS = REPO / "shared" / "branding" / "copy-defaults.json"


def fisherman_codes():
    src = RULES_GO.read_text()
    block = src.split("const (", 1)[1].split(")", 1)[0]
    return set(re.findall(r'Code[A-Za-z0-9]+\s*=\s*"([a-z0-9_]+)"', block))


class TestCopies(unittest.TestCase):
    def test_copies_are_byte_identical(self):
        canonical = CANONICAL.read_bytes()
        for copy in COPIES:
            with self.subTest(copy=str(copy.relative_to(REPO))):
                self.assertEqual(copy.read_bytes(), canonical,
                                 f"{copy} drifted from shared/recipe/fisherman_validate.py")


@unittest.skipUnless(GOLDEN.is_dir(), "fisherman submodule not checked out")
class TestGoldenAnswers(unittest.TestCase):
    def test_every_golden_parses(self):
        goldens = sorted(GOLDEN.glob("*.golden"))
        self.assertGreater(len(goldens), 5)
        for path in goldens:
            with self.subTest(golden=path.name):
                result = fv.parse(path.read_text())
                self.assertEqual(result["valid"], result["errors"] == [])

    def test_partial_hostname_renders_its_copy_key(self):
        result = fv.parse((GOLDEN / "partial-hostname.golden").read_text())
        [problem] = fv.problems(result, "hostname")
        self.assertEqual(problem["code"], "hostname_label_hyphen")
        copy = json.loads(COPY_DEFAULTS.read_text())
        self.assertEqual(fv.render(problem, copy.get), copy["validate_hostname_label_hyphen"])

    def test_problems_filters_by_field(self):
        result = fv.parse((GOLDEN / "partial-user.golden").read_text())
        self.assertEqual(fv.problems(result, "hostname"), [])
        self.assertEqual([p["code"] for p in fv.problems(result, "user.username")],
                         ["username_reserved"])


class TestParse(unittest.TestCase):
    def test_rejects_garbage(self):
        for text in ("", "not json", "[]", '{"protocol_version": 2, "errors": []}',
                     '{"protocol_version": 1}'):
            with self.subTest(text=text):
                with self.assertRaises(fv.ValidateError):
                    fv.parse(text)

    def test_an_unknown_code_shows_fishermans_message(self):
        problem = {"field": "hostname", "code": "hostname_new_rule", "message": "say why"}
        self.assertEqual(fv.render(problem, {}.get), "say why")

    def test_an_empty_copy_line_falls_back_to_the_message(self):
        problem = {"code": "hostname_required", "message": "hostname is required"}
        self.assertEqual(fv.render(problem, lambda key: ""), "hostname is required")


class TestRun(unittest.TestCase):
    """run() against a stand-in fisherman that records what it was given."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.seen_args = os.path.join(self.tmp, "args")
        self.seen_stdin = os.path.join(self.tmp, "stdin")
        self.fake = os.path.join(self.tmp, "fisherman")
        with open(self.fake, "w") as fh:
            fh.write(
                "#!/bin/sh\n"
                f'printf "%s\\n" "$@" > {self.seen_args}\n'
                f"cat > {self.seen_stdin}\n"
                'printf \'{"protocol_version":1,"valid":false,"errors":'
                '[{"field":"hostname","code":"hostname_required","message":"m"}]}\'\n'
                "exit ${FAKE_EXIT:-1}\n")
        os.chmod(self.fake, stat.S_IRWXU)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_recipe_goes_on_stdin_and_argv_ends_in_dash(self):
        recipe = {"hostname": "", "encryption": {"type": "luks-passphrase",
                                                 "passphrase": "s3cret"}}
        result = fv.run(fv.argv([self.fake]), recipe)
        self.assertEqual([p["code"] for p in fv.problems(result)], ["hostname_required"])
        with open(self.seen_args) as fh:
            args = fh.read().split()
        self.assertEqual(args, ["validate", "--json", "--partial", "-"])
        self.assertNotIn("s3cret", " ".join(args))
        with open(self.seen_stdin) as fh:
            self.assertEqual(json.load(fh), recipe)

    def test_full_mode_has_no_partial_flag(self):
        self.assertEqual(fv.argv(["fisherman"], partial=False),
                         ["fisherman", "validate", "--json", "-"])

    def test_flatpak_prefix_is_kept(self):
        self.assertEqual(fv.argv(["flatpak-spawn", "--host", "/f"])[:3],
                         ["flatpak-spawn", "--host", "/f"])

    def test_a_bad_exit_is_an_error_not_a_verdict(self):
        os.environ["FAKE_EXIT"] = "2"
        try:
            with self.assertRaises(fv.ValidateError):
                fv.run([self.fake], {})
        finally:
            del os.environ["FAKE_EXIT"]

    def test_a_missing_binary_is_an_error(self):
        with self.assertRaises(fv.ValidateError):
            fv.run([os.path.join(self.tmp, "nope")], {})


class FakeLoop:
    """Collects timers and idle callbacks; runs them when asked."""

    def __init__(self):
        self.timers = {}
        self.idle = []
        self.next_id = 1
        self.threads = []

    def timeout_add(self, ms, fn):
        self.next_id += 1
        self.timers[self.next_id] = fn
        return self.next_id

    def source_remove(self, source):
        self.timers.pop(source, None)

    def idle_add(self, fn, *args):
        self.idle.append((fn, args))

    def start_thread(self, fn):
        self.threads.append(fn)

    def run_all(self):
        for fn in list(self.timers.values()):
            fn()
        self.timers.clear()
        for fn in self.threads:
            fn()
        self.threads.clear()
        for fn, args in self.idle:
            fn(*args)
        self.idle.clear()


class TestLiveCheck(unittest.TestCase):
    def make(self, runner):
        self.loop = FakeLoop()
        self.results = []
        self.asked = []

        def recording_runner(command, recipe):
            self.asked.append(recipe)
            return runner(command, recipe)

        return fv.LiveCheck(["f", "validate"], lambda p, e: self.results.append((p, e)),
                            timeout_add=self.loop.timeout_add,
                            source_remove=self.loop.source_remove,
                            idle_add=self.loop.idle_add,
                            runner=recording_runner,
                            start_thread=self.loop.start_thread)

    def test_typing_is_debounced_to_one_check(self):
        check = self.make(lambda c, r: {"protocol_version": 1, "valid": True, "errors": []})
        for text in ("m", "my", "my-pc"):
            check.submit({"hostname": text})
        self.assertTrue(check.pending)
        self.assertEqual(len(self.loop.timers), 1)
        self.loop.run_all()
        self.assertEqual(self.asked, [{"hostname": "my-pc"}])
        self.assertEqual(self.results, [([], None)])
        self.assertFalse(check.pending)

    def test_a_stale_answer_is_dropped(self):
        check = self.make(lambda c, r: {"protocol_version": 1, "valid": True, "errors": []})
        check.submit({"hostname": "a"})
        for fn in list(self.loop.timers.values()):
            fn()
        self.loop.timers.clear()
        check.submit({"hostname": "ab"})  # typed again while the first ran
        self.loop.run_all()
        self.assertEqual(len(self.results), 1, "only the latest answer is delivered")

    def test_a_failure_is_reported_as_an_error(self):
        def broken(c, r):
            raise fv.ValidateError("cannot run fisherman validate")
        check = self.make(broken)
        check.submit({"hostname": "x"})
        self.loop.run_all()
        self.assertEqual(self.results, [(None, "cannot run fisherman validate")])


class TestEncryptionChoices(unittest.TestCase):
    def test_the_shared_file_loads_in_order(self):
        choices = fv.load_choices(REPO / "shared" / "recipe" / "encryption-choices.json")
        self.assertEqual([c["type"] for c in choices],
                         ["none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"])
        self.assertTrue(fv.needs_passphrase("tpm2-luks-passphrase", choices))
        self.assertFalse(fv.needs_passphrase("tpm2-luks", choices))
        self.assertTrue(fv.needs_tpm2("tpm2-luks", choices))
        self.assertFalse(fv.needs_tpm2("", choices))
        self.assertIsNone(fv.choice("luks", choices))


@unittest.skipUnless(RULES_GO.exists(), "fisherman submodule not checked out")
class TestCopyKeys(unittest.TestCase):
    def test_every_code_has_a_copy_key(self):
        copy = json.loads(COPY_DEFAULTS.read_text())
        codes = fisherman_codes()
        self.assertGreater(len(codes), 20)
        missing = sorted(c for c in codes if not copy.get(fv.copy_key(c), "").strip())
        self.assertEqual(missing, [], "add validate_<code> to shared/branding/copy-defaults.json")

    def test_no_copy_key_names_a_code_fisherman_lacks(self):
        copy = json.loads(COPY_DEFAULTS.read_text())
        codes = fisherman_codes()
        stale = sorted(k for k in copy if k.startswith(fv.COPY_PREFIX)
                       and k[len(fv.COPY_PREFIX):] not in codes)
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
