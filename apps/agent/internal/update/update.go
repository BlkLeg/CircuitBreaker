// apps/agent/internal/update/update.go
package update

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"circuitbreaker.dev/cb-agent/internal/config"
)

type Instruction struct {
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
	Arch    string `json:"arch"`
	OS      string `json:"os"`
}

const markerFilename = "update_pending"

func Download(cfg *config.Config, instr Instruction) (string, error) {
	url := fmt.Sprintf(
		"%s/api/v1/agents/binary/%s/%s/%s",
		strings.TrimRight(cfg.ServerURL, "/"), instr.Version, instr.OS, instr.Arch,
	)
	resp, err := http.Get(url) //nolint:gosec // cfg.ServerURL is the operator-configured, trusted server — not user input.
	if err != nil {
		return "", fmt.Errorf("update: download %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("update: download %s: status %d", url, resp.StatusCode)
	}

	tmp, err := os.CreateTemp("", "cb-agent-update-*")
	if err != nil {
		return "", fmt.Errorf("update: create temp file: %w", err)
	}
	defer tmp.Close()

	if _, err := io.Copy(tmp, resp.Body); err != nil {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: write temp file: %w", err)
	}
	if err := tmp.Chmod(0o755); err != nil {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: chmod temp file: %w", err)
	}
	return tmp.Name(), nil
}

func VerifySHA256(path, want string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("update: open %s: %w", path, err)
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return fmt.Errorf("update: hash %s: %w", path, err)
	}
	got := hex.EncodeToString(h.Sum(nil))
	if got != want {
		return fmt.Errorf("update: sha256 mismatch: got %s, want %s", got, want)
	}
	return nil
}

// moveFile renames src to dst, falling back to a copy+remove when the rename
// fails across a filesystem boundary (EXDEV) — expected in practice, since
// Download() writes into os.TempDir() while the install target usually
// lives on a different mount (e.g. /usr/local/bin).
func moveFile(src, dst string) error {
	if err := os.Rename(src, dst); err == nil {
		return nil
	}

	info, err := os.Stat(src)
	if err != nil {
		return fmt.Errorf("moveFile: stat %s: %w", src, err)
	}
	in, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("moveFile: open %s: %w", src, err)
	}
	defer in.Close()

	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, info.Mode())
	if err != nil {
		return fmt.Errorf("moveFile: create %s: %w", dst, err)
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(dst)
		return fmt.Errorf("moveFile: copy %s -> %s: %w", src, dst, err)
	}
	if err := out.Close(); err != nil {
		return fmt.Errorf("moveFile: close %s: %w", dst, err)
	}
	return os.Remove(src)
}

// Swap backs up targetPath to targetPath+".previous" and moves newPath into
// targetPath. Returns the backup path for Rollback.
func Swap(newPath, targetPath string) (string, error) {
	backupPath := targetPath + ".previous"
	if err := os.Rename(targetPath, backupPath); err != nil {
		return "", fmt.Errorf("update: back up current binary: %w", err)
	}
	if err := moveFile(newPath, targetPath); err != nil {
		os.Rename(backupPath, targetPath) // best-effort restore
		return "", fmt.Errorf("update: install new binary: %w", err)
	}
	return backupPath, nil
}

func Rollback(targetPath string) error {
	backupPath := targetPath + ".previous"
	if err := os.Rename(backupPath, targetPath); err != nil {
		return fmt.Errorf("update: rollback: %w", err)
	}
	return nil
}

func WriteMarker(stateDir, targetVersion string) error {
	return os.WriteFile(filepath.Join(stateDir, markerFilename), []byte(targetVersion), 0o600)
}

func ReadMarker(stateDir string) (string, bool, error) {
	data, err := os.ReadFile(filepath.Join(stateDir, markerFilename))
	if os.IsNotExist(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("update: read marker: %w", err)
	}
	return string(data), true, nil
}

func ClearMarker(stateDir string) error {
	err := os.Remove(filepath.Join(stateDir, markerFilename))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("update: clear marker: %w", err)
	}
	return nil
}
