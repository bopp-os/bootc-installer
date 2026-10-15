"""Headless contract tests for FishermanSession — no GTK, no real subprocess."""
import os
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from bootc_installer.utils.fisherman_session import FishermanSession


def _fake_popen(pid=4242, poll_sequence=(None, None, 0)):
    """Build a MagicMock standing in for subprocess.Popen's return value.

    poll_sequence is consumed one call at a time, then repeats the last value.
    """
    proc = MagicMock()
    proc.pid = pid
    seq = list(poll_sequence)

    def _poll():
        if seq:
            value = seq.pop(0)
        else:
            value = poll_sequence[-1]
        return value

    proc.poll.side_effect = _poll
    return proc


# The recipe the session hands to fisherman on stdin; never a file.
_RECIPE = {"disk": "/dev/vda", "hostname": "h",
           "encryption": {"type": "luks-passphrase", "passphrase": "s3cret"}}


class FishermanSessionLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.log_path = os.path.join(self.cache_dir, "fisherman-output.log")

    def _session(self, popen=None, in_flatpak=False):
        return FishermanSession(
            _RECIPE,
            in_flatpak=in_flatpak,
            stage_base=self.tmp,
            cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=self.log_path,
            popen=popen or (lambda argv, **kw: _fake_popen()),
        )

    def test_launch_creates_cache_dir_and_starts_process(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        session = self._session(popen=popen)
        argv = session.launch()
        self.assertIsNotNone(argv)
        self.assertTrue(os.path.isdir(self.cache_dir))
        popen.assert_called_once()
        self.assertIsNotNone(session.proc)

    def test_launch_removes_stale_log_before_starting(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.log_path, "w") as f:
            f.write("stale content from a previous run\n")
        session = self._session()
        session.launch()
        # The stale content is gone; launch() recreates the file empty (and
        # 0600, see FishermanSessionLogModeTests) for bash's redirect.
        with open(self.log_path) as f:
            self.assertEqual(f.read(), "")

    def test_launch_returns_none_when_staging_fails(self):
        # in_flatpak=True + a stage_base that fails the private-path check
        # (world-writable) makes stage_on_host() refuse.
        os.chmod(self.tmp, 0o777)
        session = self._session(in_flatpak=True)
        self.addCleanup(os.chmod, self.tmp, 0o700)
        argv = session.launch()
        self.assertIsNone(argv)
        self.assertIsNone(session.proc)


class FishermanSessionLogModeTests(unittest.TestCase):
    """The log holds the TPM recovery key. bash's `>` used to create it, so
    its mode followed the umask: 0644 under 022, world-readable."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.log_path = os.path.join(self.cache_dir, "fisherman-output.log")
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)

    def _launch(self):
        session = FishermanSession(
            _RECIPE,
            in_flatpak=False,
            stage_base=self.tmp,
            cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=self.log_path,
            popen=lambda argv, **kw: _fake_popen(),
        )
        return session.launch()

    def _mode(self):
        return os.stat(self.log_path).st_mode & 0o777

    def test_log_is_created_0600_before_the_process_starts(self):
        self._launch()
        self.assertEqual(self._mode(), 0o600)

    def test_bash_redirect_keeps_the_0600_mode(self):
        # What build_argv's command really does to the file, under the
        # same 022 umask that used to make it 0644.
        import subprocess

        self._launch()
        subprocess.run(
            ["bash", "-c", 'umask 022; echo recovery >"$1" 2>&1', "--", self.log_path],
            check=True,
        )
        self.assertEqual(self._mode(), 0o600)
        with open(self.log_path) as f:
            self.assertEqual(f.read(), "recovery\n")

    def test_stale_world_readable_log_is_tightened(self):
        # _reset_log_file() cannot remove it (simulated): the mode is still
        # forced to 0600 and the old content dropped.
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.log_path, "w") as f:
            f.write("old key\n")
        os.chmod(self.log_path, 0o644)
        with patch.object(FishermanSession, "_reset_log_file"):
            self._launch()
        self.assertEqual(self._mode(), 0o600)
        with open(self.log_path) as f:
            self.assertEqual(f.read(), "")

    def test_symlink_at_log_path_is_not_followed(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        target = os.path.join(self.tmp, "elsewhere")
        with open(target, "w") as f:
            f.write("keep\n")
        os.symlink(target, self.log_path)
        with patch.object(FishermanSession, "_reset_log_file"):
            self._launch()
        with open(target) as f:
            self.assertEqual(f.read(), "keep\n")


class FishermanSessionPollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def _launched_session(self, poll_sequence=(None, None, 0)):
        popen = lambda argv, **kw: _fake_popen(poll_sequence=poll_sequence)
        session = FishermanSession(
            _RECIPE,
            in_flatpak=False,
            stage_base=self.tmp,
            cache_dir=self.tmp,
            host_path=os.path.join(self.tmp, "fisherman"),
            log_path=os.path.join(self.tmp, "fisherman-output.log"),
            popen=popen,
        )
        session.launch()
        return session

    def test_poll_process_returns_none_before_exit(self):
        session = self._launched_session(poll_sequence=(None,))
        self.assertIsNone(session.poll_process())

    def test_poll_process_returns_exit_code(self):
        session = self._launched_session(poll_sequence=(0,))
        self.assertEqual(session.poll_process(), 0)

    def test_poll_process_without_launch_is_none(self):
        session = FishermanSession(_RECIPE)
        self.assertIsNone(session.poll_process())


class FishermanSessionLogTailingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.log_path = os.path.join(self.tmp, "fisherman-output.log")
        self.session = FishermanSession(
            _RECIPE,
            log_path=self.log_path,
            popen=lambda argv, **kw: _fake_popen(),
        )

    def test_open_log_for_tailing_false_until_file_exists(self):
        self.assertFalse(self.session.open_log_for_tailing())
        with open(self.log_path, "w"):
            pass
        self.assertTrue(self.session.open_log_for_tailing())

    def test_open_log_for_tailing_is_idempotent(self):
        with open(self.log_path, "w"):
            pass
        self.assertTrue(self.session.open_log_for_tailing())
        self.assertTrue(self.session.open_log_for_tailing())

    def test_read_new_lines_returns_only_complete_lines(self):
        with open(self.log_path, "w") as f:
            f.write("line one\nline two\nunfinished")
        self.session.open_log_for_tailing()
        lines = self.session.read_new_lines()
        self.assertEqual(lines, ["line one", "line two"])

    def test_read_new_lines_buffers_incomplete_line_across_calls(self):
        with open(self.log_path, "w") as f:
            f.write("partial")
        self.session.open_log_for_tailing()
        self.assertEqual(self.session.read_new_lines(), [])
        with open(self.log_path, "a") as f:
            f.write(" line\nnext\n")
        self.assertEqual(self.session.read_new_lines(), ["partial line", "next"])

    def test_read_new_lines_without_open_log_is_empty(self):
        self.assertEqual(self.session.read_new_lines(), [])

    def test_drain_remaining_flushes_final_unterminated_line_and_closes(self):
        with open(self.log_path, "w") as f:
            f.write("first\n")
        self.session.open_log_for_tailing()
        self.session.read_new_lines()
        with open(self.log_path, "a") as f:
            f.write("final no newline")
        lines = self.session.drain_remaining()
        self.assertEqual(lines, ["final no newline"])
        # Closed: a second drain returns nothing rather than erroring.
        self.assertEqual(self.session.drain_remaining(), [])

    def test_drain_remaining_without_open_log_is_empty(self):
        self.assertEqual(self.session.drain_remaining(), [])


class FishermanSessionTerminateAndCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def test_terminate_without_launch_is_a_noop(self):
        session = FishermanSession(_RECIPE)
        session.terminate()  # must not raise

    def test_terminate_skips_already_exited_process(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(poll_sequence=(0,)),
        )
        session.launch()
        with patch("os.killpg") as killpg:
            session.terminate()
            killpg.assert_not_called()

    def test_launch_starts_the_wrapper_in_its_own_session(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        session = FishermanSession(_RECIPE, popen=popen)
        session.launch()
        self.assertIs(popen.call_args.kwargs.get("start_new_session"), True)

    def test_terminate_signals_the_wrappers_group_not_ours(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(pid=4242, poll_sequence=(None,)),
        )
        session.launch()
        with patch("os.killpg") as killpg, patch("os.getpgid", return_value=os.getpgrp()):
            session.terminate()
        killpg.assert_called_once_with(4242, signal.SIGTERM)
        self.assertNotEqual(killpg.call_args.args[0], os.getpgrp())
        session.proc.wait.assert_called_once_with(timeout=FishermanSession.TERMINATE_TIMEOUT)

    def test_terminate_falls_back_to_proc_terminate_if_killpg_fails(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(poll_sequence=(None,)),
        )
        session.launch()
        with patch("os.killpg", side_effect=OSError()):
            session.terminate()
            session.proc.terminate.assert_called_once()
        session.proc.wait.assert_called_once()

    def test_terminate_tolerates_a_wrapper_that_outlives_the_wait(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(poll_sequence=(None,)),
        )
        session.launch()
        session.proc.wait.side_effect = subprocess.TimeoutExpired("bash", 5)
        with patch("os.killpg"):
            session.terminate()  # must not raise

    def test_terminate_with_a_real_child_does_not_signal_the_installer(self):
        # A real wrapper through the real subprocess.Popen. The installer
        # (this test process) traps SIGTERM: before start_new_session the
        # wrapper shared our group and killpg delivered SIGTERM here too.
        received = []
        previous = signal.signal(signal.SIGTERM, lambda *a: received.append(a[0]))
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        with patch(
            "bootc_installer.utils.fisherman_runner.build_argv",
            return_value=["sleep", "30"],
        ):
            session = FishermanSession(
                _RECIPE,
                in_flatpak=False,
                cache_dir=os.path.join(self.tmp, "cache"),
                log_path=os.path.join(self.tmp, "cache", "fisherman-output.log"),
            )
            session.launch()
        self.addCleanup(lambda: session.proc.poll() is None and session.proc.kill())
        self.assertEqual(os.getpgid(session.proc.pid), session.proc.pid)
        self.assertNotEqual(os.getpgid(session.proc.pid), os.getpgrp())

        session.terminate()

        self.assertEqual(received, [])
        self.assertEqual(session.proc.returncode, -signal.SIGTERM)

    def test_the_session_has_no_recipe_file_to_clean_up(self):
        self.assertFalse(hasattr(FishermanSession, "cleanup_recipe_file"))


class FishermanSessionStdinTests(unittest.TestCase):
    """fisherman reads the recipe from stdin (`fisherman -`, fisherman#276):
    the passphrase never touches the disk or argv."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")

    def _session(self, popen, **kw):
        return FishermanSession(
            _RECIPE, in_flatpak=False, stage_base=self.tmp, cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=os.path.join(self.cache_dir, "fisherman-output.log"),
            popen=popen, **kw)

    def test_the_recipe_is_written_to_stdin_and_closed(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        session = self._session(popen)
        argv = session.launch()
        self.assertIs(popen.call_args.kwargs.get("stdin"), subprocess.PIPE)
        written = session.proc.stdin.write.call_args.args[0]
        self.assertEqual(__import__("json").loads(written), _RECIPE)
        session.proc.stdin.close.assert_called_once()
        self.assertIn(" - >", argv[-1])
        self.assertNotIn("s3cret", " ".join(argv))

    def test_no_file_holds_the_recipe(self):
        session = self._session(lambda argv, **kw: _fake_popen())
        session.launch()
        for root, _dirs, files in os.walk(self.tmp):
            for name in files:
                with open(os.path.join(root, name), errors="replace") as fh:
                    self.assertNotIn("s3cret", fh.read(), name)

    def test_a_wrapper_that_already_died_is_not_an_exception(self):
        def popen(argv, **kw):
            proc = _fake_popen()
            proc.stdin.write.side_effect = BrokenPipeError()
            return proc
        session = self._session(popen)
        self.assertIsNotNone(session.launch())
        session.proc.stdin.close.assert_called_once()

    def test_a_real_wrapper_reads_the_recipe_on_stdin(self):
        """The real bash wrapper, with the escalation replaced by `cat`:
        what fisherman would read on stdin lands in the log."""
        log = os.path.join(self.cache_dir, "fisherman-output.log")
        with patch("bootc_installer.utils.fisherman_runner.build_argv",
                   return_value=["bash", "-c", f'cat - >"{log}" 2>&1; exit $?']):
            session = self._session(None)
            session.launch()
        self.assertEqual(session.proc.wait(timeout=10), 0)
        with open(log) as fh:
            self.assertEqual(__import__("json").load(fh), _RECIPE)

    def test_live_media_uses_sudo_and_an_installed_host_pkexec(self):
        argvs = {}
        for use_sudo in (True, False):
            popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
            self._session(popen, use_sudo=use_sudo).launch()
            argvs[use_sudo] = popen.call_args.args[0][-1]
        self.assertTrue(argvs[True].startswith("sudo /usr/local/bin/fisherman -"))
        self.assertTrue(argvs[False].startswith("pkexec /usr/local/bin/fisherman -"))
