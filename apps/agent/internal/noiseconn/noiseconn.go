// apps/agent/internal/noiseconn/noiseconn.go
package noiseconn

import (
	"fmt"

	"github.com/flynn/noise"
)

// Session wraps a Noise_IK_25519_ChaChaPoly_SHA256 handshake in the
// initiator role — the agent's role per spec §2.2. The responder counterpart
// is app.core.agent_crypto.NoiseIKResponder on the Python side.
//
// Goroutine affinity: the send cipher (Encrypt, RekeySend) and the receive
// cipher (Decrypt, RekeyRecv) are independent objects, so a Session is safe
// to use from exactly two goroutines provided one owns the send half and the
// other owns the receive half — which is precisely how internal/link uses it
// (its reader goroutine decrypts and rekeys inbound; its main loop encrypts
// and rekeys outbound). Sharing either half across goroutines is a data race.
type Session struct {
	hs   *noise.HandshakeState
	send *noise.CipherState
	recv *noise.CipherState
}

func NewInitiator(localPriv, localPub, remotePub [32]byte) (*Session, error) {
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	hs, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:   cs,
		Pattern:       noise.HandshakeIK,
		Initiator:     true,
		StaticKeypair: noise.DHKey{Private: localPriv[:], Public: localPub[:]},
		PeerStatic:    remotePub[:],
	})
	if err != nil {
		return nil, fmt.Errorf("noiseconn: new handshake state: %w", err)
	}
	return &Session{hs: hs}, nil
}

func (s *Session) WriteHandshakeMessage() ([]byte, error) {
	msg, _, _, err := s.hs.WriteMessage(nil, nil)
	if err != nil {
		return nil, fmt.Errorf("noiseconn: write handshake message: %w", err)
	}
	return msg, nil
}

func (s *Session) ReadHandshakeMessage(data []byte) error {
	_, send, recv, err := s.hs.ReadMessage(nil, data)
	if err != nil {
		return fmt.Errorf("noiseconn: read handshake message: %w", err)
	}
	s.send, s.recv = send, recv
	return nil
}

// Encrypt seals plaintext with the post-handshake send cipher. The
// underlying noise.CipherState.Encrypt returns an error (reserved for nonce
// exhaustion at 2^64 messages or a reused/copied cipher state) that cannot
// occur within a session's practical lifetime; it is converted to a panic
// here to preserve the brief-mandated (and Task 11 `internal/link`-relied
// upon) error-free public signature.
func (s *Session) Encrypt(plaintext []byte) []byte {
	ct, err := s.send.Encrypt(nil, nil, plaintext)
	if err != nil {
		panic(fmt.Sprintf("noiseconn: encrypt: %v", err))
	}
	return ct
}

func (s *Session) Decrypt(ciphertext []byte) ([]byte, error) {
	pt, err := s.recv.Decrypt(nil, nil, ciphertext)
	if err != nil {
		return nil, fmt.Errorf("noiseconn: decrypt: %w", err)
	}
	return pt, nil
}

// RekeySend applies the Noise spec §11.3 REKEY operation to the send cipher:
// k = first 32 bytes of ENCRYPT(k, 2^64-1, zerolen, zeros[32]). The nonce
// counter n is deliberately *not* reset (spec §11.3: "Rekey() only updates
// the cipher's k value, it doesn't reset n"), so the peer's matching
// RekeyRecv keeps its own n in lockstep.
//
// Callers must send the `transport.rekey` announcement frame *before* calling
// this — that frame has to be encrypted under the old key or the peer can't
// decrypt the very message telling it to rekey.
func (s *Session) RekeySend() {
	s.send.Rekey()
}

// RekeyRecv applies the same REKEY operation to the receive cipher. Callers
// must call it immediately after decrypting the peer's `transport.rekey`
// frame, before decrypting anything else — every frame after that
// announcement is sealed under the new key.
func (s *Session) RekeyRecv() {
	s.recv.Rekey()
}
