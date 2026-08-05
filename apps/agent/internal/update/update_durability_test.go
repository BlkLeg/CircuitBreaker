// apps/agent/internal/update/update_durability_test.go
package update

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

// TestSwap_PreservesTargetModeAcrossSwap covers the "preserve executable
// ownership/mode across the swap" requirement: Download always chmods its
// temp file to a fixed 0o755, so without Swap explicitly carrying the
// *target's* own mode forward, a deployment that deliberately hardened the
// installed binary's permissions (e.g. group-execute only) would have that
// silently widened back to 0o755 on every self-update.
func TestSwap_PreservesTargetModeAcrossSwap(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("old binary"), 0o750); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	if _, err := Swap(newBinary, target); err != nil {
		t.Fatalf("Swap() error = %v", err)
	}

	info, err := os.Stat(target)
	if err != nil {
		t.Fatalf("stat %s: %v", target, err)
	}
	if got := info.Mode().Perm(); got != 0o750 {
		t.Errorf("target mode after swap = %04o, want preserved 0750 (the target's original mode, not the downloaded temp file's 0755)", got)
	}
}

// TestSwap_SyncFailureLeavesTargetUntouched covers "sync the downloaded file
// before replacement": Swap fsyncs newPath before it does anything at all to
// targetPath, so a failure syncing the new binary must never leave a
// half-applied swap (a renamed-away backup with no replacement, or any
// mutation of targetPath). Using a newPath that doesn't exist makes the
// fsync step fail deterministically and cheaply, without needing to
// fabricate a real disk I/O error.
func TestSwap_SyncFailureLeavesTargetUntouched(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	missingNewBinary := filepath.Join(dir, "does-not-exist")

	if _, err := Swap(missingNewBinary, target); err == nil {
		t.Fatal("Swap() error = nil, want an error when the new binary can't be opened/synced")
	}

	got, err := os.ReadFile(target)
	if err != nil || string(got) != "old binary" {
		t.Errorf("target contents = (%q, %v), want unchanged %q — a failed sync must happen before any rename touches the target", got, err, "old binary")
	}
	if _, err := os.Stat(target + ".previous"); !os.IsNotExist(err) {
		t.Error("backup file created despite a failed sync, want none")
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

	version, _, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.2.0" {
		t.Fatalf("ReadMarker() = (%q, _, %v, %v), want (\"0.2.0\", _, true, nil)", version, present, err)
	}
}

// TestMarkerWrittenBeforeSwap_SurvivesSimulatedCrashBeforeReplacement
// simulates the exact crash window Task 25 closes: a marker is durably
// written, and then the process "crashes" before the binary swap that
// marker guards ever runs (main.go's onUpdate now performs these two steps
// in that order — see WriteMarker's doc comment). On "restart" (a fresh
// ReadMarker call, exactly what runDaemon does at startup), the marker must
// still be present and correct — a recoverable state — even though no swap
// ever happened and so there is nothing to roll back.
func TestMarkerWrittenBeforeSwap_SurvivesSimulatedCrashBeforeReplacement(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := WriteMarker(dir, "0.3.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	// Simulated crash: Swap is deliberately never called.

	version, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.3.0" {
		t.Fatalf("ReadMarker() after simulated crash = (%q, _, %v, %v), want (\"0.3.0\", _, true, nil) — recoverable state", version, present, err)
	}
	if swapped {
		t.Error("ReadMarker() reports swapped = true, want false — Swap was never called, there is nothing to roll back to")
	}

	got, err := os.ReadFile(target)
	if err != nil || string(got) != "old binary" {
		t.Errorf("target contents after simulated crash = (%q, %v), want unchanged %q", got, err, "old binary")
	}
	if _, err := os.Stat(target + ".previous"); !os.IsNotExist(err) {
		t.Error("backup file exists after a crash before Swap ran, want none")
	}
}

// TestUpdateThenCrashBeforeRestart_MarkerAndBackupRecoverable mirrors
// main.go's onUpdate ordering end to end (WriteMarker, then Swap, then
// MarkSwapped), then simulates a crash immediately after — before re-exec,
// before any hello.ack. It asserts the on-disk state a fresh restart would
// find is fully recoverable: the marker names the installed version and
// reports the swap as completed, the backup exists for Rollback, and the
// swap itself durably completed. It then exercises both outcomes a real
// restart's rollback timer could reach from that recovered state.
func TestUpdateThenCrashBeforeRestart_MarkerAndBackupRecoverable(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := WriteMarker(dir, "0.4.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	backupPath, err := Swap(newBinary, target)
	if err != nil {
		t.Fatalf("Swap() error = %v", err)
	}
	if err := MarkSwapped(dir, "0.4.0"); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}
	// Simulated crash: no re-exec, no hello.ack, nothing else runs.

	version, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.4.0" || !swapped {
		t.Fatalf("ReadMarker() after simulated crash = (%q, %v, %v, %v), want (\"0.4.0\", true, true, nil)", version, swapped, present, err)
	}
	if _, err := os.Stat(backupPath); err != nil {
		t.Errorf("backup %s missing after simulated crash, want it retained until confirmation", backupPath)
	}
	got, err := os.ReadFile(target)
	if err != nil || string(got) != "new binary" {
		t.Errorf("target contents = (%q, %v), want %q — the swap itself completed durably", got, err, "new binary")
	}

	// A fresh process's rollback timer can act on this recovered state
	// either way: Rollback(target) if hello.ack never confirms in time.
	if err := Rollback(target); err != nil {
		t.Fatalf("Rollback() error = %v", err)
	}
	got, err = os.ReadFile(target)
	if err != nil || string(got) != "old binary" {
		t.Errorf("target contents after recovered rollback = (%q, %v), want %q", got, err, "old binary")
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
