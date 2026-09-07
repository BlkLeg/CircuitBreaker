// apps/agent/internal/link/link_dataack_test.go
package link

import (
	"bytes"
	"encoding/json"
	"errors"
	"log"
	"strings"
	"sync"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// This file covers the delivery guarantee end to end — a real Noise
// handshake, real encrypted frames, the real Run loop — rather than at the
// dataFrameSender level outbound_test.go pins. The distinction matters here
// more than usual: the defect being fixed was not in the sender's arithmetic
// but in what the *wiring* believed a successful socket write meant, and only
// a test that drives the wiring can prove that belief changed.

// TestHelloAsksForAcknowledgedDelivery pins the agent half of the
// negotiation. A current agent always asks; whether it gets it is the
// server's answer, tested below.
func TestHelloAsksForAcknowledgedDelivery(t *testing.T) {
	freezeDrain(t)

	srv := newSpoolTestServerMode(t, 0, ackNegotiatedLive)
	connected, stop := srv.runAgainst(t, nil)
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("agent never reached an accepted session")
	}

	raw := srv.helloPayload()
	if raw == nil {
		t.Fatal("server recorded no hello payload")
	}
	var hello frame.HelloPayload
	if err := json.Unmarshal(raw, &hello); err != nil {
		t.Fatalf("unmarshal hello payload %s: %v", raw, err)
	}
	if !hello.AckData {
		t.Errorf("hello ack_data = false, want true (payload was %s)", raw)
	}
	if !srv.helloAskedForAck() {
		t.Error("the server did not see ack_data on the hello")
	}
}

// TestRun_SpoolHeadDoesNotAdvanceWithoutAnAck is the headline regression, and
// the one the whole phase exists for.
//
// The server here negotiates acknowledged delivery and then acknowledges
// nothing — the shape of a restart mid-drain, or of a black-holed socket in
// the up-to-60s window before the read deadline notices. Every frame reaches
// the wire and `conn.WriteMessage` returns nil for every one of them.
//
// Under the old commit-on-write drain that was enough to destroy them: the
// spool head advanced and the frames were gone. Now the connection dies with
// the entire backlog still on disk, in its original order, ready to be
// re-sent.
func TestRun_SpoolHeadDoesNotAdvanceWithoutAnAck(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()

	srv := newSpoolTestServerMode(t, 0, ackNegotiatedNever)
	sp := newTestSpool(t, spool.DefaultCapBytes)
	const backlog = 8
	for i := 1; i <= backlog; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	connected, stop := srv.runAgainst(t, sp)
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		stop()
		t.Fatal("never connected")
	}

	waitFor(t, 10*time.Second, "every frame to reach the wire", func() bool {
		return srv.countOfType(fakeDataFrameType) >= backlog
	})
	// Kill the link with everything still unacknowledged.
	stop()

	if got := sp.Len(); got != backlog {
		t.Fatalf("spool Len() = %d after %d frames reached the wire unacknowledged, want %d — "+
			"a write the server never confirmed must not be treated as delivery", got, backlog, backlog)
	}
	remaining := sp.Peek(backlog, spool.DefaultCapBytes)
	if len(remaining) != backlog {
		t.Fatalf("Peek() returned %d frames, want %d", len(remaining), backlog)
	}
	for i, f := range remaining {
		var p struct {
			N int `json:"n"`
		}
		if err := json.Unmarshal(f.Payload, &p); err != nil {
			t.Fatalf("unmarshal remaining payload %s: %v", f.Payload, err)
		}
		if p.N != i+1 {
			t.Errorf("surviving frame %d carried n=%d, want %d — order must be preserved for the resend",
				i, p.N, i+1)
		}
	}
	if srv.acksSent() != 0 {
		t.Errorf("the fake server sent %d acks, want 0 — the fixture is not testing what it claims",
			srv.acksSent())
	}
}

// TestRun_AcknowledgedFramesLeaveTheSpool is the other half: against a server
// that does acknowledge, the backlog drains completely and in order, so the
// durability fix does not simply wedge the queue.
func TestRun_AcknowledgedFramesLeaveTheSpool(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()

	srv := newSpoolTestServerMode(t, 0, ackNegotiatedLive)
	sp := newTestSpool(t, spool.DefaultCapBytes)
	const backlog = 120 // one hour of 30s-cadence samples
	for i := 1; i <= backlog; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	connected, stop := srv.runAgainst(t, sp)
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("never connected")
	}

	waitFor(t, 15*time.Second, "the whole acknowledged backlog to drain", func() bool {
		return sp.Len() == 0
	})

	got := srv.dataPayloadOrder(t)
	if len(got) < backlog {
		t.Fatalf("server saw %d data frames, want at least %d", len(got), backlog)
	}
	for i := 0; i < backlog; i++ {
		if got[i] != i+1 {
			t.Fatalf("data frame %d carried n=%d, want %d — catch-up must stay FIFO", i, got[i], i+1)
		}
	}
	if srv.acksSent() == 0 {
		t.Error("the server sent no acks — the drain cannot have been ack-driven")
	}
}

// TestRun_DataFramesAreSpooledBeforeTheyAreSent is the direct regression for
// the black-holed `sendLive`.
//
// A frame produced while the link is up used to be handed straight to the
// socket and never written to disk at all, so a socket that accepted bytes
// the server never read destroyed the observation with nothing left to
// re-send. Now every data frame is fsync'd first and is only discarded when
// the server acknowledges it — so with a server that reads but never
// acknowledges, a live-produced frame reaches the wire *and* is still on
// disk afterwards.
func TestRun_DataFramesAreSpooledBeforeTheyAreSent(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()

	srv := newSpoolTestServerMode(t, 0, ackNegotiatedNever)
	sp := newTestSpool(t, spool.DefaultCapBytes)

	dataFrames := make(chan frame.Frame, 4)
	connected, stop := srv.runAgainstWithProducer(t, sp, dataFrames)
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		stop()
		t.Fatal("never connected")
	}

	// Produced while the link is live and healthy — the exact case the old
	// routing goroutine sent straight past the disk.
	dataFrames <- numberedDataFrame(1)

	waitFor(t, 10*time.Second, "the live frame to reach the wire", func() bool {
		return srv.countOfType(fakeDataFrameType) >= 1
	})
	if got := sp.Len(); got != 1 {
		t.Fatalf("spool Len() = %d while the frame is in flight, want 1 — a live frame must be "+
			"durable before it can touch a network", got)
	}
	stop()
	if got := sp.Len(); got != 1 {
		t.Errorf("spool Len() = %d after the link died, want 1 — the observation was lost", got)
	}
}

// TestRun_AckStallEndsTheConnection covers the diagnosis: a server that keeps
// the socket alive — its pings keep refreshing the agent's 60s read deadline
// — but stops acknowledging is a fault in the server, and the agent must say
// so and reconnect rather than sitting on a connection that is delivering
// nothing.
func TestRun_AckStallEndsTheConnection(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()
	originalStall := ackStallTimeout
	ackStallTimeout = 200 * time.Millisecond
	defer func() { ackStallTimeout = originalStall }()

	srv := newSpoolTestServerMode(t, 0, ackNegotiatedNever)
	sp := newTestSpool(t, spool.DefaultCapBytes)
	for i := 1; i <= 4; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	causes := make(chan error, 4)
	connected, stop := srv.runAgainstReporting(t, sp, nil, func(cause error) {
		select {
		case causes <- cause:
		default:
		}
	})
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("never connected")
	}

	select {
	case cause := <-causes:
		if !errors.Is(cause, errAckStall) {
			t.Fatalf("disconnect cause = %v, want it to wrap errAckStall", cause)
		}
		if class := classifyFailure(cause, true); class != classComingBack {
			t.Errorf("classifyFailure(%v) = %v, want %v", cause, class, classComingBack)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the connection survived a stalled ack indefinitely — nothing was being delivered")
	}

	if got := sp.Len(); got != 4 {
		t.Errorf("spool Len() = %d after an ack stall, want 4 — a stall must commit nothing", got)
	}
}

// TestRun_OldServerFallsBackToCommitOnWriteAndSaysSo is the new-agent-to-
// old-server direction. The server never answers `data_ack`, so waiting for
// an acknowledgement would wedge the backlog forever; the agent keeps the old
// behaviour and logs, once per connection, what is at risk — in words about
// the data rather than about a protocol flag.
func TestRun_OldServerFallsBackToCommitOnWriteAndSaysSo(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()

	logs := &syncBuffer{}
	originalOut := log.Writer()
	originalFlags := log.Flags()
	log.SetOutput(logs)
	log.SetFlags(0)
	defer func() {
		log.SetOutput(originalOut)
		log.SetFlags(originalFlags)
	}()

	srv := newSpoolTestServerMode(t, 0, ackUnsupported)
	sp := newTestSpool(t, spool.DefaultCapBytes)
	const backlog = 12
	for i := 1; i <= backlog; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	connected, stop := srv.runAgainst(t, sp)
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("never connected")
	}

	waitFor(t, 10*time.Second, "the backlog to drain against a server that cannot ack", func() bool {
		return sp.Len() == 0
	})
	if srv.acksSent() != 0 {
		t.Errorf("an old server sent %d acks, want 0", srv.acksSent())
	}

	// Once per connection, not once per frame: the whole point of logging it
	// at negotiation time rather than at drain time.
	const marker = "this server does not acknowledge data frames"
	if n := strings.Count(logs.String(), marker); n != 1 {
		t.Errorf("the degraded-delivery warning appeared %d times, want exactly 1\n%s", n, logs.String())
	}
	if !strings.Contains(logs.String(), "is lost") {
		t.Error("the degraded-delivery warning does not say what is at risk")
	}
}

// syncBuffer is a bytes.Buffer safe to write from the goroutines `log` is
// called on while a test reads it.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}
