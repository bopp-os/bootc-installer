package main

// `fisherman validate --json --partial -` for the QML, and the encryption
// choices (shared/recipe/README.md).
//
// fisherman owns the hostname, username, filesystem and encryption rules
// (fisherman/docs/VALIDATE.md). The QML sends a page's fields here as a
// partial recipe on stdin; this backend hands them to fisherman on stdin too
// and prints fisherman's answer unchanged. A passphrase never goes on argv,
// which is world-readable in /proc.

import (
	"bytes"
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"time"
)

// encryptionChoicesJSON is a byte-identical copy of fisherman's
// data/encryption-choices.json (tests/unit/test_encryption_choices.py).
//
//go:embed encryption-choices.json
var encryptionChoicesJSON []byte

// EncryptionChoice is one encryption type, in the order the page offers it.
type EncryptionChoice struct {
	Type            string `json:"type"`
	Encrypted       bool   `json:"encrypted"`
	NeedsPassphrase bool   `json:"needs_passphrase"`
	NeedsTPM2       bool   `json:"needs_tpm2"`
	CopyKey         string `json:"copy_key"`
}

// encryptionChoices is the embedded file's list.
func encryptionChoices() []EncryptionChoice {
	var doc struct {
		Choices []EncryptionChoice `json:"choices"`
	}
	if err := json.Unmarshal(encryptionChoicesJSON, &doc); err != nil {
		// The file is compiled in and tested; this cannot happen at run time.
		panic(fmt.Sprintf("encryption-choices.json: %v", err))
	}
	return doc.Choices
}

// validateTimeout bounds one check. --partial reads nothing from the
// machine, so this only bounds a hung flatpak-spawn.
const validateTimeout = 10 * time.Second

// validateCommandFor is the unprivileged command: the fisherman the install
// runs, on the host. Never pkexec or sudo.
func validateCommandFor(flatpak bool) []string {
	argv := []string{"/usr/local/bin/fisherman", "validate", "--json", "--partial", "-"}
	if flatpak {
		return append([]string{"flatpak-spawn", "--host"}, argv...)
	}
	return argv
}

// runValidate sends the partial recipe on stdin to fisherman and copies its
// answer to stdout. It exits as fisherman did for 0 (valid) and 1
// (invalid); anything else means the check could not run, and is exit 2
// with the reason on stderr, which the QML treats as "no answer".
func runValidate(stdin io.Reader, stdout, stderr io.Writer) int {
	return runValidateWith(validateCommandFor(inFlatpak()), stdin, stdout, stderr)
}

// runValidateWith is runValidate with the command given (tests).
func runValidateWith(argv []string, stdin io.Reader, stdout, stderr io.Writer) int {
	recipe, err := io.ReadAll(io.LimitReader(stdin, 1<<20))
	if err != nil {
		fmt.Fprintf(stderr, "read recipe: %v\n", err)
		return 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), validateTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Stdin = bytes.NewReader(recipe)
	var out, errOut bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errOut
	err = cmd.Run()
	code := 0
	if err != nil {
		var exitErr *exec.ExitError
		if !errors.As(err, &exitErr) {
			fmt.Fprintf(stderr, "cannot run %s: %v\n", argv[0], err)
			return 2
		}
		code = exitErr.ExitCode()
	}
	if code != 0 && code != 1 {
		fmt.Fprintf(stderr, "fisherman validate failed (exit %d): %s", code, errOut.String())
		return 2
	}
	var answer struct {
		ProtocolVersion int               `json:"protocol_version"`
		Errors          []json.RawMessage `json:"errors"`
	}
	if json.Unmarshal(out.Bytes(), &answer) != nil || answer.ProtocolVersion != 1 || answer.Errors == nil {
		fmt.Fprintf(stderr, "fisherman validate printed an answer this backend cannot read: %s\n", out.String())
		return 2
	}
	_, _ = stdout.Write(out.Bytes())
	return code
}

func validateMain() {
	os.Exit(runValidate(os.Stdin, os.Stdout, os.Stderr))
}
