// apps/agent/internal/tlsdial/tlsdial_test.go
package tlsdial

import (
	"bufio"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync/atomic"
	"testing"

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

// TestNewDialer_ProxyRespectsHTTPSProxyEnv exercises both NewDialer branches
// (pin == "" and pin != "") against the same fixed env, since the pin != ""
// branch builds its own *websocket.Dialer literal rather than reusing
// websocket.DefaultDialer — it must independently wire up Proxy or it will
// silently ignore HTTPS_PROXY.
func TestNewDialer_ProxyRespectsHTTPSProxyEnv(t *testing.T) {
	wantProxy, err := url.Parse(testProxy.url())
	if err != nil {
		t.Fatal(err)
	}

	for _, pin := range []string{"", "deadbeef"} {
		t.Run(fmt.Sprintf("pin=%q", pin), func(t *testing.T) {
			d := NewDialer(pin)
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
	for _, pin := range []string{"", "deadbeef"} {
		t.Run(fmt.Sprintf("pin=%q", pin), func(t *testing.T) {
			d := NewDialer(pin)
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
// NewDialer(pin) (the self-signed / TOFU branch — the one that regressed)
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

	d := NewDialer(pin)
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
