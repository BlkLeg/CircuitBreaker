package hostinfo

import (
	"bufio"
	"bytes"
	"os"
	"runtime"
	"strings"
)

// osReleaseSourcePaths mirrors the os-release spec's own fallback order: distros that ship
// /usr/lib/os-release only (and symlink /etc/os-release to it) still resolve correctly, and a
// missing /etc copy doesn't make the host unidentifiable.
var osReleaseSourcePaths = []string{"/etc/os-release", "/usr/lib/os-release"}

// osRelease returns the distro ID (e.g. "ubuntu", "fedora") and VERSION_ID (e.g. "22.04", "44")
// from the first readable os-release file. If neither file is readable, or the file has no ID
// line, it falls back to runtime.GOOS so the OS field is never blank on a normal build.
func osRelease() (id, versionID string) {
	return osReleaseFromPaths(osReleaseSourcePaths)
}

func osReleaseFromPaths(paths []string) (id, versionID string) {
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		return parseOSRelease(data)
	}
	return runtime.GOOS, ""
}

// parseOSRelease implements the relevant subset of the os-release format (a shell-sourceable
// KEY=VALUE file): blank lines and comments are skipped, values may be double- or single-quoted
// or bare, and lines without an '=' (malformed) are skipped rather than aborting the whole parse.
// Only ID and VERSION_ID are extracted — the fields this collector reports.
func parseOSRelease(data []byte) (id, versionID string) {
	scanner := bufio.NewScanner(bytes.NewReader(data))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, found := strings.Cut(line, "=")
		if !found {
			continue // malformed line (no '='); skip and keep parsing the rest of the file
		}
		value = unquoteOSReleaseValue(strings.TrimSpace(value))
		switch strings.TrimSpace(key) {
		case "ID":
			id = value
		case "VERSION_ID":
			versionID = value
		}
	}
	if id == "" {
		id = runtime.GOOS
	}
	return id, versionID
}

// unquoteOSReleaseValue strips one layer of matching double or single quotes, the only quoting
// os-release values use in practice. Unquoted/malformed (mismatched-quote) values pass through
// unchanged.
func unquoteOSReleaseValue(v string) string {
	if len(v) >= 2 {
		if (v[0] == '"' && v[len(v)-1] == '"') || (v[0] == '\'' && v[len(v)-1] == '\'') {
			return v[1 : len(v)-1]
		}
	}
	return v
}
