"""Unit tests for progress.py — no display required."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


# Ensure the repo root is on the path so imports work without installation.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _mock_gtk_imports():
    """Inject mock GTK modules so progress.py can be imported without a display."""
    mocks = {}
    for name in [
        "gi", "gi.repository", "gi.repository.Gdk", "gi.repository.Gio",
        "gi.repository.GLib", "gi.repository.Gtk", "gi.repository.Adw",
        "gi.repository.Pango", "gi.repository.GdkPixbuf",
        "bootc_installer.views.tour", "bootc_installer.utils.run_async",
    ]:
        mocks[name] = MagicMock()
    # gi.require_version must be a callable no-op
    mocks["gi"].require_version = MagicMock()
    return mocks


class TestFishermanArgvDirect(unittest.TestCase):
    """_fisherman_argv_direct must return an argv that shell-redirects fisherman
    stdout+stderr into the log file on the host.

    Flatpak case: bash runs on the HOST via flatpak-spawn so the redirect
    happens where fisherman runs — not through the D-Bus proxy.
    """

    @classmethod
    def setUpClass(cls):
        with patch.dict("sys.modules", _mock_gtk_imports()):
            import importlib
            import bootc_installer.views.progress as mod
            # Force a fresh load with mocked GTK in case cached without mocks
            if not hasattr(mod, "_fisherman_argv_direct"):
                importlib.reload(mod)
            cls.mod = mod

    def _argv(self, in_flatpak: bool, live: bool):
        """The argv for a host that fisherman's probe calls live or not."""
        self.mod._IN_FLATPAK = in_flatpak
        with patch("bootc_installer.core.system.Systeminfo.is_live", return_value=live):
            return self.mod._fisherman_argv_direct()

    def _script(self, argv: list) -> str:
        """Return the shell script string from an argv (element after '-c')."""
        idx = argv.index("-c")
        return argv[idx + 1]

    def test_returns_list_of_strings(self):
        argv = self._argv(False, False)
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_the_recipe_is_read_from_stdin(self):
        """fisherman reads the recipe from stdin (`fisherman -`): no path is
        passed, so no recipe file can exist to be passed."""
        for flatpak, live in ((False, False), (False, True), (True, False)):
            with self.subTest(flatpak=flatpak, live=live):
                argv = self._argv(flatpak, live)
                self.assertEqual(argv[-2], "-c")
                self.assertRegex(self._script(argv), r'fisherman"? - >')
                self.assertNotIn(".json", " ".join(argv))

    def test_flatpak_normal_runs_bash_on_host(self):
        """Flatpak: bash must run on the HOST so the log redirect works."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOTC_TEST", None)
            argv = self._argv(in_flatpak=True, live=False)
        self.assertEqual(argv[0], "flatpak-spawn")
        self.assertIn("--host", argv)
        self.assertIn("bash", argv)
        script = self._script(argv)
        self.assertIn("pkexec", script)
        self.assertNotIn("flatpak-spawn", script)

    def test_flatpak_bootc_test(self):
        """BOOTC_TEST env: uses sudo with custom fisherman path on the host."""
        with patch.dict(os.environ, {"BOOTC_TEST": "1", "BOOTC_FISHERMAN_PATH": "/custom/fisherman"}):
            argv = self._argv(in_flatpak=True, live=False)
        self.assertEqual(argv[0], "flatpak-spawn")
        self.assertIn("--host", argv)
        script = self._script(argv)
        self.assertIn("sudo", script)
        self.assertIn("/custom/fisherman", script)
        self.assertNotIn("flatpak-spawn", script)

    def test_live_media_uses_sudo(self):
        argv = self._argv(in_flatpak=False, live=True)
        self.assertEqual(argv[0], "bash")
        script = self._script(argv)
        self.assertIn("sudo", script)
        self.assertIn("/usr/local/bin/fisherman", script)

    def test_an_installed_host_uses_pkexec(self):
        """An installed bootc desktop is not live media, whatever
        /run/ostree-booted says: that file is on every ostree host."""
        argv = self._argv(in_flatpak=False, live=False)
        self.assertEqual(argv[0], "bash")
        script = self._script(argv)
        self.assertIn("pkexec", script)
        self.assertIn("/usr/local/bin/fisherman", script)

    def test_log_file_redirected_in_script(self):
        """The shell script must redirect output to the log file."""
        argv = self._argv(False, False)
        script = self._script(argv)
        self.assertIn(">", script)
        self.assertIn(self.mod._FISHERMAN_LOG_PATH, script)


class TestStagingPathIsPrivate(unittest.TestCase):
    """_path_is_private gates the binary that gets handed to pkexec.

    The staged copy of fisherman is executed as root, so any path component
    another account can influence is a privilege-escalation primitive. These
    cover the cases the check exists to reject; the same-uid race is NOT
    covered because no stat-then-exec check can close it.
    """

    @classmethod
    def setUpClass(cls):
        with patch.dict("sys.modules", _mock_gtk_imports()):
            import importlib
            import bootc_installer.views.progress as mod
            if not hasattr(mod, "_path_is_private"):
                importlib.reload(mod)
            cls.mod = mod

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def test_missing_path_is_allowed(self):
        """We are about to create it; absent is not suspicious."""
        self.assertTrue(self.mod._path_is_private(os.path.join(self.tmp, "nope")))

    def test_private_file_is_allowed(self):
        path = os.path.join(self.tmp, "fisherman")
        with open(path, "w"):
            pass
        os.chmod(path, 0o700)
        self.assertTrue(self.mod._path_is_private(path))

    def test_world_writable_is_rejected(self):
        """The pre-created-directory attack: someone else owns where we stage."""
        path = os.path.join(self.tmp, "cache")
        os.mkdir(path)
        os.chmod(path, 0o777)
        self.assertFalse(self.mod._path_is_private(path))

    def test_group_writable_is_rejected(self):
        path = os.path.join(self.tmp, "cache")
        os.mkdir(path)
        os.chmod(path, 0o775)
        self.assertFalse(self.mod._path_is_private(path))

    def test_symlink_is_rejected(self):
        """lstat, not stat: a symlink must not be followed to a 'safe' target."""
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        os.chmod(target, 0o700)
        link = os.path.join(self.tmp, "link")
        os.symlink(target, link)
        self.assertFalse(self.mod._path_is_private(link))

    def test_foreign_owner_is_rejected(self):
        path = os.path.join(self.tmp, "cache")
        os.mkdir(path)
        os.chmod(path, 0o755)
        st = os.stat(path)
        fake = os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                               st.st_uid + 1, st.st_gid, st.st_size,
                               int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
        with patch.object(self.mod.os, "lstat", return_value=fake):
            self.assertFalse(self.mod._path_is_private(path))

    def test_check_mode_false_tolerates_group_writable(self):
        """The stage BASE is $HOME, which is 0775 under user-private groups.

        Refusing to install over that would be a false positive, so ownership
        alone gates the base; the directories we create ourselves get the
        full check.
        """
        path = os.path.join(self.tmp, "home")
        os.mkdir(path)
        os.chmod(path, 0o775)
        self.assertFalse(self.mod._path_is_private(path))
        self.assertTrue(self.mod._path_is_private(path, check_mode=False))


class TestStageBaseIsNotWorldWritable(unittest.TestCase):
    """The HOME fallback must never be a world-writable directory.

    It used to be "/tmp", which put the pkexec target somewhere every local
    user can write — no same-user code execution needed to substitute it.
    """

    def test_fallback_is_not_tmp(self):
        import importlib
        with patch.dict("sys.modules", _mock_gtk_imports()):
            with patch.dict(os.environ, {}, clear=True):
                import bootc_installer.views.progress as mod
                importlib.reload(mod)
                base = mod._FISHERMAN_STAGE_BASE
                self.assertNotEqual(base, "/tmp")
                self.assertFalse(mod._FISHERMAN_HOST_PATH.startswith("/tmp/"))
                self.assertEqual(base, f"/run/user/{os.getuid()}")
        # patch.dict restores sys.modules on exit, so the reloaded module is
        # dropped and later imports get a clean one.


class TestMediaStreamReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict("sys.modules", _mock_gtk_imports()):
            import importlib
            import bootc_installer.views.progress as mod
            if not hasattr(mod, "_media_stream_is_prepared"):
                importlib.reload(mod)
            cls.mod = mod

    def test_none_media_stream_is_not_prepared(self):
        self.assertFalse(self.mod._media_stream_is_prepared(None))

    def test_media_stream_readiness_uses_is_prepared(self):
        media_stream = MagicMock()
        media_stream.is_prepared.return_value = False
        self.assertFalse(self.mod._media_stream_is_prepared(media_stream))
        media_stream.is_prepared.return_value = True
        self.assertTrue(self.mod._media_stream_is_prepared(media_stream))


class TestFriendlySubstep(unittest.TestCase):
    """Tests for _friendly_substep — a pure string function; no GTK required."""

    def setUp(self):
        import importlib
        # Remove cached module so we get a fresh import with mocked GTK.
        for key in list(sys.modules.keys()):
            if "bootc_installer.views.progress" in key:
                sys.modules.pop(key)
        with patch.dict("sys.modules", _mock_gtk_imports()):
            mod = importlib.import_module("bootc_installer.views.progress")
        self.fn = mod._friendly_substep

    def test_layer_progress_pattern(self):
        result = self.fn("Pulling image: layer 23/71")
        assert "23" in result
        assert "71" in result

    def test_pulling_container_image(self):
        result = self.fn("Pulling container image")
        assert result != "Pulling container image"  # was mapped
        assert "Download" in result or "download" in result

    def test_pulling_image_fallback(self):
        result = self.fn("Pulling image sha256:abc123")
        assert result != "Pulling image sha256:abc123"  # was mapped

    def test_unknown_passthrough(self):
        result = self.fn("Some totally unknown substep message")
        assert result == "Some totally unknown substep message"

    def test_fstrim_message(self):
        result = self.fn("Running fstrim on /mnt/target")
        assert result != "Running fstrim on /mnt/target"  # was mapped


class TestLogLineForDisplay(unittest.TestCase):
    """The log pane shows fisherman events as readable lines, not raw JSON."""

    def setUp(self):
        import importlib
        for key in list(sys.modules.keys()):
            if "bootc_installer.views.progress" in key:
                sys.modules.pop(key)
        with patch.dict("sys.modules", _mock_gtk_imports()):
            mod = importlib.import_module("bootc_installer.views.progress")
        self.fn = mod._log_line_for_display

    def test_step_event_is_rendered(self):
        line = ('{"type": "step", "step": 5, "total_steps": 8, '
                '"step_name": "Installing OS", "cumulative_pct": 1, "weight_pct": 87}')
        self.assertEqual(self.fn(line), "[5/8] Installing OS")

    def test_substep_event_is_rendered(self):
        line = '{"type": "substep", "message": "Pulling image: layer 18/71"}'
        self.assertEqual(self.fn(line), "  Pulling image: layer 18/71")

    def test_no_json_reaches_the_pane_for_the_transcript(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..",
                            "shared", "progress", "dry-run-transcript.ndjson")
        with open(path, encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                if line.strip():
                    self.assertFalse(self.fn(line).lstrip().startswith("{"), line)

    def test_non_event_line_is_verbatim(self):
        self.assertEqual(self.fn("mkfs.xfs: warning"), "mkfs.xfs: warning")


class TestDemoTranscript(unittest.TestCase):
    """BOOTC_DEMO replays the shared dry-run transcript, not a private table."""

    def setUp(self):
        import importlib
        for key in list(sys.modules.keys()):
            if "bootc_installer.views.progress" in key:
                sys.modules.pop(key)
        with patch.dict("sys.modules", _mock_gtk_imports()):
            self.mod = importlib.import_module("bootc_installer.views.progress")

    def test_demo_reads_the_transcript_installed_next_to_the_parser(self):
        repo = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.assertEqual(
            str(self.mod._DEMO_TRANSCRIPT),
            os.path.join(repo, "bootc_installer", "utils", "dry-run-transcript.ndjson"))
        lines = self.mod._load_demo_transcript()
        self.assertTrue(lines)
        self.assertTrue(all(ln.startswith("{") for ln in lines))

    def test_meson_installs_the_transcript(self):
        meson = os.path.join(os.path.dirname(__file__), "..", "..",
                             "bootc_installer", "utils", "meson.build")
        with open(meson) as fh:
            self.assertIn("'dry-run-transcript.ndjson'", fh.read())

    def test_missing_transcript_is_empty_not_a_crash(self):
        self.assertEqual(self.mod._load_demo_transcript("/nonexistent/x.ndjson"), [])

    def test_demo_drives_the_parser_to_completion(self):
        from bootc_installer.utils import progress_parser
        state = progress_parser.new_progress_state()
        last = None
        for line in self.mod._load_demo_transcript():
            last = progress_parser.apply_progress_event(line, state) or last
        self.assertTrue(last["complete"])
        self.assertEqual(last["fraction"], 1.0)


class TestTerminateBeforeInstall(unittest.TestCase):
    """The Exit Installer dialog calls terminate() and then quit(). If
    terminate() raises, quit() never runs and Exit only closes the dialog."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        class _Template:
            def __call__(self, *args, **kwargs):
                return lambda klass: klass

            def Child(self, *args, **kwargs):
                return None

        mocks = _mock_gtk_imports()
        mocks["gi.repository.Gtk"].Template = _Template()
        mocks["gi.repository.Gtk"].Box = object
        mocks["gi.repository"].Gtk = mocks["gi.repository.Gtk"]
        # Loaded under its own name so the real class does not leak into the
        # MagicMock-based imports the other test classes share.
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "bootc_installer", "views", "progress.py"
        )
        with patch.dict("sys.modules", mocks):
            spec = importlib.util.spec_from_file_location("_progress_terminate_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        cls.BootcProgress = mod.BootcProgress

    def test_terminate_without_fisherman_returns_cleanly(self):
        view = self.BootcProgress.__new__(self.BootcProgress)
        view._BootcProgress__session = None
        view._video_fallback_timeout_id = None
        view._BootcProgress__hide_video_spinner = MagicMock()

        view.terminate()


if __name__ == "__main__":
    unittest.main()
