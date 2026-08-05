// apps/agent/internal/update/update_proxy_test.go
package update

import (
	"bufio"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/config"
)

// connectProxy is a minimal HTTP CONNECT proxy for tests: it accepts a
// CONNECT request, dials the requested target itself, replies 200, and then
// splices the two connections together as an opaque byte tunnel — enough to
// prove a real download routes through the configured HTTPS_PROXY rather
// than assuming tlsdial.NewTransport's Proxy field alone proves it.
type connectProxy struct {
	ln           net.Listener
	connectCount atomic.Int64

	// overrideTarget replaces the CONNECT request's target host:port for the
	// actual dial. Needed because http.ProxyFromEnvironment unconditionally
	// refuses to proxy requests whose host is loopback/localhost (see
	// golang.org/x/net/http/httpproxy's useProxy), regardless of NO_PROXY —
	// so the dialed URL must use a fake non-loopback hostname even though it
	// must, underneath, still reach the loopback-bound httptest server
	// actually serving the download.
	overrideTarget atomic.Value // string
}

func startConnectProxy() *connectProxy {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(fmt.Sprintf("update test: listen: %v", err))
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

// testProxy backs TestDownload_RespectsHTTPSProxyEnv below. Its address is
// exported into HTTPS_PROXY once, in TestMain, before any test in this
// package (or binary) runs — required because http.ProxyFromEnvironment
// memoizes its parsed environment via a package-level sync.Once
// (net/http/transport.go's envProxyOnce) for the life of the process, so a
// later t.Setenv would be silently ignored once any test has already
// triggered it (e.g. TestDownloadAndVerify_RoundTrips's plain-HTTP request).
var testProxy *connectProxy

func TestMain(m *testing.M) {
	testProxy = startConnectProxy()
	os.Setenv("HTTPS_PROXY", testProxy.url())
	os.Setenv("NO_PROXY", "")
	os.Exit(m.Run())
}

// TestDownload_RespectsHTTPSProxyEnv confirms Download — which now routes
// through tlsdial.NewTransport(cfg.TLSPin) rather than http.Get/
// http.DefaultClient — actually dials through HTTPS_PROXY end to end, for
// the pin != "" (pinned/self-signed) branch, which is the one that
// previously bypassed HTTPS_PROXY entirely (Task 13's fix covered enroll/
// link, not the update downloader). The pin == "" branch shares
// tlsdial.NewTransport's identical Proxy wiring and is covered generically
// by tlsdial_test.go; a self-signed test server can't exercise it here
// without also faking the system trust store.
func TestDownload_RespectsHTTPSProxyEnv(t *testing.T) {
	content := []byte("fake binary contents for proxy test")
	sum := sha256.Sum256(content)
	wantHash := hex.EncodeToString(sum[:])

	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(content)
	}))
	defer srv.Close()

	certSum := sha256.Sum256(srv.Certificate().RawSubjectPublicKeyInfo)
	pin := base64.StdEncoding.EncodeToString(certSum[:])

	// srv.URL is loopback (127.0.0.1:PORT), which http.ProxyFromEnvironment
	// always dials direct — see connectProxy.overrideTarget's doc comment —
	// so cfg.ServerURL below uses a fake non-loopback hostname sharing the
	// real server's port, and the test proxy is told to actually dial the
	// real (loopback) target underneath.
	realAddr := strings.TrimPrefix(srv.URL, "https://")
	_, port, err := net.SplitHostPort(realAddr)
	if err != nil {
		t.Fatalf("split srv address %q: %v", realAddr, err)
	}
	testProxy.setOverrideTarget(realAddr)
	defer testProxy.setOverrideTarget("")

	before := testProxy.connectCount.Load()
	cfg := &config.Config{ServerURL: "https://update-test-target.example.com:" + port, TLSPin: pin}
	instr := Instruction{Version: "0.2.0", SHA256: wantHash, Arch: "amd64", OS: "linux"}

	tmpPath, err := Download(cfg, instr)
	if err != nil {
		t.Fatalf("Download() error = %v", err)
	}
	defer os.Remove(tmpPath)

	if got := testProxy.connectCount.Load() - before; got != 1 {
		t.Errorf("proxy CONNECT count delta = %d, want 1 — Download did not route through HTTPS_PROXY", got)
	}
	if err := VerifySHA256(tmpPath, wantHash); err != nil {
		t.Errorf("VerifySHA256() error = %v, want nil", err)
	}
}
