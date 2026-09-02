// apps/agent/internal/tlsdial/tlsdial_test.go
package tlsdial

import (
	"bufio"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

// connectProxy is a minimal HTTP CONNECT proxy for tests: it accepts a
// CONNECT request, dials the requested target itself, replies 200, and then
// splices the two connections together as an opaque byte tunnel — enough to
// prove a real dial routes through the configured HTTPS_PROXY rather than
// just that the Proxy field resolves correctly.
type connectProxy struct {
	ln           net.Listener
	connectCount atomic.Int64

	// overrideTarget, when non-empty, replaces the CONNECT request's target
	// host:port for the actual dial. Needed because http.ProxyFromEnvironment
	// unconditionally refuses to proxy requests whose host is loopback/
	// localhost (see golang.org/x/net/http/httpproxy's useProxy), regardless
	// of NO_PROXY — so a test target has to look non-loopback in the dialed
	// URL even though it must, underneath, still reach the loopback-bound
	// httptest server actually running it.
	overrideTarget atomic.Value // string
}

func startConnectProxy() *connectProxy {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(fmt.Sprintf("tlsdial test: listen: %v", err))
	}
	p := &connectProxy{ln: ln}
	go p.serve()
	return p
}

func (p *connectProxy) url() string { return "http://" + p.ln.Addr().String() }

func (p *connectProxy) setOverrideTarget(addr string) { p.overrideTarget.Store(addr) }

func (p *connectProxy) serve() {
	for {
		conn, err := p.ln.Accept()
		if err != nil {
			return
		}
		go p.handle(conn)
	}
}

func (p *connectProxy) handle(conn net.Conn) {
	defer conn.Close()
	br := bufio.NewReader(conn)
	req, err := http.ReadRequest(br)
	if err != nil {
		return
	}
	if req.Method != http.MethodConnect {
		_, _ = conn.Write([]byte("HTTP/1.1 405 Method Not Allowed\r\n\r\n"))
		return
	}
	p.connectCount.Add(1)

	targetAddr := req.Host
	if v, _ := p.overrideTarget.Load().(string); v != "" {
		targetAddr = v
	}
	target, err := net.Dial("tcp", targetAddr)
	if err != nil {
		_, _ = conn.Write([]byte("HTTP/1.1 502 Bad Gateway\r\n\r\n"))
		return
	}
	defer target.Close()

	if _, err := conn.Write([]byte("HTTP/1.1 200 Connection Established\r\n\r\n")); err != nil {
		return
	}

	errc := make(chan error, 2)
	go func() { _, err := io.Copy(target, br); errc <- err }()
	go func() { _, err := io.Copy(conn, target); errc <- err }()
	<-errc
}

// testProxy backs every test in this file. Its address is exported into
// HTTPS_PROXY once, in TestMain, before any test runs.
//
// This single, fixed setup (rather than each test calling t.Setenv with its
// own HTTPS_PROXY value) is required by a real net/http gotcha:
// http.ProxyFromEnvironment memoizes its parsed environment via a
// package-level sync.Once (net/http/transport.go's envProxyOnce) for the
// life of the process, so whichever test happens to trigger it first "wins"
// for every later test in the same binary — a later t.Setenv is silently
// ignored. Fixing the proxy env once, before any test can trigger that
// sync.Once, sidesteps the gotcha entirely rather than fighting it.
var testProxy *connectProxy

func TestMain(m *testing.M) {
	testProxy = startConnectProxy()
	os.Setenv("HTTPS_PROXY", testProxy.url())
	os.Setenv("NO_PROXY", "excluded.example")
	os.Exit(m.Run())
}

// selfSignedLeaf returns a fresh self-signed certificate and the base64
// SHA-256 SPKI digest that pins it — the same value agent_install._spki_pin
// computes server-side.
func selfSignedLeaf(t *testing.T) (*x509.Certificate, string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "cb-test"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create certificate: %v", err)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatalf("parse certificate: %v", err)
	}
	sum := sha256.Sum256(cert.RawSubjectPublicKeyInfo)
	return cert, base64.StdEncoding.EncodeToString(sum[:])
}

// verify drives the VerifyPeerCertificate callback the way crypto/tls does.
func verify(t *testing.T, trust Trust, cert *x509.Certificate) error {
	t.Helper()
	cfg := trust.tlsConfig()
	if cfg == nil {
		t.Fatal("tlsConfig() = nil, want a config with VerifyPeerCertificate")
	}
	return cfg.VerifyPeerCertificate([][]byte{cert.Raw}, nil)
}

func TestTrust_AcceptsTheEffectivePin(t *testing.T) {
	cert, pin := selfSignedLeaf(t)
	if err := verify(t, Trust{Mode: "self_signed", Pins: []string{pin}}, cert); err != nil {
		t.Errorf("verify with the matching pin = %v, want nil", err)
	}
}

// The whole point of the successor mechanism: during the overlap, a leaf
// matching *either* candidate is accepted.
func TestTrust_AcceptsTheSuccessorPin(t *testing.T) {
	_, oldPin := selfSignedLeaf(t)
	newCert, newPin := selfSignedLeaf(t)
	trust := Trust{Mode: "self_signed", Pins: []string{oldPin, newPin}}
	if err := verify(t, trust, newCert); err != nil {
		t.Errorf("verify with the successor pin = %v, want nil", err)
	}
}

func TestTrust_RefusesAnUnrelatedLeaf(t *testing.T) {
	_, pin := selfSignedLeaf(t)
	other, _ := selfSignedLeaf(t)
	if err := verify(t, Trust{Mode: "self_signed", Pins: []string{pin}}, other); err == nil {
		t.Error("verify with an unrelated leaf = nil, want a pin-mismatch error")
	}
}

// A self_signed trust with no pins at all must fail closed. Falling through
// to "accept anything" would turn a missing-config bug into silent
// unverified TLS.
func TestTrust_SelfSignedWithNoPinsFailsClosed(t *testing.T) {
	cert, _ := selfSignedLeaf(t)
	if err := verify(t, Trust{Mode: "self_signed"}, cert); err == nil {
		t.Error("verify with no pins = nil, want an error")
	}
}

// "public" means standard system-CA verification, which is expressed by
// leaving TLSClientConfig's verification alone — so there is no
// VerifyPeerCertificate callback and no InsecureSkipVerify.
func TestTrust_PublicModeUsesStandardVerification(t *testing.T) {
	if cfg := (Trust{Mode: "public"}).tlsConfig(); cfg != nil {
		t.Errorf("public-mode tlsConfig() = %+v, want nil (standard verification)", cfg)
	}
	tr := NewTransport(Trust{Mode: "public"})
	if tr.TLSClientConfig != nil {
		t.Errorf("public-mode transport TLSClientConfig = %+v, want nil", tr.TLSClientConfig)
	}
}

// Matches is what internal/link uses to decide whether to promote and what
// to report as tls_pin_kind — which is what gates certificate activation.
// It needs its own tests: verification succeeding says a leaf was accepted,
// not *which* candidate accepted it.
func TestTrust_MatchesReportsWhichCandidateMatched(t *testing.T) {
	_, oldPin := selfSignedLeaf(t)
	newCert, newPin := selfSignedLeaf(t)
	trust := Trust{Mode: ModeSelfSigned, Pins: []string{oldPin, newPin}}

	idx, ok := trust.Matches(newCert)
	if !ok {
		t.Fatal("Matches on the successor leaf = false, want true")
	}
	if idx != 1 {
		t.Errorf("Matches index = %d, want 1 (the successor)", idx)
	}
}

func TestTrust_MatchesReportsIndexZeroForTheCurrentPin(t *testing.T) {
	cert, pin := selfSignedLeaf(t)
	_, otherPin := selfSignedLeaf(t)
	trust := Trust{Mode: ModeSelfSigned, Pins: []string{pin, otherPin}}

	idx, ok := trust.Matches(cert)
	if !ok || idx != 0 {
		t.Errorf("Matches = (%d, %v), want (0, true)", idx, ok)
	}
}

func TestTrust_MatchesReportsFalseForAnUnrelatedLeaf(t *testing.T) {
	_, pin := selfSignedLeaf(t)
	other, _ := selfSignedLeaf(t)

	if _, ok := (Trust{Mode: ModeSelfSigned, Pins: []string{pin}}).Matches(other); ok {
		t.Error("Matches on an unrelated leaf = true, want false")
	}
}

// Public mode always matches at index 0: standard verification already
// succeeded by the time Matches is asked, so there is no candidate to pick.
func TestTrust_MatchesAlwaysSucceedsInPublicMode(t *testing.T) {
	cert, _ := selfSignedLeaf(t)
	idx, ok := (Trust{Mode: ModePublic}).Matches(cert)
	if !ok || idx != 0 {
		t.Errorf("Matches in public mode = (%d, %v), want (0, true)", idx, ok)
	}
}

// Regression guard for the bug tlsdial.go documents: a bare
// &websocket.Dialer{} literal leaves HandshakeTimeout at zero, which gorilla
// treats as unbounded, so a half-open connection hangs the caller forever.
func TestNewDialer_PinnedPathKeepsAHandshakeTimeout(t *testing.T) {
	_, pin := selfSignedLeaf(t)
	d := NewDialer(Trust{Mode: "self_signed", Pins: []string{pin}})
	if d.HandshakeTimeout == 0 {
		t.Error("pinned dialer HandshakeTimeout = 0 (unbounded), want the default")
	}
	if d.Proxy == nil {
		t.Error("pinned dialer Proxy = nil, want ProxyFromEnvironment")
	}
}

// TestNewDialer_ProxyRespectsHTTPSProxyEnv exercises both NewDialer branches
// (public mode and self-signed/pinned mode) against the same fixed env,
// since the pinned branch builds its own *websocket.Dialer literal rather
// than reusing websocket.DefaultDialer — it must independently wire up Proxy
// or it will silently ignore HTTPS_PROXY.
func TestNewDialer_ProxyRespectsHTTPSProxyEnv(t *testing.T) {
	wantProxy, err := url.Parse(testProxy.url())
	if err != nil {
		t.Fatal(err)
	}

	trusts := []Trust{
		{Mode: ModePublic},
		{Mode: ModeSelfSigned, Pins: []string{"deadbeef"}},
	}
	for _, trust := range trusts {
		t.Run(fmt.Sprintf("mode=%s", trust.Mode), func(t *testing.T) {
			d := NewDialer(trust)
			if d.Proxy == nil {
				t.Fatal("Dialer.Proxy is nil, want a func that honors HTTPS_PROXY")
			}

			// gorilla/websocket's Dial rewrites the URL scheme wss -> https
			// (ws -> http) before invoking Proxy, so a plain https:// request
			// here mirrors what the dialer actually evaluates for a wss://
			// target.
			req, err := http.NewRequest(http.MethodGet, "https://target.example/api/v1/agents/link", nil)
			if err != nil {
				t.Fatal(err)
			}
			got, err := d.Proxy(req)
			if err != nil {
				t.Fatalf("Proxy() error = %v", err)
			}
			if got == nil || got.String() != wantProxy.String() {
				t.Errorf("Proxy() = %v, want %v", got, wantProxy)
			}
		})
	}
}

// TestNewDialer_ProxyRespectsNoProxyEnv confirms NO_PROXY exclusions are
// honored on both branches too.
func TestNewDialer_ProxyRespectsNoProxyEnv(t *testing.T) {
	trusts := []Trust{
		{Mode: ModePublic},
		{Mode: ModeSelfSigned, Pins: []string{"deadbeef"}},
	}
	for _, trust := range trusts {
		t.Run(fmt.Sprintf("mode=%s", trust.Mode), func(t *testing.T) {
			d := NewDialer(trust)
			if d.Proxy == nil {
				t.Fatal("Dialer.Proxy is nil, want a func that honors NO_PROXY")
			}

			req, err := http.NewRequest(http.MethodGet, "https://excluded.example/api/v1/agents/link", nil)
			if err != nil {
				t.Fatal(err)
			}
			got, err := d.Proxy(req)
			if err != nil {
				t.Fatalf("Proxy() error = %v", err)
			}
			if got != nil {
				t.Errorf("Proxy() = %v, want nil (host is in NO_PROXY)", got)
			}
		})
	}
}

// TestNewDialer_DialsThroughHTTPSProxy proves the wiring end-to-end: with
// HTTPS_PROXY pointed at a local CONNECT proxy, a real wss:// dial through
// NewDialer (the self-signed / TOFU branch — the one that regressed)
// reaches its target only via that proxy.
func TestNewDialer_DialsThroughHTTPSProxy(t *testing.T) {
	upgrader := websocket.Upgrader{}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer c.Close()
		_ = c.WriteMessage(websocket.TextMessage, []byte("hello"))
	}))
	defer srv.Close()

	sum := sha256.Sum256(srv.Certificate().RawSubjectPublicKeyInfo)
	pin := base64.StdEncoding.EncodeToString(sum[:])

	// srv.URL is loopback (127.0.0.1:PORT), which http.ProxyFromEnvironment
	// always dials direct (see connectProxy.overrideTarget's doc comment) —
	// so the dialed URL uses a fake non-loopback hostname sharing the real
	// server's port, and the test proxy is told to actually dial the real
	// (loopback) target underneath.
	realAddr := strings.TrimPrefix(srv.URL, "https://")
	_, port, err := net.SplitHostPort(realAddr)
	if err != nil {
		t.Fatalf("split srv address %q: %v", realAddr, err)
	}
	testProxy.setOverrideTarget(realAddr)
	defer testProxy.setOverrideTarget("")

	before := testProxy.connectCount.Load()
	wsURL := "wss://agent-test-target.example:" + port + "/"

	d := NewDialer(Trust{Mode: ModeSelfSigned, Pins: []string{pin}})
	conn, resp, err := d.Dial(wsURL, nil)
	if err != nil {
		status := "<nil resp>"
		if resp != nil {
			status = resp.Status
		}
		t.Fatalf("Dial() error = %v (resp status = %s)", err, status)
	}
	defer conn.Close()

	if got := testProxy.connectCount.Load() - before; got != 1 {
		t.Errorf("proxy CONNECT count delta = %d, want 1 — dial did not route through HTTPS_PROXY", got)
	}

	_, msg, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("ReadMessage() error = %v", err)
	}
	if string(msg) != "hello" {
		t.Errorf("message = %q, want %q", msg, "hello")
	}
}
