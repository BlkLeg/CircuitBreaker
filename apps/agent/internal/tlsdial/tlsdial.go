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
	"net/http"

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
//
// Both cases route through http.ProxyFromEnvironment, so HTTPS_PROXY/NO_PROXY
// (and http_proxy/no_proxy) are honored for the wss:// dial exactly as they
// would be for a plain net/http request — see Dial's internal ws->http /
// wss->https scheme rewrite, which is what makes ProxyFromEnvironment's
// http/https scheme check match a websocket URL at all. websocket.DefaultDialer
// (the pin == "" case) already sets this; the pin != "" case must set it
// explicitly, since a bare &websocket.Dialer{} literal leaves Proxy nil —
// silently bypassing any configured proxy — rather than falling back to any
// default.
func NewDialer(pin string) *websocket.Dialer {
	if pin == "" {
		return websocket.DefaultDialer
	}
	return &websocket.Dialer{
		Proxy:           http.ProxyFromEnvironment,
		TLSClientConfig: pinnedTLSConfig(pin),
	}
}

// NewTransport returns an *http.Transport configured for the same TLS trust
// policy as NewDialer, for callers making plain HTTPS requests (e.g. the
// update binary download) rather than a websocket upgrade — see
// internal/update.Download, which previously bypassed this pinning entirely
// via a bare http.Get.
//
// When pin is empty, TLSClientConfig is left nil, which makes the transport
// fall back to Go's standard system CA trust store — the same "public"
// tls_mode trust NewDialer's pin == "" branch gets via
// websocket.DefaultDialer's underlying transport.
//
// When pin is non-empty, verification is replaced with the identical exact
// SPKI-digest match NewDialer's pin != "" branch uses.
//
// Both branches set Proxy: http.ProxyFromEnvironment explicitly, matching
// NewDialer, so HTTPS_PROXY/NO_PROXY are honored the same way for downloads
// as for the link/enroll websocket connections.
func NewTransport(pin string) *http.Transport {
	t := &http.Transport{Proxy: http.ProxyFromEnvironment}
	if pin == "" {
		return t
	}
	t.TLSClientConfig = pinnedTLSConfig(pin)
	return t
}

// pinnedTLSConfig builds the tls.Config shared by NewDialer and NewTransport's
// pin != "" branches: standard chain/hostname verification is disabled in
// favor of an exact match of the leaf certificate's base64 SHA-256 SPKI
// digest against pin (see package doc for why — self-signed LAN certs
// commonly lack a SAN, which the standard verifier rejects outright).
func pinnedTLSConfig(pin string) *tls.Config {
	return &tls.Config{
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
	}
}
