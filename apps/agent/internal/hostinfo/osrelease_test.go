package hostinfo

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestParseOSRelease(t *testing.T) {
	tests := []struct {
		name          string
		content       string
		wantID        string
		wantVersionID string
	}{
		{
			name: "typical fedora fixture",
			content: `NAME="Fedora Linux"
VERSION="44 (Server Edition)"
ID=fedora
VERSION_ID=44
PRETTY_NAME="Fedora Linux 44 (Server Edition)"
`,
			wantID:        "fedora",
			wantVersionID: "44",
		},
		{
			name: "typical ubuntu fixture with single-quoted-free plain values",
			content: `PRETTY_NAME="Ubuntu 22.04.3 LTS"
NAME="Ubuntu"
VERSION_ID="22.04"
VERSION="22.04.3 LTS (Jammy Jellyfish)"
ID=ubuntu
ID_LIKE=debian
`,
			wantID:        "ubuntu",
			wantVersionID: "22.04",
		},
		{
			name: "single-quoted values are unquoted",
			content: `ID='alpine'
VERSION_ID='3.19'
`,
			wantID:        "alpine",
			wantVersionID: "3.19",
		},
		{
			name: "unquoted bare values",
			content: `ID=arch
VERSION_ID=
`,
			wantID:        "arch",
			wantVersionID: "",
		},
		{
			name: "blank lines and comments are skipped",
			content: `# this is a comment

ID=debian
# another comment
VERSION_ID=12

`,
			wantID:        "debian",
			wantVersionID: "12",
		},
		{
			name: "malformed lines without '=' are skipped, not fatal",
			content: `this line has no equals sign
ID=rocky
%%% garbage %%%
VERSION_ID=9
`,
			wantID:        "rocky",
			wantVersionID: "9",
		},
		{
			name:          "empty file falls back to runtime.GOOS with no version",
			content:       "",
			wantID:        runtime.GOOS,
			wantVersionID: "",
		},
		{
			name: "missing ID falls back to runtime.GOOS but keeps a present VERSION_ID",
			content: `NAME="Mystery Linux"
VERSION_ID=1
`,
			wantID:        runtime.GOOS,
			wantVersionID: "1",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotID, gotVersionID := parseOSRelease([]byte(tt.content))
			if gotID != tt.wantID {
				t.Errorf("parseOSRelease() id = %q, want %q", gotID, tt.wantID)
			}
			if gotVersionID != tt.wantVersionID {
				t.Errorf("parseOSRelease() versionID = %q, want %q", gotVersionID, tt.wantVersionID)
			}
		})
	}
}

func TestOSReleaseFromPaths(t *testing.T) {
	dir := t.TempDir()

	writeFile := func(t *testing.T, name, content string) string {
		t.Helper()
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
			t.Fatalf("WriteFile(%s): %v", p, err)
		}
		return p
	}

	t.Run("uses the first readable path", func(t *testing.T) {
		primary := writeFile(t, "os-release-primary", "ID=fedora\nVERSION_ID=44\n")
		missing := filepath.Join(dir, "does-not-exist")
		id, versionID := osReleaseFromPaths([]string{primary, missing})
		if id != "fedora" || versionID != "44" {
			t.Errorf("osReleaseFromPaths = (%q, %q), want (fedora, 44)", id, versionID)
		}
	})

	t.Run("falls through to the next path when the first is missing", func(t *testing.T) {
		missing := filepath.Join(dir, "does-not-exist")
		fallback := writeFile(t, "os-release-fallback", "ID=debian\nVERSION_ID=12\n")
		id, versionID := osReleaseFromPaths([]string{missing, fallback})
		if id != "debian" || versionID != "12" {
			t.Errorf("osReleaseFromPaths = (%q, %q), want (debian, 12)", id, versionID)
		}
	})

	t.Run("no path readable falls back to runtime.GOOS", func(t *testing.T) {
		missing1 := filepath.Join(dir, "missing-1")
		missing2 := filepath.Join(dir, "missing-2")
		id, versionID := osReleaseFromPaths([]string{missing1, missing2})
		if id != runtime.GOOS || versionID != "" {
			t.Errorf("osReleaseFromPaths = (%q, %q), want (%q, \"\")", id, versionID, runtime.GOOS)
		}
	})
}
