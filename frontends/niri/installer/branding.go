package main

// Product branding: a branding.json first, os-release second, neutral last.
//
// The contract, the key table and the fixtures are in shared/branding/
// (monorepo root). Every frontend resolves the same way; this is the Go
// copy, exercised against the shared fixtures by branding_test.go. Nothing
// in this file names a product.
//
// copy-defaults.json next to this file is a byte-identical copy of
// shared/branding/copy-defaults.json (the monorepo's
// tests/unit/test_shared_branding.py enforces it); it is embedded so the
// backend needs no data file at runtime.

import (
	_ "embed"
	"encoding/json"
	"net/url"
	"os"
	"strings"
)

//go:embed copy-defaults.json
var copyDefaultsJSON []byte

const (
	brandingEnvFile = "BOOTC_INSTALLER_BRANDING"
	brandingEnvName = "BOOTC_INSTALLER_PRODUCT_NAME"
	neutralName     = "Linux"
	neutralID       = "linux"
)

// Common to every frontend; desktop-specific keys live under extensions.<frontend>.
var assetKeys = []string{"welcome_image", "complete_image", "store_qr"}

// Host first: this ships as a flatpak, where /etc is the runtime's and the
// host's is under /run/host. The first readable file wins; no merging.
var brandingPaths = []string{
	"/run/host/etc/bootc-installer/branding.json",
	"/run/host/usr/share/bootc-installer/branding.json",
	"/etc/bootc-installer/branding.json",
	"/usr/share/bootc-installer/branding.json",
}

var osReleasePaths = []string{
	"/run/host/etc/os-release",
	"/run/host/usr/lib/os-release",
	"/etc/os-release",
	"/usr/lib/os-release",
}

// Branding is the JSON the QML receives under detect's "branding" key.
type Branding struct {
	Name            string              `json:"name"`
	ID              string              `json:"id"`
	Vendor          string              `json:"vendor"`
	HomeURL         string              `json:"homeUrl"`
	DocsURL         string              `json:"docsUrl"`
	SupportURL      string              `json:"supportUrl"`
	StoreURL        string              `json:"storeUrl"`
	Logo            string              `json:"logo"`
	LogoKind        string              `json:"logoKind"`
	LogoValue       string              `json:"logoValue"`
	DefaultHostname string              `json:"defaultHostname"`
	DefaultImage    string              `json:"defaultImage"`
	Copy            map[string]string   `json:"copy"`
	Assets          map[string]string   `json:"assets"`
	ConfirmQuotes   map[string][]string `json:"confirmQuotes"`
}

// copyDefaults is copy-defaults.json without its "_comment" entry.
func copyDefaults() map[string]string {
	var raw map[string]any
	out := map[string]string{}
	if json.Unmarshal(copyDefaultsJSON, &raw) != nil {
		return out
	}
	for k, v := range raw {
		if s, ok := v.(string); ok && !strings.HasPrefix(k, "_") {
			out[k] = s
		}
	}
	return out
}

// Text returns a copy line with {name} and the given placeholders filled in.
func (b Branding) Text(key string, values map[string]string) string {
	line := b.Copy[key]
	line = strings.ReplaceAll(line, "{name}", b.Name)
	for k, v := range values {
		line = strings.ReplaceAll(line, "{"+k+"}", v)
	}
	return line
}

// resolveBranding reads the machine's branding using the real search paths
// and environment.
func resolveBranding() Branding {
	paths := brandingPaths
	if p := strings.TrimSpace(os.Getenv(brandingEnvFile)); p != "" {
		paths = []string{p}
	}
	b := resolveBrandingFrom(paths, osReleasePaths, os.Getenv(brandingEnvName))
	_, err := os.Stat("/.flatpak-info")
	return b.withLogo(err == nil)
}

func (b Branding) withLogo(inFlatpak bool) Branding {
	b.LogoKind, b.LogoValue = resolveLogo(b.Logo, inFlatpak)
	if b.LogoKind == "file" {
		b.LogoValue = (&url.URL{Scheme: "file", Path: b.LogoValue}).String()
	}
	return b
}

func resolveBrandingFrom(filePaths, osrPaths []string, nameOverride string) Branding {
	var file map[string]any
	for _, p := range filePaths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		var m map[string]any
		if json.Unmarshal(data, &m) != nil || m == nil {
			continue
		}
		file = m
		break
	}
	osr := ""
	for _, p := range osrPaths {
		data, err := os.ReadFile(p)
		if err != nil || strings.TrimSpace(string(data)) == "" {
			continue
		}
		osr = string(data)
		break
	}
	return brandingFromSources(file, osr, nameOverride)
}

// brandingFromSources is the pure merge rule from shared/branding/README.md.
func brandingFromSources(file map[string]any, osReleaseText, nameOverride string) Branding {
	osr := parseOsRelease(osReleaseText)
	pick := func(key string, def string, osKeys ...string) string {
		if v, ok := file[key].(string); ok && strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
		for _, k := range osKeys {
			if v := strings.TrimSpace(osr[k]); v != "" {
				return v
			}
		}
		return def
	}
	b := Branding{
		Name:            pick("name", neutralName, "PRETTY_NAME", "NAME"),
		ID:              pick("id", neutralID, "ID"),
		Vendor:          pick("vendor", "", "VENDOR_NAME", "NAME"),
		HomeURL:         pick("home_url", "", "HOME_URL"),
		DocsURL:         pick("docs_url", "", "DOCUMENTATION_URL"),
		SupportURL:      pick("support_url", "", "SUPPORT_URL"),
		StoreURL:        pick("store_url", ""),
		Logo:            pick("logo", "", "LOGO"),
		DefaultHostname: pick("default_hostname", neutralID, "DEFAULT_HOSTNAME", "ID"),
		DefaultImage:    pick("default_image", ""),
		Copy:            copyDefaults(),
		Assets:          map[string]string{},
		ConfirmQuotes:   map[string][]string{},
	}
	if o := strings.TrimSpace(nameOverride); o != "" {
		b.Name = o
	}
	for _, k := range assetKeys {
		b.Assets[k] = ""
	}
	// Flavour: a present string key overrides, even when empty (that is how
	// a product hides a line); anything else keeps the neutral default.
	if fc, ok := file["copy"].(map[string]any); ok {
		for k, v := range fc {
			if s, ok := v.(string); ok {
				if _, known := b.Copy[k]; known {
					b.Copy[k] = strings.TrimSpace(s)
				}
			}
		}
	}
	if fa, ok := file["assets"].(map[string]any); ok {
		for k, v := range fa {
			if s, ok := v.(string); ok {
				b.Assets[k] = strings.TrimSpace(s)
			}
		}
	}
	if fq, ok := file["confirm_quotes"].(map[string]any); ok {
		for k, v := range fq {
			list, ok := v.([]any)
			if !ok {
				continue
			}
			var lines []string
			for _, item := range list {
				if s, ok := item.(string); ok && strings.TrimSpace(s) != "" {
					lines = append(lines, strings.TrimSpace(s))
				}
			}
			if len(lines) > 0 {
				b.ConfirmQuotes[k] = lines
			}
		}
	}
	return b
}

// parseOsRelease returns KEY=value pairs with quotes and backslash escapes
// removed. Lines that do not parse are skipped, not fatal.
func parseOsRelease(text string) map[string]string {
	out := map[string]string{}
	for _, raw := range strings.Split(text, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		if key == "" {
			continue
		}
		out[key] = unquoteShell(strings.TrimSpace(value))
	}
	return out
}

// unquoteShell handles the subset of shell quoting os-release allows: a
// double-quoted string with backslash escapes, a single-quoted string, or a
// bare word (which ends at the first whitespace, like shlex.split()[0]).
func unquoteShell(v string) string {
	if v == "" {
		return ""
	}
	switch v[0] {
	case '"':
		var sb strings.Builder
		for i := 1; i < len(v); i++ {
			c := v[i]
			if c == '\\' && i+1 < len(v) {
				i++
				sb.WriteByte(v[i])
				continue
			}
			if c == '"' {
				break
			}
			sb.WriteByte(c)
		}
		return strings.TrimSpace(sb.String())
	case '\'':
		rest := v[1:]
		if end := strings.IndexByte(rest, '\''); end >= 0 {
			rest = rest[:end]
		}
		return strings.TrimSpace(rest)
	default:
		if i := strings.IndexAny(v, " \t"); i >= 0 {
			v = v[:i]
		}
		return v
	}
}

// resolveLogo implements shared/branding/fixtures/logo-paths.json. Return raw
// paths here; the runtime adapter URL-escapes them before sending them to QML.
func resolveLogo(spec string, inFlatpak bool) (string, string) {
	if spec == "" {
		return "none", ""
	}
	if strings.HasPrefix(spec, "/") {
		if inFlatpak && (strings.HasPrefix(spec, "/usr/") || strings.HasPrefix(spec, "/etc/")) {
			spec = "/run/host" + spec
		}
		return "file", spec
	}
	if strings.ContainsAny(spec, "/:") {
		return "none", ""
	}
	return "theme", spec
}
