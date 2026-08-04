package noiseconn

import (
	"bytes"
	"crypto/rand"
	"fmt"
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

// newHandshakenPair returns a fully handshaken initiator Session plus the
// responder's two transport ciphers (c1 = initiator->responder, c2 =
// responder->initiator).
func newHandshakenPair(t *testing.T) (*Session, *noise.CipherState, *noise.CipherState) {
	t.Helper()
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
	msg2, c1, c2, err := responder.WriteMessage(nil, nil)
	if err != nil {
		t.Fatalf("responder.WriteMessage() error = %v", err)
	}
	if err := initiator.ReadHandshakeMessage(msg2); err != nil {
		t.Fatalf("ReadHandshakeMessage() error = %v", err)
	}
	return initiator, c1, c2
}

// TestSession_RekeyKeepsBothDirectionsWorkingAcrossIntervals drives several
// rekey intervals in a row, in both directions independently and at different
// rates, asserting traffic keeps flowing. The two directions deliberately
// rekey a different number of times per round: the whole point of the design
// is that neither side waits on the other's timer.
func TestSession_RekeyKeepsBothDirectionsWorkingAcrossIntervals(t *testing.T) {
	tests := []struct {
		name             string
		rounds           int
		msgsPerRound     int
		outboundPerRound int
		inboundPerRound  int
	}{
		{name: "single interval each way", rounds: 1, msgsPerRound: 2, outboundPerRound: 1, inboundPerRound: 1},
		{name: "many intervals in sequence", rounds: 6, msgsPerRound: 3, outboundPerRound: 1, inboundPerRound: 1},
		{name: "agent rekeys faster than server", rounds: 4, msgsPerRound: 2, outboundPerRound: 3, inboundPerRound: 1},
		{name: "server rekeys faster than agent", rounds: 4, msgsPerRound: 2, outboundPerRound: 1, inboundPerRound: 2},
		{name: "only the agent direction rekeys", rounds: 5, msgsPerRound: 2, outboundPerRound: 1, inboundPerRound: 0},
		{name: "only the server direction rekeys", rounds: 5, msgsPerRound: 2, outboundPerRound: 0, inboundPerRound: 1},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			agent, srvRecv, srvSend := newHandshakenPair(t)

			for round := 0; round < tt.rounds; round++ {
				for i := 0; i < tt.msgsPerRound; i++ {
					up := []byte(fmt.Sprintf("agent->server r%d m%d", round, i))
					got, err := srvRecv.Decrypt(nil, nil, agent.Encrypt(up))
					if err != nil {
						t.Fatalf("round %d: server decrypt error = %v", round, err)
					}
					if !bytes.Equal(got, up) {
						t.Fatalf("round %d: server got %q, want %q", round, got, up)
					}

					down := []byte(fmt.Sprintf("server->agent r%d m%d", round, i))
					ct, err := srvSend.Encrypt(nil, nil, down)
					if err != nil {
						t.Fatalf("round %d: server encrypt error = %v", round, err)
					}
					got, err = agent.Decrypt(ct)
					if err != nil {
						t.Fatalf("round %d: agent decrypt error = %v", round, err)
					}
					if !bytes.Equal(got, down) {
						t.Fatalf("round %d: agent got %q, want %q", round, got, down)
					}
				}

				// agent->server rekey: the agent announces on the old key
				// (modelled by the message above), then both halves of that
				// direction advance a generation.
				for i := 0; i < tt.outboundPerRound; i++ {
					agent.RekeySend()
					srvRecv.Rekey()
				}
				// server->agent rekey, on its own independent schedule.
				for i := 0; i < tt.inboundPerRound; i++ {
					srvSend.Rekey()
					agent.RekeyRecv()
				}
			}
		})
	}
}

// TestSession_RekeyOnOneSideOnlyBreaksThatDirection pins the failure mode the
// generation counters in internal/link exist to catch: if one peer rekeys and
// the other doesn't, that direction stops decrypting while the *other*
// direction keeps working, since the two ciphers are fully independent.
func TestSession_RekeyOnOneSideOnlyBreaksThatDirection(t *testing.T) {
	agent, srvRecv, srvSend := newHandshakenPair(t)

	agent.RekeySend() // the server never applies the matching RekeyRecv

	if _, err := srvRecv.Decrypt(nil, nil, agent.Encrypt([]byte("ping"))); err == nil {
		t.Error("server decrypted agent traffic after a one-sided rekey, want failure")
	}

	down := []byte("still fine")
	ct, err := srvSend.Encrypt(nil, nil, down)
	if err != nil {
		t.Fatalf("server encrypt error = %v", err)
	}
	got, err := agent.Decrypt(ct)
	if err != nil {
		t.Fatalf("server->agent direction broke too: %v", err)
	}
	if !bytes.Equal(got, down) {
		t.Errorf("agent got %q, want %q", got, down)
	}
}
