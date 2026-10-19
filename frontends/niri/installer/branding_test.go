package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// The fixtures every frontend's resolver is judged by. Relative to this
// package inside the monorepo; skipped when the tree is checked out alone.
var fixturesDir = filepath.Join("..", "..", "..", "shared", "branding", "fixtures")

func write(t *testing.T, dir, name, body string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

type fixtureCase struct {
	Branding       *string           `json:"branding"`
	OsRelease      *string           `json:"os_release"`
	Expect         map[string]string `json:"expect"`
	ExpectCopy     map[string]string `json:"expect_copy"`
	ExpectAssets   map[string]string `json:"expect_assets"`
	ExpectStoreURL *string           `json:"expect_store_url"`
	NameOverride   string            `json:"name_override"`
	ExpectName     string            `json:"expect_name"`
}

func loadFixtures(t *testing.T) map[string]fixtureCase {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(fixturesDir, "expected.json"))
	if err != nil {
		t.Skipf("shared fixtures not available: %v", err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatal(err)
	}
	cases := map[string]fixtureCase{}
	for name, msg := range raw {
		if name == "_comment" {
			continue
		}
		var c fixtureCase
		if err := json.Unmarshal(msg, &c); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		cases[name] = c
	}
	return cases
}

func inputs(t *testing.T, c fixtureCase) (map[string]any, string) {
	t.Helper()
	var file map[string]any
	if c.Branding != nil {
		data, err := os.ReadFile(filepath.Join(fixturesDir, *c.Branding))
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(data, &file); err != nil {
			t.Fatal(err)
		}
	}
	osr := ""
	if c.OsRelease != nil {
		data, err := os.ReadFile(filepath.Join(fixturesDir, *c.OsRelease))
		if err != nil {
			t.Fatal(err)
		}
		osr = string(data)
	}
	return file, osr
}

func asContractMap(b Branding) map[string]string {
	return map[string]string{
		"name":             b.Name,
		"id":               b.ID,
		"vendor":           b.Vendor,
		"home_url":         b.HomeURL,
		"docs_url":         b.DocsURL,
		"support_url":      b.SupportURL,
		"logo":             b.Logo,
		"default_hostname": b.DefaultHostname,
		"default_image":    b.DefaultImage,
	}
}

func TestBrandingFixtures(t *testing.T) {
	for name, c := range loadFixtures(t) {
		t.Run(name, func(t *testing.T) {
			file, osr := inputs(t, c)
			got := brandingFromSources(file, osr, c.NameOverride)
			if c.Expect != nil {
				gm := asContractMap(got)
				for k, want := range c.Expect {
					if gm[k] != want {
						t.Errorf("%s: got %q want %q", k, gm[k], want)
					}
				}
			}
			if c.ExpectName != "" && got.Name != c.ExpectName {
				t.Errorf("name override: got %q want %q", got.Name, c.ExpectName)
			}
			for k, want := range c.ExpectCopy {
				if got.Copy[k] != want {
					t.Errorf("copy.%s: got %q want %q", k, got.Copy[k], want)
				}
			}
			for k, want := range c.ExpectAssets {
				if got.Assets[k] != want {
					t.Errorf("assets.%s: got %q want %q", k, got.Assets[k], want)
				}
			}
			if c.ExpectStoreURL != nil && got.StoreURL != *c.ExpectStoreURL {
				t.Errorf("store_url: got %q want %q", got.StoreURL, *c.ExpectStoreURL)
			}
		})
	}
}

func TestResolveBrandingFromReadsInOrder(t *testing.T) {
	dir := t.TempDir()
	broken := write(t, dir, "broken.json", "{ not json")
	good := write(t, dir, "good.json", `{"name": "FromFile", "default_image": "ghcr.io/x/y:1"}`)
	osr := write(t, dir, "os-release", "ID=filetest\nPRETTY_NAME=\"From OS\"\n")
	missing := filepath.Join(dir, "missing")

	got := resolveBrandingFrom([]string{missing, broken, good}, []string{missing, osr}, "")
	if got.Name != "FromFile" || got.ID != "filetest" || got.DefaultHostname != "filetest" || got.DefaultImage != "ghcr.io/x/y:1" {
		t.Errorf("unexpected merge: %+v", got)
	}

	got = resolveBrandingFrom([]string{missing}, []string{missing}, "")
	if got.Name != neutralName || got.ID != neutralID || got.DefaultImage != "" {
		t.Errorf("nothing readable must be neutral, got %+v", got)
	}
}

func TestParseOsReleaseQuoting(t *testing.T) {
	got := parseOsRelease("# c\nNAME=\"Quoted \\\"Name\\\"\"\nPRETTY_NAME='Single'\nID=plain rest\nEMPTY=\nNOEQ\n")
	want := map[string]string{"NAME": `Quoted "Name"`, "PRETTY_NAME": "Single", "ID": "plain", "EMPTY": ""}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s: got %q want %q", k, got[k], v)
		}
	}
	if _, ok := got["NOEQ"]; ok {
		t.Error("line without = must be skipped")
	}
}

func TestCopyDefaultsMatchShared(t *testing.T) {
	shared, err := os.ReadFile(filepath.Join(fixturesDir, "..", "copy-defaults.json"))
	if err != nil {
		t.Skipf("shared copy-defaults.json not available: %v", err)
	}
	if string(shared) != string(copyDefaultsJSON) {
		t.Fatal("installer/copy-defaults.json has diverged from shared/branding/copy-defaults.json; cp the shared one over")
	}
	if copyDefaults()["welcome_title"] == "" {
		t.Fatal("copy defaults did not parse")
	}
}

func TestText(t *testing.T) {
	b := brandingFromSources(map[string]any{"name": "Marlin"}, "", "")
	if got := b.Text("confirm_warning", map[string]string{"disk": "/dev/sda"}); got != "Everything on /dev/sda will be erased. This cannot be undone." {
		t.Errorf("Text: %q", got)
	}
	if got := b.Text("welcome_title", nil); got != "Welcome to Marlin" {
		t.Errorf("Text name: %q", got)
	}
}

func TestLogoPathFixtures(t *testing.T) {
	data, err := os.ReadFile(filepath.Join(fixturesDir, "logo-paths.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixtures struct {
		Cases []struct {
			Spec      string `json:"spec"`
			InFlatpak bool   `json:"in_flatpak"`
			Kind      string `json:"kind"`
			Value     string `json:"value"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	for _, c := range fixtures.Cases {
		kind, value := resolveLogo(c.Spec, c.InFlatpak)
		if kind != c.Kind || value != c.Value {
			t.Errorf("resolveLogo(%q, %v) = (%q, %q), want (%q, %q)", c.Spec, c.InFlatpak, kind, value, c.Kind, c.Value)
		}
	}
}

func TestLogoURLPreservesSpecialCharacters(t *testing.T) {
	b := (Branding{Logo: "/usr/share/logo with spaces #1.svg"}).withLogo(true)
	if b.LogoKind != "file" || b.LogoValue != "file:///run/host/usr/share/logo%20with%20spaces%20%231.svg" {
		t.Fatalf("unexpected logo URL: %+v", b)
	}
}
