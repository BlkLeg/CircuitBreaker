// apps/agent/internal/link/outbound_test.go
package link

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// fakeDataFrameType is a made-up frame type used only in these tests, since
// no real Slice 2+ data frame type is produced anywhere in Slice 1 (Global
// Constraints: do not spool telemetry/probe/discovery frames — those payload
// types belong to Slices 2-4). It is not registered anywhere as a control
// type, so frame.IsDataFrame classifies it as a data frame exactly like a
// real future payload type would, without any code change.
const fakeDataFrameType = "test.fakedata"

func fakeDataFrame(seq uint64) frame.Frame {
	return frame.Frame{V: frame.FrameVersion, Type: fakeDataFrameType, Seq: seq, TS: time.Now().UTC(), Payload: json.RawMessage(`{}`)}
}

// fatDataFrame is a fake data frame with a ~size-byte payload, so a byte
// budget can be exercised without a megabyte fixture.
func fatDataFrame(seq uint64, size int) frame.Frame {
	f := fakeDataFrame(seq)
	f.Payload = json.RawMessage(`{"blob":"` + strings.Repeat("x", size) + `"}`)
	return f
}

// TestDataFrameSender_SendLive_SuccessNeverTouchesSpool verifies a live data
// frame that sends successfully never gets enqueued.
func TestDataFrameSender_SendLive_SuccessNeverTouchesSpool(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	var sent int
	send := func(frame.Frame) error { sent++; return nil }
	sender := newDataFrameSender(sp, send, nil)

	if err := sender.sendLive(fakeDataFrame(1)); err != nil {
		t.Fatalf("sendLive() error = %v", err)
	}
	if sent != 1 {
		t.Errorf("send called %d times, want 1", sent)
	}
	if got := sp.Len(); got != 0 {
		t.Errorf("spool Len() = %d, want 0 after a successful live send", got)
	}
}

// TestDataFrameSender_SendLive_FailureSpoolsFrame verifies a live data frame
// whose send fails is durably enqueued to the spool rather than lost.
func TestDataFrameSender_SendLive_FailureSpoolsFrame(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	sendErr := errors.New("boom: connection dead")
	send := func(frame.Frame) error { return sendErr }
	sender := newDataFrameSender(sp, send, nil)

	f := fakeDataFrame(1)
	err = sender.sendLive(f)
	if !errors.Is(err, sendErr) {
		t.Fatalf("sendLive() error = %v, want it to wrap %v", err, sendErr)
	}
	if got := sp.Len(); got != 1 {
		t.Fatalf("spool Len() = %d, want 1 after a failed live send", got)
	}
	peeked := sp.Peek(1, spool.DefaultCapBytes)
	if len(peeked) != 1 {
		t.Fatalf("Peek(1) returned %d frames, want the spooled frame", len(peeked))
	}
	if peeked[0].Seq != f.Seq || peeked[0].Type != f.Type {
		t.Errorf("spooled frame = %+v, want %+v", peeked[0], f)
	}
}

// TestDataFrameSender_SendLive_PanicsOnNonDataFrame is the explicit assertion
// required by the wiring: a heartbeat or control frame must never reach the
// spool's write path. Passing one into sendLive — which should only ever
// receive what Slice 2+ producers hand it via the DataFrames channel — is a
// programming-invariant violation, not a runtime condition, so it panics
// (mirroring noiseconn.Session.Encrypt's panic-on-invariant-violation).
func TestDataFrameSender_SendLive_PanicsOnNonDataFrame(t *testing.T) {
	controlTypes := []string{frame.TypeHeartbeat, frame.TypeTransportRekey, frame.TypeHello}
	for _, typ := range controlTypes {
		t.Run(typ, func(t *testing.T) {
			sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
			if err != nil {
				t.Fatalf("spool.Open() error = %v", err)
			}
			send := func(frame.Frame) error { return nil }
			sender := newDataFrameSender(sp, send, nil)

			defer func() {
				if r := recover(); r == nil {
					t.Errorf("sendLive(%q) did not panic, want a panic guarding the spool", typ)
				}
			}()
			sender.sendLive(frame.Frame{V: 1, Type: typ, Seq: 1, TS: time.Now().UTC(), Payload: json.RawMessage(`{}`)})

			if got := sp.Len(); got != 0 {
				t.Errorf("spool Len() = %d, want 0 — control frame must never reach the spool", got)
			}
		})
	}
}

// TestDataFrameSender_LiveSendNoLongerDrains replaces the old
// TestDataFrameSender_DrainRatio_OneDrainPerFourLiveSends: catch-up is no
// longer a side effect of live production (D-5). A live send that succeeds
// does exactly one thing — send — so a backlog sitting in the spool is
// untouched by live traffic and is instead flushed by runOnce's paced
// drainTicker arm.
func TestDataFrameSender_LiveSendNoLongerDrains(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	for i := uint64(100); i < 110; i++ {
		if err := sp.Enqueue(fakeDataFrame(i)); err != nil {
			t.Fatalf("Enqueue() error = %v", err)
		}
	}
	preloaded := sp.Len()

	var sent int
	send := func(frame.Frame) error { sent++; return nil }
	sender := newDataFrameSender(sp, send, nil)

	const liveSends = 8 // twice the old 1:4 ratio, so the old code drained twice
	for i := uint64(0); i < liveSends; i++ {
		if err := sender.sendLive(fakeDataFrame(i)); err != nil {
			t.Fatalf("sendLive(%d) error = %v", i, err)
		}
	}

	if sent != liveSends {
		t.Errorf("send() calls = %d, want %d — a live send must not also drain", sent, liveSends)
	}
	if got := sp.Len(); got != preloaded {
		t.Errorf("spool Len() after %d live sends = %d, want %d (backlog untouched by live traffic)",
			liveSends, got, preloaded)
	}
}

// TestDataFrameSender_DrainBurstRespectsFrameAndByteBudget pins the paced
// catch-up budget: one tick sends at most maxFrames frames and at most
// maxBytes of them, leaving the rest of the backlog for the next tick. This
// is what makes catch-up after a long outage bounded rather than a
// reconnect-time flood.
func TestDataFrameSender_DrainBurstRespectsFrameAndByteBudget(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	for i := uint64(1); i <= 10; i++ {
		if err := sp.Enqueue(fatDataFrame(i, 1000)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	var sent []frame.Frame
	send := func(f frame.Frame) error { sent = append(sent, f); return nil }
	sender := newDataFrameSender(sp, send, nil)

	if err := sender.drainBurst(4, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if len(sent) != 4 {
		t.Fatalf("sent %d frames, want 4 (frame budget)", len(sent))
	}
	if got := sp.Len(); got != 6 {
		t.Errorf("spool Len() = %d, want 6 after one 4-frame burst", got)
	}

	// A byte budget that fits only two ~1KiB frames caps the burst below the
	// frame budget.
	sent = nil
	if err := sender.drainBurst(4, 2500); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if len(sent) != 2 {
		t.Fatalf("sent %d frames, want 2 (byte budget)", len(sent))
	}
	if got := sp.Len(); got != 4 {
		t.Errorf("spool Len() = %d, want 4", got)
	}
	for i, f := range sent {
		if want := uint64(5 + i); f.Seq != want {
			t.Errorf("burst frame %d seq = %d, want %d (FIFO)", i, f.Seq, want)
		}
	}
}

// TestDataFrameSender_DrainBurstCommitsOnlySuccessesAndKeepsOrder replaces
// TestDataFrameSender_DrainOne_ResendFailureReEnqueues. The old drain
// re-enqueued a failed frame at the *tail*, so the oldest frame became the
// newest and its neighbours were evicted before it. Commit-after-send makes
// that impossible: only the frames that reached the wire are discarded and
// the failing frame is still at the head, in the original order.
func TestDataFrameSender_DrainBurstCommitsOnlySuccessesAndKeepsOrder(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	for i := uint64(1); i <= 5; i++ {
		if err := sp.Enqueue(fakeDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	sendErr := errors.New("boom: connection dead mid-burst")
	var attempts int
	send := func(frame.Frame) error {
		attempts++
		if attempts == 3 {
			return sendErr
		}
		return nil
	}
	sender := newDataFrameSender(sp, send, nil)

	if err := sender.drainBurst(5, spool.DefaultCapBytes); !errors.Is(err, sendErr) {
		t.Fatalf("drainBurst() error = %v, want it to wrap %v", err, sendErr)
	}
	if attempts != 3 {
		t.Errorf("send() calls = %d, want 3 — the burst must stop at the first failure", attempts)
	}
	if got := sp.Len(); got != 3 {
		t.Fatalf("spool Len() = %d, want 3 (only the 2 successes committed)", got)
	}
	remaining := sp.Peek(5, spool.DefaultCapBytes)
	if len(remaining) != 3 {
		t.Fatalf("Peek() returned %d frames, want 3", len(remaining))
	}
	for i, f := range remaining {
		if want := uint64(3 + i); f.Seq != want {
			t.Errorf("remaining frame %d seq = %d, want %d — order must be preserved, failing frame first", i, f.Seq, want)
		}
	}
}

// TestDataFrameSender_HasBacklogAndDrainBurstAreNilSpoolSafe covers the
// normal case for most callers: every link.Options in this package except
// link_spool_test.go's leaves Spool nil, and runOnce's drain ticker fires
// against all of them.
func TestDataFrameSender_HasBacklogAndDrainBurstAreNilSpoolSafe(t *testing.T) {
	sender := newDataFrameSender(nil, func(frame.Frame) error {
		t.Fatal("send() called with no spool configured")
		return nil
	}, nil)

	if sender.hasBacklog() {
		t.Error("hasBacklog() = true with a nil spool, want false")
	}
	if err := sender.drainBurst(4, 256<<10); err != nil {
		t.Errorf("drainBurst() with a nil spool error = %v, want nil", err)
	}
}

// TestDataFrameSender_CapEviction_ReachableFromSendLive verifies the spool's
// existing cap-eviction logic (spool_test.go's
// TestEnqueue_DropsOldestWhenOverCap) is actually reachable through the live
// send-failure path this task wires up, not just spool.Enqueue called
// directly in isolation.
func TestDataFrameSender_CapEviction_ReachableFromSendLive(t *testing.T) {
	const tinyCap = 300
	sp, err := spool.Open(t.TempDir(), tinyCap)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	sendErr := errors.New("send always fails")
	send := func(frame.Frame) error { return sendErr }
	sender := newDataFrameSender(sp, send, nil)

	for i := uint64(0); i < 10; i++ {
		if err := sender.sendLive(fakeDataFrame(i)); !errors.Is(err, sendErr) {
			t.Fatalf("sendLive(%d) error = %v, want %v", i, err, sendErr)
		}
	}

	size, err := sp.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if size > tinyCap {
		t.Errorf("SizeBytes() = %d, want <= %d after cap eviction", size, tinyCap)
	}
	oldest := sp.Peek(1, spool.DefaultCapBytes)
	if len(oldest) != 1 {
		t.Fatalf("Peek(1) returned %d frames, want a frame present", len(oldest))
	}
	if oldest[0].Seq == 0 {
		t.Error("Peek() returned seq=0 — oldest frame should have been evicted via the live send path")
	}
}

// TestDataFrameSender_NilSpool_SendFailurePropagatesWithoutPanic verifies a
// nil spool (e.g. Uninstall's one-shot connection, which never spools)
// disables spooling entirely rather than panicking on a send failure.
func TestDataFrameSender_NilSpool_SendFailurePropagatesWithoutPanic(t *testing.T) {
	sendErr := errors.New("boom")
	send := func(frame.Frame) error { return sendErr }
	sender := newDataFrameSender(nil, send, nil)

	if err := sender.sendLive(fakeDataFrame(1)); !errors.Is(err, sendErr) {
		t.Fatalf("sendLive() error = %v, want %v", err, sendErr)
	}
}

// TestDataFrameSender_ReportsSpoolStats verifies onSpoolStats fires with the
// spool's post-mutation depth/size after both an enqueue (send failure) and
// a drain, so callers (main.go's status.Writer wiring) see an accurate
// backlog.
func TestDataFrameSender_ReportsSpoolStats(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	var reportedDepth []int
	onStats := func(depth int, bytes int64) {
		reportedDepth = append(reportedDepth, depth)
		if bytes < 0 {
			t.Errorf("reported bytes = %d, want >= 0", bytes)
		}
	}
	sendErr := errors.New("boom")
	failing := true
	send := func(frame.Frame) error {
		if failing {
			return sendErr
		}
		return nil
	}
	sender := newDataFrameSender(sp, send, onStats)

	if err := sender.sendLive(fakeDataFrame(1)); !errors.Is(err, sendErr) {
		t.Fatalf("sendLive() error = %v, want %v", err, sendErr)
	}
	if len(reportedDepth) != 1 || reportedDepth[0] != 1 {
		t.Fatalf("reportedDepth after enqueue = %v, want [1]", reportedDepth)
	}

	failing = false
	if err := sender.drainBurst(4, 256<<10); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if len(reportedDepth) != 2 || reportedDepth[1] != 0 {
		t.Fatalf("reportedDepth after drain = %v, want [1 0] (one report per burst, not per frame)", reportedDepth)
	}
}
