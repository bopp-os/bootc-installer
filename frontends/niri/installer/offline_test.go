package main

// Unit tests for offline.go — how this backend reaches fisherman and the host.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges).

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestFishermanCommandOutsideFlatpak(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	got := fishermanCommand()
	want := []string{"sudo", "/usr/local/bin/fisherman", "-"}
	if len(got) != len(want) {
		t.Fatalf("fishermanCommand() = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("fishermanCommand() = %v, want %v", got, want)
		}
	}
}

// Not `flatpak-spawn --host pkexec`: fisherman's parent would be the host's
// session helper, and it could never be cancelled.
func TestFishermanCommandRunsPkexecInsideAHostBashInFlatpak(t *testing.T) {
	got := fishermanCommandFor(true)
	want := []string{"flatpak-spawn", "--host", "bash", "-c",
		`pkexec /usr/local/bin/fisherman -; exit $?`}
	if strings.Join(got, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("fishermanCommandFor(true) = %q, want %q", got, want)
	}
}

// The wrapper's bash for real (everything after `flatpak-spawn --host`),
// pkexec stubbed on PATH: the recipe written to the wrapper's stdin is what
// fisherman reads, `-` is its only argument, and output and status pass
// through.
func TestFlatpakWrapperPassesStdinOutputAndStatusThrough(t *testing.T) {
	dir := t.TempDir()
	got := filepath.Join(dir, "stdin")
	writeStub(t, dir, "pkexec", "#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\ncat > \""+got+"\"\necho to-stderr >&2\nexit 7\n")
	argv := fishermanCommandFor(true)[2:]

	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Env = append(os.Environ(), pathWith(dir))
	cmd.Dir = dir
	cmd.Stdin = strings.NewReader(`{"hostname":"h","encryption":{"type":"luks-passphrase","passphrase":"s3cret"}}`)
	var stdout, stderr strings.Builder
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 7 {
		t.Fatalf("exit = %v, want status 7", err)
	}
	if got, want := stdout.String(), "/usr/local/bin/fisherman|-\n"; got != want {
		t.Errorf("stdout = %q, want %q", got, want)
	}
	if stderr.String() != "to-stderr\n" {
		t.Errorf("stderr = %q", stderr.String())
	}
	read, _ := os.ReadFile(got)
	if !strings.Contains(string(read), "s3cret") {
		t.Errorf("fisherman read %q on stdin, want the recipe", read)
	}
}

func TestWrapperLeadsItsOwnProcessGroupAndGetsForwardedSignals(t *testing.T) {
	cmd := wrapperCommand([]string{"sleep", "30"})
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill() }()
	pid := cmd.Process.Pid
	pgid, err := syscall.Getpgid(pid)
	if err != nil {
		t.Fatal(err)
	}
	if pgid != pid || pgid == syscall.Getpgrp() {
		t.Fatalf("wrapper pgid = %d, pid = %d, ours = %d", pgid, pid, syscall.Getpgrp())
	}

	sigs := make(chan os.Signal, 1)
	go forwardSignals(pid, sigs)
	sigs <- syscall.SIGTERM
	close(sigs)
	err = cmd.Wait()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("wait = %v, want the wrapper killed", err)
	}
	ws := exitErr.Sys().(syscall.WaitStatus)
	if !ws.Signaled() || ws.Signal() != syscall.SIGTERM {
		t.Fatalf("wrapper status = %v, want SIGTERM", ws)
	}
}

func TestHostCommandPassthroughOutsideFlatpak(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	got := hostCommand("bootc", "status")
	want := []string{"bootc", "status"}
	if len(got) != len(want) || got[0] != want[0] || got[1] != want[1] {
		t.Fatalf("hostCommand() = %v, want %v", got, want)
	}
}
