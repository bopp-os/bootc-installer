// Sandbox plumbing: how this backend reaches fisherman and the host.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges).
//
// Live media and offline image stores are fisherman's facts now (probe's
// `live` and `offline`, probe.go). This file used to find them itself:
// `bootc status` plus /run/ostree-live and /proc/cmdline for live media, and
// $TUNA_OFFLINE_STORES, /etc/tuna-installer/offline-stores and a podman call
// per store for the offline images. Inside a Flatpak those paths are the
// runtime's, not the host's, so it found nothing.

package main

import (
	"os"
	"os/exec"
)

func inFlatpak() bool {
	_, err := os.Stat("/.flatpak-info")
	return err == nil
}

// fishermanCommand returns the program+args that run fisherman with
// privileges. fisherman reads the recipe from stdin (`fisherman -`,
// tuna-os/fisherman#276): the caller writes the JSON to the wrapper's stdin
// and closes it, so no file ever holds the passphrase.
//
// Flatpak runtimes ship no pkexec; escalate host-side. The live ISO symlinks
// the flatpak-bundled fisherman to /usr/local/bin and installs the polkit
// policy for it (tunaOS customize-live.sh).
func fishermanCommand() []string {
	return fishermanCommandFor(inFlatpak())
}

// fishermanWrapperScript runs pkexec under a host-side bash. fisherman runs
// as root, so nothing here can signal it; it cancels when its PARENT dies
// (tuna-os/fisherman#267). Run as `flatpak-spawn --host pkexec ...`, that
// parent was the host's flatpak-session-helper, which this frontend cannot
// kill. No redirection: stdin, stdout and stderr all pass through
// flatpak-spawn.
const fishermanWrapperScript = `pkexec /usr/local/bin/fisherman -; exit $?`

// fishermanCommandFor is fishermanCommand for an explicit sandbox state.
func fishermanCommandFor(flatpak bool) []string {
	if flatpak {
		return []string{"flatpak-spawn", "--host", "bash", "-c", fishermanWrapperScript}
	}
	return []string{"sudo", "/usr/local/bin/fisherman", "-"}
}

// hostCommand wraps argv so it executes on the host when sandboxed.
func hostCommand(argv ...string) []string {
	if inFlatpak() {
		return append([]string{"flatpak-spawn", "--host"}, argv...)
	}
	return argv
}

func runHost(argv ...string) ([]byte, error) {
	cmd := hostCommand(argv...)
	return exec.Command(cmd[0], cmd[1:]...).Output()
}
