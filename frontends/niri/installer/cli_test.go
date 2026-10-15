package main

// Contract tests for the argv/stdout CLI the QML frontend drives with
// Quickshell's Process. Each subcommand ends in os.Exit, so these run the test
// binary as a child process (the pattern main_test.go already uses for
// `install`) and assert on its stdout, stderr and exit status — that triple is
// the whole interface the frontend sees.
//
// The child is this same coverage-instrumented binary, so `go test -cover`
// still counts what runs inside it.

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const argvSeparator = "\x1f"

// TestMain turns this binary into the installer backend when GO_TEST_CLI_ARGV
// is set, so a test can exercise main()'s dispatch as a real process.
func TestMain(m *testing.M) {
	if argv, ok := os.LookupEnv("GO_TEST_CLI_ARGV"); ok {
		os.Args = []string{"tuna-installer-niri"}
		if argv != "" {
			os.Args = append(os.Args, strings.Split(argv, argvSeparator)...)
		}
		main()
		os.Exit(0)
	}
	os.Exit(m.Run())
}

type cliResult struct {
	stdout string
	stderr string
	code   int
}

// runCLI runs the backend as a child process with the given argv and extra
// environment, and reports everything the frontend would observe.
func runCLI(t *testing.T, env []string, argv ...string) cliResult {
	t.Helper()

	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), "GO_TEST_CLI_ARGV="+strings.Join(argv, argvSeparator))
	cmd.Env = append(cmd.Env, env...)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	code := 0
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if !errors.As(err, &exitErr) {
			t.Fatalf("running the backend: %v", err)
		}
		code = exitErr.ExitCode()
	}
	return cliResult{stdout: stdout.String(), stderr: stderr.String(), code: code}
}

// writeStub puts an executable script in dir; callers prepend dir to the
// child's PATH so the backend finds it instead of the real tool.
func writeStub(t *testing.T, dir, name, script string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

func pathWith(dir string) string {
	return "PATH=" + dir + string(os.PathListSeparator) + os.Getenv("PATH")
}

// ---------------------------------------------------------------------------
// dispatch
// ---------------------------------------------------------------------------

func TestCLIWithoutArgumentsPrintsUsageAndFails(t *testing.T) {
	got := runCLI(t, nil)

	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	for _, want := range []string{"Usage:", "discover-disks", "detect", "install", "readiness"} {
		if !strings.Contains(got.stderr, want) {
			t.Errorf("usage text is missing %q; stderr = %q", want, got.stderr)
		}
	}
	if got.stdout != "" {
		// The frontend parses stdout as JSON; diagnostics belong on stderr.
		t.Errorf("stdout = %q, want empty", got.stdout)
	}
}

func TestCLIRejectsAnUnknownCommand(t *testing.T) {
	got := runCLI(t, nil, "reformat-everything")

	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	if !strings.Contains(got.stderr, "Unknown command: reformat-everything") {
		t.Errorf("stderr = %q, want it to name the unknown command", got.stderr)
	}
	if got.stdout != "" {
		t.Errorf("stdout = %q, want empty", got.stdout)
	}
}

// ---------------------------------------------------------------------------
// discover-disks
// ---------------------------------------------------------------------------

// discover-disks prints the probe's eligible disks in the shape the QML
// reads (and shared/probe/fixtures/*.expected.json pins).
func TestDiscoverDisksPrintsTheProbedDisks(t *testing.T) {
	got := runCLI(t, []string{fakeProbeEnv + "=" + filepath.Join(probeFixtures, "vm.json")}, "discover-disks")
	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	var disks []map[string]any
	if err := json.Unmarshal([]byte(got.stdout), &disks); err != nil {
		t.Fatalf("stdout is not a JSON array: %v\n%s", err, got.stdout)
	}
	if len(disks) != 1 || disks[0]["path"] != "/dev/vda" || disks[0]["size_label"] != "64 GiB" {
		t.Errorf("disks = %v, want only /dev/vda at 64 GiB", disks)
	}
}

// With nothing eligible the frontend still gets a JSON array, not "null".
func TestDiscoverDisksWithNoEligibleDiskStillEmitsAnArray(t *testing.T) {
	got := runCLI(t, []string{fakeProbeEnv + "=" + filepath.Join(probeFixtures, "container.json")}, "discover-disks")
	if got.code != 0 || strings.TrimSpace(got.stdout) != "[]" {
		t.Errorf("code = %d, stdout = %q, want 0 and []", got.code, got.stdout)
	}
}

// A failed probe is reported, not papered over with a scan of our own.
func TestDiscoverDisksFailsWhenTheProbeFails(t *testing.T) {
	got := runCLI(t, []string{fakeProbeEnv + "=/nonexistent/probe.json"}, "discover-disks")
	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	if !strings.Contains(got.stderr, "/nonexistent/probe.json") {
		t.Errorf("stderr = %q, want the reason", got.stderr)
	}
	if got.stdout != "" {
		t.Errorf("stdout = %q, want empty", got.stdout)
	}
}

// ---------------------------------------------------------------------------
// detect
// ---------------------------------------------------------------------------

// The keys detectEnvironment emits are the frontend's environment contract:
// installer.qml reads each one by name. Renaming or dropping one breaks the
// UI silently, so pin them.
func TestDetectEmitsTheEnvironmentContract(t *testing.T) {
	got := runCLI(t, []string{fakeProbeEnv + "=" + filepath.Join(probeFixtures, "vm.json")}, "detect")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}

	var env map[string]any
	if err := json.Unmarshal([]byte(got.stdout), &env); err != nil {
		t.Fatalf("stdout is not the JSON object the frontend parses: %v\n%s", err, got.stdout)
	}
	for _, key := range []string{"isLive", "liveImage", "offlineImages", "hasTpm", "unmet",
		"encryptionChoices", "branding"} {
		if _, ok := env[key]; !ok {
			t.Errorf("detect output is missing the %q key; got %v", key, env)
		}
	}
	// The stores are fisherman's now: the QML never sees or sends them.
	if _, ok := env["offlineStores"]; ok {
		t.Errorf("detect still reports offlineStores: %v", env["offlineStores"])
	}
	if _, ok := env["hasTpm"].(bool); !ok {
		t.Errorf("hasTpm = %v (%T), want a bool", env["hasTpm"], env["hasTpm"])
	}
	if unmet, ok := env["unmet"].([]any); !ok || len(unmet) != 3 {
		t.Errorf("unmet = %v (%T), want the vm fixture's three items", env["unmet"], env["unmet"])
	}
	// The vm fixture booted from live media: live facts are the probe's.
	if env["isLive"] != true || env["liveImage"] != "ghcr.io/example/os:stable" {
		t.Errorf("isLive, liveImage = %v, %v; want the vm fixture's live facts", env["isLive"], env["liveImage"])
	}
	choices, ok := env["encryptionChoices"].([]any)
	if !ok || len(choices) != 4 {
		t.Fatalf("encryptionChoices = %v, want the four choices", env["encryptionChoices"])
	}
	if c := choices[3].(map[string]any); c["type"] != "tpm2-luks-passphrase" ||
		c["needs_passphrase"] != true || c["needs_tpm2"] != true {
		t.Errorf("encryptionChoices[3] = %v", c)
	}
	// The branding object per shared/branding/README.md; the QML reads its
	// name, id, defaultHostname and defaultImage.
	b, ok := env["branding"].(map[string]any)
	if !ok {
		t.Fatalf("branding = %v (%T), want an object", env["branding"], env["branding"])
	}
	for _, key := range []string{"name", "id", "defaultHostname", "defaultImage"} {
		if _, ok := b[key].(string); !ok {
			t.Errorf("branding.%s = %v (%T), want a string", key, b[key], b[key])
		}
	}
	if b["name"] == "" || b["id"] == "" {
		t.Errorf("branding must never be nameless: %v", b)
	}
}

// An installed host is not live media, whatever bootc says: the probe says
// so, and a failed probe is not live either.
func TestDetectIsNotLiveOffLiveMediaOrWithoutAProbe(t *testing.T) {
	for _, fixture := range []string{filepath.Join(probeFixtures, "container.json"), "/nonexistent/probe.json"} {
		got := runCLI(t, []string{fakeProbeEnv + "=" + fixture}, "detect")
		var env struct {
			IsLive        bool     `json:"isLive"`
			LiveImage     string   `json:"liveImage"`
			OfflineImages []string `json:"offlineImages"`
		}
		if err := json.Unmarshal([]byte(got.stdout), &env); err != nil {
			t.Fatalf("%s: %v\n%s", fixture, err, got.stdout)
		}
		if env.IsLive || env.LiveImage != "" || env.OfflineImages == nil || len(env.OfflineImages) != 0 {
			t.Errorf("%s: %+v, want not live and an empty offlineImages array", fixture, env)
		}
	}
}

// ---------------------------------------------------------------------------
// install: the recipe on fisherman's stdin
// ---------------------------------------------------------------------------

func TestInstallPipesTheRecipeToFishermanOnStdin(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	argsFile := filepath.Join(dir, "args")
	stdinFile := filepath.Join(dir, "stdin")
	// sudo stands in for the escalation: it records what fisherman would get.
	writeStub(t, dir, "sudo", "#!/bin/sh\necho \"$@\" > "+argsFile+"\ncat > "+stdinFile+"\n")
	runtime := t.TempDir()
	recipe := `{"disk":"/dev/vda","filesystem":"xfs","encryption":{"type":"luks-passphrase","passphrase":"s3cret"},"hostname":"h","distroID":"x","selinuxDisabled":false}`

	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), "GO_TEST_CLI_ARGV=install", pathWith(dir),
		"XDG_RUNTIME_DIR="+runtime, "TMPDIR="+runtime, "XDG_STATE_HOME="+t.TempDir())
	cmd.Stdin = strings.NewReader(recipe)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("install: %v\n%s", err, out)
	}
	args, _ := os.ReadFile(argsFile)
	if strings.TrimSpace(string(args)) != "/usr/local/bin/fisherman -" {
		t.Errorf("fisherman argv = %q, want the stdin form", args)
	}
	if strings.Contains(string(args), "s3cret") {
		t.Error("the passphrase reached argv")
	}
	var got Recipe
	data, _ := os.ReadFile(stdinFile)
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("fisherman's stdin is not the recipe: %v\n%s", err, data)
	}
	if got.Encryption.Passphrase != "s3cret" || got.AdditionalImageStores != nil {
		t.Errorf("recipe on stdin = %+v; want it as sent, with no stores added", got)
	}
	entries, _ := os.ReadDir(runtime)
	if len(entries) != 0 {
		t.Errorf("install left files behind: %v", entries)
	}
}

// ---------------------------------------------------------------------------
// validate: fisherman's answer, passed through
// ---------------------------------------------------------------------------

func TestValidatePassesFishermansAnswerThrough(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	stdinFile := filepath.Join(dir, "stdin")
	argsFile := filepath.Join(dir, "args")
	fake := filepath.Join(dir, "fisherman")
	answer := `{"protocol_version":1,"valid":false,"errors":[{"field":"hostname","code":"hostname_label_hyphen","message":"m"}]}`
	writeStub(t, dir, "fisherman", "#!/bin/sh\necho \"$@\" > "+argsFile+"\ncat > "+stdinFile+"\necho '"+answer+"'\nexit 1\n")

	var stdout, stderr strings.Builder
	code := runValidateWith([]string{fake, "validate", "--json", "--partial", "-"},
		strings.NewReader(`{"hostname":"-router"}`), &stdout, &stderr)
	if code != 1 {
		t.Fatalf("code = %d, stderr = %q", code, stderr.String())
	}
	if strings.TrimSpace(stdout.String()) != answer {
		t.Errorf("stdout = %q, want fisherman's answer", stdout.String())
	}
	if data, _ := os.ReadFile(stdinFile); string(data) != `{"hostname":"-router"}` {
		t.Errorf("fisherman read %q on stdin", data)
	}
}

func TestValidateThatCannotRunIsExit2(t *testing.T) {
	var stdout, stderr strings.Builder
	code := runValidateWith([]string{"/nonexistent/fisherman"}, strings.NewReader("{}"), &stdout, &stderr)
	if code != 2 || stdout.String() != "" {
		t.Errorf("code = %d, stdout = %q; want 2 and nothing on stdout", code, stdout.String())
	}
}

func TestValidateCommandIsUnprivilegedPartialAndOnStdin(t *testing.T) {
	for _, flatpak := range []bool{false, true} {
		argv := validateCommandFor(flatpak)
		tail := strings.Join(argv[len(argv)-5:], " ")
		if tail != "/usr/local/bin/fisherman validate --json --partial -" {
			t.Errorf("validateCommandFor(%v) = %v", flatpak, argv)
		}
		for _, a := range argv {
			if a == "sudo" || a == "pkexec" {
				t.Errorf("validate runs privileged: %v", argv)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// readiness
// ---------------------------------------------------------------------------

func TestReadinessSubcommandWritesTheStamp(t *testing.T) {
	runtimeDir := t.TempDir()

	got := runCLI(t, []string{"XDG_RUNTIME_DIR=" + runtimeDir}, "readiness", "welcome")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	body, err := os.ReadFile(filepath.Join(runtimeDir, stampName))
	if err != nil {
		t.Fatalf("no stamp was written: %v", err)
	}
	if !strings.Contains(string(body), "page=welcome") {
		t.Errorf("stamp = %q, want the page the frontend passed", body)
	}
}

// Without a page argument the stamp still has to be well formed — a smoke test
// parses it either way.
func TestReadinessSubcommandDefaultsThePage(t *testing.T) {
	runtimeDir := t.TempDir()

	got := runCLI(t, []string{"XDG_RUNTIME_DIR=" + runtimeDir}, "readiness")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	body, err := os.ReadFile(filepath.Join(runtimeDir, stampName))
	if err != nil {
		t.Fatalf("no stamp was written: %v", err)
	}
	if !strings.Contains(string(body), "page=unknown") {
		t.Errorf("stamp = %q, want page=unknown", body)
	}
}

// The stamp is observability. A frontend that cannot write it must still come
// up, so this path reports on stderr and exits 0 by design.
func TestReadinessSubcommandSucceedsWhenTheStampCannotBeWritten(t *testing.T) {
	got := runCLI(t, []string{"XDG_RUNTIME_DIR="}, "readiness", "welcome")

	if got.code != 0 {
		t.Fatalf("exit code = %d, want 0 — a failed stamp must not fail the UI", got.code)
	}
	if !strings.Contains(got.stderr, "readiness:") {
		t.Errorf("stderr = %q, want the failure reported", got.stderr)
	}
}

// readinessStamp itself, in process: it is the seam between the environment
// and writeReadinessStamp.
func TestReadinessStampUsesTheRuntimeDirFromTheEnvironment(t *testing.T) {
	runtimeDir := t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", runtimeDir)

	readinessStamp("disk")

	body, err := os.ReadFile(filepath.Join(runtimeDir, stampName))
	if err != nil {
		t.Fatalf("no stamp was written: %v", err)
	}
	if !strings.Contains(string(body), "page=disk") {
		t.Errorf("stamp = %q, want page=disk", body)
	}
}

func TestReadinessStampIsBestEffortWithoutARuntimeDir(t *testing.T) {
	t.Setenv("XDG_RUNTIME_DIR", "")

	// Must not panic and must not exit: the install path keeps working.
	readinessStamp("welcome")
}
