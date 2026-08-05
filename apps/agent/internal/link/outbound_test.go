// apps/agent/internal/link/outbound_test.go
package link

import (
	"encoding/json"
	"errors"
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
	got, ok, err := sp.Drain()
	if err != nil || !ok {
		t.Fatalf("Drain() = (%v, %v, %v), want the spooled frame", got, ok, err)
	}
	if got.Seq != f.Seq || got.Type != f.Type {
		t.Errorf("spooled frame = %+v, want %+v", got, f)
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

// TestDataFrameSender_DrainRatio_OneDrainPerFourLiveSends verifies the
// required 1:4 interleave: with live data frames flowing (all sending
// successfully) and a backlog already sitting in the spool, exactly one
// spooled frame drains for every four successful live sends —
// spool.DrainInterleaveRatio.
func TestDataFrameSender_DrainRatio_OneDrainPerFourLiveSends(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	// Preload a backlog bigger than what this test will ever drain, so a
	// drain always has something available to pull.
	for i := uint64(100); i < 110; i++ {
		if err := sp.Enqueue(fakeDataFrame(i)); err != nil {
			t.Fatalf("Enqueue() error = %v", err)
		}
	}
	preloaded := sp.Len()

	var sentTypes []frame.Frame
	send := func(f frame.Frame) error {
		sentTypes = append(sentTypes, f)
		return nil
	}
	sender := newDataFrameSender(sp, send, nil)

	const liveSends = 12 // three full 4-live cycles
	for i := uint64(0); i < liveSends; i++ {
		if err := sender.sendLive(fakeDataFrame(i)); err != nil {
			t.Fatalf("sendLive(%d) error = %v", i, err)
		}
	}

	wantDrains := liveSends / spool.DrainInterleaveRatio
	wantTotalSends := liveSends + wantDrains
	if len(sentTypes) != wantTotalSends {
		t.Errorf("total send() calls = %d, want %d (%d live + %d drained)",
			len(sentTypes), wantTotalSends, liveSends, wantDrains)
	}
	if got := sp.Len(); got != preloaded-wantDrains {
		t.Errorf("spool Len() after = %d, want %d (%d preloaded - %d drained)",
			got, preloaded-wantDrains, preloaded, wantDrains)
	}
}

// TestDataFrameSender_DrainOne_ResendFailureReEnqueues verifies a drained
// frame whose resend fails is put back into the spool rather than lost.
func TestDataFrameSender_DrainOne_ResendFailureReEnqueues(t *testing.T) {
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	backlog := fakeDataFrame(7)
	if err := sp.Enqueue(backlog); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}

	sendErr := errors.New("boom")
	send := func(frame.Frame) error { return sendErr }
	sender := newDataFrameSender(sp, send, nil)

	if err := sender.drainOne(); !errors.Is(err, sendErr) {
		t.Fatalf("drainOne() error = %v, want it to wrap %v", err, sendErr)
	}
	if got := sp.Len(); got != 1 {
		t.Fatalf("spool Len() = %d, want 1 — resend failure must re-enqueue, not drop", got)
	}
	got, ok, err := sp.Drain()
	if err != nil || !ok || got.Seq != backlog.Seq {
		t.Errorf("re-enqueued frame = (%+v, %v, %v), want the original backlog frame", got, ok, err)
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
	got, ok, err := sp.Drain()
	if err != nil || !ok {
		t.Fatalf("Drain() = (%v, %v, %v), want a frame present", got, ok, err)
	}
	if got.Seq == 0 {
		t.Error("Drain() returned seq=0 — oldest frame should have been evicted via the live send path")
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
	if err := sender.drainOne(); err != nil {
		t.Fatalf("drainOne() error = %v", err)
	}
	if len(reportedDepth) != 2 || reportedDepth[1] != 0 {
		t.Fatalf("reportedDepth after drain = %v, want [1 0]", reportedDepth)
	}
}
