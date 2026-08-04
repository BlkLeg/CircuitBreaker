package link

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
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
		OnUpdate: func(payload json.RawMessage) error {
			var instr struct {
				Version string `json:"version"`
			}
			if err := json.Unmarshal(payload, &instr); err != nil {
				return err
			}
			if instr.Version != "0.2.0" {
				t.Errorf("OnUpdate payload version = %q, want %q", instr.Version, "0.2.0")
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
// receipt of one.
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

	var connectedCount int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected: func() {
			atomic.AddInt32(&connectedCount, 1)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	_ = Run(ctx, opts)

	if got := atomic.LoadInt32(&connectedCount); got != 0 {
		t.Errorf("OnConnected fired %d time(s) on a rejected hello.ack, want 0", got)
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
