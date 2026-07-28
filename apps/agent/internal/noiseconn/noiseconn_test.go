package noiseconn

import (
	"bytes"
	"crypto/rand"
	"testing"

	"github.com/flynn/noise"
)

func generateKeypair(t *testing.T) (priv, pub [32]byte) {
	t.Helper()
	dhKey, err := noise.DH25519.GenerateKeypair(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKeypair() error = %v", err)
	}
	copy(priv[:], dhKey.Private)
	copy(pub[:], dhKey.Public)
	return priv, pub
}

// newTestResponder builds a bare noise.HandshakeState in the responder role,
// standing in for the Python agent_crypto.NoiseIKResponder this initiator
// will really talk to (proven in Task 10's cross-language conformance test).
func newTestResponder(t *testing.T, priv, pub [32]byte) *noise.HandshakeState {
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
	return hs
}

func TestInitiator_CompletesHandshakeAndExchangesTransportMessage(t *testing.T) {
	serverPriv, serverPub := generateKeypair(t)
	agentPriv, agentPub := generateKeypair(t)

	initiator, err := NewInitiator(agentPriv, agentPub, serverPub)
	if err != nil {
		t.Fatalf("NewInitiator() error = %v", err)
	}

	responder := newTestResponder(t, serverPriv, serverPub)

	msg1, err := initiator.WriteHandshakeMessage()
	if err != nil {
		t.Fatalf("WriteHandshakeMessage() error = %v", err)
	}

	if _, _, _, err := responder.ReadMessage(nil, msg1); err != nil {
		t.Fatalf("responder.ReadMessage() error = %v", err)
	}
	msg2, respSend, respRecv, err := responder.WriteMessage(nil, nil)
	if err != nil {
		t.Fatalf("responder.WriteMessage() error = %v", err)
	}

	if err := initiator.ReadHandshakeMessage(msg2); err != nil {
		t.Fatalf("ReadHandshakeMessage() error = %v", err)
	}

	ct := initiator.Encrypt([]byte("hello from agent"))
	pt, err := respSend.Decrypt(nil, nil, ct)
	// respSend is the responder's send cipher; per Noise's directional
	// convention the initiator's Encrypt and the responder's matching
	// decrypt cipher must be the SAME direction's CipherState (c1, the
	// initiator->responder cipher). If this decrypt fails with an auth
	// error, swap which of respSend/respRecv is used here — the flynn/noise
	// c1/c2 return order needs confirming against the installed version,
	// exactly as app.core.agent_crypto's dissononce equivalent does on the
	// Python side (Task 2, Step 6's note).
	if err != nil {
		t.Fatalf("responder decrypt error = %v", err)
	}
	if !bytes.Equal(pt, []byte("hello from agent")) {
		t.Errorf("decrypted = %q, want %q", pt, "hello from agent")
	}
	_ = respRecv
}
