// Package tlsdial builds a *websocket.Dialer that honors agent.toml's
// tls_pin — the agent-side counterpart of agent_install.py's SPKI pinning
// (Task 17). Self-signed certs generated for LAN appliances commonly carry
// only a legacy CN (no SAN), which Go's standard chain verifier rejects
// outright regardless of trust, so pinning bypasses chain/hostname
// verification entirely in favor of an exact SPKI key match.
package tlsdial

import (
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"fmt"

	"github.com/gorilla/websocket"
)

// NewDialer returns a websocket.Dialer configured for the server's TLS mode.
//
// When pin is empty, dials with the standard system CA trust store (publicly
// trusted certs, e.g. Let's Encrypt — spec's "public" tls_mode).
//
// When pin is non-empty (self-signed / TOFU install, spec's "self_signed"
// tls_mode), standard verification is replaced with an exact match of the
// leaf certificate's base64 SHA-256 SPKI digest against pin.
func NewDialer(pin string) *websocket.Dialer {
	if pin == "" {
		return websocket.DefaultDialer
	}
	return &websocket.Dialer{
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, // verified below via VerifyPeerCertificate
			VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {
				if len(rawCerts) == 0 {
					return fmt.Errorf("tlsdial: server presented no certificate")
				}
				cert, err := x509.ParseCertificate(rawCerts[0])
				if err != nil {
					return fmt.Errorf("tlsdial: parse server certificate: %w", err)
				}
				sum := sha256.Sum256(cert.RawSubjectPublicKeyInfo)
				got := base64.StdEncoding.EncodeToString(sum[:])
				if got != pin {
					return fmt.Errorf("tlsdial: certificate pin mismatch (got %s, want %s)", got, pin)
				}
				return nil
			},
		},
	}
}
