// apps/agent/internal/update/update_durability_test.go
package update

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

// TestSwap_NewVersionAlwaysInstalledAt0755 covers the "fixed 0755, no mode
// preservation" property that replaces the old preserveModeAndOwnership
// step (specs/2026-08-05-cb-agent-self-update-fix-design.md): every version
// directory and binary is created directly by cb-agent, as cb-agent, at a
// fixed mode — there is no "restore the original owner/mode" step because
// nothing is ever renamed over an existing root-owned file anymore.
func TestSwap_NewVersionAlwaysInstalledAt0755(t *testing.T) {
	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "0.1.0")
	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(oldVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	// Deliberately a narrower mode than 0755 — Swap must still land the
	// installed copy at 0755, not preserve this.
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o700); err != nil {
		t.Fatal(err)
	}

	if _, err := Swap(newBinary, "0.2.0", dir); err != nil {
		t.Fatalf("Swap() error = %v", err)
	}

	info, err := os.Stat(filepath.Join(dir, "versions", "0.2.0", "cb-agent"))
	if err != nil {
		t.Fatalf("stat new version binary: %v", err)
	}
	if got := info.Mode().Perm(); got != 0o755 {
		t.Errorf("new version binary mode = %04o, want 0755", got)
	}
}

// TestSwap_SyncFailureLeavesTargetUntouched covers "sync the downloaded file
// before replacement": Swap fsyncs newBinaryPath before it does anything at
// all to current or the versions directory, so a failure syncing the new
// binary must never leave a half-applied swap.
func TestSwap_SyncFailureLeavesTargetUntouched(t *testing.T) {
	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "0.1.0")
	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(oldVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	missingNewBinary := filepath.Join(dir, "does-not-exist")

	if _, err := Swap(missingNewBinary, "0.2.0", dir); err == nil {
		t.Fatal("Swap() error = nil, want an error when the new binary can't be opened/synced")
	}

	target, err := os.Readlink(currentLink)
	if err != nil || target != filepath.Join(oldVersionDir, "cb-agent") {
		t.Errorf("current symlink = (%q, %v), want unchanged %q", target, err, filepath.Join(oldVersionDir, "cb-agent"))
	}
	if _, err := os.Stat(filepath.Join(dir, "versions", "0.2.0")); !os.IsNotExist(err) {
		t.Error("new version dir created despite a failed sync, want none")
	}
}

// TestWriteMarker_LeavesNoStrayTempFiles covers WriteMarker's atomic-write
// implementation (temp file + fsync + rename): after a successful call, the
// state directory must contain exactly the marker file, never a leftover
// ".tmp-*" file from the write.
func TestWriteMarker_LeavesNoStrayTempFiles(t *testing.T) {
	dir := t.TempDir()
	if err := WriteMarker(dir, "0.5.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != markerFilename {
		names := make([]string, len(entries))
		for i, e := range entries {
			names[i] = e.Name()
		}
		t.Errorf("dir entries after WriteMarker() = %v, want exactly [%q]", names, markerFilename)
	}
}

// TestWriteMarker_OverwritesExistingMarkerAtomically covers the repeat-write
// case (an update instruction arriving while an unrelated stale marker
// exists, or a retried write): the rename-based atomic write must correctly
// replace an existing marker file's contents, not merely succeed the first
// time a file is created fresh.
func TestWriteMarker_OverwritesExistingMarkerAtomically(t *testing.T) {
	dir := t.TempDir()
	if err := WriteMarker(dir, "0.1.0"); err != nil {
		t.Fatalf("WriteMarker(0.1.0) error = %v", err)
	}
	if err := WriteMarker(dir, "0.2.0"); err != nil {
		t.Fatalf("WriteMarker(0.2.0) error = %v", err)
	}

	version, _, _, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.2.0" {
		t.Fatalf("ReadMarker() = (%q, _, _, %v, %v), want (\"0.2.0\", _, _, true, nil)", version, present, err)
	}
}

func TestMarkerWrittenBeforeSwap_SurvivesSimulatedCrashBeforeReplacement(t *testing.T) {
	dir := t.TempDir()
	versionDir := filepath.Join(dir, "versions", "0.1.0")
	if err := os.MkdirAll(versionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(versionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(versionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}

	if err := WriteMarker(dir, "0.3.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	// Simulated crash: Swap is deliberately never called.

	version, prevVersionDir, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.3.0" {
		t.Fatalf("ReadMarker() after simulated crash = (%q, _, _, %v, %v), want (\"0.3.0\", _, _, true, nil) — recoverable state", version, present, err)
	}
	if swapped {
		t.Error("ReadMarker() reports swapped = true, want false — Swap was never called, there is nothing to roll back to")
	}
	if prevVersionDir != "" {
		t.Errorf("ReadMarker() prevVersionDir = %q, want empty — Swap never ran, nothing was recorded", prevVersionDir)
	}

	target, err := os.Readlink(currentLink)
	if err != nil || target != filepath.Join(versionDir, "cb-agent") {
		t.Errorf("current symlink after simulated crash = (%q, %v), want unchanged %q", target, err, filepath.Join(versionDir, "cb-agent"))
	}
}

func TestUpdateThenCrashBeforeRestart_MarkerAndBackupRecoverable(t *testing.T) {
	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "0.3.0")
	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(oldVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := WriteMarker(dir, "0.4.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	prevVersionDir, err := Swap(newBinary, "0.4.0", dir)
	if err != nil {
		t.Fatalf("Swap() error = %v", err)
	}
	if err := MarkSwapped(dir, "0.4.0", prevVersionDir, time.Now().Add(2*time.Minute)); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}
	// Simulated crash: no re-exec, no hello.ack, nothing else runs.

	version, gotPrev, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.4.0" || !swapped || gotPrev != oldVersionDir {
		t.Fatalf("ReadMarker() after simulated crash = (%q, %q, %v, %v, %v), want (\"0.4.0\", %q, true, true, nil)", version, gotPrev, swapped, present, err, oldVersionDir)
	}
	newVersionDir := filepath.Join(dir, "versions", "0.4.0")
	target, err := os.Readlink(currentLink)
	if err != nil || target != filepath.Join(newVersionDir, "cb-agent") {
		t.Errorf("current symlink = (%q, %v), want %q — the swap itself completed durably", target, err, filepath.Join(newVersionDir, "cb-agent"))
	}

	// A fresh process's rollback timer can act on this recovered state
	// either way: Rollback if hello.ack never confirms in time.
	if err := Rollback(currentLink, gotPrev); err != nil {
		t.Fatalf("Rollback() error = %v", err)
	}
	target, err = os.Readlink(currentLink)
	if err != nil || target != filepath.Join(oldVersionDir, "cb-agent") {
		t.Errorf("current symlink after recovered rollback = (%q, %v), want %q", target, err, filepath.Join(oldVersionDir, "cb-agent"))
	}
}

// TestMoveFile_CrossDeviceCopyFallbackSyncsDestination exercises moveFile's
// copy+remove fallback — taken when os.Rename fails with EXDEV, which
// moveFile's own doc comment documents as the ordinary production case,
// since Download() writes into os.TempDir() while the install target
// usually lives on a different mount (e.g. /usr/local/bin). Every other
// test in this package moves files within a single t.TempDir(), which stays
// on one filesystem and so only ever exercises the rename fast path; this
// test forces the fallback by using two directories that are genuinely on
// different filesystems (skipping itself if the environment doesn't offer
// two, e.g. no writable /dev/shm, or if they happen to share a device).
//
// It can't directly observe that Sync() itself ran — that's an OS/hardware
// durability property, not one visible to a test process without actually
// crash-testing hardware — but it does force the code path containing that
// call to run to completion and checks it produces a byte-correct,
// correctly-moded destination file with the source removed: a regression
// that broke the fallback's error handling (e.g. Close running before Sync,
// or an early return skipping the source removal) would show up here as
// either an error or corrupted/incomplete output.
func TestMoveFile_CrossDeviceCopyFallbackSyncsDestination(t *testing.T) {
	const srcRoot, dstRoot = "/dev/shm", "/tmp"
	var srcStat, dstStat syscall.Stat_t
	if err := syscall.Stat(srcRoot, &srcStat); err != nil {
		t.Skipf("%s not available in this environment: %v", srcRoot, err)
	}
	if err := syscall.Stat(dstRoot, &dstStat); err != nil {
		t.Skipf("%s not available in this environment: %v", dstRoot, err)
	}
	if srcStat.Dev == dstStat.Dev {
		t.Skipf("%s and %s are on the same filesystem here (dev %d) — can't force moveFile's EXDEV fallback", srcRoot, dstRoot, srcStat.Dev)
	}

	srcDir, err := os.MkdirTemp(srcRoot, "cb-agent-update-test-*")
	if err != nil {
		t.Skipf("MkdirTemp(%s): %v", srcRoot, err)
	}
	defer os.RemoveAll(srcDir)
	dstDir, err := os.MkdirTemp(dstRoot, "cb-agent-update-test-*")
	if err != nil {
		t.Skipf("MkdirTemp(%s): %v", dstRoot, err)
	}
	defer os.RemoveAll(dstDir)

	src := filepath.Join(srcDir, "src-binary")
	content := []byte("cross-device binary contents")
	if err := os.WriteFile(src, content, 0o755); err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dstDir, "dst-binary")

	if err := moveFile(src, dst); err != nil {
		t.Fatalf("moveFile() across %s -> %s error = %v, want nil (EXDEV must fall back to copy+sync)", srcRoot, dstRoot, err)
	}

	if _, err := os.Stat(src); !os.IsNotExist(err) {
		t.Errorf("source %s still exists after moveFile(), want removed", src)
	}
	got, err := os.ReadFile(dst)
	if err != nil || string(got) != string(content) {
		t.Errorf("destination contents = (%q, %v), want (%q, nil)", got, err, content)
	}
	info, err := os.Stat(dst)
	if err != nil {
		t.Fatal(err)
	}
	if gotMode := info.Mode().Perm(); gotMode != 0o755 {
		t.Errorf("destination mode = %04o, want 0755 (source's mode preserved)", gotMode)
	}
}

// TestPruneVersions_KeepsCurrentAndNamedVersionRemovesRest covers the
// retention rule Section 5 of specs/2026-08-05-cb-agent-self-update-fix-
// design.md specifies: after an update confirms, only current's target and
// the version just confirmed-away-from survive.
func TestPruneVersions_KeepsCurrentAndNamedVersionRemovesRest(t *testing.T) {
	dir := t.TempDir()
	for _, v := range []string{"0.1.0", "0.2.0", "0.3.0"} {
		if err := os.MkdirAll(filepath.Join(dir, "versions", v), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	currentDir := filepath.Join(dir, "versions", "0.3.0")
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(currentDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	keepDir := filepath.Join(dir, "versions", "0.2.0")

	if err := PruneVersions(dir, currentLink, keepDir); err != nil {
		t.Fatalf("PruneVersions() error = %v", err)
	}

	for _, want := range []string{currentDir, keepDir} {
		if _, err := os.Stat(want); err != nil {
			t.Errorf("stat %s after PruneVersions() = %v, want it retained", want, err)
		}
	}
	pruned := filepath.Join(dir, "versions", "0.1.0")
	if _, err := os.Stat(pruned); !os.IsNotExist(err) {
		t.Errorf("stat %s after PruneVersions() = %v, want removed", pruned, err)
	}
}

// TestPruneVersions_EmptyKeepStillRetainsCurrent covers the first-ever-
// update case: keepVersionDir is "" (no marker was present — see
// cmd/cb-agent/main.go's onConnected), but current's own target must never
// be pruned.
func TestPruneVersions_EmptyKeepStillRetainsCurrent(t *testing.T) {
	dir := t.TempDir()
	currentDir := filepath.Join(dir, "versions", "0.1.0")
	if err := os.MkdirAll(currentDir, 0o755); err != nil {
		t.Fatal(err)
	}
	staleDir := filepath.Join(dir, "versions", "0.0.9")
	if err := os.MkdirAll(staleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(currentDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}

	if err := PruneVersions(dir, currentLink, ""); err != nil {
		t.Fatalf("PruneVersions() error = %v", err)
	}

	if _, err := os.Stat(currentDir); err != nil {
		t.Errorf("stat current dir after PruneVersions() = %v, want retained", err)
	}
	if _, err := os.Stat(staleDir); !os.IsNotExist(err) {
		t.Errorf("stat stale dir after PruneVersions() = %v, want removed", err)
	}
}

// TestPruneVersions_MissingCurrentSymlinkPrunesNothing covers the
// final-review finding that a missing/unreadable current would otherwise
// resolve to an empty liveDir, which would then match no versions/<v> entry
// as "live" — deleting the entire versions/ tree, including whatever
// version this process might currently be running through. PruneVersions
// must refuse to prune at all rather than risk that.
func TestPruneVersions_MissingCurrentSymlinkPrunesNothing(t *testing.T) {
	dir := t.TempDir()
	someVersionDir := filepath.Join(dir, "versions", "0.1.0")
	if err := os.MkdirAll(someVersionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir) // deliberately never created

	if err := PruneVersions(dir, currentLink, ""); err != nil {
		t.Fatalf("PruneVersions() with no current symlink error = %v, want nil (no-op, not an error)", err)
	}

	if _, err := os.Stat(someVersionDir); err != nil {
		t.Errorf("stat %s after PruneVersions() = %v, want retained — pruning must refuse to run without a resolvable current", someVersionDir, err)
	}
}
