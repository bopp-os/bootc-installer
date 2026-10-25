package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// The account step writes the recipe's `user` block, as XFCE does
// (docs/PARITY.md gap #4). Before it, Recipe had no User field, so a block
// the QML sent was dropped when runInstall re-encoded the recipe.

// installedJSON is what runInstall hands fisherman for this QML recipe.
func installedJSON(t *testing.T, qml string) map[string]any {
	t.Helper()
	var r Recipe
	if err := json.Unmarshal([]byte(qml), &r); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	normalizeRecipe(&r, "neutral")
	data, err := json.Marshal(r)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatalf("re-read: %v", err)
	}
	return out
}

func TestUserBlockReachesFisherman(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","hostname":"box",
		"encryption":{"type":"none"},
		"user":{"username":"jo","fullname":"Jo Doe","password":"pw","groups":["wheel"]}}`)
	want := map[string]any{
		"username": "jo", "fullname": "Jo Doe", "password": "pw",
		"groups": []any{"wheel"},
	}
	if !reflect.DeepEqual(out["user"], want) {
		t.Fatalf("user block = %#v, want %#v", out["user"], want)
	}
}

func TestUserBlockShapeMatchesXFCE(t *testing.T) {
	// Every key present, fullname included when empty, groups ["wheel"]:
	// the shape XFCE's build_recipe writes.
	u := User{Username: "jo", Password: "pw", Groups: defaultUserGroups}
	data, err := json.Marshal(u)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := string(data), `{"username":"jo","fullname":"","password":"pw","groups":["wheel"]}`; got != want {
		t.Fatalf("user JSON = %s, want %s", got, want)
	}
}

func TestUserGroupsDefaultToWheel(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","user":{"username":"jo","password":"pw"}}`)
	user, _ := out["user"].(map[string]any)
	if !reflect.DeepEqual(user["groups"], []any{"wheel"}) {
		t.Fatalf("groups = %#v, want [wheel]", user["groups"])
	}
}

func TestUserGroupsAreKeptWhenGiven(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","user":{"username":"jo","password":"pw","groups":["wheel","audio"]}}`)
	user, _ := out["user"].(map[string]any)
	if !reflect.DeepEqual(user["groups"], []any{"wheel", "audio"}) {
		t.Fatalf("groups = %#v", user["groups"])
	}
}

func TestUserBlockOmittedWhenAbsent(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","hostname":"box"}`)
	if _, ok := out["user"]; ok {
		t.Fatalf("a recipe with no account gained a user block: %#v", out["user"])
	}
}

func TestUserBlockWithoutUsernameIsDropped(t *testing.T) {
	// The schema's "an empty username skips the step": a password with no
	// account is not passed on.
	out := installedJSON(t, `{"disk":"/dev/vda","user":{"username":"","password":"pw"}}`)
	if _, ok := out["user"]; ok {
		t.Fatalf("an empty username still sent a user block: %#v", out["user"])
	}
}

func TestDefaultGroupsAreNotShared(t *testing.T) {
	var a, b Recipe
	a.User = &User{Username: "a"}
	b.User = &User{Username: "b"}
	normalizeRecipe(&a, "x")
	normalizeRecipe(&b, "x")
	a.User.Groups[0] = "changed"
	if b.User.Groups[0] != "wheel" || defaultUserGroups[0] != "wheel" {
		t.Fatal("normalizeRecipe aliased defaultUserGroups between recipes")
	}
}

func TestNormalizeRecipeDistroID(t *testing.T) {
	r := Recipe{}
	normalizeRecipe(&r, "fallback")
	if r.DistroID != "fallback" {
		t.Fatalf("distroID = %q, want the branding's", r.DistroID)
	}
	r = Recipe{DistroID: "given"}
	normalizeRecipe(&r, "fallback")
	if r.DistroID != "given" {
		t.Fatalf("distroID = %q, want the recipe's own", r.DistroID)
	}
}

func TestQMLHoldsTheAccountStep(t *testing.T) {
	// The QML half of the contract, read as text: the recipe carries the
	// user block with groups ["wheel"], the partial recipe asks fisherman
	// about user.username, and the problem is shown through the copy keys
	// validate_username_* (via validate_<code>).
	qml := readQML(t)
	for _, want := range []string{
		`groups: ["wheel"]`,
		`user: { username: root.username }`,
		`problemText("user.username")`,
		`"Account"`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("ui/installer.qml lacks %q", want)
		}
	}
}

func readQML(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("..", "ui", "installer.qml"))
	if err != nil {
		t.Fatalf("read installer.qml: %v", err)
	}
	return string(data)
}
