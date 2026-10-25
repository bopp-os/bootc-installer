// TunaOS Niri Installer — Go backend
//
// A plain argv/stdout CLI, not a service: the QML frontend runs it with
// Quickshell's Process for each operation (`discover-disks`, `detect`,
// `install`, `validate`, `readiness [page]`) and parses what comes back on
// stdout. This backend wraps fisherman; the disk list, TPM, requirements,
// live media and offline images are fisherman's own (`fisherman probe
// --json`, probe.go), and so are the recipe rules (`fisherman validate
// --json`, validate.go).

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
)

// Recipe is the fisherman install recipe (see ../../INSTALLER-FRONTENDS.md §1).
type Recipe struct {
	Disk            string     `json:"disk"`
	Filesystem      string     `json:"filesystem"`
	BtrfsSubvolumes bool       `json:"btrfsSubvolumes"`
	Encryption      Encryption `json:"encryption"`
	// Image may be empty in live-ISO mode: bootc installs the running container.
	Image            string   `json:"image,omitempty"`
	TargetImgref     string   `json:"targetImgref,omitempty"`
	Bootloader       string   `json:"bootloader,omitempty"`
	ComposeFsBackend bool     `json:"composeFsBackend,omitempty"`
	Flatpaks         []string `json:"flatpaks,omitempty"`
	// AdditionalImageStores lists offline OCI stores. Left out, fisherman
	// exposes the stores it finds on the host; this backend never fills it.
	AdditionalImageStores []string `json:"additionalImageStores,omitempty"`
	DistroID              string   `json:"distroID"`
	SelinuxDisabled       bool     `json:"selinuxDisabled"`
	Hostname              string   `json:"hostname"`
	// User is the account fisherman creates. Left out (nil), fisherman
	// creates none; normalizeRecipe drops a block with no username, the
	// schema's "empty skips" rule, so it never reaches fisherman half-filled.
	User *User `json:"user,omitempty"`
}

// User is the recipe's `user` block (shared/recipe/fisherman-recipe.schema.json).
// The password travels with the recipe on stdin only, like the passphrase.
type User struct {
	Username string   `json:"username"`
	Fullname string   `json:"fullname"`
	Password string   `json:"password"`
	Groups   []string `json:"groups"`
}

// defaultUserGroups is what the account joins when the UI names no groups:
// wheel, as on XFCE, because the account the wizard creates is the only one
// on the installed system and has to be able to administer it.
var defaultUserGroups = []string{"wheel"}

type Encryption struct {
	// "none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"
	Type       string `json:"type"`
	Passphrase string `json:"passphrase,omitempty"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: tuna-installer-niri <command> [args...]")
		fmt.Fprintln(os.Stderr, "Commands:")
		fmt.Fprintln(os.Stderr, "  discover-disks     List the disks fisherman offers as JSON")
		fmt.Fprintln(os.Stderr, "  detect             Report live media, offline images, TPM, requirements and encryption choices as JSON")
		fmt.Fprintln(os.Stderr, "  install            Run fisherman with the recipe JSON read from stdin")
		fmt.Fprintln(os.Stderr, "  validate           Check a partial recipe from stdin with fisherman validate --json --partial")
		fmt.Fprintln(os.Stderr, "  readiness [page]   Record that the UI window presented a frame")
		fmt.Fprintln(os.Stderr, "  reboot             Restart the host (the done page's action)")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "discover-disks":
		discoverDisks()
	case "detect":
		detectEnvironment()
	case "install":
		// The recipe may hold a LUKS passphrase; read it from stdin rather
		// than argv so it never shows up in /proc/PID/cmdline (world-readable
		// on Linux). The QML frontend writes it with Quickshell's
		// Process.write().
		recipeJSON, err := io.ReadAll(os.Stdin)
		if err != nil {
			fmt.Fprintf(os.Stderr, "read recipe: %v\n", err)
			os.Exit(1)
		}
		runInstall(string(recipeJSON))
	case "validate":
		// A page's fields as a partial recipe, on stdin for the same reason.
		validateMain()
	case "reboot":
		// The done page's Restart. On the host through flatpak-spawn when
		// sandboxed, like every other frontend's reboot path.
		if out, err := runHost("systemctl", "reboot"); err != nil {
			fmt.Fprintf(os.Stderr, "reboot: %v\n%s", err, out)
			os.Exit(1)
		}
	case "readiness":
		// Called by the QML layer from ApplicationWindow.onFrameSwapped. See
		// readiness.go for why the write lives on this side of the boundary.
		page := ""
		if len(os.Args) > 2 {
			page = os.Args[2]
		}
		readinessStamp(page)
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", os.Args[1])
		os.Exit(1)
	}
}

// discoverDisks prints the disks fisherman offers, in its order, rendered
// per shared/probe/README.md ([]ProbeDisk). On a probe failure it prints the
// reason on stderr and exits 1; the QML shows that reason.
func discoverDisks() {
	facts, err := runProbe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(facts.Disks); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

// detectEnvironment reports the environment facts for the QML frontend.
func detectEnvironment() {
	// Every fact is fisherman's. A failed probe offers no TPM choices,
	// warns about nothing and is not live media; discover-disks reports the
	// failure.
	facts, err := runProbe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		facts = ProbeFacts{OfflineImages: []string{}}
	}
	result := map[string]any{
		// probe's live.is_live: only then may the recipe leave `image`
		// empty, which installs the running system.
		"isLive": facts.IsLive,
		// The booted image on live media, for display; "" otherwise.
		"liveImage": facts.LiveImage,
		// Image refs in the host's offline stores (offline.images).
		"offlineImages": facts.OfflineImages,
		// fisherman's tpm.usable. The UI hides the TPM encryption options
		// when this is false, rather than offering a choice that would fail
		// later at install time.
		"hasTpm": err == nil && facts.TPMUsable,
		// fisherman's system.unmet ("ram", "cpu", "uefi"): the welcome page
		// warns about each one.
		"unmet": unmetOrEmpty(facts, err),
		// The encryption types in display order, with needs_passphrase and
		// needs_tpm2: fisherman's data/encryption-choices.json, embedded.
		"encryptionChoices": encryptionChoices(),
		// Product identity per shared/branding/README.md: branding.json,
		// then os-release, then neutral. The QML takes its product name,
		// hostname seed, distroID and default image from here; nothing in
		// the frontend names a product.
		"branding": resolveBranding(),
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(result); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

func unmetOrEmpty(facts ProbeFacts, err error) []string {
	if err != nil || facts.Unmet == nil {
		return []string{}
	}
	return facts.Unmet
}

// wrapperCommand builds the fisherman wrapper's command in a process group
// of its own. The shared cancel contract is "kill your wrapper's process
// group", which must never be this backend's (or Quickshell's) group.
func wrapperCommand(argv []string) *exec.Cmd {
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	return cmd
}

// forwardSignals relays every signal this backend receives to the wrapper's
// process group (pgid == the wrapper's pid). Before the wrapper had a group
// of its own, a signal to this backend's group (Ctrl-C in a terminal, or a
// session teardown) reached the wrapper too; this keeps that working. The
// UI has no cancel button, so nothing else signals the group yet.
func forwardSignals(pgid int, sigs <-chan os.Signal) {
	for sig := range sigs {
		if s, ok := sig.(syscall.Signal); ok {
			_ = syscall.Kill(-pgid, s)
		}
	}
}

// normalizeRecipe fills what the UI may leave out before the recipe goes on
// to fisherman: the branding's distroID, and the user block's groups. A user
// block with no username is dropped rather than sent: fisherman would skip
// it anyway, and a password with no account has nowhere to go.
func normalizeRecipe(recipe *Recipe, distroID string) {
	if recipe.DistroID == "" {
		recipe.DistroID = distroID
	}
	if recipe.User != nil {
		if recipe.User.Username == "" {
			recipe.User = nil
		} else if recipe.User.Groups == nil {
			recipe.User.Groups = append([]string(nil), defaultUserGroups...)
		}
	}
}

func runInstall(recipeJSON string) {
	if len(recipeJSON) == 0 {
		fmt.Fprintln(os.Stderr, "invalid recipe: empty")
		os.Exit(1)
	}
	var recipe Recipe
	if err := json.Unmarshal([]byte(recipeJSON), &recipe); err != nil {
		fmt.Fprintf(os.Stderr, "invalid recipe: %v\n", err)
		os.Exit(1)
	}

	// An empty image (install the running system) and the offline stores
	// are fisherman's to judge and find (tuna-os/fisherman#276): it rejects
	// an empty image off live media before touching a disk, and exposes the
	// host's stores when additionalImageStores is absent.
	normalizeRecipe(&recipe, resolveBranding().ID)

	data, err := json.Marshal(recipe)
	if err != nil {
		fmt.Fprintf(os.Stderr, "encode recipe: %v\n", err)
		os.Exit(1)
	}

	// flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman -' in
	// Flatpak, sudo /usr/local/bin/fisherman - otherwise. The recipe goes on
	// the wrapper's stdin, which closes at EOF: no file holds it.
	cmd := wrapperCommand(fishermanCommand())
	cmd.Stdin = bytes.NewReader(data)

	// Tee fisherman's output to a persistent log in addition to the pipe
	// Quickshell reads (root.installLog in installer.qml) — that property is
	// in-memory only and gone the moment the window closes.
	logFile, logErr := openInstallLog()
	if logErr != nil {
		fmt.Fprintf(os.Stderr, "install log: %v\n", logErr)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	} else {
		defer logFile.Close()
		fmt.Fprintln(logFile, "=== install started, recipe on stdin ===")
		cmd.Stdout = io.MultiWriter(os.Stdout, logFile)
		cmd.Stderr = io.MultiWriter(os.Stderr, logFile)
	}

	runErr := cmd.Start()
	if runErr == nil {
		sigs := make(chan os.Signal, 1)
		signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
		go forwardSignals(cmd.Process.Pid, sigs)
		runErr = cmd.Wait()
		signal.Stop(sigs)
	}
	if logFile != nil {
		fmt.Fprintf(logFile, "=== install exited: %v ===\n", runErr)
	}
	if runErr != nil {
		fmt.Fprintf(os.Stderr, "fisherman failed: %v\n", runErr)
		os.Exit(1)
	}
}
