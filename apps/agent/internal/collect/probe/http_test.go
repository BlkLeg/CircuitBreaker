package probe

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

// httpHarness is the seam every test below runs through. It gives the checker a fake resolver
// and a fake dialer so a test can put an httptest server behind an address that is *inside*
// testScope() — 127.0.0.1 is permanently special-use in netscope, so a probe test can never
// simply point at a loopback listener and still exercise the scope path it is there to prove.
//
// The scope check itself is untouched: the checker resolves through h.resolve, evaluates the
// answers against the real netscope, and only then hands h.dial the address it approved. So
// h.dialed is exactly "what the agent decided to connect to", which is what the security tests
// assert on.
type httpHarness struct {
	mu       sync.Mutex
	dialed   []string
	resolved []string
	answers  map[string][]string
	routes   map[string]string
	// failAfter, when non-zero, refuses every dial past the first failAfter. It is how a test
	// makes the certificate capture fail while the request itself succeeds.
	failAfter int

	checker *httpChecker
}

func newHTTPHarness(t *testing.T) *httpHarness {
	t.Helper()
	h := &httpHarness{answers: map[string][]string{}, routes: map[string]string{}}
	checker, ok := newHTTPChecker(Deps{Scope: testScope, Resolve: h.resolve}).(*httpChecker)
	if !ok {
		t.Fatalf("newHTTPChecker returned %T, want *httpChecker", newHTTPChecker(Deps{}))
	}
	checker.dial = h.dial
	h.checker = checker
	return h
}

func (h *httpHarness) resolve(_ context.Context, host string) ([]string, error) {
	h.mu.Lock()
	h.resolved = append(h.resolved, host)
	answer, ok := h.answers[host]
	h.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("probe test: no DNS answer configured for %q", host)
	}
	return answer, nil
}

func (h *httpHarness) dial(ctx context.Context, network, addr string) (net.Conn, error) {
	h.mu.Lock()
	h.dialed = append(h.dialed, addr)
	backend, ok := h.routes[addr]
	if h.failAfter > 0 && len(h.dialed) > h.failAfter {
		ok = false
	}
	h.mu.Unlock()
	if !ok {
		return nil, &net.OpError{Op: "dial", Net: network, Err: errors.New("connection refused")}
	}
	return (&net.Dialer{}).DialContext(ctx, network, backend)
}

// publish makes hostname resolve to ip and routes connections to that address to srv.
func (h *httpHarness) publish(t *testing.T, hostname, ip string, srv *httptest.Server) {
	t.Helper()
	parsed, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse test server URL: %v", err)
	}
	port := "80"
	if parsed.Scheme == "https" {
		port = "443"
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	h.answers[hostname] = []string{ip}
	h.routes[net.JoinHostPort(ip, port)] = parsed.Host
}

func (h *httpHarness) answer(hostname string, addrs ...string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.answers[hostname] = addrs
}

func (h *httpHarness) dials() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.dialed...)
}

func (h *httpHarness) lookups() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.resolved...)
}

// httpConfigJSON builds a probe.assign config the way the backend serializes monitor_items.params.
func httpConfigJSON(t *testing.T, fields map[string]any) json.RawMessage {
	t.Helper()
	raw, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal http config: %v", err)
	}
	return raw
}

func httpSampleValue(t *testing.T, out Outcome, metric string) float64 {
	t.Helper()
	for _, sample := range out.Samples {
		if sample.Metric == metric {
			return sample.Value
		}
	}
	t.Fatalf("outcome has no %q sample: %+v", metric, out.Samples)
	return 0
}

func httpSampleMetrics(out Outcome) []string {
	names := make([]string, 0, len(out.Samples))
	for _, sample := range out.Samples {
		names = append(names, sample.Metric)
	}
	return names
}

// ---------------------------------------------------------------------------
// Parity with collectors/web.py::collect_http
// ---------------------------------------------------------------------------

func TestHTTPChecker_SampleOrderIsAvailLatencyStatusThenCertDays(t *testing.T) {
	t.Parallel()

	plain := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(plain.Close)

	h := newHTTPHarness(t)
	h.publish(t, "plain.test", inScopeHost, plain)

	out, err := h.checker.Check(context.Background(), "plain.test", httpConfigJSON(t, map[string]any{
		"url": "http://plain.test/",
	}))
	if err != nil {
		t.Fatalf("plain check: %v", err)
	}
	if got, want := httpSampleMetrics(out), []string{"avail", "latency_ms", "http_status"}; !httpSameStrings(got, want) {
		t.Fatalf("plain sample order = %v, want %v", got, want)
	}

	secure := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(secure.Close)

	hs := newHTTPHarness(t)
	hs.publish(t, "secure.test", otherInScopeHost, secure)

	out, err = hs.checker.Check(context.Background(), "secure.test", httpConfigJSON(t, map[string]any{
		"url":        "https://secure.test/",
		"verify_tls": false,
	}))
	if err != nil {
		t.Fatalf("tls check: %v", err)
	}
	want := []string{"avail", "latency_ms", "http_status", "cert_days_remaining"}
	if got := httpSampleMetrics(out); !httpSameStrings(got, want) {
		t.Fatalf("tls sample order = %v, want %v", got, want)
	}
	if !out.Up {
		t.Fatalf("expected an up outcome, got %+v", out)
	}
	if httpSampleValue(t, out, "avail") != 1 {
		t.Fatalf("avail = %v, want 1", httpSampleValue(t, out, "avail"))
	}
	if httpSampleValue(t, out, "http_status") != 200 {
		t.Fatalf("http_status = %v, want 200", httpSampleValue(t, out, "http_status"))
	}
	tlsDetails, ok := out.Details["tls"].(map[string]any)
	if !ok {
		t.Fatalf("details = %+v, want a tls object", out.Details)
	}
	for _, key := range []string{"subject_cn", "issuer_cn", "expires_at", "days_remaining"} {
		if _, present := tlsDetails[key]; !present {
			t.Fatalf("tls details are missing %q: %+v", key, tlsDetails)
		}
	}
}

func TestHTTPChecker_AcceptedStatusRangesAndBareCodes(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		code := 200
		if _, err := fmt.Sscanf(r.URL.Path, "/%d", &code); err != nil {
			code = 200
		}
		w.WriteHeader(code)
	}))
	t.Cleanup(srv.Close)

	cases := []struct {
		name   string
		status int
		ranges []string
		up     bool
	}{
		{"default range accepts 200", 200, nil, true},
		{"default range accepts 299", 299, nil, true},
		{"empty list falls back to 200-299", 404, []string{}, false},
		{"empty list accepts 204", 204, []string{}, true},
		{"bare code matches", 302, []string{"301", "302"}, true},
		{"bare code does not match", 200, []string{"301", "302"}, false},
		{"inclusive range lower bound", 400, []string{"400-499"}, true},
		{"inclusive range upper bound", 499, []string{"400-499"}, true},
		{"range excludes just outside", 500, []string{"400-499"}, false},
		{"whitespace inside a range is tolerated", 201, []string{" 200 - 299 "}, true},
		{"non-numeric range never matches", 404, []string{"4xx"}, false},
		{"leading dash is not a range", 500, []string{"-500"}, false},
		{"multiple entries, second matches", 503, []string{"200-299", "503"}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			h := newHTTPHarness(t)
			h.publish(t, "status.test", inScopeHost, srv)
			config := map[string]any{"url": fmt.Sprintf("http://status.test/%d", tc.status)}
			if tc.ranges != nil {
				config["accepted_statuses"] = tc.ranges
			}
			out, err := h.checker.Check(context.Background(), "status.test", httpConfigJSON(t, config))
			if err != nil {
				t.Fatalf("check: %v", err)
			}
			if out.Up != tc.up {
				t.Fatalf("up = %v, want %v (msg %q)", out.Up, tc.up, out.Msg)
			}
			wantAvail := 0.0
			if tc.up {
				wantAvail = 1
			}
			if got := httpSampleValue(t, out, "avail"); got != wantAvail {
				t.Fatalf("avail = %v, want %v", got, wantAvail)
			}
		})
	}
}

func TestHTTPChecker_KeywordAndInvertedKeyword(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(r.URL.Query().Get("body")))
	}))
	t.Cleanup(srv.Close)

	cases := []struct {
		name   string
		body   string
		invert bool
		up     bool
	}{
		{"present and wanted", "all systems healthy", false, true},
		{"absent and wanted", "everything is on fire", false, false},
		{"present and forbidden", "all systems healthy", true, false},
		{"absent and forbidden", "everything is on fire", true, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			h := newHTTPHarness(t)
			h.publish(t, "keyword.test", inScopeHost, srv)
			out, err := h.checker.Check(context.Background(), "keyword.test", httpConfigJSON(t, map[string]any{
				"url":            "http://keyword.test/?body=" + url.QueryEscape(tc.body),
				"keyword":        "healthy",
				"keyword_invert": tc.invert,
			}))
			if err != nil {
				t.Fatalf("check: %v", err)
			}
			if out.Up != tc.up {
				t.Fatalf("up = %v, want %v (msg %q)", out.Up, tc.up, out.Msg)
			}
		})
	}

	t.Run("an empty keyword disables the check", func(t *testing.T) {
		t.Parallel()
		h := newHTTPHarness(t)
		h.publish(t, "nokeyword.test", inScopeHost, srv)
		out, err := h.checker.Check(context.Background(), "nokeyword.test", httpConfigJSON(t, map[string]any{
			"url":     "http://nokeyword.test/?body=anything",
			"keyword": "",
		}))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		if !out.Up {
			t.Fatalf("up = false, want true (msg %q)", out.Msg)
		}
	})
}

func TestHTTPChecker_DottedJSONPathWithIndexSegmentsComparedAsStrings(t *testing.T) {
	t.Parallel()

	const body = `{"items":[{"name":"a","count":3},{"name":"b"}],"ok":true,"nested":{"deep":{"v":null}}}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/not-json" {
			_, _ = w.Write([]byte("<html>nope</html>"))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)

	cases := []struct {
		name     string
		path     string
		expected any
		up       bool
		route    string
	}{
		{name: "dotted key", path: "items[0].name", expected: "a", up: true},
		{name: "an integer compares as its string", path: "items[0].count", expected: "3", up: true},
		{name: "a negative index counts from the end", path: "items[-1].name", expected: "b", up: true},
		{name: "a bool compares as Python's True", path: "ok", expected: "True", up: true},
		{name: "a null compares as Python's None", path: "nested.deep.v", expected: "None", up: true},
		{name: "an out-of-range index resolves to None", path: "items[5].name", expected: "x", up: false},
		{name: "a missing key resolves to None", path: "nope.deeper", expected: "x", up: false},
		{name: "a mismatch fails", path: "items[0].name", expected: "z", up: false},
		{name: "no expected value skips the assertion", path: "items[0].name", expected: nil, up: true},
		{name: "unparseable JSON resolves to None", path: "items[0].name", expected: "a", up: false, route: "/not-json"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			h := newHTTPHarness(t)
			h.publish(t, "json.test", inScopeHost, srv)
			config := map[string]any{
				"url":       "http://json.test" + tc.route,
				"json_path": tc.path,
			}
			if tc.expected != nil {
				config["expected_value"] = tc.expected
			}
			out, err := h.checker.Check(context.Background(), "json.test", httpConfigJSON(t, config))
			if err != nil {
				t.Fatalf("check: %v", err)
			}
			if out.Up != tc.up {
				t.Fatalf("up = %v, want %v (msg %q)", out.Up, tc.up, out.Msg)
			}
		})
	}
}

func TestHTTPChecker_MessageStringsMatchBackendExactly(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/503":
			w.WriteHeader(http.StatusServiceUnavailable)
		case "/json":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"degraded"}`))
		default:
			_, _ = w.Write([]byte("everything is on fire"))
		}
	}))
	t.Cleanup(srv.Close)

	check := func(t *testing.T, config map[string]any) Outcome {
		t.Helper()
		h := newHTTPHarness(t)
		h.publish(t, "msg.test", inScopeHost, srv)
		out, err := h.checker.Check(context.Background(), "msg.test", httpConfigJSON(t, config))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		return out
	}

	t.Run("unexpected status", func(t *testing.T) {
		t.Parallel()
		out := check(t, map[string]any{"url": "http://msg.test/503"})
		if out.Msg != "unexpected status 503" {
			t.Fatalf("msg = %q", out.Msg)
		}
	})

	t.Run("keyword not found", func(t *testing.T) {
		t.Parallel()
		out := check(t, map[string]any{"url": "http://msg.test/", "keyword": "healthy"})
		if out.Msg != "keyword not found: 'healthy'" {
			t.Fatalf("msg = %q", out.Msg)
		}
	})

	t.Run("keyword found", func(t *testing.T) {
		t.Parallel()
		out := check(t, map[string]any{
			"url": "http://msg.test/", "keyword": "on fire", "keyword_invert": true,
		})
		if out.Msg != "keyword found: 'on fire'" {
			t.Fatalf("msg = %q", out.Msg)
		}
	})

	t.Run("json mismatch", func(t *testing.T) {
		t.Parallel()
		out := check(t, map[string]any{
			"url": "http://msg.test/json", "json_path": "status", "expected_value": "ok",
		})
		if out.Msg != "json status = 'degraded', expected 'ok'" {
			t.Fatalf("msg = %q", out.Msg)
		}
	})

	t.Run("json mismatch on an unresolvable path renders None", func(t *testing.T) {
		t.Parallel()
		out := check(t, map[string]any{
			"url": "http://msg.test/json", "json_path": "missing", "expected_value": "ok",
		})
		if out.Msg != "json missing = None, expected 'ok'" {
			t.Fatalf("msg = %q", out.Msg)
		}
	})

	t.Run("success", func(t *testing.T) {
		t.Parallel()
		out := check(t, map[string]any{"url": "http://msg.test/"})
		latency := httpSampleValue(t, out, "latency_ms")
		want := fmt.Sprintf("200 in %sms", httpPyFloat(latency))
		if out.Msg != want {
			t.Fatalf("msg = %q, want %q", out.Msg, want)
		}
		if !regexp.MustCompile(`^200 in [0-9]+\.[0-9]{1,2}ms$`).MatchString(out.Msg) {
			t.Fatalf("msg %q does not have the backend's shape", out.Msg)
		}
	})
}

func TestHTTPChecker_TLSDetailsComeFromASeparateConnectionAndNeverFailTheCheck(t *testing.T) {
	t.Parallel()

	t.Run("capture opens its own handshake", func(t *testing.T) {
		t.Parallel()
		var handshakes atomic.Int64
		srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = w.Write([]byte("ok"))
		}))
		srv.TLS = &tls.Config{
			MinVersion: tls.VersionTLS12,
			GetConfigForClient: func(*tls.ClientHelloInfo) (*tls.Config, error) {
				handshakes.Add(1)
				return nil, nil
			},
		}
		srv.StartTLS()
		t.Cleanup(srv.Close)

		h := newHTTPHarness(t)
		h.publish(t, "sep.test", inScopeHost, srv)
		out, err := h.checker.Check(context.Background(), "sep.test", httpConfigJSON(t, map[string]any{
			"url": "https://sep.test/", "verify_tls": false,
		}))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		if !out.Up {
			t.Fatalf("up = false (msg %q)", out.Msg)
		}
		if got := handshakes.Load(); got != 2 {
			t.Fatalf("server saw %d handshakes, want 2 (one request, one certificate capture)", got)
		}
		if got := len(h.dials()); got != 2 {
			t.Fatalf("checker dialed %d times (%v), want 2", got, h.dials())
		}
	})

	t.Run("a failed capture leaves the check untouched", func(t *testing.T) {
		t.Parallel()
		// A plain-HTTP server behind an https:// URL: the handshake cannot succeed, which is
		// the backend's swallowed-exception path. The check itself must still report the
		// target, just without cert samples or tls details.
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = w.Write([]byte("ok"))
		}))
		t.Cleanup(srv.Close)

		h := newHTTPHarness(t)
		h.publish(t, "nocert.test", inScopeHost, srv)
		out, err := h.checker.Check(context.Background(), "nocert.test", httpConfigJSON(t, map[string]any{
			"url": "http://nocert.test/",
		}))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		if !out.Up {
			t.Fatalf("up = false (msg %q)", out.Msg)
		}
		if out.Details != nil {
			t.Fatalf("details = %+v, want none for a plain-http target", out.Details)
		}
		for _, metric := range httpSampleMetrics(out) {
			if metric == "cert_days_remaining" {
				t.Fatalf("plain http produced a cert sample: %v", httpSampleMetrics(out))
			}
		}
	})

	t.Run("an https target whose certificate capture fails still reports", func(t *testing.T) {
		t.Parallel()
		secure := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = w.Write([]byte("ok"))
		}))
		t.Cleanup(secure.Close)

		h := newHTTPHarness(t)
		h.publish(t, "brokencert.test", inScopeHost, secure)
		// Only the request's own dial succeeds; the capture's second connection is refused,
		// which is the backend's swallowed-exception path for an https target.
		h.mu.Lock()
		h.failAfter = 1
		h.mu.Unlock()

		out, err := h.checker.Check(context.Background(), "brokencert.test", httpConfigJSON(t, map[string]any{
			"url": "https://brokencert.test/", "verify_tls": false,
		}))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		if !out.Up {
			t.Fatalf("up = false (msg %q)", out.Msg)
		}
		if out.Details != nil {
			t.Fatalf("details = %+v, want none when the capture connection failed", out.Details)
		}
		if got, want := httpSampleMetrics(out), []string{"avail", "latency_ms", "http_status"}; !httpSameStrings(got, want) {
			t.Fatalf("samples = %v, want %v", got, want)
		}
	})
}

func TestHTTPChecker_TransportErrorEmitsAvailZeroWithHTTPErrorReasonAndNoLatencySample(t *testing.T) {
	t.Parallel()

	h := newHTTPHarness(t)
	// Resolvable and in scope, but nothing is listening: the dialer refuses.
	h.answer("dead.test", inScopeHost)

	out, err := h.checker.Check(context.Background(), "dead.test", httpConfigJSON(t, map[string]any{
		"url": "http://dead.test/",
	}))
	if err != nil {
		t.Fatalf("a refused connection is a datum, not a checker error: %v", err)
	}
	if out.Up {
		t.Fatalf("up = true for a refused connection")
	}
	if got, want := httpSampleMetrics(out), []string{"avail"}; !httpSameStrings(got, want) {
		t.Fatalf("samples = %v, want exactly %v", got, want)
	}
	if out.Samples[0].Value != 0 {
		t.Fatalf("avail = %v, want 0", out.Samples[0].Value)
	}
	if out.Samples[0].ErrorReason != "http_error" {
		t.Fatalf("error_reason = %q, want %q", out.Samples[0].ErrorReason, "http_error")
	}
	if !strings.HasPrefix(out.Msg, "request failed: ") {
		t.Fatalf("msg = %q, want the backend's `request failed: {ExcType}` shape", out.Msg)
	}
	if strings.Contains(out.Msg, "dead.test") || strings.Contains(out.Msg, inScopeHost) {
		t.Fatalf("msg %q leaks the request URL", out.Msg)
	}
	if out.Details != nil {
		t.Fatalf("details = %+v, want none on a transport failure", out.Details)
	}
}

// ---------------------------------------------------------------------------
// Security invariants (§5, D-10)
// ---------------------------------------------------------------------------

func TestHTTPChecker_RejectsNonHTTPSchemeBeforeResolving(t *testing.T) {
	t.Parallel()

	for _, target := range []string{"file:///etc/shadow", "ftp://files.test/x", "gopher://a.test/"} {
		t.Run(target, func(t *testing.T) {
			t.Parallel()
			h := newHTTPHarness(t)
			h.answer("files.test", inScopeHost)
			h.answer("a.test", inScopeHost)

			_, err := h.checker.Check(context.Background(), "files.test", httpConfigJSON(t, map[string]any{
				"url": target,
			}))
			if err == nil {
				t.Fatalf("checker accepted %q", target)
			}
			if got := h.lookups(); len(got) != 0 {
				t.Fatalf("checker resolved %v before rejecting the scheme", got)
			}
			if got := h.dials(); len(got) != 0 {
				t.Fatalf("checker dialed %v for a non-http scheme", got)
			}
		})
	}
}

func TestHTTPChecker_RedirectToOutOfScopeHostIsRejected(t *testing.T) {
	t.Parallel()

	var reached atomic.Int64
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/elsewhere" {
			reached.Add(1)
			return
		}
		http.Redirect(w, r, "http://elsewhere.test/elsewhere", http.StatusFound)
	}))
	t.Cleanup(origin.Close)

	h := newHTTPHarness(t)
	h.publish(t, "origin.test", inScopeHost, origin)
	// elsewhere.test resolves out of scope; the route exists so that a checker which *did*
	// follow the hop would visibly reach the handler instead of failing to connect.
	h.answer("elsewhere.test", outOfScopeHost)
	h.mu.Lock()
	h.routes[net.JoinHostPort(outOfScopeHost, "80")] = strings.TrimPrefix(origin.URL, "http://")
	h.mu.Unlock()

	_, err := h.checker.Check(context.Background(), "origin.test", httpConfigJSON(t, map[string]any{
		"url": "http://origin.test/",
	}))
	if err == nil {
		t.Fatalf("checker followed a redirect out of scope")
	}
	var refusal *httpScopeRefusal
	if !errors.As(err, &refusal) {
		t.Fatalf("err = %v (%T), want a scope refusal", err, err)
	}
	if reached.Load() != 0 {
		t.Fatalf("the out-of-scope destination was contacted %d times", reached.Load())
	}
	for _, addr := range h.dials() {
		if strings.HasPrefix(addr, outOfScopeHost) {
			t.Fatalf("checker dialed the out-of-scope address: %v", h.dials())
		}
	}
	if strings.Contains(err.Error(), "://") {
		t.Fatalf("refusal %q echoes the request URL", err)
	}
}

func TestHTTPChecker_RedirectToPublicIPIsRejected(t *testing.T) {
	t.Parallel()

	const publicIP = "198.51.100.10"
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://"+publicIP+"/", http.StatusMovedPermanently)
	}))
	t.Cleanup(origin.Close)

	h := newHTTPHarness(t)
	h.publish(t, "hop.test", inScopeHost, origin)

	_, err := h.checker.Check(context.Background(), "hop.test", httpConfigJSON(t, map[string]any{
		"url": "http://hop.test/",
	}))
	if err == nil {
		t.Fatalf("checker followed a redirect to a public IP literal")
	}
	var refusal *httpScopeRefusal
	if !errors.As(err, &refusal) {
		t.Fatalf("err = %v (%T), want a scope refusal", err, err)
	}
	if !strings.Contains(err.Error(), publicIP) {
		t.Fatalf("refusal %q does not name the refused address", err)
	}
	for _, addr := range h.dials() {
		if strings.HasPrefix(addr, publicIP) {
			t.Fatalf("checker dialed the public IP: %v", h.dials())
		}
	}
}

func TestHTTPChecker_EveryResolvedAddressIsCheckedNotJustTheFirst(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(srv.Close)

	h := newHTTPHarness(t)
	h.publish(t, "rebind.test", inScopeHost, srv)
	// The first answer is in scope, the second is not: a checker that judged only answer[0]
	// would connect happily, which is the DNS-rebinding hole this pins shut.
	h.answer("rebind.test", inScopeHost, outOfScopeHost)

	_, err := h.checker.Check(context.Background(), "rebind.test", httpConfigJSON(t, map[string]any{
		"url": "http://rebind.test/",
	}))
	if err == nil {
		t.Fatalf("checker accepted a name with one out-of-scope answer")
	}
	var refusal *httpScopeRefusal
	if !errors.As(err, &refusal) {
		t.Fatalf("err = %v (%T), want a scope refusal", err, err)
	}
	if got := h.dials(); len(got) != 0 {
		t.Fatalf("checker dialed %v despite an out-of-scope answer", got)
	}
}

func TestHTTPChecker_ResponseBodyIsBoundedAtOneMiB(t *testing.T) {
	t.Parallel()

	const marker = "MARKER"
	serve := func(offset int) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Content-Type", "text/plain")
			_, _ = w.Write([]byte(strings.Repeat("x", offset)))
			_, _ = w.Write([]byte(marker))
			_, _ = w.Write([]byte(strings.Repeat("x", 4096)))
		}))
	}

	t.Run("a keyword ending on the last inspected byte is found", func(t *testing.T) {
		t.Parallel()
		srv := serve(httpMaxResponseBytes - len(marker))
		t.Cleanup(srv.Close)
		h := newHTTPHarness(t)
		h.publish(t, "edge.test", inScopeHost, srv)
		out, err := h.checker.Check(context.Background(), "edge.test", httpConfigJSON(t, map[string]any{
			"url": "http://edge.test/", "keyword": marker,
		}))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		if !out.Up {
			t.Fatalf("keyword inside the bound was not found: %q", out.Msg)
		}
	})

	t.Run("a keyword starting one byte past the bound is not inspected", func(t *testing.T) {
		t.Parallel()
		srv := serve(httpMaxResponseBytes)
		t.Cleanup(srv.Close)
		h := newHTTPHarness(t)
		h.publish(t, "past.test", inScopeHost, srv)
		out, err := h.checker.Check(context.Background(), "past.test", httpConfigJSON(t, map[string]any{
			"url": "http://past.test/", "keyword": marker,
		}))
		if err != nil {
			t.Fatalf("check: %v", err)
		}
		if out.Up {
			t.Fatalf("checker inspected past the 1 MiB bound")
		}
		if out.Msg != "keyword not found: 'MARKER'" {
			t.Fatalf("msg = %q", out.Msg)
		}
	})
}

func TestHTTPChecker_ResultCarriesNoRequestHeadersOrBody(t *testing.T) {
	t.Parallel()

	const (
		headerValue = "header-value-must-not-escape"
		requestBody = "request-body-must-not-escape"
	)
	var sawHeader, sawBody atomic.Bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Probe-Secret") == headerValue {
			sawHeader.Store(true)
		}
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<16))
		if string(body) == requestBody {
			sawBody.Store(true)
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(srv.Close)

	h := newHTTPHarness(t)
	h.publish(t, "echo.test", inScopeHost, srv)
	out, err := h.checker.Check(context.Background(), "echo.test", httpConfigJSON(t, map[string]any{
		"url":     "http://echo.test/",
		"method":  "post",
		"headers": map[string]string{"X-Probe-Secret": headerValue},
		"body":    requestBody,
	}))
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if !sawHeader.Load() || !sawBody.Load() {
		t.Fatalf("the request did not carry its configured header (%v) and body (%v)", sawHeader.Load(), sawBody.Load())
	}
	encoded, err := json.Marshal(out)
	if err != nil {
		t.Fatalf("marshal outcome: %v", err)
	}
	for _, secret := range []string{headerValue, requestBody} {
		if strings.Contains(string(encoded), secret) {
			t.Fatalf("outcome %s carries %q", encoded, secret)
		}
	}
	if out.Details != nil {
		t.Fatalf("details = %+v, want none for a plain-http target", out.Details)
	}
}

func TestHTTPChecker_BasicAndBearerCredentialsNeverAppearInResultOrLogs(t *testing.T) {
	t.Parallel()

	const (
		username = "probe-user"
		password = "p4ssw0rd-must-not-escape"
		token    = "t0ken-must-not-escape"
	)

	cases := []struct {
		name    string
		config  map[string]any
		secrets []string
		assert  func(t *testing.T, r *http.Request)
	}{
		{
			name: "basic",
			config: map[string]any{
				"auth_type": "basic", "username": username, "password": password,
			},
			secrets: []string{password},
			assert: func(t *testing.T, r *http.Request) {
				t.Helper()
				user, pass, ok := r.BasicAuth()
				if !ok || user != username || pass != password {
					t.Errorf("server saw basic auth (%q, %q, %v)", user, pass, ok)
				}
			},
		},
		{
			name:    "bearer",
			config:  map[string]any{"auth_type": "bearer", "token": token},
			secrets: []string{token},
			assert: func(t *testing.T, r *http.Request) {
				t.Helper()
				if got := r.Header.Get("Authorization"); got != "Bearer "+token {
					t.Errorf("Authorization = %q", got)
				}
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			// Not parallel: it replaces the process-wide log writer.
			var logs strings.Builder
			previous := log.Writer()
			log.SetOutput(&logs)
			t.Cleanup(func() { log.SetOutput(previous) })

			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				tc.assert(t, r)
				_, _ = w.Write([]byte("ok"))
			}))
			t.Cleanup(srv.Close)

			h := newHTTPHarness(t)
			h.publish(t, "auth.test", inScopeHost, srv)
			config := map[string]any{"url": "http://auth.test/"}
			for key, value := range tc.config {
				config[key] = value
			}
			out, err := h.checker.Check(context.Background(), "auth.test", httpConfigJSON(t, config))
			if err != nil {
				t.Fatalf("check: %v", err)
			}
			if !out.Up {
				t.Fatalf("up = false (msg %q)", out.Msg)
			}
			encoded, err := json.Marshal(out)
			if err != nil {
				t.Fatalf("marshal outcome: %v", err)
			}
			for _, secret := range tc.secrets {
				if strings.Contains(string(encoded), secret) {
					t.Fatalf("outcome %s carries the credential", encoded)
				}
				if strings.Contains(logs.String(), secret) {
					t.Fatalf("log output %q carries the credential", logs.String())
				}
			}
			if strings.Contains(string(encoded), "Authorization") || strings.Contains(logs.String(), "Authorization") {
				t.Fatalf("an Authorization header escaped: result=%s logs=%q", encoded, logs.String())
			}
		})
	}
}

func httpSameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
