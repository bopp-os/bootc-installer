package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// shared/probe/fixtures: the same probe outputs, and the renderings every
// frontend must produce from them (shared/probe/README.md).
var probeFixtures = filepath.Join("..", "..", "..", "shared", "probe", "fixtures")

func TestProbeFixturesRenderLikeEveryFrontend(t *testing.T) {
	if _, err := os.Stat(probeFixtures); err != nil {
		t.Skip("shared/probe/fixtures is absent; this tree is checked out alone")
	}
	for _, name := range []string{"laptop", "container", "vm", "pure-live-oci"} {
		t.Run(name, func(t *testing.T) {
			input, err := os.ReadFile(filepath.Join(probeFixtures, name+".json"))
			if err != nil {
				t.Fatal(err)
			}
			raw, err := os.ReadFile(filepath.Join(probeFixtures, name+".expected.json"))
			if err != nil {
				t.Fatal(err)
			}
			var want struct {
				Disks         []ProbeDisk `json:"disks"`
				TPMUsable     bool        `json:"tpm_usable"`
				Unmet         []string    `json:"unmet"`
				LiveImage     string      `json:"live_image"`
				OfflineImages []string    `json:"offline_images"`
			}
			if err := json.Unmarshal(raw, &want); err != nil {
				t.Fatal(err)
			}
			facts, err := parseProbe(input)
			if err != nil {
				t.Fatal(err)
			}
			// What discover-disks prints is exactly the shared rendering.
			got, _ := json.Marshal(facts.Disks)
			wantJSON, _ := json.Marshal(want.Disks)
			if string(got) != string(wantJSON) {
				t.Errorf("disks:\n got %s\nwant %s", got, wantJSON)
			}
			if facts.TPMUsable != want.TPMUsable {
				t.Errorf("tpm usable = %v, want %v", facts.TPMUsable, want.TPMUsable)
			}
			if !reflect.DeepEqual(facts.Unmet, want.Unmet) {
				t.Errorf("unmet = %v, want %v", facts.Unmet, want.Unmet)
			}
			if facts.LiveImage != want.LiveImage {
				t.Errorf("live image = %q, want %q", facts.LiveImage, want.LiveImage)
			}
			if !reflect.DeepEqual(facts.OfflineImages, want.OfflineImages) {
				t.Errorf("offline images = %v, want %v", facts.OfflineImages, want.OfflineImages)
			}
		})
	}
}

func TestProbeRejectsWhatItCannotRead(t *testing.T) {
	for _, text := range []string{"", "not json", "[]", `{"protocol_version": 2}`, `{}`} {
		if _, err := parseProbe([]byte(text)); err == nil {
			t.Errorf("parseProbe(%q) accepted it", text)
		}
	}
}

func TestProbeOffersOnlyEligibleDisks(t *testing.T) {
	facts, err := parseProbe([]byte(`{"protocol_version":1,"disks":[
		{"path":"/dev/a","eligible":false,"excluded_reason":"something_new"},
		{"path":"/dev/b"},
		{"path":"/dev/c","eligible":true,"model":"","size_label":"1 TiB"}]}`))
	if err != nil {
		t.Fatal(err)
	}
	if len(facts.Disks) != 1 || facts.Disks[0].Title != "/dev/c" {
		t.Errorf("disks = %+v, want only /dev/c titled by its path", facts.Disks)
	}
	if facts.Unmet == nil {
		t.Error("unmet must be an empty array, never null, for the QML")
	}
}

func TestProbeCommandIsUnprivilegedAndOnTheHost(t *testing.T) {
	host := []string{"/usr/local/bin/fisherman", "probe", "--json"}
	if got := probeCommandFor(false); !reflect.DeepEqual(got, host) {
		t.Errorf("host = %v", got)
	}
	if got := probeCommandFor(true); !reflect.DeepEqual(got, append([]string{"flatpak-spawn", "--host"}, host...)) {
		t.Errorf("flatpak = %v", got)
	}
}
