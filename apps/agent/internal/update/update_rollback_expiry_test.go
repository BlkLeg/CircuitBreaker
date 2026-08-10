// apps/agent/internal/update/update_rollback_expiry_test.go
package update

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// The defect these tests pin (F-8, diagnosed 2026-08-09):
//
// The rollback safety net used to live entirely in cmd/cb-agent's
// watchForRollback — an in-process `time.Sleep(rollbackWindow)`. That
// goroutine is only spawned *after* runDaemon's unconditional, fatal
// enroll.Run succeeds, so an update that leaves the agent unable to reach the
// server at all (a bad server URL, a broken TLS pin, a partitioned network, or
// simply a binary that dies before enrolling) exits with os.Exit(1) long
// before the window can elapse — and, because the marker carried no deadline,
// each restart began the window again from zero. The rollback could therefore
// never fire in precisely the cases it exists to cover; it worked only when
// the new binary could still enroll but could not complete a hello.ack.
//
// MarkSwapped now stamps a durable deadline into the marker, and
// RollbackIfExpired evaluates it from disk with no server contact at all, so a
// crash-looping agent converges on a rollback instead of looping forever.

// stagedUpdate builds the on-disk state a swapped-but-unconfirmed update
// leaves behind: a previous version directory, a `current` symlink already
// re-pointed at the new version, and a marker in phasePendingConfirm carrying
// deadline. It returns the state dir, the current-link path and the previous
// version directory the rollback must restore.
func stagedUpdate(t *testing.T, deadline time.Time) (dir, currentLink, oldVersionDir string) {
	t.Helper()
	dir = t.TempDir()
	oldVersionDir = filepath.Join(dir, "versions", "1.0.0")
	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink = CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(oldVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := WriteMarker(dir, "2.0.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	prevVersionDir, err := Swap(newBinary, "2.0.0", dir)
	if err != nil {
		t.Fatalf("Swap() error = %v", err)
	}
	if err := MarkSwapped(dir, "2.0.0", prevVersionDir, deadline); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}
	return dir, currentLink, oldVersionDir
}

func currentTarget(t *testing.T, currentLink string) string {
	t.Helper()
	target, err := os.Readlink(currentLink)
	if err != nil {
		t.Fatalf("Readlink(current) error = %v", err)
	}
	return target
}

// TestRollbackIfExpired_PastDeadlineRollsBackWithoutAnyServerContact is the
// core of the fix: the decision is made from the marker on disk alone, so it
// still happens on an agent that can never reach the server again.
func TestRollbackIfExpired_PastDeadlineRollsBackWithoutAnyServerContact(t *testing.T) {
	dir, currentLink, oldVersionDir := stagedUpdate(t, time.Now().Add(-time.Second))

	rolledBackFrom, err := RollbackIfExpired(dir, currentLink, time.Now())
	if err != nil {
		t.Fatalf("RollbackIfExpired() error = %v", err)
	}
	if rolledBackFrom != "2.0.0" {
		t.Errorf("RollbackIfExpired() = %q, want %q", rolledBackFrom, "2.0.0")
	}
	if got, want := currentTarget(t, currentLink), filepath.Join(oldVersionDir, "cb-agent"); got != want {
		t.Errorf("current symlink = %q, want %q — the previous binary must be restored", got, want)
	}
	// The next process, once it does reconnect, is the one that reports this.
	failed, ok, err := ReadRollbackReport(dir)
	if err != nil || !ok || failed != "2.0.0" {
		t.Errorf("ReadRollbackReport() = (%q, %v, %v), want (\"2.0.0\", true, nil)", failed, ok, err)
	}
	// Clearing the marker is what stops the next start from rolling back
	// again, forever, against a version that is no longer installed.
	if _, _, _, present, _ := ReadMarker(dir); present {
		t.Error("marker still present after a completed rollback, want it cleared")
	}
}

// TestRollbackIfExpired_BeforeDeadlineLeavesEverythingAlone pins the other
// half: a restart inside the window (a routine re-exec, a host reboot) must
// not cost a healthy update its confirmation.
func TestRollbackIfExpired_BeforeDeadlineLeavesEverythingAlone(t *testing.T) {
	dir, currentLink, _ := stagedUpdate(t, time.Now().Add(time.Hour))
	newTarget := currentTarget(t, currentLink)

	rolledBackFrom, err := RollbackIfExpired(dir, currentLink, time.Now())
	if err != nil {
		t.Fatalf("RollbackIfExpired() error = %v", err)
	}
	if rolledBackFrom != "" {
		t.Errorf("RollbackIfExpired() = %q, want \"\" — the window has not elapsed", rolledBackFrom)
	}
	if got := currentTarget(t, currentLink); got != newTarget {
		t.Errorf("current symlink = %q, want %q unchanged", got, newTarget)
	}
	if _, _, _, present, _ := ReadMarker(dir); !present {
		t.Error("marker cleared inside the window, want it left in place for the confirmation to clear")
	}
}

// TestRollbackIfExpired_UnswappedMarkerIsNotRolledBack mirrors
// watchForRollback's phasePendingSwap rule: if Swap never ran, `current` was
// never re-pointed and there is nothing to undo. Rolling back here would
// downgrade a healthy binary to whatever unrelated version an earlier marker
// happened to name.
func TestRollbackIfExpired_UnswappedMarkerIsNotRolledBack(t *testing.T) {
	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "1.0.0")
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
	if err := WriteMarker(dir, "2.0.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}

	rolledBackFrom, err := RollbackIfExpired(dir, currentLink, time.Now().Add(time.Hour))
	if err != nil {
		t.Fatalf("RollbackIfExpired() error = %v", err)
	}
	if rolledBackFrom != "" {
		t.Errorf("RollbackIfExpired() = %q, want \"\" — Swap never ran, there is nothing to roll back", rolledBackFrom)
	}
	if got, want := currentTarget(t, currentLink), filepath.Join(oldVersionDir, "cb-agent"); got != want {
		t.Errorf("current symlink = %q, want %q untouched", got, want)
	}
}

// TestRollbackIfExpired_MarkerWithoutADeadlineIsLeftToTheInProcessWatcher
// covers the upgrade path: a marker written by a previous agent build carries
// no deadline. Treating "no deadline" as "expired" would roll back a perfectly
// healthy in-flight update the first time a new binary started, so the absence
// is deliberately inert and watchForRollback remains that marker's only judge.
func TestRollbackIfExpired_MarkerWithoutADeadlineIsLeftToTheInProcessWatcher(t *testing.T) {
	dir, currentLink, _ := stagedUpdate(t, time.Time{})
	newTarget := currentTarget(t, currentLink)

	rolledBackFrom, err := RollbackIfExpired(dir, currentLink, time.Now().Add(24*time.Hour))
	if err != nil {
		t.Fatalf("RollbackIfExpired() error = %v", err)
	}
	if rolledBackFrom != "" {
		t.Errorf("RollbackIfExpired() = %q, want \"\" — a deadline-less marker predates this mechanism", rolledBackFrom)
	}
	if got := currentTarget(t, currentLink); got != newTarget {
		t.Errorf("current symlink = %q, want %q unchanged", got, newTarget)
	}
	if _, _, _, present, _ := ReadMarker(dir); !present {
		t.Error("deadline-less marker cleared, want it left for watchForRollback")
	}
}

// TestRollbackIfExpired_NoMarkerIsANoOp — the overwhelmingly common startup.
func TestRollbackIfExpired_NoMarkerIsANoOp(t *testing.T) {
	dir := t.TempDir()

	rolledBackFrom, err := RollbackIfExpired(dir, CurrentLinkPath(dir), time.Now())
	if err != nil {
		t.Fatalf("RollbackIfExpired() error = %v", err)
	}
	if rolledBackFrom != "" {
		t.Errorf("RollbackIfExpired() = %q, want \"\"", rolledBackFrom)
	}
}

// TestRollbackIfExpired_FailedRollbackStillClearsTheMarker mirrors
// watchForRollback's reasoning: an un-restorable previous version (recorded
// here as an empty prevVersionDir) must not re-arm the same doomed attempt on
// every subsequent start.
func TestRollbackIfExpired_FailedRollbackStillClearsTheMarker(t *testing.T) {
	dir := t.TempDir()
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(dir, "versions", "2.0.0", "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	if err := MarkSwapped(dir, "2.0.0", "", time.Now().Add(-time.Second)); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	rolledBackFrom, err := RollbackIfExpired(dir, currentLink, time.Now())
	if err == nil {
		t.Error("RollbackIfExpired() error = nil, want the rollback failure surfaced")
	}
	if rolledBackFrom != "" {
		t.Errorf("RollbackIfExpired() = %q, want \"\" — nothing was restored", rolledBackFrom)
	}
	if _, _, _, present, _ := ReadMarker(dir); present {
		t.Error("marker still present after a failed rollback, want it cleared to avoid a permanently stuck retry loop")
	}
}

// TestMarker_DeadlineSurvivesAReadWriteRoundTrip pins the wire format itself:
// the deadline is the whole point of the marker gaining a fourth field, and a
// round-trip that silently dropped it would make every test above pass against
// a mechanism that does nothing on a real restart.
func TestMarker_DeadlineSurvivesAReadWriteRoundTrip(t *testing.T) {
	dir := t.TempDir()
	deadline := time.Now().Add(2 * time.Minute).UTC().Truncate(time.Second)

	if err := MarkSwapped(dir, "3.1.4", "/var/lib/cb-agent/versions/3.1.3", deadline); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	m, present, err := readMarker(dir)
	if err != nil || !present {
		t.Fatalf("readMarker() = (_, %v, %v), want (_, true, nil)", present, err)
	}
	if !m.deadline.Equal(deadline) {
		t.Errorf("marker deadline = %v, want %v", m.deadline, deadline)
	}
	if m.version != "3.1.4" || m.prevVersionDir != "/var/lib/cb-agent/versions/3.1.3" {
		t.Errorf("marker = %+v, want the version and prevVersionDir preserved alongside the deadline", m)
	}
	// The 5-value ReadMarker is unchanged for every existing caller.
	version, prev, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || !swapped || version != "3.1.4" || prev != "/var/lib/cb-agent/versions/3.1.3" {
		t.Errorf("ReadMarker() = (%q, %q, %v, %v, %v), want the pre-existing contract intact", version, prev, swapped, present, err)
	}
}
