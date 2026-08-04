package hostinfo

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"strings"
)

// machineIDSourcePaths are tried in order; the first that reads successfully wins. Mirrors
// systemd's own /etc/machine-id -> /var/lib/dbus/machine-id fallback.
var machineIDSourcePaths = []string{"/etc/machine-id", "/var/lib/dbus/machine-id"}

// machineIDHash returns the sha256 hex digest of this host's machine ID, or "" if neither source
// path is readable (containers/minimal images without either file).
func machineIDHash() string {
	return machineIDHashFromPaths(machineIDSourcePaths)
}

func machineIDHashFromPaths(paths []string) string {
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		if hash, ok := hashMachineID(data); ok {
			return hash
		}
	}
	return ""
}

// hashMachineID trims surrounding whitespace/newline before hashing — the raw file content
// (particularly /etc/machine-id) commonly carries a trailing newline that must not change the
// hash. Returns ok=false for empty-after-trim content (e.g. a zero-byte or whitespace-only file)
// rather than hashing an empty string.
func hashMachineID(data []byte) (hash string, ok bool) {
	trimmed := strings.TrimSpace(string(data))
	if trimmed == "" {
		return "", false
	}
	sum := sha256.Sum256([]byte(trimmed))
	return hex.EncodeToString(sum[:]), true
}
