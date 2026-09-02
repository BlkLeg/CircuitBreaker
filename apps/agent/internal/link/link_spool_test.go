// apps/agent/internal/link/link_spool_test.go
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// TestRun_DataFramesFlowThroughLiveConnectionWithoutSpooling drives a full
// Run() connection — real Noise handshake, real encrypted WS frames — and
// pushes fake data frames (fakeDataFrameType — no real Slice 1 data frame
// type exists to test with) through Options.DataFrames while heartbeats keep
// ticking on their own schedule. It verifies, through the actually-wired
// path (not just a direct dataFrameSender call):
//   - live data frames reach the server over the connection;
//   - the spool stays empty throughout, since every send here succeeds —
//     spooling is a send-failure fallback, not a parallel duplicate path;
//   - heartbeat frames flow independently and never touch the spool either.
func TestRun_DataFramesFlowThroughLiveConnectionWithoutSpooling(t *testing.T) {
	originalInterval := heartbeatInterval
	heartbeatInterval = 100 * time.Millisecond
	defer func() { heartbeatInterval = originalInterval }()

	serverPriv, serverPub := generateTestKeypair(t)

	var mu sync.Mutex
	var dataFramesSeen, heartbeatsSeen int

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Fatalf("upgrade: %v", err)
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			t.Errorf("responder handshake: %v", err)
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("expected a hello frame after handshake: %v", err)
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := responder.Decrypt(ct)
			if err != nil {
				return
			}
			var f map[string]any
			json.Unmarshal(pt, &f)
			mu.Lock()
			switch f["type"] {
			case fakeDataFrameType:
				dataFramesSeen++
			case "heartbeat":
				heartbeatsSeen++
			}
			mu.Unlock()
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}

	dataFrames := make(chan frame.Frame, 8)
	var connected sync.WaitGroup
	connected.Add(1)
	var onConnectedOnce sync.Once

	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		Spool:      sp,
		DataFrames: dataFrames,
		OnConnected: func() {
			onConnectedOnce.Do(connected.Done)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()

	connected.Wait()
	for i := 0; i < 5; i++ {
		dataFrames <- frame.Frame{Type: fakeDataFrameType, Payload: json.RawMessage(`{}`)}
	}

	// Give the connection time to carry both the data frames and at least
	// one heartbeat tick before tearing down.
	time.Sleep(500 * time.Millisecond)
	cancel()
	<-done

	mu.Lock()
	defer mu.Unlock()
	if dataFramesSeen != 5 {
		t.Errorf("server saw %d data frames, want 5", dataFramesSeen)
	}
	if heartbeatsSeen == 0 {
		t.Error("server saw no heartbeat frames — heartbeat ticker should keep running independently")
	}
	if got := sp.Len(); got != 0 {
		t.Errorf("spool Len() = %d, want 0 — no send failed, so nothing should have been spooled", got)
	}
}

// recordedFrame is one frame the fake backend decrypted, with the moment it
// arrived — which is what lets a test assert *ordering against the
// hello.ack*, not merely that something eventually showed up.
type recordedFrame struct {
	typ     string
	payload json.RawMessage
	at      time.Time
}

// spoolTestServer is the catch-up harness: a real Noise responder over
// httptest that reads continuously from the moment the handshake completes
// (so arrival timestamps are meaningful rather than an artifact of when the
// server got round to reading), records every frame, and can delay the
// hello.ack to open a window in which a correctly-gated agent must send
// nothing.
type spoolTestServer struct {
	url       string
	serverPub [32]byte

	mu     sync.Mutex
	ackAt  time.Time
	frames []recordedFrame
	// hello is the raw `hello` payload this connection opened with. It is
	// captured separately from `frames` because the hello is read inline,
	// before the recording goroutine starts (that goroutine exists so
	// arrival *times* are meaningful, which the hello does not need).
	hello json.RawMessage
}

func newSpoolTestServer(t *testing.T, ackDelay time.Duration) *spoolTestServer {
	t.Helper()
	serverPriv, serverPub := generateTestKeypair(t)
	s := &spoolTestServer{}

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		helloPT, err := responder.Decrypt(helloCt)
		if err != nil {
			return
		}
		var helloFrame struct {
			Payload json.RawMessage `json:"payload"`
		}
		if err := json.Unmarshal(helloPT, &helloFrame); err == nil {
			s.mu.Lock()
			s.hello = helloFrame.Payload
			s.mu.Unlock()
		}

		// Read continuously from here on, on its own goroutine, so anything
		// the agent sends during the ack delay is timestamped when it
		// actually arrives. Only this goroutine reads; only the handler
		// goroutine writes.
		done := make(chan struct{})
		go func() {
			defer close(done)
			for {
				_, ct, err := conn.ReadMessage()
				if err != nil {
					return
				}
				pt, err := responder.Decrypt(ct)
				if err != nil {
					return
				}
				var f struct {
					Type    string          `json:"type"`
					Payload json.RawMessage `json:"payload"`
				}
				if err := json.Unmarshal(pt, &f); err != nil {
					return
				}
				s.mu.Lock()
				s.frames = append(s.frames, recordedFrame{typ: f.Type, payload: f.Payload, at: time.Now()})
				s.mu.Unlock()
			}
		}()

		if ackDelay > 0 {
			select {
			case <-time.After(ackDelay):
			case <-done:
				return
			}
		}
		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		}
		ackBytes, _ := json.Marshal(ack)
		s.mu.Lock()
		s.ackAt = time.Now()
		s.mu.Unlock()
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		<-done
	}))
	t.Cleanup(srv.Close)
	s.url = "ws" + strings.TrimPrefix(srv.URL, "http")
	s.serverPub = serverPub
	return s
}

// dataPayloadOrder returns the "n" field of every fake data frame the server
// saw, in arrival order.
func (s *spoolTestServer) dataPayloadOrder(t *testing.T) []int {
	t.Helper()
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []int
	for _, f := range s.frames {
		if f.typ != fakeDataFrameType {
			continue
		}
		var p struct {
			N int `json:"n"`
		}
		if err := json.Unmarshal(f.payload, &p); err != nil {
			t.Fatalf("unmarshal data frame payload %s: %v", f.payload, err)
		}
		out = append(out, p.N)
	}
	return out
}

// helloPayload returns the raw `hello` payload the agent opened with, or nil
// if no hello has been read yet.
func (s *spoolTestServer) helloPayload() json.RawMessage {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.hello
}

// payloadsOfType returns every recorded payload of the given frame type, in
// arrival order.
func (s *spoolTestServer) payloadsOfType(typ string) []json.RawMessage {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []json.RawMessage
	for _, f := range s.frames {
		if f.typ == typ {
			out = append(out, f.payload)
		}
	}
	return out
}

func (s *spoolTestServer) countOfType(typ string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	var n int
	for _, f := range s.frames {
		if f.typ == typ {
			n++
		}
	}
	return n
}

// dataFramesBeforeAck counts fake data frames that arrived before the
// hello.ack was written (all of them, if no ack was ever sent).
func (s *spoolTestServer) dataFramesBeforeAck() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	var n int
	for _, f := range s.frames {
		if f.typ != fakeDataFrameType {
			continue
		}
		if s.ackAt.IsZero() || f.at.Before(s.ackAt) {
			n++
		}
	}
	return n
}

// numberedDataFrame carries its ordinal in the payload, because runOnce
// re-stamps Seq on every frame it sends (spooled frames included), so the
// payload is the only thing that survives to prove FIFO order end to end.
func numberedDataFrame(n int) frame.Frame {
	return frame.Frame{
		V: frame.FrameVersion, Type: fakeDataFrameType, Seq: uint64(n),
		TS: time.Now().UTC(), Payload: json.RawMessage(`{"n":` + strconv.Itoa(n) + `}`),
	}
}

// runAgainst starts Run against s with the given spool and returns a stop
// func. There is deliberately no DataFrames producer: catch-up must not
// depend on live traffic.
func (s *spoolTestServer) runAgainst(t *testing.T, sp *spool.Spool) (connected <-chan struct{}, stop func()) {
	t.Helper()
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	connectedCh := make(chan struct{})
	var once sync.Once
	opts := Options{
		Config:       &config.Config{ServerURL: s.url, ServerStaticPK: hex.EncodeToString(s.serverPub[:])},
		Key:          key,
		AgentVersion: "0.1.0-test",
		Spool:        sp,
		OnConnected:  func() { once.Do(func() { close(connectedCh) }) },
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()
	return connectedCh, func() {
		cancel()
		<-done
	}
}

func waitFor(t *testing.T, budget time.Duration, desc string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(budget)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(2 * time.Millisecond)
	}
	t.Fatalf("timed out after %s waiting for %s", budget, desc)
}

// TestRun_CatchUpDrainsBacklogWithinBound is the core of D-5: a backlog
// accumulated during an outage drains on its own, paced, with *no live
// production at all*. Under the old 1:4 interleave this hung forever — a
// drain only happened as a side effect of a successful live send, so a
// disabled or failing collector meant the backlog sat until cap eviction
// discarded it.
func TestRun_CatchUpDrainsBacklogWithinBound(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()

	srv := newSpoolTestServer(t, 0)
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	const backlog = 120 // one hour of 30s-cadence samples
	for i := 0; i < backlog; i++ {
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

	waitFor(t, 10*time.Second, "the whole backlog to drain", func() bool {
		return srv.countOfType(fakeDataFrameType) >= backlog
	})

	got := srv.dataPayloadOrder(t)
	if len(got) != backlog {
		t.Fatalf("server saw %d data frames, want exactly %d", len(got), backlog)
	}
	for i, n := range got {
		if n != i {
			t.Fatalf("data frame %d carried n=%d, want %d — catch-up must stay FIFO", i, n, i)
		}
	}
	if depth := sp.Len(); depth != 0 {
		t.Errorf("spool Len() = %d, want 0 — every sent frame must be committed", depth)
	}
}

// TestRun_DrainNeverStartsBeforeHelloAck guards the connectedFired condition
// on the new drain arm: the server has not accepted this session yet, so
// nothing may be committed against it.
func TestRun_DrainNeverStartsBeforeHelloAck(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 5 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()

	const ackDelay = 300 * time.Millisecond // ~60 drain ticks
	srv := newSpoolTestServer(t, ackDelay)
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	const backlog = 40
	for i := 0; i < backlog; i++ {
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

	waitFor(t, 10*time.Second, "the backlog to drain after the ack", func() bool {
		return srv.countOfType(fakeDataFrameType) >= backlog
	})
	if early := srv.dataFramesBeforeAck(); early != 0 {
		t.Errorf("%d data frames arrived before hello.ack, want 0 — drain must wait for an accepted session", early)
	}
}

// TestRunOnce_DrainTickerIsInertWithoutASpool covers the shape of every
// link.Options in this package except the ones above: no spool at all. The
// drain ticker still fires on every connection, so without nil guards on
// hasBacklog/drainBurst this panics on the first tick.
func TestRunOnce_DrainTickerIsInertWithoutASpool(t *testing.T) {
	originalTick := drainTickInterval
	drainTickInterval = 2 * time.Millisecond
	defer func() { drainTickInterval = originalTick }()
	originalHeartbeat := heartbeatInterval
	heartbeatInterval = 50 * time.Millisecond
	defer func() { heartbeatInterval = originalHeartbeat }()

	srv := newSpoolTestServer(t, 0)
	connected, stop := srv.runAgainst(t, nil) // Options.Spool left nil
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("never connected")
	}

	// Heartbeats prove the connection survived a few hundred drain ticks
	// rather than dying (or panicking) on the first one.
	waitFor(t, 5*time.Second, "heartbeats to keep flowing across many drain ticks", func() bool {
		return srv.countOfType(frame.TypeHeartbeat) >= 3
	})
	if got := srv.countOfType(fakeDataFrameType); got != 0 {
		t.Errorf("server saw %d data frames with no spool configured, want 0", got)
	}
}

// freezeDrain stops the paced catch-up burst for the duration of a test by
// pushing drainTickInterval out of reach. The spool-state reporting tests
// below care about what the *link* says the depth is, so the backlog has to
// hold still while they look at it.
func freezeDrain(t *testing.T) {
	t.Helper()
	original := drainTickInterval
	drainTickInterval = time.Hour
	t.Cleanup(func() { drainTickInterval = original })
}

// TestHelloCarriesSpoolDepthAtConnect pins the at-connect half of D-12: the
// `hello` frame reports how many frames were still spooled when the
// connection came up. internal/hostinfo stays spool-agnostic (the spool is
// owned by the link, not by host collection), so internal/link is what
// stamps HelloPayload.SpoolDepth from Options.Spool.
func TestHelloCarriesSpoolDepthAtConnect(t *testing.T) {
	freezeDrain(t)

	srv := newSpoolTestServer(t, 0)
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	for i := 0; i < 2; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	connected, stop := srv.runAgainst(t, sp)
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
	if hello.SpoolDepth != 2 {
		t.Errorf("hello spool_depth = %d, want 2 (payload was %s)", hello.SpoolDepth, raw)
	}
}

// TestHeartbeatCarriesSpoolStats pins the live half of D-12: every heartbeat
// carries the current spool depth and size, which is what lets the Agent
// Detail catch-up indicator both appear *and* clear while a single
// connection stays up. The payload used to be a hardcoded `{}`.
func TestHeartbeatCarriesSpoolStats(t *testing.T) {
	freezeDrain(t)
	originalHeartbeat := heartbeatInterval
	heartbeatInterval = 25 * time.Millisecond
	defer func() { heartbeatInterval = originalHeartbeat }()

	srv := newSpoolTestServer(t, 0)
	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	for i := 0; i < 2; i++ {
		if err := sp.Enqueue(numberedDataFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	wantBytes, err := sp.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if wantBytes <= 0 {
		t.Fatalf("SizeBytes() = %d, want > 0 — the fixture must have real bytes on disk", wantBytes)
	}

	connected, stop := srv.runAgainst(t, sp)
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("agent never reached an accepted session")
	}
	waitFor(t, 5*time.Second, "a heartbeat frame", func() bool {
		return srv.countOfType(frame.TypeHeartbeat) > 0
	})

	payloads := srv.payloadsOfType(frame.TypeHeartbeat)
	var hb frame.HeartbeatPayload
	if err := json.Unmarshal(payloads[0], &hb); err != nil {
		t.Fatalf("unmarshal heartbeat payload %s: %v", payloads[0], err)
	}
	if hb.SpoolDepth != 2 {
		t.Errorf("heartbeat spool_depth = %d, want 2 (payload was %s)", hb.SpoolDepth, payloads[0])
	}
	if hb.SpoolBytes != wantBytes {
		t.Errorf("heartbeat spool_bytes = %d, want %d (payload was %s)", hb.SpoolBytes, wantBytes, payloads[0])
	}

	// The wire bytes themselves must carry both keys explicitly, even at
	// zero — D-12: an empty `{}` heartbeat is reserved to mean "this agent
	// predates spool reporting", which is what lets the backend keep its
	// columns NULL for such an agent instead of writing a fake 0.
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(payloads[0], &keys); err != nil {
		t.Fatalf("unmarshal heartbeat payload as a map: %v", err)
	}
	for _, key := range []string{"spool_depth", "spool_bytes"} {
		if _, ok := keys[key]; !ok {
			t.Errorf("heartbeat payload %s is missing %q — the field must not carry omitempty", payloads[0], key)
		}
	}
}

// TestHeartbeatReportsAnEmptySpoolAsExplicitZeros is the other half of the
// no-omitempty rule: a connection with no spool at all still emits both
// keys as 0, so the backend can tell "empty" from "not reported".
func TestHeartbeatReportsAnEmptySpoolAsExplicitZeros(t *testing.T) {
	originalHeartbeat := heartbeatInterval
	heartbeatInterval = 25 * time.Millisecond
	defer func() { heartbeatInterval = originalHeartbeat }()

	srv := newSpoolTestServer(t, 0)
	connected, stop := srv.runAgainst(t, nil) // Options.Spool left nil
	defer stop()
	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("agent never reached an accepted session")
	}
	waitFor(t, 5*time.Second, "a heartbeat frame", func() bool {
		return srv.countOfType(frame.TypeHeartbeat) > 0
	})

	// Asserted on the raw JSON rather than the decoded struct: the property
	// under test is that the zeros are *present on the wire*, which a decode
	// would supply from the zero value whether they were sent or not. Both
	// keys are checked individually so an additive field elsewhere in the
	// payload does not fail a test that is not about it.
	payload := string(srv.payloadsOfType(frame.TypeHeartbeat)[0])
	for _, want := range []string{`"spool_depth":0`, `"spool_bytes":0`} {
		if !strings.Contains(payload, want) {
			t.Errorf("heartbeat payload = %s, want it to contain %s", payload, want)
		}
	}
}
