// Link-level tests for the update-dispatch boundary: the inbound `update` arm
// is enqueue-only, refusals surface as explicit failed statuses, and the
// UpdateStatusFrames drain arm neither stalls heartbeats nor breaks sequence
// ownership.
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
)

// upgradeAckSendUpdate is the shared fake-server prefix: upgrade, Noise
// handshake, hello, accepted hello.ack, then one `update` instruction. The
// handler's read loop is left to the caller via the returned decrypting
// reader.
//
// Duplicated per the package's established test style (see
// testResponderSession's doc comment): each test owns its harness.
func sendUpdateInstruction(t *testing.T, srvPriv, srvPub [32]byte, version string) (*httptest.Server, *testResponderSession) {
	t.Helper()
	upgrader := websocket.Upgrader{}
	var responder *testResponderSession
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		resp := newTestResponderSession(t, srvPriv, srvPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := resp.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		// The hello must be decrypted, not merely read — the responder's
		// receive cipher carries a nonce counter, and skipping one message
		// desynchronizes it (see the probe heartbeat test).
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := resp.Decrypt(helloCt); err != nil {
			return
		}
		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ack))

		instr, _ := json.Marshal(map[string]any{
			"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]string{"version": version, "sha256": "abc123", "arch": "amd64", "os": "linux"},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(instr))

		responder = resp
	}))
	t.Cleanup(srv.Close)
	return srv, responder
}

// The wire contract: an instruction the enqueue boundary refuses — queue full,
// worker stopping, malformed payload — must reach the server as an explicit
// update.status(failed) carrying the instruction's own version and the refusal
// reason. A silent drop leaves the server waiting on a status that never
// arrives, which is what this test forbids.
func TestRun_RefusedUpdateInstructionReportsExplicitFailedStatus(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

	var mu atomicStatusList
	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		resp := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := resp.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := resp.Decrypt(helloCt); err != nil {
			return
		}
		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ack))
		instr, _ := json.Marshal(map[string]any{
			"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]string{"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(instr))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := resp.Decrypt(ct)
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
			if f.Type == "update.status" {
				var st statusEntry
				if err := json.Unmarshal(f.Payload, &st); err != nil {
					return
				}
				mu.add(st.Version, st.Phase, st.Error)
			}
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnUpdate: func(json.RawMessage) error {
			// The daemon's queue-full refusal, verbatim: the message is the
			// whole contract, and the wire format pins its wording.
			return errors.New("update already in progress")
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	got := mu.snapshot()
	if len(got) != 1 {
		t.Fatalf("observed %d update.status frames, want exactly 1: %+v", len(got), got)
	}
	want := statusEntry{"0.2.0", "failed", "update already in progress"}
	if got[0] != want {
		t.Errorf("refusal status = %+v, want %+v — the refused instruction must be reported, not dropped", got[0], want)
	}
}

// Heartbeats keep leaving on schedule while update statuses drain, and every
// frame the server observes — heartbeat or update.status — carries a strictly
// increasing sequence number. That monotonicity is the single-writer proof: the
// drain arm runs on the same event-loop goroutine that stamps seq for
// heartbeats, so a second writer touching the socket directly would show up
// here as a duplicate or a gap.
func TestRun_UpdateStatusFramesDrainWithoutStallingHeartbeatsOrSequenceOrder(t *testing.T) {
	originalInterval := heartbeatInterval
	heartbeatInterval = 100 * time.Millisecond
	defer func() { heartbeatInterval = originalInterval }()

	serverPriv, serverPub := generateTestKeypair(t)

	type observedFrame struct {
		Type string
		Seq  uint64
	}
	var (
		beatMu  sync.Mutex
		frames  []observedFrame
		statusN atomic.Int32
	)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		resp := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := resp.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := resp.Decrypt(helloCt); err != nil {
			return
		}
		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ack))
		instr, _ := json.Marshal(map[string]any{
			"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]string{"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(instr))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := resp.Decrypt(ct)
			if err != nil {
				return
			}
			var f struct {
				Type string `json:"type"`
				Seq  uint64 `json:"seq"`
			}
			if err := json.Unmarshal(pt, &f); err != nil {
				return
			}
			beatMu.Lock()
			frames = append(frames, observedFrame{Type: f.Type, Seq: f.Seq})
			beatMu.Unlock()
			if f.Type == "update.status" {
				statusN.Add(1)
			}
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	// The worker's side of the contract, driven hard: a burst of status
	// events from a goroutine the link does not know about, paced so the
	// drain arm and the heartbeat ticker must interleave for 2s.
	const events = 40
	statusC := make(chan UpdateStatusEvent, 4)
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnUpdate:           func(json.RawMessage) error { return nil },
		UpdateStatusFrames: statusC,
	}
	go func() {
		for i := 0; i < events; i++ {
			select {
			case statusC <- UpdateStatusEvent{Version: "0.2.0", Phase: "started"}:
			default:
				// Never expected — the drain arm keeps pace — but a worker
				// must not block the test on a full buffer either.
			}
			time.Sleep(25 * time.Millisecond)
		}
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	beatMu.Lock()
	observed := append([]observedFrame(nil), frames...)
	beatMu.Unlock()

	var heartbeats, statuses int
	lastSeq := uint64(0)
	for _, f := range observed {
		if f.Seq <= lastSeq {
			t.Fatalf("frame %q seq %d followed seq %d — sequence numbers regressed, which is the two-writer signature", f.Type, f.Seq, lastSeq)
		}
		lastSeq = f.Seq
		switch f.Type {
		case "heartbeat":
			heartbeats++
		case "update.status":
			statuses++
		}
	}
	if statuses < events {
		t.Errorf("observed %d of %d status frames — the drain arm is losing events", statuses, events)
	}
	if heartbeats < 3 {
		t.Errorf("saw %d heartbeats in 2s at a %s interval — the status drain stalled the connection loop", heartbeats, heartbeatInterval)
	}
}

// TestRunOnce_ReadDeadlineFiresAfterUpdateEnqueued pins the
// disconnect-while-updating half of the contract: after the TypeUpdate arm has
// handed the instruction off (enqueue-only, returns immediately), a silent peer
// must still trip the steady-state read deadline. An update body that occupied
// the event loop instead would starve this path.
func TestRunOnce_ReadDeadlineFiresAfterUpdateEnqueued(t *testing.T) {
	shrinkReadTimeout(t, 400*time.Millisecond)

	serverPriv, serverPub := generateTestKeypair(t)
	var updateCalls atomic.Int32
	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		resp := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := resp.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := resp.Decrypt(helloCt); err != nil {
			return
		}
		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ack))
		instr, _ := json.Marshal(map[string]any{
			"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]string{"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(instr))

		// Drain agent writes forever; send nothing more — black-hole silence.
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	opts := Options{
		Config:            &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:               key,
		AgentVersion:      "0.1.0-test",
		OnConnected:       func() {},
		OnRejected:        func(string) {},
		OnCapabilitiesSet: func(json.RawMessage) error { return nil },
		OnUpdate: func(json.RawMessage) error {
			updateCalls.Add(1)
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	start := time.Now()
	_, err = runOnce(ctx, opts)
	elapsed := time.Since(start)

	if updateCalls.Load() != 1 {
		t.Fatalf("OnUpdate called %d time(s), want 1 — the instruction must have been enqueued before silence", updateCalls.Load())
	}
	if !errors.Is(err, errReadTimeout) {
		t.Fatalf("runOnce err = %v, want it to wrap errReadTimeout after the update was enqueued", err)
	}
	if errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("runOnce hung until the context expired — the read deadline never fired after the update")
	}
	if elapsed > 3*time.Second {
		t.Errorf("runOnce took %s to notice a silent peer after enqueue, want ~%s", elapsed, readTimeout)
	}
}

// TestRun_ReconnectDoesNotReplayUpdateInstruction covers the reconnect rule
// from the link side: a drop after the instruction was enqueued must not cause
// the agent to invent a second OnUpdate call. The server owns re-issue; the
// agent only acts on frames it actually receives.
func TestRun_ReconnectDoesNotReplayUpdateInstruction(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	var (
		connections atomic.Int32
		updateCalls atomic.Int32
		secondReady = make(chan struct{})
		secondOnce  sync.Once
	)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		n := connections.Add(1)
		resp := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := resp.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := resp.Decrypt(helloCt); err != nil {
			return
		}
		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ack))

		if n == 1 {
			instr, _ := json.Marshal(map[string]any{
				"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
				"payload": map[string]string{"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"},
			})
			conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(instr))
			// Give the agent a moment to enqueue, then drop the link.
			time.Sleep(100 * time.Millisecond)
			conn.Close()
			return
		}

		secondOnce.Do(func() { close(secondReady) })
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnUpdate: func(json.RawMessage) error {
			updateCalls.Add(1)
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = Run(ctx, opts)
	}()

	select {
	case <-secondReady:
	case <-time.After(3 * time.Second):
		t.Fatal("agent never reconnected after the first connection dropped")
	}
	// Hold the second connection open briefly so a spurious re-dispatch
	// would have time to fire OnUpdate again.
	time.Sleep(500 * time.Millisecond)
	cancel()
	<-done

	if updateCalls.Load() != 1 {
		t.Errorf("OnUpdate called %d time(s), want 1 — reconnect must not invent a second update for the same instruction", updateCalls.Load())
	}
}
