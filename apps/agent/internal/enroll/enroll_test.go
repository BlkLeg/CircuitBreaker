package enroll

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/flynn/noise"
	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
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

// testResponderSession is a direct analogue of noiseconn.Session, wired for
// Initiator: false, standing in for the Python NoiseIKResponder for the
// purposes of exercising enroll.Run's client-side behavior in isolation.
//
// flynn/noise's WriteMessage/ReadMessage return (c1, c2) in a fixed order
// regardless of role: c1 is always the initiator->responder cipher, c2 the
// responder->initiator cipher (confirmed empirically in noiseconn_test.go,
// where the responder's first-returned cipher state successfully decrypted
// what the initiator encrypted with its own first-returned cipher state).
// So the responder's "send" cipher (for encrypting to the initiator) is c2,
// and its "recv" cipher (for decrypting from the initiator) is c1 — the
// mirror image of noiseconn.Session, which uses c1 to send and c2 to
// receive.
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

// ReadHandshakeMessage processes the initiator's message 1 and returns
// message 2 to send back, completing the (single round-trip) IK handshake
// and deriving the transport cipher states.
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

func TestRun_PrintsPairingCodeAndReturnsOnActive(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Fatalf("upgrade error: %v", err)
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)

		_, msg1, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("read handshake msg1: %v", err)
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			t.Fatalf("responder handshake: %v", err)
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, msg2); err != nil {
			t.Fatalf("write handshake msg2: %v", err)
		}

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("read hello: %v", err)
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Fatalf("decrypt hello: %v", err)
		}

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"agent_id": 1, "pairing_code": "ABCD-EFGH-JKMN"},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		final := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"agent_id": 1, "status": "active"},
		}
		finalBytes, _ := json.Marshal(final)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(finalBytes))
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	cfg := &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])}
	if err := Run(cfg, key, "0.1.0-test"); err != nil {
		t.Fatalf("Run() error = %v, want nil (status=active)", err)
	}
}
