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

		grants := map[string]any{
			"v": 1, "type": "capabilities.set", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]bool{"host_telemetry": true},
		}
		grantsBytes, _ := json.Marshal(grants)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(grantsBytes))

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

	var capabilitiesApplied int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnCapabilitiesSet: func(json.RawMessage) error {
			atomic.AddInt32(&capabilitiesApplied, 1)
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_ = Run(ctx, opts) // returns ctx.Err() (deadline exceeded) — that's the expected exit

	if atomic.LoadInt32(&capabilitiesApplied) == 0 {
		t.Error("OnCapabilitiesSet was never called")
	}
	if atomic.LoadInt32(&heartbeats) == 0 {
		t.Error("no heartbeat frames were received")
	}
}
