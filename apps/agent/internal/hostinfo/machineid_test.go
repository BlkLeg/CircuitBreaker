package hostinfo

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestHashMachineID(t *testing.T) {
	rawExpected := func(trimmed string) string {
		sum := sha256.Sum256([]byte(trimmed))
		return hex.EncodeToString(sum[:])
	}

	tests := []struct {
		name     string
		data     string
		wantHash string
		wantOK   bool
	}{
		{
			name:     "trims trailing newline before hashing",
			data:     "abc123def456\n",
			wantHash: rawExpected("abc123def456"),
			wantOK:   true,
		},
		{
			name:     "trims surrounding whitespace before hashing",
			data:     "  abc123def456  \n",
			wantHash: rawExpected("abc123def456"),
			wantOK:   true,
		},
		{
			name:     "no trailing newline hashes the same as with one",
			data:     "abc123def456",
			wantHash: rawExpected("abc123def456"),
			wantOK:   true,
		},
		{
			name:   "empty content is not a valid machine ID",
			data:   "",
			wantOK: false,
		},
		{
			name:   "whitespace-only content is not a valid machine ID",
			data:   "   \n\t",
			wantOK: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			hash, ok := hashMachineID([]byte(tt.data))
			if ok != tt.wantOK {
				t.Fatalf("hashMachineID(%q) ok = %v, want %v", tt.data, ok, tt.wantOK)
			}
			if ok && hash != tt.wantHash {
				t.Errorf("hashMachineID(%q) = %q, want %q", tt.data, hash, tt.wantHash)
			}
		})
	}
}

func TestHashMachineID_TrimmingChangesTheHash(t *testing.T) {
	// Documents the specific requirement: hashing raw (untrimmed) bytes must NOT be what we
	// compute, since /etc/machine-id commonly carries a trailing newline that a naive
	// sha256.Sum256(data) would bake into the hash.
	data := []byte("abc123def456\n")
	trimmedHash, ok := hashMachineID(data)
	if !ok {
		t.Fatalf("hashMachineID(%q) ok = false, want true", data)
	}
	rawSum := sha256.Sum256(data)
	rawHash := hex.EncodeToString(rawSum[:])
	if trimmedHash == rawHash {
		t.Errorf("hashMachineID(%q) = %q equals the untrimmed hash %q; whitespace was not trimmed before hashing", data, trimmedHash, rawHash)
	}
}

func TestMachineIDHashFromPaths(t *testing.T) {
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
		primary := writeFile(t, "primary", "primary-id\n")
		missing := filepath.Join(dir, "does-not-exist")
		got := machineIDHashFromPaths([]string{primary, missing})
		want, _ := hashMachineID([]byte("primary-id"))
		if got != want {
			t.Errorf("machineIDHashFromPaths = %q, want %q", got, want)
		}
	})

	t.Run("falls through to the next path when the first is missing", func(t *testing.T) {
		missing := filepath.Join(dir, "does-not-exist")
		fallback := writeFile(t, "fallback", "fallback-id\n")
		got := machineIDHashFromPaths([]string{missing, fallback})
		want, _ := hashMachineID([]byte("fallback-id"))
		if got != want {
			t.Errorf("machineIDHashFromPaths = %q, want %q", got, want)
		}
	})

	t.Run("falls through when the first path is empty content", func(t *testing.T) {
		empty := writeFile(t, "empty", "")
		fallback := writeFile(t, "fallback2", "fallback-id-2\n")
		got := machineIDHashFromPaths([]string{empty, fallback})
		want, _ := hashMachineID([]byte("fallback-id-2"))
		if got != want {
			t.Errorf("machineIDHashFromPaths = %q, want %q", got, want)
		}
	})

	t.Run("returns empty string when no path is readable", func(t *testing.T) {
		missing1 := filepath.Join(dir, "missing-1")
		missing2 := filepath.Join(dir, "missing-2")
		got := machineIDHashFromPaths([]string{missing1, missing2})
		if got != "" {
			t.Errorf("machineIDHashFromPaths = %q, want empty string", got)
		}
	})
}
