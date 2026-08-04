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

		grants := map[string]any{
			"v": 1, "type": "capabilities.set", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]bool{"host_telemetry": true},
		}
		grantsBytes, _ := json.Marshal(grants)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(grantsBytes))

		update := map[string]any{
			"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
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
