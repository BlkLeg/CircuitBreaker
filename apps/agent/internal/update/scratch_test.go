// apps/agent/internal/update/scratch_test.go
package update

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

// isolateScratch points every environment variable scratchDir reads at this
// test's own directories, so a candidate is chosen because the test arranged
// it and not because the machine running the suite happens to have a roomy
// /tmp. TMPDIR is what os.TempDir() reads.
func isolateScratch(t *testing.T) (state string, temp string) {
	t.Helper()
	state, temp = t.TempDir(), t.TempDir()
	t.Setenv("CB_AGENT_DOWNLOAD_DIR", "")
	t.Setenv("CB_AGENT_STATE_DIR", state)
	t.Setenv("TMPDIR", temp)
	return state, temp
}

// The agent's own state directory is the first choice on purpose. It is the
// same filesystem as the install target (/var/lib/cb-agent/versions/...), so
// Swap becomes a rename rather than the cross-mount copy moveFile falls back
// to, and it is real disk rather than the RAM-backed tmpfs systemd's
// PrivateTmp= hands this unit.
func TestScratchDirPrefersTheAgentsOwnStateDir(t *testing.T) {
	state, _ := isolateScratch(t)

	dir, err := scratchDir(1024)
	if err != nil {
		t.Fatalf("scratchDir() error = %v, want nil", err)
	}

	want := filepath.Join(state, scratchDirName)
	if dir != want {
		t.Errorf("scratchDir() = %q, want %q", dir, want)
	}
	if info, statErr := os.Stat(dir); statErr != nil || !info.IsDir() {
		t.Errorf("scratchDir() did not create %q: %v", dir, statErr)
	}
}

// An operator whose /var/lib is the full filesystem needs a way out that does
// not involve editing the agent.
func TestScratchDirHonoursTheOperatorsOverride(t *testing.T) {
	isolateScratch(t)
	override := t.TempDir()
	t.Setenv("CB_AGENT_DOWNLOAD_DIR", override)

	dir, err := scratchDir(1024)
	if err != nil {
		t.Fatalf("scratchDir() error = %v, want nil", err)
	}
	if dir != override {
		t.Errorf("scratchDir() = %q, want the override %q", dir, override)
	}
}

// A regular file rather than a mode-0000 directory: root ignores permission
// bits, and this fallback must be exercised for every uid the agent might run
// as rather than skipping under one of them (REL-19).
func TestScratchDirFallsBackWhenTheStateDirIsUnusable(t *testing.T) {
	_, temp := isolateScratch(t)
	blocked := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(blocked, []byte("x"), 0o644); err != nil {
		t.Fatalf("write blocking file: %v", err)
	}
	t.Setenv("CB_AGENT_STATE_DIR", blocked)

	dir, err := scratchDir(1024)
	if err != nil {
		t.Fatalf("scratchDir() error = %v, want the fallback to succeed", err)
	}
	if dir != temp {
		t.Errorf("scratchDir() = %q, want the TMPDIR fallback %q", dir, temp)
	}
}

// The failure an operator actually has to act on. Naming every candidate and
// what each had free is the difference between "no space left on device" from
// somewhere inside curl and a message that says where to free it.
func TestScratchDirNamesEveryCandidateWhenNoneHasRoom(t *testing.T) {
	state, temp := isolateScratch(t)

	_, err := scratchDir(1 << 62)
	if err == nil {
		t.Fatal("scratchDir() with an impossible requirement = nil error, want a refusal")
	}
	for _, want := range []string{state, temp, "/var/tmp"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("scratchDir() error = %q, does not name candidate %q", err, want)
		}
	}
}

// Staging in a persistent directory means nothing else ever cleans it: a crash
// between download and swap used to leave its debris in /tmp, where the OS
// eventually swept it. Here the agent has to sweep its own.
func TestStaleStagedDownloadsAreSweptAway(t *testing.T) {
	state, _ := isolateScratch(t)
	staging := filepath.Join(state, scratchDirName)
	if err := os.MkdirAll(staging, 0o700); err != nil {
		t.Fatalf("create staging dir: %v", err)
	}

	stale := filepath.Join(staging, "cb-agent-update-abandoned")
	fresh := filepath.Join(staging, "cb-agent-update-inflight")
	unrelated := filepath.Join(staging, "operator-put-this-here")
	for _, path := range []string{stale, fresh, unrelated} {
		if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
			t.Fatalf("seed %s: %v", path, err)
		}
	}
	old := time.Now().Add(-2 * staleScratchAge)
	if err := os.Chtimes(stale, old, old); err != nil {
		t.Fatalf("age the stale file: %v", err)
	}
	if err := os.Chtimes(unrelated, old, old); err != nil {
		t.Fatalf("age the unrelated file: %v", err)
	}

	if _, err := scratchDir(1024); err != nil {
		t.Fatalf("scratchDir() error = %v, want nil", err)
	}

	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Errorf("stale download %s survived the sweep (stat err = %v)", stale, err)
	}
	if _, err := os.Stat(fresh); err != nil {
		t.Errorf("in-flight download %s was swept: %v", fresh, err)
	}
	if _, err := os.Stat(unrelated); err != nil {
		t.Errorf("sweep deleted a file it does not own: %s (%v)", unrelated, err)
	}
}

// The end-to-end property the whole change exists for: a downloaded binary
// does not land in /tmp when the agent has a directory of its own.
func TestDownloadStagesInTheAgentsOwnDirectory(t *testing.T) {
	state, temp := isolateScratch(t)

	content := []byte("fake binary contents")
	sum := sha256.Sum256(content)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write(content)
	}))
	defer srv.Close()

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{
		Version: "0.2.0", SHA256: hex.EncodeToString(sum[:]), Arch: "amd64", OS: "linux",
	}

	path, err := Download(cfg, tlsdial.Trust{Mode: tlsdial.ModePublic}, instr)
	if err != nil {
		t.Fatalf("Download() error = %v", err)
	}
	defer os.Remove(path)

	want := filepath.Join(state, scratchDirName)
	if filepath.Dir(path) != want {
		t.Errorf("Download() staged in %q, want %q", filepath.Dir(path), want)
	}
	if strings.HasPrefix(path, temp) {
		t.Errorf("Download() staged in the temp directory %q despite a usable state dir", temp)
	}
}
