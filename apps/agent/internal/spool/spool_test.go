package spool

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/logging"
)

// TestMain silences the eviction warnings the other tests in this package
// legitimately produce. They are WARNING lines by design, so without this
// every eviction test writes several to the suite's stderr and buries a real
// failure. TestEnqueue_EvictionIsAudibleAtWarnLogLevel overrides this for its
// own duration, which is what keeps the silencing from hiding the very
// behaviour the package is meant to guarantee.
func TestMain(m *testing.M) {
	restore := logging.UseWriter(io.Discard, logging.LevelWarn)
	code := m.Run()
	restore()
	os.Exit(code)
}

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
	if err := s.commit(3); err != nil {
		t.Fatalf("Commit(3) error = %v", err)
	}
	if got := s.Len(); got != 0 {
		t.Errorf("Len() after Commit(3) = %d, want 0", got)
	}
	if got := s.Peek(10, DefaultCapBytes); len(got) != 0 {
		t.Errorf("Peek() on an empty spool = %v, want no frames", seqs(got))
	}
	if err := s.commit(1); err != nil {
		t.Errorf("Commit() past the end error = %v, want nil (clamped)", err)
	}
}

func TestEnqueue_DropsOldestWhenOverCap(t *testing.T) {
	// A tiny cap that fits only a couple of frames, to exercise eviction
	// without a 64MB fixture.
	const tinyCap = 300
	dir := t.TempDir()
	s, err := Open(dir, tinyCap)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	// The frames are stamped on a fixed, strictly increasing grid rather than
	// with time.Now(), so the destroyed *window* the stats report is checkable
	// against known instants instead of against the clock the test runs on.
	base := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	firstTS := base
	for i := uint64(0); i < 10; i++ {
		f := testFrame(i)
		f.TS = base.Add(time.Duration(i) * time.Minute)
		if err := s.Enqueue(f); err != nil {
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

	// The policy is unchanged; what must also hold now is that the loss was
	// *recorded*. A spool that drops observations and reports nothing is the
	// defect this half of the test exists to catch: depth simply stops
	// rising, and nothing else on the agent or the server ever says why.
	stats := s.EvictionStats()
	dropped := int64(10 - s.Len())
	if stats.Frames != dropped {
		t.Errorf("EvictionStats().Frames = %d, want %d (10 enqueued, %d still queued)", stats.Frames, dropped, s.Len())
	}
	// The exact sum, not merely "> 0". The frames were enqueued in order and
	// eviction is strictly oldest-first, so the destroyed bytes are the
	// encoded sizes of exactly seqs [0, dropped) — computable, and therefore
	// worth asserting rather than approximating.
	var wantBytes int64
	for i := int64(0); i < dropped; i++ {
		f := testFrame(uint64(i))
		f.TS = base.Add(time.Duration(i) * time.Minute)
		encoded, encodeErr := frame.Encode(f)
		if encodeErr != nil {
			t.Fatalf("Encode() error = %v", encodeErr)
		}
		wantBytes += int64(len(encoded)) + 1
	}
	if stats.Bytes != wantBytes {
		t.Errorf("EvictionStats().Bytes = %d, want %d (the encoded size of the dropped frames)", stats.Bytes, wantBytes)
	}
	// Both bounds are asserted against the *known instants the fixtures were
	// stamped with*, not merely against each other. "Widen from the dropped
	// entries' own f.TS, not from wall-clock now" is the requirement, and an
	// implementation that stamped NewestDroppedTS with time.Now() would pass
	// every non-zero/ordering check while being exactly wrong.
	wantOldest := firstTS
	wantNewest := base.Add(time.Duration(dropped-1) * time.Minute)
	if !stats.OldestDroppedTS.Equal(wantOldest) {
		t.Errorf("EvictionStats().OldestDroppedTS = %v, want %v — the oldest dropped frame's own TS", stats.OldestDroppedTS, wantOldest)
	}
	if !stats.NewestDroppedTS.Equal(wantNewest) {
		t.Errorf("EvictionStats().NewestDroppedTS = %v, want %v — the newest dropped frame's own TS, not wall clock", stats.NewestDroppedTS, wantNewest)
	}
	if stats.LastEvictedAt.IsZero() {
		t.Error("EvictionStats().LastEvictedAt is zero — an eviction happened and must be stamped")
	}
	// LastEvictedAt is the one wall-clock field, and must not have been
	// confused with the window: it describes when the destruction ran.
	if !stats.LastEvictedAt.After(wantNewest) {
		t.Errorf("EvictionStats().LastEvictedAt = %v, want a wall-clock instant after the destroyed window's end %v", stats.LastEvictedAt, wantNewest)
	}

	// And it must survive an agent restart. The record is the audit trail for
	// permanently destroyed data; a restart that zeroes it is indistinguishable
	// from never having lost anything.
	if err := s.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}
	reopened, err := Open(dir, tinyCap)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	defer reopened.Close()
	if got := reopened.EvictionStats(); got != stats {
		t.Errorf("EvictionStats() after reopen = %+v, want %+v — the record must persist across a restart", got, stats)
	}

	// Cumulative, never reset: more eviction on the reopened spool adds to
	// the reloaded total rather than starting a fresh count.
	for i := uint64(10); i < 20; i++ {
		if err := reopened.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) after reopen error = %v", i, err)
		}
	}
	if after := reopened.EvictionStats(); after.Frames <= stats.Frames {
		t.Errorf("EvictionStats().Frames after further eviction = %d, want > %d (cumulative)", after.Frames, stats.Frames)
	}
}

// TestEnqueue_EvictionIsAudibleAtWarnLogLevel pins the severity of the
// eviction line, which is not a cosmetic detail.
//
// internal/logging.Configure points the standard `log` package at a gate that
// forwards a record only while Info is enabled, so a log.Printf line vanishes
// entirely at `log_level = "warn"` no matter what word it contains. "warn" is
// the setting an operator picks to quieten a homelab box — so emitting this
// through log.Printf would mean the single local signal that data was
// permanently destroyed could be switched off by someone reducing noise, and
// this whole mechanism would be silent again for exactly the audience it was
// built for.
//
// It also pins "once per eviction batch, not once per destroyed frame": the
// fat frame below displaces several small ones in a single Enqueue, which is
// the shape a real cap breach takes and the only shape that can tell the two
// rules apart.
func TestEnqueue_EvictionIsAudibleAtWarnLogLevel(t *testing.T) {
	var captured bytes.Buffer
	restore := logging.UseWriter(&captured, logging.LevelWarn)
	defer restore()

	const cap = 1000
	s, err := Open(t.TempDir(), cap)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	base := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	for i := uint64(0); i < 10; i++ {
		f := testFrame(i)
		f.TS = base.Add(time.Duration(i) * time.Minute)
		if err := s.Enqueue(f); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if captured.Len() != 0 {
		t.Fatalf("log before any eviction = %q, want silence", captured.String())
	}

	// One frame big enough to displace several at once.
	fat := fatFrame(10, 400)
	fat.TS = base.Add(10 * time.Minute)
	if err := s.Enqueue(fat); err != nil {
		t.Fatalf("Enqueue(fat) error = %v", err)
	}

	out := captured.String()
	if !strings.Contains(out, "permanently discarded") {
		t.Fatalf("log at level=warn = %q, want the eviction warning — a line an operator quietening the agent must still receive", out)
	}
	if got := strings.Count(out, "permanently discarded"); got != 1 {
		t.Errorf("eviction warning appeared %d times, want exactly 1 for a single eviction batch", got)
	}
	match := regexp.MustCompile(`permanently discarded (\d+) buffered`).FindStringSubmatch(out)
	if match == nil {
		t.Fatalf("eviction warning = %q, want it to name the destroyed count", out)
	}
	count, convErr := strconv.Atoi(match[1])
	if convErr != nil {
		t.Fatalf("Atoi(%q) error = %v", match[1], convErr)
	}
	if count < 2 {
		t.Fatalf("the batch destroyed %d frame(s); this test cannot distinguish per-batch from per-frame logging unless it destroys several at once", count)
	}
	// The line has to be actionable on its own, not merely present.
	for _, want := range []string{"2026-09-01T00:00:00Z", "spool_cap_bytes", "cannot be recovered"} {
		if !strings.Contains(out, want) {
			t.Errorf("eviction warning = %q, want it to name %q", out, want)
		}
	}
}

// TestEvictionStats_ZeroWhenNothingEvicted pins the other half of the
// contract: a spool that has never breached its cap reports an empty record,
// with zero bounds rather than fabricated ones. `cb-agent status` and the
// server's UI both key "say nothing" off exactly this.
func TestEvictionStats_ZeroWhenNothingEvicted(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()
	for i := uint64(0); i < 5; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if got := (s.EvictionStats()); got != (EvictionStats{}) {
		t.Errorf("EvictionStats() = %+v, want the zero value with nothing evicted", got)
	}
	if _, err := os.Stat(filepath.Join(dir, evictedFilename)); !os.IsNotExist(err) {
		t.Errorf("os.Stat(%s) err = %v, want the record file to be absent until something is destroyed", evictedFilename, err)
	}
}

// TestOpen_RefusesACorruptEvictionRecord pins that a damaged record fails
// Open rather than resetting to zero. Silently starting the count over is the
// exact failure mode this file exists to prevent — it would read as "this
// agent has never lost anything", which is a stronger and falser claim than
// "this agent cannot tell you".
func TestOpen_RefusesACorruptEvictionRecord(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, evictedFilename), []byte("{not json"), 0o600); err != nil {
		t.Fatalf("write corrupt record: %v", err)
	}
	if _, err := Open(dir, DefaultCapBytes); err == nil {
		t.Fatal("Open() error = nil, want a failure rather than a silently reset eviction record")
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

	if err := s.commit(2); err != nil {
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
	if err := s.commit(2); err != nil {
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

	if err := s.commit(50); err != nil {
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
	if err := s.commit(frames); err != nil {
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
	if err := s.commit(2); err != nil { // below the compaction thresholds
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

// TestSpool_PositionsSurviveCommitAndEviction pins the property the whole
// position mechanism exists for: an absolute position names the same frame
// however the head moves underneath it.
//
// The head moves for two reasons — a commit, and the drop-oldest cap policy —
// and a caller holding frames across a round trip cannot tell which happened,
// or how far. Head-relative bookkeeping is therefore unsafe for it: `Commit(n)`
// and a head-relative skip both mean "the first n live frames", and both name
// different frames after an eviction than they did when the caller decided on
// them.
func TestSpool_PositionsSurviveCommitAndEviction(t *testing.T) {
	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	for i := uint64(0); i < 6; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	if got := s.Origin(); got != 0 {
		t.Fatalf("Origin() = %d on a fresh spool, want 0", got)
	}
	res := s.PeekAt(FromHead, 3, DefaultCapBytes)
	if len(res.Frames) != 3 || res.Start != 0 || res.Origin != 0 {
		t.Fatalf("PeekAt(FromHead) = %d frames at %d (origin %d), want 3 at 0 (origin 0)",
			len(res.Frames), res.Start, res.Origin)
	}
	if res.Frames[0].Seq != 0 {
		t.Errorf("PeekAt(FromHead) first frame seq = %d, want 0", res.Frames[0].Seq)
	}

	// Look past what is already in flight, by position.
	res = s.PeekAt(3, 3, DefaultCapBytes)
	if len(res.Frames) != 3 || res.Start != 3 {
		t.Fatalf("PeekAt(3) = %d frames at %d, want 3 at 3", len(res.Frames), res.Start)
	}
	if res.Frames[0].Seq != 3 {
		t.Errorf("PeekAt(3) first frame seq = %d, want 3", res.Frames[0].Seq)
	}

	// Committing through position 2 discards exactly the first three.
	if err := s.CommitThrough(2); err != nil {
		t.Fatalf("CommitThrough(2) error = %v", err)
	}
	if got := s.Len(); got != 3 {
		t.Errorf("Len() = %d after CommitThrough(2), want 3", got)
	}
	if got := s.Origin(); got != 3 {
		t.Errorf("Origin() = %d after CommitThrough(2), want 3", got)
	}

	// Replaying a watermark that has already been applied frees nothing more
	// — the alternative is discarding live frames a second time.
	if err := s.CommitThrough(2); err != nil {
		t.Fatalf("CommitThrough(2) replay error = %v", err)
	}
	if got := s.Len(); got != 3 {
		t.Errorf("Len() = %d after replaying CommitThrough(2), want 3", got)
	}

	res = s.PeekAt(FromHead, 1, DefaultCapBytes)
	if len(res.Frames) != 1 || res.Frames[0].Seq != 3 || res.Start != 3 {
		t.Errorf("PeekAt(FromHead) after a commit = seq %v at %d, want seq 3 at 3",
			res.Frames, res.Start)
	}
}

// TestSpool_CommitThroughIgnoresPositionsTheCapDestroyed is the spool half of
// the loss this mechanism prevents.
//
// A caller that sent frames and is waiting for them to be acknowledged holds
// positions at the head of the backlog — which is exactly where cap eviction
// takes from. If its commit were a count, it would discard that many frames
// from the *new* head: never-sent frames, destroyed silently, on top of the
// ones eviction already destroyed and reported.
func TestSpool_CommitThroughIgnoresPositionsTheCapDestroyed(t *testing.T) {
	first := testFrame(0)
	encoded, err := frame.Encode(first)
	if err != nil {
		t.Fatalf("Encode() error = %v", err)
	}
	// Room for exactly four of these.
	s, err := Open(t.TempDir(), int64(len(encoded)+1)*4)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	for i := uint64(0); i < 8; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	origin := s.Origin()
	if origin == 0 {
		t.Fatal("nothing was evicted — the cap is too generous for this fixture")
	}
	remaining := s.Len()

	// A watermark for frames the cap already destroyed must free nothing.
	if err := s.CommitThrough(origin - 1); err != nil {
		t.Fatalf("CommitThrough(%d) error = %v", origin-1, err)
	}
	if got := s.Len(); got != remaining {
		t.Errorf("Len() = %d after committing through a destroyed position, want %d — "+
			"%d never-sent frame(s) were discarded", got, remaining, remaining-got)
	}

	// A watermark straddling the eviction frees only the part still present.
	if err := s.CommitThrough(origin); err != nil {
		t.Fatalf("CommitThrough(%d) error = %v", origin, err)
	}
	if got := s.Len(); got != remaining-1 {
		t.Errorf("Len() = %d after committing through the new head, want %d", got, remaining-1)
	}
}

// TestRecordDestroyed_CountsAnObservationTheSpoolCouldNotBuffer covers the
// other way an observation dies: not the cap, but a spool that could not
// accept the write at all — a full disk, a read-only /var.
//
// Since every data frame is now spooled before it can reach a socket, a
// refused write is the end of that observation, and it lands in the same
// permanent record cap eviction writes to. The operator-facing fact is
// identical, and a loss that is real but invisible is the one outcome the
// whole eviction-reporting effort exists to prevent.
func TestRecordDestroyed_CountsAnObservationTheSpoolCouldNotBuffer(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if got := s.EvictionStats().Frames; got != 0 {
		t.Fatalf("EvictionStats().Frames = %d on a fresh spool, want 0", got)
	}

	observed := time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC)
	lost := testFrame(1)
	lost.TS = observed
	s.RecordDestroyed(lost, "spool write failed")

	stats := s.EvictionStats()
	if stats.Frames != 1 {
		t.Errorf("EvictionStats().Frames = %d, want 1", stats.Frames)
	}
	if stats.Bytes <= 0 {
		t.Errorf("EvictionStats().Bytes = %d, want the frame's encoded size", stats.Bytes)
	}
	if !stats.OldestDroppedTS.Equal(observed) || !stats.NewestDroppedTS.Equal(observed) {
		t.Errorf("destroyed window = %v..%v, want both %v — the bound must be the observation's "+
			"own time, not when the write failed", stats.OldestDroppedTS, stats.NewestDroppedTS, observed)
	}
	if stats.LastEvictedAt.IsZero() {
		t.Error("LastEvictedAt is zero — the wall-clock half of the record was not written")
	}

	// Persisted, so a restart still reports it. This is a record of destroyed
	// data; forgetting it across a restart would understate the loss.
	reopened, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	if got := reopened.EvictionStats().Frames; got != 1 {
		t.Errorf("EvictionStats().Frames after reopen = %d, want 1", got)
	}
}

// TestRecordDestroyed_ReportsOncePerWindowButCountsEveryLoss pins the split
// between the record and the reporting.
//
// The counters must be exact — they are what the fleet view reads, and an
// under-reported loss is worse than none because it looks authoritative. The
// log line and the fsync behind it must not be, because the condition that
// drives them is by nature sustained: a full disk stays full, and a line plus
// a failing write per sample is a storm layered on a storage failure. The
// first loss in a window still reports immediately, so an isolated failure is
// never silent.
func TestRecordDestroyed_ReportsOncePerWindowButCountsEveryLoss(t *testing.T) {
	var logs bytes.Buffer
	restore := logging.UseWriter(&logs, logging.LevelWarn)
	defer restore()

	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}

	const lost = 25
	for i := uint64(1); i <= lost; i++ {
		s.RecordDestroyed(testFrame(i), "spool write failed")
	}

	if got := s.EvictionStats().Frames; got != lost {
		t.Errorf("EvictionStats().Frames = %d, want %d — the record may never be throttled", got, lost)
	}
	if got := s.EvictionStats().Bytes; got <= 0 {
		t.Errorf("EvictionStats().Bytes = %d, want the destroyed frames' size", got)
	}

	lines := strings.Count(logs.String(), "could not be buffered")
	if lines != 1 {
		t.Errorf("wrote %d loss lines for %d losses inside one window, want 1\n%s",
			lines, lost, logs.String())
	}
	// That one line is the *first* loss, reported the instant it happened —
	// the 24 behind it are batched, not dropped.
	if !strings.Contains(logs.String(), "permanently lost 1 observation(s)") {
		t.Errorf("the first loss was not reported on its own:\n%s", logs.String())
	}

	// A new window reports again, carrying everything batched since the last
	// line rather than only the frame that happened to reopen it — and the
	// cumulative total is the honest one throughout.
	s.mu.Lock()
	s.lastDestroyedReport = time.Now().Add(-2 * destroyedReportInterval)
	s.mu.Unlock()
	s.RecordDestroyed(testFrame(lost+1), "spool write failed")

	if got := strings.Count(logs.String(), "could not be buffered"); got != 2 {
		t.Errorf("wrote %d loss lines after the window elapsed, want 2\n%s", got, logs.String())
	}
	if !strings.Contains(logs.String(), "permanently lost 25 observation(s)") {
		t.Errorf("the second line does not carry the 25 losses batched behind it:\n%s", logs.String())
	}
	if !strings.Contains(logs.String(), "cumulative loss for this agent is 26 observation(s)") {
		t.Errorf("the cumulative total does not account for every loss:\n%s", logs.String())
	}
	if got := s.EvictionStats().Frames; got != lost+1 {
		t.Errorf("EvictionStats().Frames = %d, want %d", got, lost+1)
	}
}

// stampedFrame is testFrame with a chosen observation time, for the tests that
// care which *window* of history a loss line claims to cover.
func stampedFrame(seq uint64, ts time.Time) frame.Frame {
	f := testFrame(seq)
	f.TS = ts.UTC()
	return f
}

// TestRecordDestroyed_PermanentRecordSurvivesARestartMidWindow is the C2
// regression.
//
// Throttling the log line is right; throttling the *persist* with it was not.
// The record is documented as cumulative for the life of the state directory
// and is the audit trail for destroyed data, so a restart inside the reporting
// window — which is exactly what an operator does after freeing the disk that
// caused the losses — must not find a smaller number than the one the running
// agent was reporting. The server treats any decrease as the state directory
// having been recreated and writes a permanent audit event saying so, which
// would be a confidently wrong claim about data loss layered on top of real
// data loss.
func TestRecordDestroyed_PermanentRecordSurvivesARestartMidWindow(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}

	const lost = 25
	for i := uint64(1); i <= lost; i++ {
		s.RecordDestroyed(testFrame(i), "spool write failed")
	}
	live := s.EvictionStats()
	if live.Frames != lost {
		t.Fatalf("in-memory EvictionStats().Frames = %d, want %d", live.Frames, lost)
	}

	// No Close: a full disk is as likely to end in a kill as in a clean stop,
	// and the record has to be right either way.
	restarted, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("reopen error = %v", err)
	}
	got := restarted.EvictionStats()
	if got.Frames != lost {
		t.Errorf("after restart the permanent record reports %d of %d destroyed observation(s) — "+
			"batching the persist loses them outright, and a cumulative counter that goes down "+
			"makes the server log a false state-directory reset", got.Frames, lost)
	}
	if got.Bytes != live.Bytes {
		t.Errorf("after restart the record reports %d bytes, want %d", got.Bytes, live.Bytes)
	}
	if !got.LastEvictedAt.Equal(live.LastEvictedAt) {
		t.Errorf("after restart LastEvictedAt = %v, want %v", got.LastEvictedAt, live.LastEvictedAt)
	}
}

// TestRecordDestroyed_BatchedLineNamesTheWholeDestroyedWindow checks the
// batched line describes the hole it is reporting.
//
// It printed the triggering frame's timestamp — the *newest* in the batch —
// followed by "..", which reads as "the hole starts here" when the hole in
// fact ends there. `cb-agent status` sends operators to this exact line, so
// pointing them at the wrong end of the gap is worse than a stray log string.
func TestRecordDestroyed_BatchedLineNamesTheWholeDestroyedWindow(t *testing.T) {
	var logs bytes.Buffer
	restore := logging.UseWriter(&logs, logging.LevelWarn)
	defer restore()

	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}

	base := time.Date(2026, 9, 7, 12, 0, 0, 0, time.UTC)
	const lost = 25
	for i := uint64(1); i <= lost; i++ {
		s.RecordDestroyed(stampedFrame(i, base.Add(time.Duration(i)*time.Second)), "spool write failed")
	}
	// Reopen the window so the batch behind the first line is reported.
	s.mu.Lock()
	s.lastDestroyedReport = time.Now().Add(-2 * destroyedReportInterval)
	s.mu.Unlock()
	s.RecordDestroyed(stampedFrame(lost+1, base.Add(time.Duration(lost+1)*time.Second)), "spool write failed")

	// The batched line covers frames 2..26 — everything since the first loss,
	// which reported on its own.
	want := "covering " + base.Add(2*time.Second).Format(time.RFC3339) +
		".." + base.Add(time.Duration(lost+1)*time.Second).Format(time.RFC3339)
	if !strings.Contains(logs.String(), want) {
		t.Errorf("batched loss line does not name the window it destroyed, want %q:\n%s", want, logs.String())
	}
}

// TestRecordDestroyed_RecordsWhichCauseDestroyedTheData covers the operator
// question `cb-agent status` could not answer.
//
// Both the size cap and a refused write fold into one counter, deliberately —
// the operator-facing fact is identical. But the *remedies* are opposite, and
// with only a count the status output has to list both and ask the operator to
// go grep. The record now carries the most recent cause so it can say which
// one actually happened.
func TestRecordDestroyed_RecordsWhichCauseDestroyedTheData(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}

	s.RecordDestroyed(testFrame(1), "spool write failed: read-only file system")
	got := s.EvictionStats()
	if got.LastDestroyedCause != CauseWriteFailed {
		t.Errorf("LastDestroyedCause = %q, want %q", got.LastDestroyedCause, CauseWriteFailed)
	}
	if got.LastDestroyedReason != "spool write failed: read-only file system" {
		t.Errorf("LastDestroyedReason = %q, want the underlying error", got.LastDestroyedReason)
	}

	restarted, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("reopen error = %v", err)
	}
	if got := restarted.EvictionStats(); got.LastDestroyedCause != CauseWriteFailed ||
		got.LastDestroyedReason != "spool write failed: read-only file system" {
		t.Errorf("after restart cause = %q reason = %q, want them preserved",
			got.LastDestroyedCause, got.LastDestroyedReason)
	}
}

// TestEvictionStats_CauseIsAMachineCodeNotTheProse guards the discriminator
// itself. `cb-agent status` picks which remedy to print from the cause, and
// the remedies are opposite — so the thing it branches on must not be a
// sentence someone will reasonably copy-edit. Rewording CapEvictionReason
// must not turn a persisted cap eviction into a write failure.
func TestEvictionStats_CauseIsAMachineCodeNotTheProse(t *testing.T) {
	if CauseSizeCap == CapEvictionReason {
		t.Fatal("the cause code and the operator-facing sentence are the same string — " +
			"a copy edit to the sentence would silently reclassify every persisted record")
	}
	for _, code := range []string{CauseSizeCap, CauseWriteFailed} {
		if strings.ContainsAny(code, " .") {
			t.Errorf("cause code %q reads as prose; it is control flow and should not be edited as copy", code)
		}
	}
}

// TestEnqueue_CapEvictionRecordsItselfAsTheCause is the other half: the size
// cap is a cause too, and the one the status output should name when it is
// what happened most recently.
func TestEnqueue_CapEvictionRecordsItselfAsTheCause(t *testing.T) {
	restore := logging.UseWriter(io.Discard, logging.LevelWarn)
	defer restore()

	f := testFrame(1)
	encoded, err := frame.Encode(f)
	if err != nil {
		t.Fatalf("Encode() error = %v", err)
	}
	// Room for two frames, so the third evicts the first.
	s, err := Open(t.TempDir(), int64(len(encoded)+1)*2)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	for i := uint64(1); i <= 3; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	stats := s.EvictionStats()
	if stats.Frames == 0 {
		t.Fatal("nothing was evicted — the fixture is not at the cap")
	}
	if stats.LastDestroyedCause != CauseSizeCap {
		t.Errorf("LastDestroyedCause = %q, want %q", stats.LastDestroyedCause, CauseSizeCap)
	}
	if stats.LastDestroyedReason != CapEvictionReason {
		t.Errorf("LastDestroyedReason = %q, want %q", stats.LastDestroyedReason, CapEvictionReason)
	}
}

// TestRecordDestroyed_PersistFailureIsReportedWhenItStarts covers the one
// thing worse than a record that cannot be written: one that cannot be
// written silently.
//
// The loss line is rate-limited to one a minute, deliberately. Attaching the
// persist error to it would hide a failure that began just after a line for
// up to a minute and then attribute it to whichever sample happened to reopen
// the window. It is reported on the transition into failing instead, and
// repeated no more often than the loss line while it lasts.
func TestRecordDestroyed_PersistFailureIsReportedWhenItStarts(t *testing.T) {
	var logs bytes.Buffer
	restore := logging.UseWriter(&logs, logging.LevelWarn)
	defer restore()

	dir := t.TempDir()
	s, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	// A path under a directory that does not exist fails every write, on any
	// platform and whatever the test process's privileges are.
	s.mu.Lock()
	s.evictedPath = filepath.Join(dir, "gone", evictedFilename)
	s.mu.Unlock()

	s.RecordDestroyed(testFrame(1), "spool write failed: no space left on device")
	if got := strings.Count(logs.String(), "could not persist the eviction record"); got != 1 {
		t.Fatalf("wrote %d persist-failure lines for the first failure, want 1\n%s", got, logs.String())
	}

	// Still inside the window: the loss line is suppressed, and so is a
	// repeat of the persist failure.
	for i := uint64(2); i <= 20; i++ {
		s.RecordDestroyed(testFrame(i), "spool write failed: no space left on device")
	}
	if got := strings.Count(logs.String(), "could not persist the eviction record"); got != 1 {
		t.Errorf("wrote %d persist-failure lines inside one window, want 1\n%s", got, logs.String())
	}
	if got := strings.Count(logs.String(), "could not be buffered"); got != 1 {
		t.Errorf("wrote %d loss lines inside one window, want 1\n%s", got, logs.String())
	}

	// Recovering and failing again reports again: this is a new run, not a
	// continuation of the one already reported.
	s.mu.Lock()
	s.evictedPath = filepath.Join(dir, evictedFilename)
	s.mu.Unlock()
	s.RecordDestroyed(testFrame(21), "spool write failed: no space left on device")
	s.mu.Lock()
	s.evictedPath = filepath.Join(dir, "gone", evictedFilename)
	s.mu.Unlock()
	s.RecordDestroyed(testFrame(22), "spool write failed: no space left on device")
	if got := strings.Count(logs.String(), "could not persist the eviction record"); got != 2 {
		t.Errorf("wrote %d persist-failure lines after recovering and failing again, want 2\n%s",
			got, logs.String())
	}

	// The counters are exact throughout, including for the losses whose
	// record could not be written.
	if got := s.EvictionStats().Frames; got != 22 {
		t.Errorf("EvictionStats().Frames = %d, want 22 — a persist failure must not lose a count", got)
	}
}
