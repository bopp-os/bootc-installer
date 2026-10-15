package main

// Hardware facts from `fisherman probe --json` (shared/probe/README.md).
//
// fisherman decides which disks may be installed to, labels their sizes, and
// answers TPM 2.0 and the RAM/CPU/UEFI requirements. This backend used to run
// `lsblk -J` itself, offered every TYPE == disk (zram and the live USB
// included), passed lsblk's size strings through, and probed the TPM itself.
// This file only runs the command and keeps the answer; it filters and
// formats nothing.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"
)

// probeProtocolVersion is the schema version this reader understands
// (fisherman/docs/PROBE.md).
const probeProtocolVersion = 1

// fakeProbeEnv is the test and screenshot seam: a file holding probe output.
// When set, no process runs. Every frontend honours the same variable.
const fakeProbeEnv = "BOOTC_INSTALLER_FAKE_PROBE"

// probeTimeout bounds lsblk and `bootc status`; a hung host helper must not
// hang the wizard.
const probeTimeout = 30 * time.Second

// ProbeDisk is one eligible disk, as every frontend renders it. It is also
// the exact shape `discover-disks` prints for the QML, and the shape of
// shared/probe/fixtures/*.expected.json.
type ProbeDisk struct {
	Path           string `json:"path"`
	Title          string `json:"title"` // the model, or the path when unknown
	Model          string `json:"model"`
	SizeLabel      string `json:"size_label"` // fisherman's, verbatim
	TransportLabel string `json:"transport_label"`
	Removable      bool   `json:"removable"`
}

// ProbeFacts is what the wizard needs from one probe run.
type ProbeFacts struct {
	Disks     []ProbeDisk
	TPMUsable bool
	Unmet     []string // "ram", "cpu", "uefi"
	// IsLive: the host booted from live media (live.is_live). Only then may
	// the recipe leave `image` empty, which installs the running system.
	IsLive bool
	// LiveImage is the booted image when live (live.live_image), else "".
	LiveImage string
	// OfflineImages are the image refs in the host's offline stores
	// (offline.images). The stores themselves are fisherman's: a recipe that
	// leaves additionalImageStores out gets them.
	OfflineImages []string
}

// parseProbe reads probe output.
func parseProbe(data []byte) (ProbeFacts, error) {
	var raw struct {
		ProtocolVersion *int `json:"protocol_version"`
		Disks           []struct {
			Path           string `json:"path"`
			Model          string `json:"model"`
			SizeLabel      string `json:"size_label"`
			TransportLabel string `json:"transport_label"`
			Removable      bool   `json:"removable"`
			Eligible       *bool  `json:"eligible"`
		} `json:"disks"`
		TPM struct {
			Usable bool `json:"usable"`
		} `json:"tpm"`
		System struct {
			Unmet []string `json:"unmet"`
		} `json:"system"`
		Live struct {
			IsLive    bool   `json:"is_live"`
			LiveImage string `json:"live_image"`
		} `json:"live"`
		Offline struct {
			Images []string `json:"images"`
		} `json:"offline"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return ProbeFacts{}, fmt.Errorf("fisherman probe printed invalid JSON: %w", err)
	}
	if raw.ProtocolVersion == nil || *raw.ProtocolVersion != probeProtocolVersion {
		v := "missing"
		if raw.ProtocolVersion != nil {
			v = fmt.Sprint(*raw.ProtocolVersion)
		}
		return ProbeFacts{}, fmt.Errorf("fisherman probe protocol_version %s is not %d", v, probeProtocolVersion)
	}
	facts := ProbeFacts{Disks: []ProbeDisk{}, TPMUsable: raw.TPM.Usable, Unmet: []string{},
		IsLive: raw.Live.IsLive, OfflineImages: []string{}}
	if raw.Live.IsLive {
		facts.LiveImage = raw.Live.LiveImage
	}
	if raw.Offline.Images != nil {
		facts.OfflineImages = raw.Offline.Images
	}
	for _, d := range raw.Disks {
		// A missing flag or an unknown excluded_reason means "not eligible".
		if d.Eligible == nil || !*d.Eligible {
			continue
		}
		title := d.Model
		if title == "" {
			title = d.Path
		}
		facts.Disks = append(facts.Disks, ProbeDisk{
			Path: d.Path, Title: title, Model: d.Model, SizeLabel: d.SizeLabel,
			TransportLabel: d.TransportLabel, Removable: d.Removable,
		})
	}
	if raw.System.Unmet != nil {
		facts.Unmet = raw.System.Unmet
	}
	return facts, nil
}

// probeCommandFor is the unprivileged command: the fisherman the install
// runs, on the host. Never pkexec or sudo.
func probeCommandFor(flatpak bool) []string {
	argv := []string{"/usr/local/bin/fisherman", "probe", "--json"}
	if flatpak {
		return append([]string{"flatpak-spawn", "--host"}, argv...)
	}
	return argv
}

// runProbe runs the probe, or reads BOOTC_INSTALLER_FAKE_PROBE. There is no
// fallback scan: on failure the error says why.
func runProbe() (ProbeFacts, error) {
	if fake := os.Getenv(fakeProbeEnv); fake != "" {
		data, err := os.ReadFile(fake)
		if err != nil {
			return ProbeFacts{}, fmt.Errorf("%s=%s: %w", fakeProbeEnv, fake, err)
		}
		return parseProbe(data)
	}
	argv := probeCommandFor(inFlatpak())
	ctx, cancel := context.WithTimeout(context.Background(), probeTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if ctx.Err() != nil {
		return ProbeFacts{}, fmt.Errorf("fisherman probe did not finish within %s", probeTimeout)
	}
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			first := strings.SplitN(strings.TrimSpace(stderr.String()), "\n", 2)[0]
			if first == "" {
				first = "no message"
			}
			return ProbeFacts{}, fmt.Errorf("fisherman probe failed (exit %d): %s", exitErr.ExitCode(), first)
		}
		return ProbeFacts{}, fmt.Errorf("cannot run %s: %w", argv[0], err)
	}
	return parseProbe(out)
}
