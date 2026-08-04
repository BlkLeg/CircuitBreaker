package hostinfo

import (
	"bufio"
	"bytes"
	"os"
	"strings"
)

// osReleaseSourcePaths mirrors the os-release spec's own fallback order: distros that ship
// /usr/lib/os-release only (and symlink /etc/os-release to it) still resolve correctly, and a
// missing /etc copy doesn't make the host unidentifiable.
var osReleaseSourcePaths = []string{"/etc/os-release", "/usr/lib/os-release"}

// osRelease returns the distro ID (e.g. "ubuntu", "fedora") and VERSION_ID (e.g. "22.04", "44")
// from the first readable os-release file, feeding HelloPayload.OSVersion via formatOSVersion
// (see hostinfo.go's package doc for why this is kept separate from the GOOS-style
// HelloPayload.OS). If neither file is readable, or the file has no ID line, both return values
// are empty — there is no runtime.GOOS fallback here; that field's fallback lives directly in
// Collect, sourced from runtime.GOOS, independent of os-release.
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
	return "", ""
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
	return id, versionID
}

// formatOSVersion combines the distro ID and VERSION_ID parsed from os-release into the single
// "name version" string HelloPayload.OSVersion reports (e.g. "fedora 44"). Either half may be
// missing (unreadable file, or a VERSION_ID-less rolling-release distro); this degrades
// gracefully to whichever half is present, or "" if neither is.
func formatOSVersion(id, versionID string) string {
	switch {
	case id == "" && versionID == "":
		return ""
	case id == "":
		return versionID
	case versionID == "":
		return id
	default:
		return id + " " + versionID
	}
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
