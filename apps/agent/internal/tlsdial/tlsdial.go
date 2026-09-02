// Package tlsdial builds a *websocket.Dialer (and *http.Transport) that
// honors agent.toml's TLS trust policy — the agent-side counterpart of
// agent_install.py's SPKI pinning (Task 17). Self-signed certs generated for
// LAN appliances commonly carry only a legacy CN (no SAN), which Go's
// standard chain verifier rejects outright regardless of trust, so pinning
// bypasses chain/hostname verification entirely in favor of an exact SPKI
// key match.
//
// The policy is carried as a Trust rather than a bare pin string so that a
// server-side certificate rotation can advertise a successor pin alongside
// the current one (a `tls.pin.rotate` frame) and so that a cutover away
// from pinning entirely — to standard public-CA verification — can be
// expressed too. See Trust's doc comment for why a pin-only value cannot
// say that.
package tlsdial

import (
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"fmt"
	"net/http"

	"github.com/gorilla/websocket"
)

// Trust is the TLS trust policy one dial should honor.
//
// Mode "public" means standard system-CA verification (the spec's "public"
// tls_mode — publicly trusted certs, e.g. Let's Encrypt), and Pins is
// ignored. Mode "self_signed" replaces chain/hostname verification with an
// exact match of the leaf's base64 SHA-256 SPKI digest against Pins, which
// is ordered: the effective policy first, then a successor advertised by a
// `tls.pin.rotate` frame and still inside its overlap window.
//
// Carrying the mode rather than a bare pin string is what makes a cutover
// *between* modes expressible. agent_install._tls_mode_and_pin returns an
// empty pin for a Let's Encrypt certificate and an SPKI digest otherwise, so
// a server moving in either direction changes which kind of verification
// applies — not merely which digest matches. A pin-only advertisement could
// not say "stop pinning", and every agent would be stranded on the cutover.
type Trust struct {
	Mode string
	Pins []string
}

const (
	ModeSelfSigned = "self_signed"
	ModePublic     = "public"
)

// tlsConfig returns the *tls.Config this policy needs, or nil when standard
// verification applies and the caller should leave TLSClientConfig unset.
func (t Trust) tlsConfig() *tls.Config {
	if t.Mode == ModePublic {
		return nil
	}
	pins := append([]string(nil), t.Pins...)
	return &tls.Config{
		InsecureSkipVerify: true, // verified below via VerifyPeerCertificate
		VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {
			if len(rawCerts) == 0 {
				return fmt.Errorf("tlsdial: server presented no certificate")
			}
			// Fail closed. A self_signed policy with no candidates is a
			// configuration bug, and accepting anything here would silently
			// convert it into unverified TLS.
			if len(pins) == 0 {
				return fmt.Errorf("tlsdial: no certificate pin configured for self-signed trust")
			}
			cert, err := x509.ParseCertificate(rawCerts[0])
			if err != nil {
				return fmt.Errorf("tlsdial: parse server certificate: %w", err)
			}
			sum := sha256.Sum256(cert.RawSubjectPublicKeyInfo)
			got := base64.StdEncoding.EncodeToString(sum[:])
			for _, pin := range pins {
				if got == pin {
					return nil
				}
			}
			return fmt.Errorf(
				"tlsdial: certificate pin mismatch (got %s, tried %d candidate(s))",
				got, len(pins),
			)
		},
	}
}

// Matches reports whether cert satisfies this policy's pin set, and which
// candidate index matched. Used by internal/link to tell the server which
// policy a completed handshake actually used (the `tls_pin_kind` field on
// hello) and to decide whether to promote. Mode "public" always matches at
// index 0: standard verification already succeeded by the time this is asked.
func (t Trust) Matches(cert *x509.Certificate) (int, bool) {
	if t.Mode == ModePublic {
		return 0, true
	}
	sum := sha256.Sum256(cert.RawSubjectPublicKeyInfo)
	got := base64.StdEncoding.EncodeToString(sum[:])
	for i, pin := range t.Pins {
		if got == pin {
			return i, true
		}
	}
	return -1, false
}

// NewDialer returns a websocket.Dialer honoring trust.
//
// Both modes route through http.ProxyFromEnvironment, so HTTPS_PROXY/NO_PROXY
// (and http_proxy/no_proxy) are honored for the wss:// dial exactly as they
// would be for a plain net/http request — see Dial's internal ws->http /
// wss->https scheme rewrite, which is what makes ProxyFromEnvironment's
// http/https scheme check match a websocket URL at all. websocket.DefaultDialer
// already sets this; the pinned branch must set it explicitly, since a bare
// &websocket.Dialer{} literal leaves Proxy nil — silently bypassing any
// configured proxy — rather than falling back to a default.
func NewDialer(trust Trust) *websocket.Dialer {
	cfg := trust.tlsConfig()
	if cfg == nil {
		return websocket.DefaultDialer
	}
	return &websocket.Dialer{
		Proxy:           http.ProxyFromEnvironment,
		TLSClientConfig: cfg,
		// Carried over from websocket.DefaultDialer deliberately. gorilla
		// applies this only `if d.HandshakeTimeout != 0`, so a bare literal
		// left the pinned path — the one every real deployment takes,
		// because the installer always writes a tls_pin — with no bound at
		// all, while the unpinned fallback kept the 45s one. A half-open
		// connection then hangs the caller forever.
		HandshakeTimeout: websocket.DefaultDialer.HandshakeTimeout,
	}
}

// NewTransport returns an *http.Transport with the same trust policy as
// NewDialer, for callers making plain HTTPS requests (the update binary and
// signature downloads) rather than a websocket upgrade.
func NewTransport(trust Trust) *http.Transport {
	t := &http.Transport{Proxy: http.ProxyFromEnvironment}
	t.TLSClientConfig = trust.tlsConfig()
	return t
}
