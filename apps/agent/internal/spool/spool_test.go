package spool

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func testFrame(seq uint64) frame.Frame {
	return frame.Frame{V: 1, Type: "telemetry.host", Seq: seq, TS: time.Now().UTC(), Payload: json.RawMessage(`{}`)}
}

// fatFrame is a ~size-byte frame, used by the sub-quadratic enqueue test to
// make a whole-file rewrite per enqueue expensive enough to be measurable.
func fatFrame(seq uint64, size int) frame.Frame {
	f := testFrame(seq)
	f.Payload = json.RawMessage(`{"blob":"` + strings.Repeat("x", size) + `"}`)
	return f
}

func seqs(frames []frame.Frame) []uint64 {
	got := make([]uint64, 0, len(frames))
	for _, f := range frames {
		got = append(got, f.Seq)
	}
	return got
}

func wantSeqs(t *testing.T, frames []frame.Frame, want ...uint64) {
	t.Helper()
	got := seqs(frames)
	if len(got) != len(want) {
		t.Fatalf("frames = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("frames = %v, want %v (FIFO order)", got, want)
		}
	}
}

func lineCount(t *testing.T, path string) int {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	if len(data) == 0 {
		return 0
	}
	return bytes.Count(data, []byte("\n"))
}

func TestEnqueuePeekCommit_FIFO(t *testing.T) {
	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	for i := uint64(0); i < 3; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if got := s.Len(); got != 3 {
		t.Errorf("Len() = %d, want 3", got)
	}

	wantSeqs(t, s.Peek(10, DefaultCapBytes), 0, 1, 2)
	if err := s.Commit(3); err != nil {
		t.Fatalf("Commit(3) error = %v", err)
	}
	if got := s.Len(); got != 0 {
		t.Errorf("Len() after Commit(3) = %d, want 0", got)
	}
	if got := s.Peek(10, DefaultCapBytes); len(got) != 0 {
		t.Errorf("Peek() on an empty spool = %v, want no frames", seqs(got))
	}
	if err := s.Commit(1); err != nil {
		t.Errorf("Commit() past the end error = %v, want nil (clamped)", err)
	}
}

func TestEnqueue_DropsOldestWhenOverCap(t *testing.T) {
	// A tiny cap that fits only a couple of frames, to exercise eviction
	// without a 64MB fixture.
	const tinyCap = 300
	s, err := Open(t.TempDir(), tinyCap)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	for i := uint64(0); i < 10; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	size, err := s.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if size > tinyCap {
		t.Errorf("SizeBytes() = %d, want <= %d after eviction", size, tinyCap)
	}

	got := s.Peek(1, DefaultCapBytes)
	if len(got) != 1 {
		t.Fatalf("Peek(1) = %v, want a frame present", seqs(got))
	}
	if got[0].Seq == 0 {
		t.Error("Peek() returned seq=0 — oldest frame should have been evicted, not the newest")
	}
	// Eviction compacts, so the file must not still carry the dropped frames.
	if lines, want := lineCount(t, filepath.Join(filepath.Dir(s.path), queueFilename)), s.Len(); lines != want {
		t.Errorf("queue.jsonl lines = %d, want %d — eviction must rewrite the file", lines, want)
	}
}

func TestOpen_RecoversExistingQueueAfterReopen(t *testing.T) {
	dir := t.TempDir()
	first, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if err := first.Enqueue(testFrame(1)); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}

	second, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	defer second.Close()
	if got := second.Len(); got != 1 {
		t.Errorf("Len() after reopen = %d, want 1 (unclean-shutdown recovery)", got)
	}
}

// TestSpool_PeekDoesNotConsumeUntilCommit pins the two-phase contract: a
// frame is only discarded once the caller has actually sent it, so a crash
// mid-burst re-sends rather than loses (delivery is at-least-once and the
// backend dedupes on (agent_id, sample_id, collected_at)).
func TestSpool_PeekDoesNotConsumeUntilCommit(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	for i := uint64(1); i <= 3; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	wantSeqs(t, s.Peek(3, DefaultCapBytes), 1, 2, 3)

	crashed, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() after Peek error = %v", err)
	}
	if got := crashed.Len(); got != 3 {
		t.Errorf("Len() after reopen following an uncommitted Peek = %d, want 3", got)
	}
	crashed.Close()

	if err := s.Commit(2); err != nil {
		t.Fatalf("Commit(2) error = %v", err)
	}
	after, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() after Commit error = %v", err)
	}
	defer after.Close()
	if got := after.Len(); got != 1 {
		t.Fatalf("Len() after reopen following Commit(2) = %d, want 1", got)
	}
	wantSeqs(t, after.Peek(3, DefaultCapBytes), 3)
}

// TestSpool_CommitPreservesFIFOAfterPartialFailure is the direct regression
// for the old tail-requeue bug: a burst that fails partway through committed
// only its successes, and the uncommitted remainder stays at the *head* in
// its original order rather than being re-appended to the tail (where cap
// eviction would drop its neighbours first).
func TestSpool_CommitPreservesFIFOAfterPartialFailure(t *testing.T) {
	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()
	for i := uint64(1); i <= 5; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	wantSeqs(t, s.Peek(5, DefaultCapBytes), 1, 2, 3, 4, 5)
	if err := s.Commit(2); err != nil {
		t.Fatalf("Commit(2) error = %v", err)
	}
	wantSeqs(t, s.Peek(3, DefaultCapBytes), 3, 4, 5)
}

// TestSpool_PeekHonoursByteBudgetAndAlwaysMakesProgress covers the byte half
// of the budget, plus the anti-stall rule: a single frame larger than
// maxBytes is still returned, otherwise a fat frame at the head would wedge
// the queue forever.
func TestSpool_PeekHonoursByteBudgetAndAlwaysMakesProgress(t *testing.T) {
	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()
	for i := uint64(1); i <= 4; i++ {
		if err := s.Enqueue(fatFrame(i, 1000)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	got := s.Peek(4, 2500)
	if len(got) != 2 {
		t.Fatalf("Peek(4, 2500) returned %d frames (%v), want 2 (~1KiB each)", len(got), seqs(got))
	}
	wantSeqs(t, got, 1, 2)

	wantSeqs(t, s.Peek(4, 1), 1)
	if got := s.Peek(0, DefaultCapBytes); len(got) != 0 {
		t.Errorf("Peek(0, …) = %v, want no frames", seqs(got))
	}
}

// TestSpool_EnqueueIsSubQuadratic pins the append-only write path. Under the
// old whole-file rewrite, 2000 x ~4KiB enqueues rewrote ~8GB; appending one
// line each writes ~8MB.
func TestSpool_EnqueueIsSubQuadratic(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	const frames = 2000
	start := time.Now()
	for i := uint64(0); i < frames; i++ {
		if err := s.Enqueue(fatFrame(i, 4096)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	elapsed := time.Since(start)

	if got := s.Len(); got != frames {
		t.Fatalf("Len() = %d, want %d", got, frames)
	}
	if got := lineCount(t, filepath.Join(dir, queueFilename)); got != frames {
		t.Errorf("queue.jsonl lines = %d, want %d (one appended line per enqueue)", got, frames)
	}
	// Generous: the quadratic path writes three orders of magnitude more.
	if budget := 30 * time.Second; elapsed > budget {
		t.Errorf("%d enqueues took %s, want < %s — enqueue must not rewrite the whole file", frames, elapsed, budget)
	}
}

// TestSpool_SizeBytesIsIncrementalAndMatchesFile pins the running byte
// counter against the file it describes, so the status file's spool_bytes
// cannot drift from reality.
func TestSpool_SizeBytesIsIncrementalAndMatchesFile(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	queuePath := filepath.Join(dir, queueFilename)
	for i := uint64(1); i <= 50; i++ {
		if err := s.Enqueue(fatFrame(i, 200)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
		size, err := s.SizeBytes()
		if err != nil {
			t.Fatalf("SizeBytes() error = %v", err)
		}
		st, err := os.Stat(queuePath)
		if err != nil {
			t.Fatalf("stat %s: %v", queuePath, err)
		}
		if size != st.Size() {
			t.Fatalf("SizeBytes() = %d after %d enqueues, want %d (queue.jsonl size)", size, i, st.Size())
		}
	}

	if err := s.Commit(50); err != nil {
		t.Fatalf("Commit(50) error = %v", err)
	}
	size, err := s.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if size != 0 {
		t.Errorf("SizeBytes() after committing everything = %d, want 0", size)
	}
}

// TestSpool_CompactsAfterHeadThreshold verifies a long catch-up burst does
// not leave the consumed prefix on disk forever.
func TestSpool_CompactsAfterHeadThreshold(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	const frames = 600 // > compactHeadThreshold
	for i := uint64(0); i < frames; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if err := s.Commit(frames); err != nil {
		t.Fatalf("Commit(%d) error = %v", frames, err)
	}

	st, err := os.Stat(filepath.Join(dir, queueFilename))
	if err != nil {
		t.Fatalf("stat queue.jsonl: %v", err)
	}
	if st.Size() != 0 {
		t.Errorf("queue.jsonl size = %d after committing %d frames, want 0 (compaction)", st.Size(), frames)
	}
	if _, err := os.Stat(filepath.Join(dir, headFilename)); !os.IsNotExist(err) {
		t.Errorf("stat queue.head = %v, want the marker removed by compaction", err)
	}
	if got := s.Len(); got != 0 {
		t.Errorf("Len() = %d, want 0", got)
	}
}

// TestSpool_LoadHonoursHeadMarker covers restart across an uncompacted
// commit, and the deliberately forgiving handling of a missing or garbage
// marker (head=0 — re-send everything, which is safe because delivery is
// idempotent).
func TestSpool_LoadHonoursHeadMarker(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	for i := uint64(1); i <= 5; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if err := s.Commit(2); err != nil { // below the compaction thresholds
		t.Fatalf("Commit(2) error = %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, headFilename)); err != nil {
		t.Fatalf("stat queue.head after an uncompacted Commit: %v, want the marker written", err)
	}
	s.Close()

	reopened, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	if got := reopened.Len(); got != 3 {
		t.Fatalf("Len() after reopen = %d, want 3 (consumed prefix dropped)", got)
	}
	wantSeqs(t, reopened.Peek(5, DefaultCapBytes), 3, 4, 5)
	if got := lineCount(t, filepath.Join(dir, queueFilename)); got != 3 {
		t.Errorf("queue.jsonl lines after reopen = %d, want 3 (load compacts immediately)", got)
	}
	if _, err := os.Stat(filepath.Join(dir, headFilename)); !os.IsNotExist(err) {
		t.Errorf("stat queue.head after reopen = %v, want the marker removed", err)
	}
	reopened.Close()

	if err := os.WriteFile(filepath.Join(dir, headFilename), []byte("not-a-number"), 0o600); err != nil {
		t.Fatalf("write garbage marker: %v", err)
	}
	garbage, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() with a garbage marker error = %v", err)
	}
	defer garbage.Close()
	if got := garbage.Len(); got != 3 {
		t.Errorf("Len() with a garbage marker = %d, want 3 (head=0 — re-send everything)", got)
	}
}

// TestSpool_HealsTornFinalLineOnLoad pins the package doc's recovery promise
// against the append-only write path: an unclean shutdown can leave a
// half-written final line, and because Enqueue appends with O_APPEND the very
// next frame would otherwise be concatenated onto that torn line and lost
// forever. load() must rewrite the file whenever it skipped an undecodable
// line, not only when there is a consumed prefix to drop.
func TestSpool_HealsTornFinalLineOnLoad(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	for i := uint64(1); i <= 3; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if err := s.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}

	// Simulate a crash partway through appending the third line.
	queuePath := filepath.Join(dir, queueFilename)
	st, err := os.Stat(queuePath)
	if err != nil {
		t.Fatalf("stat %s: %v", queuePath, err)
	}
	if err := os.Truncate(queuePath, st.Size()-20); err != nil {
		t.Fatalf("truncate %s: %v", queuePath, err)
	}

	recovered, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() after a torn write error = %v", err)
	}
	if got := recovered.Len(); got != 2 {
		t.Fatalf("Len() after recovery = %d, want 2 (torn final line dropped)", got)
	}
	if got := lineCount(t, queuePath); got != 2 {
		t.Errorf("queue.jsonl lines after recovery = %d, want 2 — load must rewrite away the torn line", got)
	}
	// The torn bytes must be gone from the file, not merely skipped in
	// memory: the running byte counter describes what is on disk.
	size, err := recovered.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if st, err := os.Stat(queuePath); err != nil {
		t.Fatalf("stat %s: %v", queuePath, err)
	} else if st.Size() != size {
		t.Errorf("queue.jsonl size = %d after recovery, want %d (SizeBytes) — the torn tail must be rewritten away", st.Size(), size)
	}
	if err := recovered.Enqueue(testFrame(99)); err != nil {
		t.Fatalf("Enqueue() after recovery error = %v", err)
	}
	wantSeqs(t, recovered.Peek(10, DefaultCapBytes), 1, 2, 99)
	if err := recovered.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}

	reopened, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	defer reopened.Close()
	// The frame enqueued after recovery must survive a restart: fused onto
	// the torn line it decodes as nothing at all.
	wantSeqs(t, reopened.Peek(10, DefaultCapBytes), 1, 2, 99)
}
