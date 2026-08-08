package link

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/flynn/noise"
	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/noiseconn"
)

// statusEntry/atomicStatusList capture update.status frames a fake test
// server observes, guarded by a mutex since the server's read loop runs on
// its own goroutine concurrently with whatever the test does after Run
// returns.
type statusEntry struct {
	Version, Phase, Error string
}

type atomicStatusList struct {
	mu      sync.Mutex
	entries []statusEntry
}

func (l *atomicStatusList) add(version, phase, errMsg string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.entries = append(l.entries, statusEntry{version, phase, errMsg})
}

func (l *atomicStatusList) snapshot() []statusEntry {
	l.mu.Lock()
	defer l.mu.Unlock()
	out := make([]statusEntry, len(l.entries))
	copy(out, l.entries)
	return out
}

// generateTestKeypair mirrors noiseconn_test.go's generateKeypair.
func generateTestKeypair(t *testing.T) (priv, pub [32]byte) {
	t.Helper()
	dhKey, err := noise.DH25519.GenerateKeypair(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKeypair() error = %v", err)
	}
	copy(priv[:], dhKey.Private)
	copy(pub[:], dhKey.Public)
	return priv, pub
}

// testResponderSession mirrors enroll_test.go's helper of the same name —
// duplicated per Task 11's plan note since this codebase has no shared Go
// test-utility package yet.
type testResponderSession struct {
	hs   *noise.HandshakeState
	send *noise.CipherState // c2: responder -> initiator
	recv *noise.CipherState // c1: initiator -> responder
}

func newTestResponderSession(t *testing.T, priv, pub [32]byte) *testResponderSession {
	t.Helper()
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	hs, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:   cs,
		Pattern:       noise.HandshakeIK,
		Initiator:     false,
		StaticKeypair: noise.DHKey{Private: priv[:], Public: pub[:]},
	})
	if err != nil {
		t.Fatalf("NewHandshakeState() error = %v", err)
	}
	return &testResponderSession{hs: hs}
}

func (s *testResponderSession) ReadHandshakeMessage(msg1 []byte) ([]byte, error) {
	if _, _, _, err := s.hs.ReadMessage(nil, msg1); err != nil {
		return nil, fmt.Errorf("testResponderSession: read message 1: %w", err)
	}
	msg2, c1, c2, err := s.hs.WriteMessage(nil, nil)
	if err != nil {
		return nil, fmt.Errorf("testResponderSession: write message 2: %w", err)
	}
	s.recv = c1
	s.send = c2
	return msg2, nil
}

func (s *testResponderSession) Encrypt(plaintext []byte) []byte {
	ct, err := s.send.Encrypt(nil, nil, plaintext)
	if err != nil {
		panic(fmt.Sprintf("testResponderSession: encrypt: %v", err))
	}
	return ct
}

func (s *testResponderSession) Decrypt(ciphertext []byte) ([]byte, error) {
	pt, err := s.recv.Decrypt(nil, nil, ciphertext)
	if err != nil {
		return nil, fmt.Errorf("testResponderSession: decrypt: %w", err)
	}
	return pt, nil
}

func TestRun_SendsHeartbeatsAndAppliesCapabilitiesSet(t *testing.T) {
	originalInterval := heartbeatInterval
	heartbeatInterval = 200 * time.Millisecond
	defer func() { heartbeatInterval = originalInterval }()

	serverPriv, serverPub := generateTestKeypair(t)
	var heartbeats int32

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

		grants := map[string]any{
			"v": 1, "type": "capabilities.set", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]bool{"host_telemetry": true},
		}
		grantsBytes, _ := json.Marshal(grants)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(grantsBytes))

		update := map[string]any{
			"v": 1, "type": "update", "seq": 2, "ts": time.Now().UTC(),
			"payload": map[string]string{"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"},
		}
		updateBytes, _ := json.Marshal(update)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(updateBytes))

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
			if f["type"] == "heartbeat" {
				atomic.AddInt32(&heartbeats, 1)
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

	var capabilitiesApplied, connectedCount, updateApplied int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnCapabilitiesSet: func(json.RawMessage) error {
			atomic.AddInt32(&capabilitiesApplied, 1)
			return nil
		},
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
		OnUpdate: func(payload json.RawMessage, send SendUpdateStatus) error {
			var instr struct {
				Version string `json:"version"`
			}
			if err := json.Unmarshal(payload, &instr); err != nil {
				return err
			}
			if instr.Version != "0.2.0" {
				t.Errorf("OnUpdate payload version = %q, want %q", instr.Version, "0.2.0")
			}
			if err := send(instr.Version, "started", ""); err != nil {
				t.Errorf("send(started) error = %v", err)
			}
			atomic.AddInt32(&updateApplied, 1)
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_ = Run(ctx, opts) // returns ctx.Err() (deadline exceeded) — that's the expected exit

	if atomic.LoadInt32(&connectedCount) == 0 {
		t.Error("OnConnected was never called")
	}
	if atomic.LoadInt32(&updateApplied) == 0 {
		t.Error("OnUpdate was never called")
	}

	if atomic.LoadInt32(&capabilitiesApplied) == 0 {
		t.Error("OnCapabilitiesSet was never called")
	}
	if atomic.LoadInt32(&heartbeats) == 0 {
		t.Error("no heartbeat frames were received")
	}
}

// TestRun_OnUpdateSendsStartedThenFailedStatusFrames drives an `update` frame
// whose OnUpdate callback reports "started" then simulates a download
// failure by reporting "failed" with a message — the two update.status calls
// Task 24 expects for a failing update, both sent over the same live
// connection the `update` frame arrived on, in order, before any retry or
// reconnect.
func TestRun_OnUpdateSendsStartedThenFailedStatusFrames(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

	type observed struct {
		Version string `json:"version"`
		Phase   string `json:"phase"`
		Error   string `json:"error"`
	}
	var mu atomicStatusList

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

		grants := map[string]any{
			"v": 1, "type": "capabilities.set", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]bool{"host_telemetry": true},
		}
		grantsBytes, _ := json.Marshal(grants)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(grantsBytes))

		update := map[string]any{
			"v": 1, "type": "update", "seq": 2, "ts": time.Now().UTC(),
			"payload": map[string]string{"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"},
		}
		updateBytes, _ := json.Marshal(update)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(updateBytes))

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
			json.Unmarshal(pt, &f)
			if f.Type == "update.status" {
				var st observed
				json.Unmarshal(f.Payload, &st)
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
		OnUpdate: func(payload json.RawMessage, send SendUpdateStatus) error {
			var instr struct {
				Version string `json:"version"`
			}
			if err := json.Unmarshal(payload, &instr); err != nil {
				return err
			}
			if err := send(instr.Version, "started", ""); err != nil {
				t.Errorf("send(started) error = %v", err)
			}
			if err := send(instr.Version, "failed", "simulated download failure"); err != nil {
				t.Errorf("send(failed) error = %v", err)
			}
			return fmt.Errorf("simulated download failure")
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	got := mu.snapshot()
	if len(got) != 2 {
		t.Fatalf("observed %d update.status frames, want 2: %+v", len(got), got)
	}
	if got[0] != (statusEntry{"0.2.0", "started", ""}) {
		t.Errorf("first update.status = %+v, want {0.2.0 started }", got[0])
	}
	if got[1] != (statusEntry{"0.2.0", "failed", "simulated download failure"}) {
		t.Errorf("second update.status = %+v, want {0.2.0 failed simulated download failure}", got[1])
	}
}

// TestRun_ReportsRolledBackOnceConnectedThenClears drives an accepted
// hello.ack with ReportPendingUpdateOutcome reporting a pending rollback —
// the situation main.go's rollback goroutine leaves behind for the next
// process to report, since it has no live connection of its own at the
// moment it decides to roll back (Task 24). Asserts the agent sends exactly
// one update.status(rolled_back) frame right after the accepted hello.ack,
// and that ClearPendingUpdateOutcome fires only once the send actually
// succeeded.
func TestRun_ReportsRolledBackOnceConnectedThenClears(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	var mu atomicStatusList

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
			var f struct {
				Type    string          `json:"type"`
				Payload json.RawMessage `json:"payload"`
			}
			json.Unmarshal(pt, &f)
			if f.Type == "update.status" {
				var st struct {
					Version string `json:"version"`
					Phase   string `json:"phase"`
					Error   string `json:"error"`
				}
				json.Unmarshal(f.Payload, &st)
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

	pending := true
	var cleared int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		ReportPendingUpdateOutcome: func() (string, bool) {
			if !pending {
				return "", false
			}
			return "0.3.0", true
		},
		ClearPendingUpdateOutcome: func() {
			pending = false
			atomic.AddInt32(&cleared, 1)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	got := mu.snapshot()
	if len(got) != 1 {
		t.Fatalf("observed %d update.status frames, want 1: %+v", len(got), got)
	}
	if got[0] != (statusEntry{"0.3.0", "rolled_back", ""}) {
		t.Errorf("update.status = %+v, want {0.3.0 rolled_back }", got[0])
	}
	if atomic.LoadInt32(&cleared) != 1 {
		t.Errorf("ClearPendingUpdateOutcome called %d time(s), want 1", cleared)
	}
}

// TestRun_RespondsToServerPingWithImmediateHeartbeat verifies the agent's
// handling of the server->agent `ping` frame (frame.TypePing): a WS-level
// liveness probe distinct from the agent's own heartbeat ticker. The ticker
// is stretched to 5s — far longer than this test runs — so any heartbeat
// frame the fake server observes can only be the agent's immediate reply to
// the `ping`, not its regular cadence (ws_agents.py's `_send_ping` is the
// server-side counterpart that sends this frame).
func TestRun_RespondsToServerPingWithImmediateHeartbeat(t *testing.T) {
	originalInterval := heartbeatInterval
	heartbeatInterval = 5 * time.Second
	defer func() { heartbeatInterval = originalInterval }()

	serverPriv, serverPub := generateTestKeypair(t)
	heartbeatReceived := make(chan struct{}, 1)

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

		var outSeq uint64
		send := func(typ string, payload any) {
			f := map[string]any{
				"v": 1, "type": typ, "seq": outSeq, "ts": time.Now().UTC(), "payload": payload,
			}
			outSeq++
			data, _ := json.Marshal(f)
			conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(data))
		}

		send("hello.ack", map[string]any{"accepted": true, "agent_id": 1})
		send("ping", map[string]any{})

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
			if f["type"] == "heartbeat" {
				select {
				case heartbeatReceived <- struct{}{}:
				default:
				}
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
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()

	select {
	case <-heartbeatReceived:
		// Good — the agent replied to the ping well before its own 5s
		// heartbeat ticker could ever have fired.
	case <-time.After(1 * time.Second):
		t.Fatal("agent did not send a heartbeat frame in response to a server ping frame")
	}

	cancel()
	<-done
}

// TestRun_DropsReplayedAndInvalidInboundFrames drives the same handshake as
// TestRun_SendsHeartbeatsAndAppliesCapabilitiesSet, but has the fake server
// send a run of frames designed to be rejected by the inbound sequence
// guard — a duplicate seq, a decreasing seq, an unsupported version, and a
// malformed (empty-type) frame — interleaved with one genuinely new
// capabilities.set. Only the genuinely new frame should ever reach
// OnCapabilitiesSet; the connection must survive all four rejections.
func TestRun_DropsReplayedAndInvalidInboundFrames(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

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

		send := func(v int, typ string, seq uint64, payload any) {
			f := map[string]any{"v": v, "type": typ, "seq": seq, "ts": time.Now().UTC(), "payload": payload}
			data, _ := json.Marshal(f)
			conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(data))
		}

		// First, a legitimate capabilities.set at seq 0 — accepted.
		send(1, "capabilities.set", 0, map[string]bool{"host_telemetry": true})
		// Replays/violations that must all be dropped.
		send(1, "capabilities.set", 0, map[string]bool{"host_telemetry": false}) // duplicate seq
		send(1, "capabilities.set", 0, map[string]bool{"host_telemetry": false}) // decreasing (still 0, treated as duplicate again — exercise both branches below)
		send(2, "capabilities.set", 1, map[string]bool{"host_telemetry": false}) // unsupported version
		send(1, "", 2, map[string]bool{"host_telemetry": false})                 // malformed: empty type
		// A genuinely new, strictly-increasing, well-formed frame — accepted.
		send(1, "capabilities.set", 3, map[string]bool{"host_telemetry": false, "remote_probe": true})

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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

	var applied int32
	var lastPayload atomic.Value
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnCapabilitiesSet: func(payload json.RawMessage) error {
			atomic.AddInt32(&applied, 1)
			lastPayload.Store(string(payload))
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	if got := atomic.LoadInt32(&applied); got != 2 {
		t.Errorf("OnCapabilitiesSet called %d times, want 2 (seq 0 and seq 3 only)", got)
	}
	if v, ok := lastPayload.Load().(string); !ok || !strings.Contains(v, "remote_probe") {
		t.Errorf("last applied payload = %v, want the seq=3 frame's payload", v)
	}
}

// TestRun_OnConnectedWaitsForAcceptedHelloAck drives handshake + hello to
// completion, then deliberately withholds hello.ack behind a gate so the
// test can assert OnConnected has NOT fired off the bare handshake — only
// after the gate is released and an accepted hello.ack actually arrives.
func TestRun_OnConnectedWaitsForAcceptedHelloAck(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	release := make(chan struct{})

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

		// Handshake and hello are both done at this point, but we
		// deliberately hold off on hello.ack until the test releases us —
		// this is what proves OnConnected isn't tied to bare handshake
		// completion.
		<-release

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 7},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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

	var connectedCount int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()

	// Give the handshake+hello round trip time to land on the wire while
	// hello.ack is still withheld, then assert OnConnected has not fired.
	time.Sleep(300 * time.Millisecond)
	if got := atomic.LoadInt32(&connectedCount); got != 0 {
		t.Fatalf("OnConnected fired %d time(s) before any hello.ack was sent, want 0", got)
	}

	close(release)

	deadline := time.Now().Add(2 * time.Second)
	for atomic.LoadInt32(&connectedCount) == 0 {
		if time.Now().After(deadline) {
			t.Fatal("OnConnected never fired after an accepted hello.ack was sent")
		}
		time.Sleep(10 * time.Millisecond)
	}

	cancel()
	<-done
}

// TestRun_OnConnectedNeverFiresOnRejectedHelloAck sends a hello.ack with
// accepted:false and asserts OnConnected is never called for the lifetime
// of the run — link success requires an *accepted* hello.ack, not merely
// receipt of one. It also asserts OnRejected fires exactly once with the
// server's stated reason, since the two hooks exist precisely to distinguish
// this outcome from an accepted link.
func TestRun_OnConnectedNeverFiresOnRejectedHelloAck(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

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
			"payload": map[string]any{"accepted": false, "reason": "device_pk_mismatch"},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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

	var connectedCount, rejectedCount int32
	var lastReason atomic.Value
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
		OnRejected: func(reason string) {
			atomic.AddInt32(&rejectedCount, 1)
			lastReason.Store(reason)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	_ = Run(ctx, opts)

	if got := atomic.LoadInt32(&connectedCount); got != 0 {
		t.Errorf("OnConnected fired %d time(s) on a rejected hello.ack, want 0", got)
	}
	if got := atomic.LoadInt32(&rejectedCount); got == 0 {
		t.Error("OnRejected never fired for a rejected hello.ack")
	}
	if got, _ := lastReason.Load().(string); got != "device_pk_mismatch" {
		t.Errorf("OnRejected reason = %q, want %q", got, "device_pk_mismatch")
	}
}

// TestRun_OnDisconnectedFiresWithCauseOnConnectionLoss drives an accepted
// hello.ack and then has the fake server close the connection, asserting
// OnDisconnected fires with a non-nil cause — the hook main.go uses to
// record the daemon's last error in the runtime status file.
func TestRun_OnDisconnectedFiresWithCauseOnConnectionLoss(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

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
		// Drop the connection immediately by returning — the deferred
		// conn.Close() fires, and the client's next read fails.
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	var disconnectedCount int32
	var lastCause atomic.Value
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnDisconnected: func(cause error) {
			atomic.AddInt32(&disconnectedCount, 1)
			lastCause.Store(cause)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	_ = Run(ctx, opts)

	if got := atomic.LoadInt32(&disconnectedCount); got == 0 {
		t.Fatal("OnDisconnected never fired after the connection dropped")
	}
	cause, _ := lastCause.Load().(error)
	if cause == nil {
		t.Error("OnDisconnected fired with a nil cause, want a non-nil error describing the drop")
	}
}

// TestRun_OnDisconnectedNotCalledOnCleanShutdown asserts OnDisconnected does
// not fire when Run exits because its context was cancelled — an
// intentional daemon shutdown is not a link failure and must not be
// recorded as one.
func TestRun_OnDisconnectedNotCalledOnCleanShutdown(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

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
			if _, err := responder.Decrypt(ct); err != nil {
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

	var connectedCount, disconnectedCount int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
		OnDisconnected: func(error) {
			atomic.AddInt32(&disconnectedCount, 1)
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()

	deadline := time.Now().Add(2 * time.Second)
	for atomic.LoadInt32(&connectedCount) == 0 {
		if time.Now().After(deadline) {
			cancel()
			<-done
			t.Fatal("OnConnected never fired")
		}
		time.Sleep(10 * time.Millisecond)
	}

	cancel()
	<-done

	if got := atomic.LoadInt32(&disconnectedCount); got != 0 {
		t.Errorf("OnDisconnected fired %d time(s) on a clean ctx-cancelled shutdown, want 0", got)
	}
}

// TestRunOnce_DropBeforeStabilityWindowIsNotStable drives an accepted
// hello.ack and then has the fake server close the connection immediately
// — well before stabilityWindow elapses. runOnce must report stable=false:
// an accepted hello.ack alone isn't enough to reset backoff, the connection
// also has to survive the stability window (Finding 1 of the task-4
// review).
func TestRunOnce_DropBeforeStabilityWindowIsNotStable(t *testing.T) {
	originalWindow := stabilityWindow
	stabilityWindow = 300 * time.Millisecond
	defer func() { stabilityWindow = originalWindow }()

	serverPriv, serverPub := generateTestKeypair(t)

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
		// Deliberately drop the connection right after the accepted
		// hello.ack — well inside stabilityWindow (300ms) — by returning
		// immediately, which fires the deferred conn.Close().
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	var connectedCount int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	stable, _ := runOnce(ctx, opts)

	if atomic.LoadInt32(&connectedCount) == 0 {
		t.Fatal("OnConnected never fired — accepted hello.ack should still trigger it")
	}
	if stable {
		t.Error("runOnce reported stable=true for a connection that dropped before stabilityWindow elapsed, want false")
	}
}

// TestRunOnce_StaysUpPastStabilityWindowIsStable drives an accepted
// hello.ack and keeps the connection alive past stabilityWindow (the test
// context deadline extends beyond it). runOnce must report stable=true
// once the window has elapsed while the connection is still up.
func TestRunOnce_StaysUpPastStabilityWindowIsStable(t *testing.T) {
	originalWindow := stabilityWindow
	stabilityWindow = 150 * time.Millisecond
	defer func() { stabilityWindow = originalWindow }()

	serverPriv, serverPub := generateTestKeypair(t)

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

		// Stay up well past stabilityWindow (150ms) — keep reading so the
		// connection isn't torn down by the client's own writes stalling.
		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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

	var connectedCount int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
	}

	// Deadline comfortably past stabilityWindow (150ms) so runOnce is still
	// connected when the window elapses, then returns via ctx.Err().
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	stable, err := runOnce(ctx, opts)

	if atomic.LoadInt32(&connectedCount) == 0 {
		t.Fatal("OnConnected never fired")
	}
	if !stable {
		t.Error("runOnce reported stable=false for a connection that stayed up past stabilityWindow, want true")
	}
	if err != context.DeadlineExceeded {
		t.Errorf("runOnce err = %v, want context.DeadlineExceeded", err)
	}
}

func (s *testResponderSession) RekeySend() { s.send.Rekey() }
func (s *testResponderSession) RekeyRecv() { s.recv.Rekey() }

// TestRun_RekeysBothDirectionsOverMultipleIntervals runs the real link loop
// with rekeyInterval shrunk from 15 minutes to a few milliseconds, so several
// rekey generations elapse in each direction inside one test.
//
// The fake server plays the full protocol on both sides: it applies the
// agent's `transport.rekey` announcements to its own receive cipher, and
// independently announces + applies its own send-cipher rekeys on a different
// schedule. Traffic has to keep flowing across every generation, which is only
// possible if the old-key-then-rekey ordering and the key derivation both hold
// on both sides.
// TestResolveRekeyInterval_UnsetIsInert pins the production-safety guarantee
// for rekeyIntervalEnvOverride: with CB_AGENT_TEST_REKEY_INTERVAL_SECONDS
// unset (the state of every real deployment), resolveRekeyInterval must
// return exactly the 15-minute production default — byte-for-byte identical
// to what this function returned before the override existed. This is the
// test the doc comments on rekeyIntervalEnvOverride/rekeyInterval point to.
func TestResolveRekeyInterval_UnsetIsInert(t *testing.T) {
	t.Setenv(rekeyIntervalEnvOverride, "")
	if got := resolveRekeyInterval(); got != 15*time.Minute {
		t.Fatalf("resolveRekeyInterval() with env unset = %v, want 15m0s (production default must not move)", got)
	}
}

// TestResolveRekeyInterval_HonorsOverride confirms the override actually
// takes effect when explicitly set — the other half of the contract next to
// TestResolveRekeyInterval_UnsetIsInert.
func TestResolveRekeyInterval_HonorsOverride(t *testing.T) {
	t.Setenv(rekeyIntervalEnvOverride, "7")
	if got := resolveRekeyInterval(); got != 7*time.Second {
		t.Fatalf("resolveRekeyInterval() with env=7 = %v, want 7s", got)
	}
}

// TestResolveRekeyInterval_IgnoresGarbageAndNonPositive confirms malformed or
// non-positive overrides are silently ignored rather than e.g. panicking or
// producing a zero/negative ticker interval — the fallback is always the
// production default in that case, never a broken interval.
func TestResolveRekeyInterval_IgnoresGarbageAndNonPositive(t *testing.T) {
	for _, v := range []string{"not-a-number", "0", "-5"} {
		t.Setenv(rekeyIntervalEnvOverride, v)
		if got := resolveRekeyInterval(); got != 15*time.Minute {
			t.Fatalf("resolveRekeyInterval() with env=%q = %v, want 15m0s (production default)", v, got)
		}
	}
}

func TestRun_RekeysBothDirectionsOverMultipleIntervals(t *testing.T) {
	originalRekey, originalHeartbeat := rekeyInterval, heartbeatInterval
	rekeyInterval = 60 * time.Millisecond
	heartbeatInterval = 40 * time.Millisecond
	defer func() { rekeyInterval, heartbeatInterval = originalRekey, originalHeartbeat }()

	const serverRekeyTarget = 3
	serverPriv, serverPub := generateTestKeypair(t)
	var agentRekeys, heartbeatsAfterFirstRekey, badRekeyFrames int32

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

		if _, helloCt, err := conn.ReadMessage(); err != nil {
			return
		} else if _, err := responder.Decrypt(helloCt); err != nil {
			return
		}

		var outSeq uint64
		send := func(typ string, payload any) {
			f := map[string]any{
				"v": 1, "type": typ, "seq": outSeq, "ts": time.Now().UTC(), "payload": payload,
			}
			outSeq++
			data, _ := json.Marshal(f)
			conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(data))
		}

		send("hello.ack", map[string]any{"accepted": true, "agent_id": 1})

		// Server -> agent rekey: announce under the OLD send key, then rotate,
		// then prove the agent followed by sending a frame under the NEW key
		// that it must still be able to apply.
		serverRekeys := uint64(0)
		serverRekey := func() {
			serverRekeys++
			send("transport.rekey", map[string]any{
				"direction": "outbound", "generation": serverRekeys,
			})
			responder.RekeySend()
			send("capabilities.set", map[string]bool{"host_telemetry": true})
		}

		var seenAgentRekeys uint64
		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := responder.Decrypt(ct)
			if err != nil {
				// Any decrypt failure here means the two sides' ciphers fell
				// out of step — the exact bug this test exists to catch.
				atomic.AddInt32(&badRekeyFrames, 1)
				return
			}
			var f struct {
				Type    string `json:"type"`
				Payload struct {
					Direction  string `json:"direction"`
					Generation uint64 `json:"generation"`
				} `json:"payload"`
			}
			if err := json.Unmarshal(pt, &f); err != nil {
				atomic.AddInt32(&badRekeyFrames, 1)
				return
			}

			switch f.Type {
			case "transport.rekey":
				// The announcement itself arrived under the old key (it just
				// decrypted); rotate the receive cipher to match the agent's
				// send cipher, which it rotated right after sending this.
				seenAgentRekeys++
				if f.Payload.Direction != "outbound" || f.Payload.Generation != seenAgentRekeys {
					atomic.AddInt32(&badRekeyFrames, 1)
					return
				}
				responder.RekeyRecv()
				atomic.StoreInt32(&agentRekeys, int32(seenAgentRekeys))
			case "heartbeat":
				if seenAgentRekeys > 0 {
					atomic.AddInt32(&heartbeatsAfterFirstRekey, 1)
				}
			}

			if serverRekeys < serverRekeyTarget {
				serverRekey()
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

	var capabilitiesApplied int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnCapabilitiesSet: func(json.RawMessage) error {
			atomic.AddInt32(&capabilitiesApplied, 1)
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	if got := atomic.LoadInt32(&badRekeyFrames); got != 0 {
		t.Errorf("server saw %d undecryptable/malformed frames, want 0", got)
	}
	if got := atomic.LoadInt32(&agentRekeys); got < 3 {
		t.Errorf("agent announced %d outbound rekeys, want at least 3", got)
	}
	if got := atomic.LoadInt32(&heartbeatsAfterFirstRekey); got == 0 {
		t.Error("no agent heartbeat decrypted after the first agent->server rekey")
	}
	if got := atomic.LoadInt32(&capabilitiesApplied); got < serverRekeyTarget {
		t.Errorf("agent applied %d capabilities.set frames sent under rekeyed server keys, want %d",
			got, serverRekeyTarget)
	}
}

// TestApplyInboundRekey covers the validation around the receive-side cipher
// swap. Every rejection is fatal on purpose: once the peer has rotated its
// send cipher, skipping the matching receive rekey leaves the direction
// permanently undecryptable, so failing fast into a reconnect is the only
// recoverable outcome.
func TestApplyInboundRekey(t *testing.T) {
	tests := []struct {
		name    string
		startAt uint64
		payload string
		wantErr bool
		wantGen uint64
	}{
		{name: "first generation", startAt: 0, payload: `{"direction":"outbound","generation":1}`, wantGen: 1},
		{name: "next generation", startAt: 7, payload: `{"direction":"outbound","generation":8}`, wantGen: 8},
		{name: "replayed generation", startAt: 3, payload: `{"direction":"outbound","generation":3}`, wantErr: true, wantGen: 3},
		{name: "skipped generation", startAt: 3, payload: `{"direction":"outbound","generation":5}`, wantErr: true, wantGen: 3},
		{name: "zero generation", startAt: 0, payload: `{"direction":"outbound","generation":0}`, wantErr: true},
		{name: "inbound direction is nonsense", startAt: 0, payload: `{"direction":"inbound","generation":1}`, wantErr: true},
		{name: "missing direction", startAt: 0, payload: `{"generation":1}`, wantErr: true},
		{name: "malformed payload", startAt: 0, payload: `not json`, wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			session, _, _ := newHandshakenSession(t)
			gen := tt.startAt
			err := applyInboundRekey(session, frame.Frame{
				V: frame.FrameVersion, Type: frame.TypeTransportRekey,
				Payload: json.RawMessage(tt.payload),
			}, &gen)

			if tt.wantErr && err == nil {
				t.Fatal("applyInboundRekey() error = nil, want an error")
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("applyInboundRekey() error = %v, want nil", err)
			}
			if gen != tt.wantGen {
				t.Errorf("generation = %d, want %d", gen, tt.wantGen)
			}
		})
	}
}

// newHandshakenSession returns a completed initiator Session plus the
// responder's receive/send ciphers, for tests that need to poke at cipher
// state directly rather than over a socket.
func newHandshakenSession(t *testing.T) (*noiseconn.Session, *noise.CipherState, *noise.CipherState) {
	t.Helper()
	serverPriv, serverPub := generateTestKeypair(t)
	agentPriv, agentPub := generateTestKeypair(t)

	session, err := noiseconn.NewInitiator(agentPriv, agentPub, serverPub)
	if err != nil {
		t.Fatalf("NewInitiator() error = %v", err)
	}
	responder := newTestResponderSession(t, serverPriv, serverPub)
	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		t.Fatalf("WriteHandshakeMessage() error = %v", err)
	}
	msg2, err := responder.ReadHandshakeMessage(msg1)
	if err != nil {
		t.Fatalf("responder handshake: %v", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		t.Fatalf("ReadHandshakeMessage() error = %v", err)
	}
	return session, responder.recv, responder.send
}

// ── Task 28: server-key rotation (key.rotate kind="server") ────────────────

func TestServerKeyCandidates_NoStateDirReturnsOnlyConfigKey(t *testing.T) {
	cfg := &config.Config{ServerStaticPK: strings.Repeat("aa", 32)}

	got := serverKeyCandidates(cfg, "")

	if len(got) != 1 || got[0] != cfg.ServerStaticPK {
		t.Errorf("serverKeyCandidates() = %v, want [%q]", got, cfg.ServerStaticPK)
	}
}

func TestServerKeyCandidates_NoPersistedRotationReturnsOnlyConfigKey(t *testing.T) {
	dir := t.TempDir()
	cfg := &config.Config{ServerStaticPK: strings.Repeat("aa", 32)}

	got := serverKeyCandidates(cfg, dir)

	if len(got) != 1 || got[0] != cfg.ServerStaticPK {
		t.Errorf("serverKeyCandidates() = %v, want [%q]", got, cfg.ServerStaticPK)
	}
}

func TestServerKeyCandidates_IncludesPersistedSuccessor(t *testing.T) {
	dir := t.TempDir()
	cfg := &config.Config{ServerStaticPK: strings.Repeat("aa", 32)}
	successor := strings.Repeat("bb", 32)
	if err := config.SaveServerKeyRotation(dir, config.ServerKeyRotation{SuccessorPK: successor}); err != nil {
		t.Fatalf("SaveServerKeyRotation() error = %v", err)
	}

	got := serverKeyCandidates(cfg, dir)

	want := []string{cfg.ServerStaticPK, successor}
	if len(got) != 2 || got[0] != want[0] || got[1] != want[1] {
		t.Errorf("serverKeyCandidates() = %v, want %v", got, want)
	}
}

func TestServerKeyCandidates_SkipsSuccessorIdenticalToCurrent(t *testing.T) {
	dir := t.TempDir()
	cfg := &config.Config{ServerStaticPK: strings.Repeat("aa", 32)}
	if err := config.SaveServerKeyRotation(dir, config.ServerKeyRotation{SuccessorPK: cfg.ServerStaticPK}); err != nil {
		t.Fatalf("SaveServerKeyRotation() error = %v", err)
	}

	got := serverKeyCandidates(cfg, dir)

	if len(got) != 1 {
		t.Errorf("serverKeyCandidates() = %v, want exactly [%q]", got, cfg.ServerStaticPK)
	}
}

// TestRunOnce_PersistsSuccessorServerKeyFromKeyRotateFrame proves the
// receiving half of Task 28's fix: an inbound `key.rotate` (kind="server")
// frame durably persists its successor_pk via config.SaveServerKeyRotation,
// so it survives past this connection (and a restart).
func TestRunOnce_PersistsSuccessorServerKeyFromKeyRotateFrame(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	_, successorPub := generateTestKeypair(t)
	expiry := time.Now().Add(7 * 24 * time.Hour).UTC().Truncate(time.Second)

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
			t.Errorf("expected a hello frame: %v", err)
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

		rotate := map[string]any{
			"v": 1, "type": "key.rotate", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]any{
				"kind":         "server",
				"successor_pk": hex.EncodeToString(successorPub[:]),
				"expiry":       expiry,
			},
		}
		rotateBytes, _ := json.Marshal(rotate)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(rotateBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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
		Config:       &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:          key,
		AgentVersion: "0.1.0-test",
		StateDir:     dir,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	_ = Run(ctx, opts)

	got, err := config.LoadServerKeyRotation(dir)
	if err != nil {
		t.Fatalf("LoadServerKeyRotation() error = %v", err)
	}
	if got == nil {
		t.Fatal("LoadServerKeyRotation() = nil, want the persisted successor key")
	}
	wantPK := hex.EncodeToString(successorPub[:])
	if got.SuccessorPK != wantPK {
		t.Errorf("SuccessorPK = %q, want %q", got.SuccessorPK, wantPK)
	}
	if !got.Expiry.Equal(expiry) {
		t.Errorf("Expiry = %v, want %v", got.Expiry, expiry)
	}
}

// TestRunOnce_IgnoresKeyRotateWithDeviceKind proves kind="device" — Task 27's
// own agent -> server direction, never something the server sends — is
// logged and left alone rather than persisted as a trusted server key.
func TestRunOnce_IgnoresKeyRotateWithDeviceKind(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

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
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			return
		}

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		rotate := map[string]any{
			"v": 1, "type": "key.rotate", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]any{
				"kind":         "device",
				"successor_pk": strings.Repeat("ab", 32),
				"expiry":       time.Now().Add(time.Hour),
			},
		}
		rotateBytes, _ := json.Marshal(rotate)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(rotateBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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
		Config:       &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:          key,
		AgentVersion: "0.1.0-test",
		StateDir:     dir,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	got, err := config.LoadServerKeyRotation(dir)
	if err != nil {
		t.Fatalf("LoadServerKeyRotation() error = %v", err)
	}
	if got != nil {
		t.Errorf("LoadServerKeyRotation() = %+v, want nil (kind=device must not be persisted)", got)
	}
}

// TestRunOnce_AcceptsSuccessorServerKeyOncePreviousKeyIsNoLongerValid proves
// the initiator half of Task 28's fix: with a successor key already
// persisted (as TestRunOnce_PersistsSuccessorServerKeyFromKeyRotateFrame
// proved key.rotate delivers), the agent still connects successfully even
// though its config file's ServerStaticPK now names a key the server no
// longer holds — mirroring the server's own accept-either-key stance from
// the other direction: candidate 1 (the stale config key) fails the Noise
// handshake against this server, and the agent falls back to candidate 2
// (the persisted successor) within the same connection attempt, no reconnect
// or backoff wait required.
func TestRunOnce_AcceptsSuccessorServerKeyOncePreviousKeyIsNoLongerValid(t *testing.T) {
	staleServerPriv, staleServerPub := generateTestKeypair(t)
	_ = staleServerPriv // never used to build a responder — this server no longer holds it
	successorPriv, successorPub := generateTestKeypair(t)

	var connectedCount int32
	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		responder := newTestResponderSession(t, successorPriv, successorPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			// Expected for the agent's first candidate (its config still
			// names staleServerPub, which this server no longer holds the
			// matching private key for) — exactly the scenario this test
			// proves recovery from, not a failure of this test itself.
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			return
		}

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))
		atomic.AddInt32(&connectedCount, 1)

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if _, err := responder.Decrypt(ct); err != nil {
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

	// The successor key was already advertised to this agent on some
	// earlier connection and durably persisted — see
	// TestRunOnce_PersistsSuccessorServerKeyFromKeyRotateFrame for proof of
	// that half; this test starts from its result.
	if err := config.SaveServerKeyRotation(dir, config.ServerKeyRotation{
		SuccessorPK: hex.EncodeToString(successorPub[:]),
		Expiry:      time.Now().Add(24 * time.Hour),
	}); err != nil {
		t.Fatalf("SaveServerKeyRotation() error = %v", err)
	}

	opts := Options{
		// Deliberately still the *stale* key — proving the agent falls back
		// to the persisted successor rather than requiring a config rewrite.
		Config:       &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(staleServerPub[:])},
		Key:          key,
		AgentVersion: "0.1.0-test",
		StateDir:     dir,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	if atomic.LoadInt32(&connectedCount) == 0 {
		t.Error("agent never connected using the persisted successor server key")
	}
}

// TestRun_DeliversProbeAssignToTheCallback drives one `probe.assign` and one `probe.cancel`
// control frame through a live link and asserts both reach their callbacks with the payload
// bytes untouched. The run id is the only identifier a result may be posted against, so anything
// this path normalizes or re-encodes makes the result unmatchable server-side.
func TestRun_DeliversProbeAssignToTheCallback(t *testing.T) {
	const runID = "3f9c1a7be04d42a1b8e6c05d7f1a2b3c"

	serverPriv, serverPub := generateTestKeypair(t)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
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
			t.Errorf("responder handshake: %v", err)
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		// The hello has to be *decrypted*, not merely read: the responder's receive cipher
		// carries a nonce counter, and skipping one message desynchronizes it from the agent's
		// send cipher, failing every subsequent decrypt.
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}

		for seq, f := range []map[string]any{
			{"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
				"payload": map[string]any{"accepted": true, "agent_id": 1}},
			{"v": 1, "type": "probe.assign", "seq": 1, "ts": time.Now().UTC(),
				"payload": map[string]any{
					"run_id": runID, "monitor_id": 42, "check_type": "http",
					"host": "app.internal.example.com", "config": map[string]any{},
					"scheduled_at": "2026-08-07T18:00:00Z", "deadline_at": "2026-08-07T18:00:20Z",
				}},
			{"v": 1, "type": "probe.cancel", "seq": 2, "ts": time.Now().UTC(),
				"payload": map[string]any{"run_id": runID, "reason": "monitor_paused"}},
		} {
			_ = seq
			data, _ := json.Marshal(f)
			conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(data))
		}

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

	assigned := make(chan frame.ProbeAssignPayload, 4)
	cancelled := make(chan frame.ProbeCancelPayload, 4)
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnProbeAssign: func(payload json.RawMessage) error {
			var assign frame.ProbeAssignPayload
			if err := json.Unmarshal(payload, &assign); err != nil {
				return err
			}
			assigned <- assign
			return nil
		},
		OnProbeCancel: func(payload json.RawMessage) error {
			var cancel frame.ProbeCancelPayload
			if err := json.Unmarshal(payload, &cancel); err != nil {
				return err
			}
			cancelled <- cancel
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go func() { _ = Run(ctx, opts) }()

	select {
	case assign := <-assigned:
		if assign.RunID != runID {
			t.Errorf("run_id = %q, want %q", assign.RunID, runID)
		}
		if assign.MonitorID != 42 || assign.CheckType != "http" || assign.Host != "app.internal.example.com" {
			t.Errorf("assignment = %+v", assign)
		}
		if assign.DeadlineAt.IsZero() {
			t.Error("deadline_at did not decode")
		}
	case <-ctx.Done():
		t.Fatal("OnProbeAssign was never called")
	}

	select {
	case cancellation := <-cancelled:
		if cancellation.RunID != runID || cancellation.Reason != "monitor_paused" {
			t.Errorf("cancellation = %+v", cancellation)
		}
	case <-ctx.Done():
		t.Fatal("OnProbeCancel was never called")
	}
}

// serveInboundFrames stands up one link server that completes the Noise handshake, accepts the
// hello, immediately pushes frames in the order given and then reads until the agent goes away.
// It is a helper rather than a third inline copy of the handshake because the two discovery tests
// below differ only in the handlers they install, never in what the server does.
func serveInboundFrames(t *testing.T, frames ...map[string]any) (wsURL, serverPKHex string) {
	t.Helper()
	serverPriv, serverPub := generateTestKeypair(t)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
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
			t.Errorf("responder handshake: %v", err)
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		// The hello has to be *decrypted*, not merely read: skipping a message desynchronizes the
		// responder's receive cipher from the agent's send cipher and fails every later decrypt.
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}

		outbound := append([]map[string]any{
			{"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
				"payload": map[string]any{"accepted": true, "agent_id": 1}},
		}, frames...)
		for _, f := range outbound {
			data, marshalErr := json.Marshal(f)
			if marshalErr != nil {
				t.Errorf("marshal inbound frame: %v", marshalErr)
				return
			}
			if err := conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(data)); err != nil {
				return
			}
		}

		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	t.Cleanup(srv.Close)
	return "ws" + strings.TrimPrefix(srv.URL, "http"), hex.EncodeToString(serverPub[:])
}

// discoveryTestDispatchID is the 32 lowercase hex characters a backend dispatch id is, and the one
// field a finding can be matched against server-side.
const discoveryTestDispatchID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"

// discoveryInboundFrames are one `discovery.request` and one `discovery.cancel` for the same
// dispatch, as the backend writes them.
func discoveryInboundFrames() []map[string]any {
	return []map[string]any{
		{"v": 1, "type": "discovery.request", "seq": 1, "ts": time.Now().UTC(),
			"payload": map[string]any{
				"dispatch_id": discoveryTestDispatchID, "scan_job_id": 41,
				"targets": []string{"10.20.0.8/30"}, "methods": []string{"neighbor_cache"},
				"tcp_ports": []int{22}, "host_timeout_ms": 200, "max_concurrent_hosts": 4,
				"scope_version": "3f1c9a2b4d6e8071", "deadline_at": "2026-08-08T18:00:20Z",
			}},
		{"v": 1, "type": "discovery.cancel", "seq": 2, "ts": time.Now().UTC(),
			"payload": map[string]any{"dispatch_id": discoveryTestDispatchID, "reason": "scope_changed"}},
	}
}

// TestRun_DeliversDiscoveryRequestAndCancelToTheirCallbacks is Task 14's inbound half, and the
// regression guard for the gap it closed: before these two switch arms existed the frame types
// decoded cleanly, passed the seq guard and were then dropped on the floor. Server-side that is
// indistinguishable from an agent that never heard the dispatch — the scan job sits at
// `running` with no finding and no refusal until its dispatch deadline expires.
//
// The payload is asserted field by field for the same reason the probe test above does it:
// dispatch_id is the only identifier a finding may be posted against, and every bound here is
// re-checked by the agent against its own grant, so anything this path re-encodes or normalizes
// makes the whole dispatch either unmatchable or wrongly authorized.
func TestRun_DeliversDiscoveryRequestAndCancelToTheirCallbacks(t *testing.T) {
	wsURL, serverPK := serveInboundFrames(t, discoveryInboundFrames()...)

	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	requested := make(chan frame.DiscoveryRequestPayload, 4)
	cancelled := make(chan frame.DiscoveryCancelPayload, 4)
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: serverPK},
		Key:    key, AgentVersion: "0.1.0-test",
		OnDiscoveryRequest: func(payload json.RawMessage) error {
			var req frame.DiscoveryRequestPayload
			if err := json.Unmarshal(payload, &req); err != nil {
				return err
			}
			requested <- req
			return nil
		},
		OnDiscoveryCancel: func(payload json.RawMessage) error {
			var cancellation frame.DiscoveryCancelPayload
			if err := json.Unmarshal(payload, &cancellation); err != nil {
				return err
			}
			cancelled <- cancellation
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go func() { _ = Run(ctx, opts) }()

	select {
	case req := <-requested:
		if req.DispatchID != discoveryTestDispatchID {
			t.Errorf("dispatch_id = %q, want %q", req.DispatchID, discoveryTestDispatchID)
		}
		if req.ScanJobID != 41 {
			t.Errorf("scan_job_id = %d, want 41", req.ScanJobID)
		}
		if len(req.Targets) != 1 || req.Targets[0] != "10.20.0.8/30" {
			t.Errorf("targets = %v, want [10.20.0.8/30]", req.Targets)
		}
		if len(req.Methods) != 1 || req.Methods[0] != "neighbor_cache" {
			t.Errorf("methods = %v, want [neighbor_cache]", req.Methods)
		}
		if len(req.TCPPorts) != 1 || req.TCPPorts[0] != 22 {
			t.Errorf("tcp_ports = %v, want [22]", req.TCPPorts)
		}
		if req.HostTimeoutMS != 200 || req.MaxConcurrentHosts != 4 {
			t.Errorf("bounds = %+v, want host_timeout_ms 200 and max_concurrent_hosts 4", req)
		}
		if req.ScopeVersion != "3f1c9a2b4d6e8071" {
			t.Errorf("scope_version = %q, want %q", req.ScopeVersion, "3f1c9a2b4d6e8071")
		}
		if req.DeadlineAt.IsZero() {
			t.Error("deadline_at did not decode")
		}
	case <-ctx.Done():
		t.Fatal("OnDiscoveryRequest was never called")
	}

	select {
	case cancellation := <-cancelled:
		if cancellation.DispatchID != discoveryTestDispatchID || cancellation.Reason != "scope_changed" {
			t.Errorf("cancellation = %+v", cancellation)
		}
	case <-ctx.Done():
		t.Fatal("OnDiscoveryCancel was never called")
	}
}

// TestRunOnce_DiscoveryFramesSurviveAMissingOrRefusingHandler pins the two properties the
// discovery arms share with the probe arms, both of which are about not amplifying a small fault
// into a dropped link.
//
// No handler: runOnce is reachable without Run's defaulting (this package's own tests call it
// directly, and Uninstall's one-shot connection installs nothing), so an inbound discovery frame
// must be a no-op rather than a nil call that takes the process down.
//
// A refusing handler: a refusal is already reported to the server as a terminal `rejected`
// summary by internal/collect/discover itself, so the returned error is log material only. Ending
// the connection over it would tear down the very link that summary has to travel back over, and
// the job would then hang for its whole deadline — the exact failure the refusal was avoiding.
func TestRunOnce_DiscoveryFramesSurviveAMissingOrRefusingHandler(t *testing.T) {
	tests := []struct {
		name    string
		install bool
	}{
		{name: "no handler installed at all", install: false},
		{name: "handlers that refuse the frame", install: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			wsURL, serverPK := serveInboundFrames(t, discoveryInboundFrames()...)

			dir := t.TempDir()
			key, err := enroll.LoadOrCreateDeviceKey(dir)
			if err != nil {
				t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
			}

			var calls atomic.Int32
			// runOnce is called directly here, bypassing Run's callback defaulting, so the
			// handlers this connection does need are supplied explicitly — and the two under
			// test are left nil in the first case on purpose.
			opts := Options{
				Config: &config.Config{ServerURL: wsURL, ServerStaticPK: serverPK},
				Key:    key, AgentVersion: "0.1.0-test",
				OnConnected:       func() {},
				OnRejected:        func(string) {},
				OnCapabilitiesSet: func(json.RawMessage) error { return nil },
				OnUpdate:          func(json.RawMessage, SendUpdateStatus) error { return nil },
			}
			if tt.install {
				refuse := func(json.RawMessage) error {
					calls.Add(1)
					return errors.New("refused: local_discovery is not enabled on this agent")
				}
				opts.OnDiscoveryRequest = refuse
				opts.OnDiscoveryCancel = refuse
			}

			// The context is the mechanism, not a safety net: "runOnce ran until the test
			// stopped it" is exactly the assertion, so it is deliberately far shorter than
			// readTimeout (60s) and heartbeatInterval (20s), neither of which can fire first.
			ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
			defer cancel()

			errCh := make(chan error, 1)
			go func() {
				_, runErr := runOnce(ctx, opts)
				errCh <- runErr
			}()

			select {
			case runErr := <-errCh:
				if !errors.Is(runErr, context.DeadlineExceeded) {
					t.Fatalf("runOnce err = %v, want context.DeadlineExceeded — an inbound "+
						"discovery frame with no handler, or one its handler refused, must "+
						"not end the connection", runErr)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("runOnce never returned")
			}

			if tt.install && calls.Load() != 2 {
				t.Errorf("handler calls = %d, want 2 (one discovery.request, one discovery.cancel) "+
					"— the connection surviving proves nothing if the arms never ran",
					calls.Load())
			}
		})
	}
}

// TestRun_ProbeAssignHandlerDoesNotDelayHeartbeats pins the constraint the whole
// internal/collect/probe runtime exists to satisfy. The inbound switch that dispatches
// probe.assign runs on the same goroutine as the websocket writer and the heartbeat ticker, and
// `incoming` is unbuffered — so a burst of assignments must flow straight through an
// enqueue-only handler while heartbeats keep leaving on schedule. If either the switch arm or
// the handler ever blocks, the gap between heartbeats grows past the server's 60s dead-link
// deadline (_LINK_DEAD_SECONDS) and the link is torn down mid-check.
func TestRun_ProbeAssignHandlerDoesNotDelayHeartbeats(t *testing.T) {
	originalInterval := heartbeatInterval
	heartbeatInterval = 100 * time.Millisecond
	defer func() { heartbeatInterval = originalInterval }()

	const assignments = 50

	serverPriv, serverPub := generateTestKeypair(t)

	var (
		beatMu sync.Mutex
		beats  []time.Time
	)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
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
			t.Errorf("responder handshake: %v", err)
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		// The hello has to be *decrypted*, not merely read: the responder's receive cipher
		// carries a nonce counter, and skipping one message desynchronizes it from the agent's
		// send cipher, failing every subsequent decrypt.
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}

		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ack))

		for i := 0; i < assignments; i++ {
			assign, _ := json.Marshal(map[string]any{
				"v": 1, "type": "probe.assign", "seq": i + 1, "ts": time.Now().UTC(),
				"payload": map[string]any{
					"run_id": fmt.Sprintf("%032x", i), "monitor_id": i, "check_type": "tcp",
					"host": "10.20.0.9", "config": map[string]any{},
					"scheduled_at": "2026-08-07T18:00:00Z", "deadline_at": "2026-08-07T18:00:20Z",
				},
			})
			if err := conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(assign)); err != nil {
				return
			}
		}

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
			if f["type"] == "heartbeat" {
				beatMu.Lock()
				beats = append(beats, time.Now())
				beatMu.Unlock()
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

	// An enqueue-only handler, exactly as probe.Runtime.Assign is: it writes into a bounded
	// buffer and returns, and nothing in this test ever drains it.
	delivered := make(chan struct{}, assignments)
	var received int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnProbeAssign: func(json.RawMessage) error {
			atomic.AddInt32(&received, 1)
			select {
			case delivered <- struct{}{}:
			default:
			}
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = Run(ctx, opts)

	if got := atomic.LoadInt32(&received); got != assignments {
		t.Errorf("delivered %d of %d assignments", got, assignments)
	}

	beatMu.Lock()
	observed := append([]time.Time(nil), beats...)
	beatMu.Unlock()
	if len(observed) < 3 {
		t.Fatalf("saw %d heartbeats in 2s at a %s interval — the assignment burst stalled the connection loop",
			len(observed), heartbeatInterval)
	}
	for i := 1; i < len(observed); i++ {
		if gap := observed[i].Sub(observed[i-1]); gap > 5*heartbeatInterval {
			t.Fatalf("heartbeat %d arrived %s after its predecessor, at a %s interval", i, gap, heartbeatInterval)
		}
	}
}
