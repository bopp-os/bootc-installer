"""GTK-free fisherman process-lifecycle adapter.

Owns everything about running the privileged fisherman helper that is not
GTK: staging (delegated to fisherman_runner), argv construction (ditto),
launching and polling the subprocess, handing it the recipe on stdin, and
tailing its log file for new lines. No recipe file is written: fisherman
reads the recipe from stdin (`fisherman -`, tuna-os/fisherman#276), so the
passphrase and the user password never touch the disk.

`bootc_installer.views.progress.BootcProgress` is the GTK consumer: it owns
the widget state (progress bar, video, console) and the GLib timers that
call into this adapter, but it does not itself touch os.unlink, subprocess,
or file descriptors for the fisherman transport. That split is what makes
this module importable, and testable, without a display.

apply_progress_event() in progress_parser.py remains the protocol-translation
boundary; this module only decides *when* to hand it a line, not how to
interpret one.
"""

import json
import logging
import os
import signal
import subprocess

from bootc_installer.utils import fisherman_runner

logger = logging.getLogger("Installer::FishermanSession")


class FishermanSession:
    """Runs one fisherman install, from launch to log drain to cleanup.

    Callers (a GTK widget, a headless test, an alternative frontend) drive
    this with their own scheduling — poll_process() and read_new_lines() are
    meant to be called from a timer, but this class does not start one.
    """

    def __init__(
        self,
        recipe: dict,
        *,
        in_flatpak: bool = fisherman_runner.IN_FLATPAK,
        use_sudo: bool = False,
        stage_base: str = fisherman_runner.STAGE_BASE,
        cache_dir: str = fisherman_runner.CACHE_DIR,
        host_path: str = fisherman_runner.HOST_PATH,
        log_path: str = fisherman_runner.LOG_PATH,
        popen=None,
    ):
        self._recipe = recipe
        self._in_flatpak = in_flatpak
        self._use_sudo = use_sudo
        self._stage_base = stage_base
        self._cache_dir = cache_dir
        self._host_path = host_path
        self.log_path = log_path
        # Injectable for tests; defaults to the real subprocess.Popen.
        if popen is None:
            popen = subprocess.Popen
        self._popen = popen

        self.proc = None
        self._log_file = None
        self._log_linebuf = ""

    def stage(self) -> bool:
        """Copy fisherman to a host-visible location, if running in Flatpak."""
        return fisherman_runner.stage_on_host(
            in_flatpak=self._in_flatpak,
            stage_base=self._stage_base,
            cache_dir=self._cache_dir,
            host_path=self._host_path,
        )

    def _reset_log_file(self):
        """Remove any stale log so a fresh open always starts at position 0.

        bash's '>' redirect truncates an existing file, but a Python handle
        opened before that truncation would still sit at the old EOF and
        read() would return empty even though new content is present.
        """
        try:
            os.unlink(self.log_path)
            logger.info("Deleted stale log file: %s", self.log_path)
        except FileNotFoundError:
            logger.info("No stale log file to delete")
        except OSError as e:
            logger.error("Failed to delete stale log: %s", e)

    def _create_private_log(self):
        """Create the log 0600 before bash's redirect opens it.

        The `>` redirect in fisherman_runner.build_argv used to create the
        file, so its mode followed the umask: 0644 under the usual 022,
        readable by every local user. The log carries fisherman's full
        output, including the TPM recovery key. bash's `>` truncates an
        existing file without touching its mode, so creating it here first
        is enough. Not done with `umask 077` in the bash wrapper: fisherman
        inherits that umask and, as root, writes the target system's files.

        O_NOFOLLOW refuses a symlink planted at the path; fchmod covers a
        stale file that _reset_log_file() could not remove.
        """
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        try:
            fd = os.open(self.log_path, flags, 0o600)
        except OSError as e:
            logger.error("Could not create private log %s: %s", self.log_path, e)
            return
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)

    def launch(self):
        """Stage fisherman if needed, then start it. Returns argv used, or None on staging failure."""
        if not self.stage():
            return None
        os.makedirs(self._cache_dir, exist_ok=True)
        self._reset_log_file()
        self._create_private_log()
        argv = fisherman_runner.build_argv(
            in_flatpak=self._in_flatpak,
            use_sudo=self._use_sudo,
            host_path=self._host_path,
            log_path=self.log_path,
        )
        logger.info("Launching fisherman: %s", argv)
        # bash handles writing stdout+stderr to the log file via shell
        # redirection. Do NOT pass stdout= here — flatpak-spawn uses D-Bus,
        # not a real pipe fd, so a Python-side pipe would never fill.
        #
        # stdin IS a pipe: it carries the recipe. flatpak-spawn forwards its
        # stdin fd to the host bash, and bash, pkexec and sudo hand it on to
        # fisherman, which reads to EOF.
        #
        # start_new_session: the wrapper (bash, or flatpak-spawn) leads its
        # own process group, which terminate() signals. Without it the
        # wrapper shared the GUI's group, and terminate()'s
        # killpg(getpgid(wrapper)) sent SIGTERM to the installer itself.
        # fisherman runs as root under pkexec, so the wrapper is all this
        # process can signal; fisherman cancels when its parent dies.
        self.proc = self._popen(argv, stdin=subprocess.PIPE, start_new_session=True)
        logger.info("Fisherman PID: %s", self.proc.pid)
        self._write_recipe()
        return argv

    def _write_recipe(self):
        """Write the recipe to fisherman's stdin and close it.

        A recipe is a few KiB, well under a pipe's buffer, so the write does
        not wait for fisherman (or the polkit prompt in front of it) to read.
        If the wrapper is already gone, fisherman never ran and its exit code
        says why; nothing is written anywhere else.
        """
        stdin = getattr(self.proc, "stdin", None)
        if stdin is None:
            return
        try:
            stdin.write(json.dumps(self._recipe).encode("utf-8"))
        except (BrokenPipeError, OSError) as e:
            logger.error("Could not hand the recipe to fisherman: %s", e)
        finally:
            try:
                stdin.close()
            except OSError:
                pass

    def poll_process(self):
        """Return the exit code if fisherman has finished, else None."""
        if self.proc is None:
            return None
        return self.proc.poll()

    def open_log_for_tailing(self) -> bool:
        """Try to open the log file for tailing. Returns False if it does not exist yet (retry)."""
        if self._log_file is not None:
            return True
        if not os.path.exists(self.log_path):
            return False
        try:
            self._log_file = open(self.log_path, "r")  # noqa: SIM115 - kept open across polls, closed in drain_remaining()
            logger.info("Log watcher OPENED %s (pos=%d)", self.log_path, self._log_file.tell())
            return True
        except OSError as e:
            logger.error("Log watcher open FAILED: %s", e)
            return False

    def read_new_lines(self) -> list[str]:
        """Read any newly-written complete lines from the log file.

        Incomplete trailing data is buffered until the next call. Returns []
        if the log file is not open or has no new complete lines.
        """
        if self._log_file is None:
            return []
        new_text = self._log_file.read()
        if not new_text:
            return []
        self._log_linebuf += new_text
        lines = self._log_linebuf.split("\n")
        self._log_linebuf = lines[-1]
        return lines[:-1]

    def drain_remaining(self) -> list[str]:
        """Read whatever is left (including a final unterminated line) and close the log.

        Call once after poll_process() reports the process has exited, to
        pick up any bytes written between the last poll and process exit.
        """
        lines = []
        if self._log_file is not None:
            remaining = self._log_file.read()
            if remaining:
                self._log_linebuf += remaining
            combined = (self._log_linebuf + "\n").split("\n")
            self._log_linebuf = ""
            lines = [line for line in combined if line.strip()]
            self._log_file.close()
            self._log_file = None
        return lines

    # How long terminate() waits for the wrapper to exit after SIGTERM.
    TERMINATE_TIMEOUT = 5.0

    def terminate(self):
        """Cancel the install (e.g. window closed): SIGTERM the wrapper's group.

        launch() starts the wrapper as the leader of its own process group,
        so the group id is its pid. That is signalled directly rather than
        through os.getpgid(): if the wrapper were ever in this process's
        group, getpgid() would name the installer's own group (which is what
        used to happen), while killpg(pid) fails with ESRCH and falls back
        to signalling the wrapper alone.

        fisherman runs as root via pkexec, so it cannot be signalled from
        here; it notices its parent's death and runs its cleanup handler
        (unmount, close LUKS), exiting 130. The wrapper is then reaped with
        a bounded wait so its exit status is collected, not left a zombie.
        """
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            return
        logger.warning("Terminating fisherman (PID %s) due to window close", self.proc.pid)
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.proc.terminate()
            except OSError as e:
                logger.debug("Could not terminate fisherman process: %s", e)
        try:
            code = self.proc.wait(timeout=self.TERMINATE_TIMEOUT)
            logger.info("fisherman wrapper exited with %s after SIGTERM", code)
        except subprocess.TimeoutExpired:
            logger.warning("fisherman wrapper (PID %s) still running %.0fs after SIGTERM",
                           self.proc.pid, self.TERMINATE_TIMEOUT)
