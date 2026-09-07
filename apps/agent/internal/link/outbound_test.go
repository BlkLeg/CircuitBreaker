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

// fakeWire stands in for runOnce's sendDataFrame: it assigns this
// "connection's" sequence numbers the same way (a monotonic counter, starting
// at 1), records every frame it wrote, and can be told to fail on a given
// call so a mid-burst disconnect can be reproduced exactly.
//
// The returned byte count is the real encoded length, so the in-flight byte
// window is exercised against the same numbers production would see.
type fakeWire struct {
	seq  uint64
	sent []frame.Frame
	// failOn returns a non-nil error to fail the n-th send (1-based). Nil
	// means every send succeeds.
	failOn func(n int) error
}

func (w *fakeWire) send(f frame.Frame) (uint64, int64, error) {
	n := len(w.sent) + 1
	if w.failOn != nil {
		if err := w.failOn(n); err != nil {
			return 0, 0, err
		}
	}
	encoded, err := frame.Encode(f)
	if err != nil {
		return 0, 0, err
	}
	w.seq++
	w.sent = append(w.sent, f)
	return w.seq, int64(len(encoded)), nil
}

func (w *fakeWire) count() int { return len(w.sent) }

// payloadOrder returns the "n" field of every frame written, in send order,
// for fixtures built with numberedDataFrame.
func (w *fakeWire) payloadOrder(t *testing.T) []int {
	t.Helper()
	out := make([]int, 0, len(w.sent))
	for _, f := range w.sent {
		var p struct {
			N int `json:"n"`
		}
		if err := json.Unmarshal(f.Payload, &p); err != nil {
			t.Fatalf("unmarshal payload %s: %v", f.Payload, err)
		}
		out = append(out, p.N)
	}
	return out
}

// newTestSpool opens a spool in a temp dir, failing the test on error.
func newTestSpool(t *testing.T, capBytes int64) *spool.Spool {
	t.Helper()
	sp, err := spool.Open(t.TempDir(), capBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	return sp
}

// ackingSender builds a sender with `data.ack` negotiated — the mode every
// current agent talking to a current server runs in.
func ackingSender(t *testing.T, sp *spool.Spool, wire *fakeWire) *dataFrameSender {
	t.Helper()
	s := newDataFrameSender(sp, wire.send, nil)
	s.negotiateAck(true)
	return s
}

// TestDataFrameSender_SendLive_SuccessNeverTouchesSpool verifies a live data
// frame that sends successfully never gets enqueued.
func TestDataFrameSender_SendLive_SuccessNeverTouchesSpool(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	wire := &fakeWire{}
	sender := newDataFrameSender(sp, wire.send, nil)

	if err := sender.sendLive(fakeDataFrame(1)); err != nil {
		t.Fatalf("sendLive() error = %v", err)
	}
	if wire.count() != 1 {
		t.Errorf("send called %d times, want 1", wire.count())
	}
	if got := sp.Len(); got != 0 {
		t.Errorf("spool Len() = %d, want 0 after a successful live send", got)
	}
}

// TestDataFrameSender_SendLive_FailureSpoolsFrame verifies a live data frame
// whose send fails is durably enqueued to the spool rather than lost.
func TestDataFrameSender_SendLive_FailureSpoolsFrame(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	sendErr := errors.New("boom: connection dead")
	wire := &fakeWire{failOn: func(int) error { return sendErr }}
	sender := newDataFrameSender(sp, wire.send, nil)

	f := fakeDataFrame(1)
	err := sender.sendLive(f)
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

// TestDataFrameSender_SendLive_StampsAMissingObservationTime pins the other
// half of moving the timestamp to enqueue: sendLive serves the nil-spool path,
// which has no enqueue to do the stamping, so it must do it itself rather than
// putting a year-1 instant on the wire.
func TestDataFrameSender_SendLive_StampsAMissingObservationTime(t *testing.T) {
	wire := &fakeWire{}
	sender := newDataFrameSender(nil, wire.send, nil)

	unstamped := frame.Frame{V: frame.FrameVersion, Type: fakeDataFrameType, Payload: json.RawMessage(`{}`)}
	if err := sender.sendLive(unstamped); err != nil {
		t.Fatalf("sendLive() error = %v", err)
	}
	if wire.count() != 1 {
		t.Fatalf("send called %d times, want 1", wire.count())
	}
	if wire.sent[0].TS.IsZero() {
		t.Error("sendLive wrote a frame with a zero TS — an observation must never reach the wire undated")
	}
}

// TestDataFrameSender_SendLive_PanicsOnNonDataFrame is the explicit assertion
// required by the wiring: a heartbeat or control frame must never reach the
// spool's write path. Passing one into sendLive — which should only ever
// receive what a data-frame producer hands it — is a programming-invariant
// violation, not a runtime condition, so it panics (mirroring
// noiseconn.Session.Encrypt's panic-on-invariant-violation).
func TestDataFrameSender_SendLive_PanicsOnNonDataFrame(t *testing.T) {
	controlTypes := []string{frame.TypeHeartbeat, frame.TypeTransportRekey, frame.TypeHello, frame.TypeDataAck}
	for _, typ := range controlTypes {
		t.Run(typ, func(t *testing.T) {
			sp := newTestSpool(t, spool.DefaultCapBytes)
			wire := &fakeWire{}
			sender := newDataFrameSender(sp, wire.send, nil)

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
	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := uint64(100); i < 110; i++ {
		if err := sp.Enqueue(fakeDataFrame(i)); err != nil {
			t.Fatalf("Enqueue() error = %v", err)
		}
	}
	preloaded := sp.Len()

	wire := &fakeWire{}
	sender := newDataFrameSender(sp, wire.send, nil)

	const liveSends = 8 // twice the old 1:4 ratio, so the old code drained twice
	for i := uint64(0); i < liveSends; i++ {
		if err := sender.sendLive(fakeDataFrame(i)); err != nil {
			t.Fatalf("sendLive(%d) error = %v", i, err)
		}
	}

	if wire.count() != liveSends {
		t.Errorf("send() calls = %d, want %d — a live send must not also drain", wire.count(), liveSends)
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
//
// Run under commit-on-ack, with an ack after each tick, so the budget is
// pinned in the mode production actually uses.
func TestDataFrameSender_DrainBurstRespectsFrameAndByteBudget(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := uint64(1); i <= 10; i++ {
		if err := sp.Enqueue(fatDataFrame(i, 1000)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	wire := &fakeWire{}
	sender := ackingSender(t, sp, wire)

	if err := sender.drainBurst(4, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if wire.count() != 4 {
		t.Fatalf("sent %d frames, want 4 (frame budget)", wire.count())
	}
	if err := sender.onDataAck(wire.seq); err != nil {
		t.Fatalf("onDataAck() error = %v", err)
	}
	if got := sp.Len(); got != 6 {
		t.Errorf("spool Len() = %d, want 6 after one acknowledged 4-frame burst", got)
	}

	// A byte budget that fits only two ~1KiB frames caps the burst below the
	// frame budget.
	wire.sent = nil
	if err := sender.drainBurst(4, 2500); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if wire.count() != 2 {
		t.Fatalf("sent %d frames, want 2 (byte budget)", wire.count())
	}
	if err := sender.onDataAck(wire.seq); err != nil {
		t.Fatalf("onDataAck() error = %v", err)
	}
	if got := sp.Len(); got != 4 {
		t.Errorf("spool Len() = %d, want 4", got)
	}
	for i, f := range wire.sent {
		if want := uint64(5 + i); f.Seq != want {
			t.Errorf("burst frame %d seq = %d, want %d (FIFO)", i, f.Seq, want)
		}
	}
}

// TestDataFrameSender_DrainBurstCommitsNothingUntilAcked is the headline
// guarantee, at unit scale. It replaces
// TestDataFrameSender_DrainBurstCommitsOnlySuccessesAndKeepsOrder, whose
// premise — commit the ones that reached the wire — was exactly the defect:
// "reached the wire" is not "reached the server", so a connection dying after
// a successful write destroyed the frames it had already discarded.
//
// Now nothing is committed by sending. The burst runs, the connection breaks
// mid-way, and every frame is still in the spool in its original order, the
// failing one included.
func TestDataFrameSender_DrainBurstCommitsNothingUntilAcked(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := 1; i <= 5; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	sendErr := errors.New("boom: connection dead mid-burst")
	wire := &fakeWire{failOn: func(n int) error {
		if n == 3 {
			return sendErr
		}
		return nil
	}}
	sender := ackingSender(t, sp, wire)

	if err := sender.drainBurst(5, spool.DefaultCapBytes); !errors.Is(err, sendErr) {
		t.Fatalf("drainBurst() error = %v, want it to wrap %v", err, sendErr)
	}
	if wire.count() != 2 {
		t.Errorf("send() succeeded %d times, want 2 — the burst must stop at the first failure", wire.count())
	}
	if got := sp.Len(); got != 5 {
		t.Fatalf("spool Len() = %d, want 5 — nothing may be committed without an ack", got)
	}
	remaining := sp.Peek(5, spool.DefaultCapBytes)
	if len(remaining) != 5 {
		t.Fatalf("Peek() returned %d frames, want 5", len(remaining))
	}
	for i, f := range remaining {
		var p struct {
			N int `json:"n"`
		}
		if err := json.Unmarshal(f.Payload, &p); err != nil {
			t.Fatalf("unmarshal remaining payload %s: %v", f.Payload, err)
		}
		if p.N != i+1 {
			t.Errorf("remaining frame %d carried n=%d, want %d — order must be preserved", i, p.N, i+1)
		}
	}
}

// TestDataFrameSender_PartialAckCommitsOnlyThePrefix pins the watermark's
// shape: an ack names the highest sequence number terminally handled, so it
// releases a leading run of the in-flight window and leaves the rest of it
// waiting.
func TestDataFrameSender_PartialAckCommitsOnlyThePrefix(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := 1; i <= 6; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	wire := &fakeWire{}
	sender := ackingSender(t, sp, wire)
	if err := sender.drainBurst(6, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if wire.count() != 6 {
		t.Fatalf("sent %d frames, want 6", wire.count())
	}

	// Seqs 1..6 were assigned in order; ack only the first three.
	if err := sender.onDataAck(3); err != nil {
		t.Fatalf("onDataAck(3) error = %v", err)
	}
	if got := sp.Len(); got != 3 {
		t.Fatalf("spool Len() = %d, want 3 — only the acked prefix may be committed", got)
	}
	if got := len(sender.inflight); got != 3 {
		t.Errorf("in-flight window holds %d frames, want 3", got)
	}
	remaining := sp.Peek(6, spool.DefaultCapBytes)
	for i, f := range remaining {
		var p struct {
			N int `json:"n"`
		}
		if err := json.Unmarshal(f.Payload, &p); err != nil {
			t.Fatalf("unmarshal remaining payload %s: %v", f.Payload, err)
		}
		if want := i + 4; p.N != want {
			t.Errorf("remaining frame %d carried n=%d, want %d", i, p.N, want)
		}
	}

	// A watermark below what has already been released frees nothing rather
	// than double-committing.
	if err := sender.onDataAck(2); err != nil {
		t.Fatalf("onDataAck(2) error = %v", err)
	}
	if got := sp.Len(); got != 3 {
		t.Errorf("spool Len() = %d after a stale watermark, want 3", got)
	}

	if err := sender.onDataAck(6); err != nil {
		t.Fatalf("onDataAck(6) error = %v", err)
	}
	if got := sp.Len(); got != 0 {
		t.Errorf("spool Len() = %d after acking everything, want 0", got)
	}
	if got := len(sender.inflight); got != 0 {
		t.Errorf("in-flight window holds %d frames after a full ack, want 0", got)
	}
}

// TestDataFrameSender_InflightWindowBoundsUnackedFrames verifies the window
// caps what may be on the wire unacknowledged, so a server that reads but
// never acks stops the flow instead of letting the whole spool run away into
// it.
func TestDataFrameSender_InflightWindowBoundsUnackedFrames(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	const backlog = maxInflightFrames + 20
	for i := 1; i <= backlog; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	wire := &fakeWire{}
	sender := ackingSender(t, sp, wire)

	// Drain far more aggressively than production's 4-per-tick so only the
	// window, not the per-tick budget, can be what stops it.
	for i := 0; i < 10; i++ {
		if err := sender.drainBurst(backlog, spool.DefaultCapBytes); err != nil {
			t.Fatalf("drainBurst() error = %v", err)
		}
	}
	if wire.count() != maxInflightFrames {
		t.Fatalf("sent %d frames with nothing acked, want %d (the in-flight window)",
			wire.count(), maxInflightFrames)
	}
	if got := sp.Len(); got != backlog {
		t.Errorf("spool Len() = %d, want %d — an unacked frame is still undelivered", got, backlog)
	}

	// Acking the window reopens it, and the next burst picks up exactly where
	// the last one stopped rather than re-sending from the head.
	if err := sender.onDataAck(uint64(maxInflightFrames)); err != nil {
		t.Fatalf("onDataAck() error = %v", err)
	}
	if err := sender.drainBurst(backlog, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if wire.count() != backlog {
		t.Fatalf("sent %d frames after the window reopened, want %d", wire.count(), backlog)
	}
	order := wire.payloadOrder(t)
	for i, n := range order {
		if n != i+1 {
			t.Fatalf("frame %d carried n=%d, want %d — the window must not re-send or skip", i, n, i+1)
		}
	}
}

// TestDataFrameSender_InflightByteWindowBoundsUnackedFrames is the same bound
// expressed in bytes: 64 unusually fat frames must not put an unbounded
// amount of memory and socket buffer in flight.
func TestDataFrameSender_InflightByteWindowBoundsUnackedFrames(t *testing.T) {
	sp := newTestSpool(t, 32<<20)
	// ~256 KiB each: 16 of them exceed the 4 MiB byte window well before the
	// 64-frame one.
	const fat = 256 << 10
	for i := uint64(1); i <= 40; i++ {
		if err := sp.Enqueue(fatDataFrame(i, fat)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	wire := &fakeWire{}
	sender := ackingSender(t, sp, wire)
	for i := 0; i < 10; i++ {
		if err := sender.drainBurst(40, spool.DefaultCapBytes); err != nil {
			t.Fatalf("drainBurst() error = %v", err)
		}
	}

	if wire.count() >= maxInflightFrames {
		t.Errorf("sent %d frames, want fewer than the %d-frame window — the byte window must bind first",
			wire.count(), maxInflightFrames)
	}
	// The byte window is a threshold, not a hard ceiling: PeekFrom always
	// returns its first frame so an oversized one cannot wedge the queue, so
	// the overshoot is bounded by exactly one frame and no more.
	if limit := maxInflightBytes + int64(fat) + 1024; sender.inflightBytes > limit {
		t.Errorf("in-flight bytes = %d, want <= %d (the cap plus at most one frame)",
			sender.inflightBytes, limit)
	}
	if sender.inflightBytes < maxInflightBytes {
		t.Errorf("in-flight bytes = %d, want the window filled to at least %d before it closed",
			sender.inflightBytes, maxInflightBytes)
	}
	if wire.count() == 0 {
		t.Error("sent no frames at all — the byte window must not wedge the queue")
	}
}

// TestDataFrameSender_AckStallEndsTheConnection verifies a server that keeps
// reading but stops acknowledging is diagnosed as itself rather than left to
// the 60s read deadline, and that the error it raises takes the
// server-is-coming-back reconnect ladder.
func TestDataFrameSender_AckStallEndsTheConnection(t *testing.T) {
	original := ackStallTimeout
	ackStallTimeout = 20 * time.Millisecond
	t.Cleanup(func() { ackStallTimeout = original })

	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := 1; i <= 4; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	wire := &fakeWire{}
	sender := ackingSender(t, sp, wire)

	if err := sender.drainBurst(4, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	if err := sender.drainBurst(4, spool.DefaultCapBytes); err != nil {
		t.Fatalf("second drainBurst() error = %v, want nil before the stall deadline", err)
	}

	time.Sleep(40 * time.Millisecond)
	err := sender.drainBurst(4, spool.DefaultCapBytes)
	if !errors.Is(err, errAckStall) {
		t.Fatalf("drainBurst() error = %v, want it to wrap errAckStall", err)
	}
	if class := classifyFailure(err, true); class != classComingBack {
		t.Errorf("classifyFailure(ack stall) = %v, want %v — a server that answers the socket "+
			"but not the ingest path is up and having a bad minute", class, classComingBack)
	}
	if got := sp.Len(); got != 4 {
		t.Errorf("spool Len() = %d, want 4 — a stall must commit nothing", got)
	}
}

// TestDataFrameSender_AckStallClockRestartsOnRealProgress verifies the stall
// deadline measures "no ack has advanced the watermark", not "the connection
// is old": an ack that actually releases frames restarts the clock, while one
// that releases nothing does not.
func TestDataFrameSender_AckStallClockRestartsOnRealProgress(t *testing.T) {
	original := ackStallTimeout
	ackStallTimeout = 60 * time.Millisecond
	t.Cleanup(func() { ackStallTimeout = original })

	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := 1; i <= 6; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	wire := &fakeWire{}
	sender := ackingSender(t, sp, wire)

	if err := sender.drainBurst(6, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v", err)
	}
	time.Sleep(40 * time.Millisecond)
	if err := sender.onDataAck(3); err != nil {
		t.Fatalf("onDataAck(3) error = %v", err)
	}
	time.Sleep(40 * time.Millisecond)
	// 80ms since the frames went out, but only 40ms since the last real
	// progress — not a stall.
	if err := sender.drainBurst(6, spool.DefaultCapBytes); err != nil {
		t.Fatalf("drainBurst() error = %v, want nil — a partial ack is progress", err)
	}

	time.Sleep(40 * time.Millisecond)
	if err := sender.drainBurst(6, spool.DefaultCapBytes); !errors.Is(err, errAckStall) {
		t.Fatalf("drainBurst() error = %v, want errAckStall once progress actually stopped", err)
	}
}

// TestDataFrameSender_WithoutNegotiatedAckFallsBackToCommitOnWrite covers the
// new-agent-to-old-server direction: a server that never answers `data_ack`
// cannot acknowledge anything, so waiting for an ack would wedge the spool
// forever. The agent instead keeps the pre-acknowledgement behaviour —
// degraded, and logged as such once per connection, but functional.
func TestDataFrameSender_WithoutNegotiatedAckFallsBackToCommitOnWrite(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := uint64(1); i <= 5; i++ {
		if err := sp.Enqueue(fakeDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	sendErr := errors.New("boom: connection dead mid-burst")
	wire := &fakeWire{failOn: func(n int) error {
		if n == 3 {
			return sendErr
		}
		return nil
	}}
	// No negotiateAck call at all — exactly what an old server's hello.ack
	// leaves behind.
	sender := newDataFrameSender(sp, wire.send, nil)

	if err := sender.drainBurst(5, spool.DefaultCapBytes); !errors.Is(err, sendErr) {
		t.Fatalf("drainBurst() error = %v, want it to wrap %v", err, sendErr)
	}
	if got := sp.Len(); got != 3 {
		t.Fatalf("spool Len() = %d, want 3 (only the 2 successes committed)", got)
	}
	remaining := sp.Peek(5, spool.DefaultCapBytes)
	for i, f := range remaining {
		if want := uint64(3 + i); f.Seq != want {
			t.Errorf("remaining frame %d seq = %d, want %d — order must be preserved, failing frame first", i, f.Seq, want)
		}
	}

	// And an ack arriving anyway — a stray frame, or a server that changed
	// its mind — must not commit a second time on a connection that already
	// commits on write.
	if err := sender.onDataAck(5); err != nil {
		t.Fatalf("onDataAck() error = %v", err)
	}
	if got := sp.Len(); got != 3 {
		t.Errorf("spool Len() = %d after an unnegotiated ack, want 3", got)
	}
}

// TestDataFrameSender_HasBacklogAndDrainBurstAreNilSpoolSafe covers the
// normal case for several callers: Uninstall's one-shot connection and this
// package's spool-less tests leave Spool nil, and runOnce's drain ticker
// fires against all of them.
func TestDataFrameSender_HasBacklogAndDrainBurstAreNilSpoolSafe(t *testing.T) {
	sender := newDataFrameSender(nil, func(frame.Frame) (uint64, int64, error) {
		t.Fatal("send() called with no spool configured")
		return 0, 0, nil
	}, nil)
	sender.negotiateAck(true)

	if sender.hasBacklog() {
		t.Error("hasBacklog() = true with a nil spool, want false")
	}
	if err := sender.drainBurst(4, 256<<10); err != nil {
		t.Errorf("drainBurst() with a nil spool error = %v, want nil", err)
	}
	if err := sender.onDataAck(9); err != nil {
		t.Errorf("onDataAck() with a nil spool error = %v, want nil", err)
	}
}

// TestDataFrameSender_CapEviction_ReachableFromSendLive verifies the spool's
// existing cap-eviction logic (spool_test.go's
// TestEnqueue_DropsOldestWhenOverCap) is actually reachable through the live
// send-failure path, not just spool.Enqueue called directly in isolation.
func TestDataFrameSender_CapEviction_ReachableFromSendLive(t *testing.T) {
	const tinyCap = 300
	sp := newTestSpool(t, tinyCap)
	sendErr := errors.New("send always fails")
	wire := &fakeWire{failOn: func(int) error { return sendErr }}
	sender := newDataFrameSender(sp, wire.send, nil)

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
	wire := &fakeWire{failOn: func(int) error { return sendErr }}
	sender := newDataFrameSender(nil, wire.send, nil)

	if err := sender.sendLive(fakeDataFrame(1)); !errors.Is(err, sendErr) {
		t.Fatalf("sendLive() error = %v, want %v", err, sendErr)
	}
}

// TestDataFrameSender_ReportsSpoolStats verifies onSpoolStats fires with the
// spool's post-mutation depth/size after an enqueue (send failure), after a
// drain that puts frames in flight, and after the ack that finally commits
// them — so callers (main.go's status.Writer wiring) see an accurate backlog
// at every step, including the one where the depth deliberately does not move.
func TestDataFrameSender_ReportsSpoolStats(t *testing.T) {
	sp := newTestSpool(t, spool.DefaultCapBytes)
	var reportedDepth []int
	onStats := func(depth int, bytes int64) {
		reportedDepth = append(reportedDepth, depth)
		if bytes < 0 {
			t.Errorf("reported bytes = %d, want >= 0", bytes)
		}
	}
	sendErr := errors.New("boom")
	failing := true
	wire := &fakeWire{failOn: func(int) error {
		if failing {
			return sendErr
		}
		return nil
	}}
	sender := newDataFrameSender(sp, wire.send, onStats)
	sender.negotiateAck(true)

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
	if len(reportedDepth) != 2 || reportedDepth[1] != 1 {
		t.Fatalf("reportedDepth after drain = %v, want [1 1] — an unacked frame is still buffered", reportedDepth)
	}

	if err := sender.onDataAck(wire.seq); err != nil {
		t.Fatalf("onDataAck() error = %v", err)
	}
	if len(reportedDepth) != 3 || reportedDepth[2] != 0 {
		t.Fatalf("reportedDepth after ack = %v, want [1 1 0]", reportedDepth)
	}
}
