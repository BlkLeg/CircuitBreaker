package probe

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// httpMaxResponseBytes is §5's bounded inspection window. Keyword and JSON-path assertions see
// the first mebibyte of the body and nothing more: the agent runs on somebody's NAS with a
// monitor pointed at whatever an administrator typed, so an unbounded ReadAll is a
// remote-triggerable OOM rather than a thoroughness feature.
const httpMaxResponseBytes = 1 << 20

// httpDefaultTimeout mirrors collect_http's `params.get("timeout", 10.0)`. The collector default
// is the real default, not schemas/monitor.py's: `_validate_config` persists
// `model_dump(exclude_unset=True)`, so a stored config usually has no `timeout` key at all.
const httpDefaultTimeout = 10.0

// httpMaxRedirects is net/http's own default limit, restated because CheckRedirect replaces the
// default policy wholesale — forgetting it would turn a redirect loop into an unbounded walk
// that only the assignment deadline stops.
const httpMaxRedirects = 10

// httpDefaultStatusRanges mirrors web.py's `_DEFAULT_RANGES`. An *empty* accepted_statuses list
// falls back to it, exactly like the backend's `ranges or _DEFAULT_RANGES`.
var httpDefaultStatusRanges = []string{"200-299"}

// errHTTPTooManyRedirects is the Go stand-in for httpx.TooManyRedirects, which collect_http sees
// as an ordinary transport exception.
var errHTTPTooManyRedirects = errors.New("probe: too many redirects")

// httpScopeRefusal is the agent declining to connect. It is a distinct type, not a plain error,
// because the two failure modes have opposite meanings: a transport failure is an observation
// about the target (avail=0), while a refusal says the check never ran and the monitor must keep
// its last known state.
//
// Its message is built here rather than borrowed from the wrapping *url.Error, whose Error()
// includes the request URL — which D-10 says may carry credentials in its userinfo or query.
type httpScopeRefusal struct{ msg string }

func (e *httpScopeRefusal) Error() string { return e.msg }

// httpConfig is the monitor's HttpConfig as the server sends it inside probe.assign.config.
//
// Three fields are pointers on purpose. `timeout`, `verify_tls` and `follow_redirects` all have
// non-zero defaults, and a sparse config (the normal case — see httpDefaultTimeout) must take the
// default rather than Go's zero value. `expected_value` is a pointer for the same reason
// collect_http tests `expected is not None`: an empty string is a real expectation.
type httpConfig struct {
	URL              string            `json:"url"`
	Method           string            `json:"method"`
	Headers          map[string]string `json:"headers"`
	Body             string            `json:"body"`
	Timeout          *float64          `json:"timeout"`
	AuthType         string            `json:"auth_type"`
	Username         string            `json:"username"`
	Password         string            `json:"password"`
	Token            string            `json:"token"`
	AcceptedStatuses []string          `json:"accepted_statuses"`
	Keyword          string            `json:"keyword"`
	KeywordInvert    bool              `json:"keyword_invert"`
	JSONPath         string            `json:"json_path"`
	ExpectedValue    *string           `json:"expected_value"`
	VerifyTLS        *bool             `json:"verify_tls"`
	FollowRedirects  *bool             `json:"follow_redirects"`
}

func (c httpConfig) timeout() float64 {
	if c.Timeout == nil || *c.Timeout <= 0 {
		return httpDefaultTimeout
	}
	return *c.Timeout
}

func (c httpConfig) verifyTLS() bool       { return c.VerifyTLS == nil || *c.VerifyTLS }
func (c httpConfig) followRedirects() bool { return c.FollowRedirects == nil || *c.FollowRedirects }

func (c httpConfig) method() string {
	if strings.TrimSpace(c.Method) == "" {
		return http.MethodGet
	}
	return strings.ToUpper(strings.TrimSpace(c.Method))
}

// httpChecker mirrors app.services.monitoring.collectors.web::collect_http and adds the three
// things §5 requires that the backend collector does not do: every resolved address and every
// redirect hop is validated against the agent's own scope before a connection is opened, the
// response body is inspected under a hard bound, and nothing derived from the request — headers,
// body, credentials, or the URL itself — can reach the result or a log line.
//
// It builds its own http.Transport rather than reusing internal/tlsdial: tlsdial pins the
// Circuit Breaker server's SPKI, and a monitored target has an unrelated certificate and its own
// verify_tls setting.
type httpChecker struct {
	scope   func() netscope.Scope
	resolve Resolver

	// dial is the last step, after scope has approved a concrete address. It is a field so a
	// test can put a listener behind an in-scope address: 127.0.0.1 is permanently special-use
	// in netscope, so a test that dialed loopback directly could not exercise the scope path.
	dial func(ctx context.Context, network, addr string) (net.Conn, error)
}

func newHTTPChecker(deps Deps) Checker {
	return &httpChecker{
		scope:   deps.Scope,
		resolve: deps.Resolve,
		dial:    (&net.Dialer{}).DialContext,
	}
}

func (c *httpChecker) Check(ctx context.Context, host string, cfg json.RawMessage) (Outcome, error) {
	var conf httpConfig
	if len(cfg) > 0 {
		// The decoder error is deliberately dropped: it quotes the offending input, and the
		// input is the monitor's config — which carries the password (D-10).
		if err := json.Unmarshal(cfg, &conf); err != nil {
			return Outcome{}, errors.New("probe: the monitor's http configuration could not be decoded")
		}
	}

	target := conf.URL
	if target == "" {
		target = fmt.Sprintf("http://%s/", host)
	}
	parsed, err := url.Parse(target)
	if err != nil {
		return Outcome{}, errors.New("probe: the monitor's url could not be parsed")
	}
	// The scheme gate runs before anything resolves. `file://` and `gopher://` are the reason:
	// a checker that resolved first would already have leaked the destination to the network,
	// and one that dialed first would be a local-file read primitive driven from the server.
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return Outcome{}, fmt.Errorf("probe: %q is not a probeable url scheme; only http and https are", parsed.Scheme)
	}
	if parsed.Host == "" {
		return Outcome{}, errors.New("probe: the monitor's url names no host")
	}

	requestCtx, cancel := context.WithTimeout(ctx, httpSeconds(conf.timeout()))
	defer cancel()

	status, body, latency, err := c.request(requestCtx, parsed, conf)
	if err != nil {
		var refusal *httpScopeRefusal
		if errors.As(err, &refusal) {
			// Re-returned unwrapped: the *url.Error around it names the request URL.
			return Outcome{}, refusal
		}
		if ctx.Err() != nil {
			// The run's own deadline or a probe.cancel, not the target: hand the runtime the
			// context error it knows how to classify.
			return Outcome{}, ctx.Err()
		}
		return Outcome{
			Samples: []frame.ProbeSample{{Metric: "avail", Value: 0, ErrorReason: "http_error"}},
			Msg:     "request failed: " + httpExceptionName(err),
		}, nil
	}

	samples := []frame.ProbeSample{
		{Metric: "latency_ms", Value: latency},
		{Metric: "http_status", Value: float64(status)},
	}
	// Certificate capture is a second, independent connection and never fails the check —
	// byte-for-byte the backend's `_tls_details`, including that it inspects the *original*
	// URL rather than wherever the redirects ended up.
	details := c.tlsDetails(requestCtx, parsed, conf)
	if days, ok := httpCertDays(details); ok {
		samples = append(samples, frame.ProbeSample{Metric: "cert_days_remaining", Value: days})
	}

	if !httpStatusAccepted(status, conf.AcceptedStatuses) {
		return Outcome{
			Samples: httpWithAvail(samples, 0),
			Msg:     fmt.Sprintf("unexpected status %d", status),
			Details: details,
		}, nil
	}

	if conf.Keyword != "" {
		found := strings.Contains(body, conf.Keyword)
		if found == conf.KeywordInvert {
			verb := "not found"
			if conf.KeywordInvert {
				verb = "found"
			}
			return Outcome{
				Samples: httpWithAvail(samples, 0),
				Msg:     fmt.Sprintf("keyword %s: %s", verb, httpPyRepr(conf.Keyword)),
				Details: details,
			}, nil
		}
	}

	if conf.JSONPath != "" && conf.ExpectedValue != nil {
		value := httpJSONPath(body, conf.JSONPath)
		if httpPyStr(value) != *conf.ExpectedValue {
			return Outcome{
				Samples: httpWithAvail(samples, 0),
				Msg: fmt.Sprintf("json %s = %s, expected %s",
					conf.JSONPath, httpPyRepr(value), httpPyRepr(*conf.ExpectedValue)),
				Details: details,
			}, nil
		}
	}

	return Outcome{
		Up:      true,
		Samples: httpWithAvail(samples, 1),
		Msg:     fmt.Sprintf("%d in %sms", status, httpPyFloat(latency)),
		Details: details,
	}, nil
}

// request performs the one HTTP request and returns the status, the bounded body and the latency
// in milliseconds, mirroring web.py's `_request` — including that latency covers reading the
// body, because httpx.request has already read it by the time it returns.
func (c *httpChecker) request(ctx context.Context, target *url.URL, conf httpConfig) (int, string, float64, error) {
	var payload io.Reader
	if conf.Body != "" {
		payload = strings.NewReader(conf.Body)
	}
	request, err := http.NewRequestWithContext(ctx, conf.method(), target.String(), payload)
	if err != nil {
		return 0, "", 0, err
	}
	for name, value := range conf.Headers {
		// net/http keeps the Host header out of the header map; setting it there is silently
		// ignored, which would quietly break virtual-host monitors.
		if http.CanonicalHeaderKey(name) == "Host" {
			request.Host = value
			continue
		}
		request.Header.Set(name, value)
	}
	switch conf.AuthType {
	case "basic":
		request.SetBasicAuth(conf.Username, conf.Password)
	case "bearer":
		if conf.Token != "" {
			request.Header.Set("Authorization", "Bearer "+conf.Token)
		}
	}

	client := &http.Client{
		Transport: &http.Transport{
			// No proxy, ever: a proxy would turn every scope decision into a suggestion, since
			// the agent would be dialing the proxy and the proxy would be reaching the target.
			Proxy:       nil,
			DialContext: c.dialContext,
			//nolint:gosec // G402: verify_tls is the monitor's own setting; the backend's
			// collector honors it identically, and this is a monitored third-party target, not
			// the Circuit Breaker control plane.
			TLSClientConfig:   &tls.Config{InsecureSkipVerify: !conf.verifyTLS(), MinVersion: tls.VersionTLS10},
			DisableKeepAlives: true,
		},
		CheckRedirect: func(request *http.Request, via []*http.Request) error {
			if !conf.followRedirects() {
				return http.ErrUseLastResponse
			}
			if len(via) >= httpMaxRedirects {
				return errHTTPTooManyRedirects
			}
			return c.validateHop(request.Context(), request.URL)
		},
	}
	defer client.CloseIdleConnections()

	start := time.Now()
	response, err := client.Do(request)
	if err != nil {
		return 0, "", 0, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, httpMaxResponseBytes))
	if err != nil {
		// httpx reads the body inside `request()`, so a truncated response is a transport
		// exception there too — not a status the check gets to evaluate.
		return 0, "", 0, err
	}
	latency := httpRound2(float64(time.Since(start).Microseconds()) / 1000)
	return response.StatusCode, string(body), latency, nil
}

// dialContext is the single place a probe connection is opened. Scope is evaluated against the
// *resolved* answers and the connection is then made to one of those exact addresses — never by
// handing the hostname back to the system resolver, which would reopen the rebinding window
// between the decision and the connect.
func (c *httpChecker) dialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, &httpScopeRefusal{msg: "probe: the destination address could not be parsed"}
	}
	resolved, err := c.resolveHost(ctx, host)
	if err != nil {
		return nil, &httpScopeRefusal{msg: fmt.Sprintf("probe: the destination %s could not be resolved", host)}
	}
	decision := netscope.Evaluate(c.scope(), host, resolved)
	if !decision.Allowed {
		return nil, &httpScopeRefusal{msg: httpRefusalMessage("destination", host, decision)}
	}
	dialAddr := addr
	if len(resolved) > 0 {
		dialAddr = net.JoinHostPort(resolved[0], port)
	}
	return c.dial(ctx, network, dialAddr)
}

// validateHop re-runs the scheme gate and the scope check for one redirect target, before
// net/http builds the request that would dial it. dialContext would catch an out-of-scope hop as
// well; doing it here too is what makes the refusal name the *hop* rather than an address, and
// it is the only place a scheme change (https -> file) can be seen at all.
func (c *httpChecker) validateHop(ctx context.Context, target *url.URL) error {
	if target.Scheme != "http" && target.Scheme != "https" {
		return &httpScopeRefusal{
			msg: fmt.Sprintf("probe: a redirect to the %q scheme is not probeable; only http and https are", target.Scheme),
		}
	}
	host := target.Hostname()
	resolved, err := c.resolveHost(ctx, host)
	if err != nil {
		return &httpScopeRefusal{msg: fmt.Sprintf("probe: the redirect destination %s could not be resolved", host)}
	}
	if decision := netscope.Evaluate(c.scope(), host, resolved); !decision.Allowed {
		return &httpScopeRefusal{msg: httpRefusalMessage("redirect destination", host, decision)}
	}
	return nil
}

// resolveHost returns the answers a destination must be judged by. An IP literal has none —
// netscope judges it directly — and returning nil for one keeps "a name is only as safe as its
// worst answer" from degrading into "no answers, so allowed".
func (c *httpChecker) resolveHost(ctx context.Context, host string) ([]string, error) {
	if _, err := netip.ParseAddr(host); err == nil {
		return nil, nil
	}
	if c.resolve == nil {
		return net.DefaultResolver.LookupHost(ctx, host)
	}
	return c.resolve(ctx, host)
}

// tlsDetails is the Go twin of web.py's `_tls_details`: a separate TLS connection, best effort,
// never able to fail the check.
//
// One deliberate difference: the handshake honors the monitor's verify_tls, where the backend
// always verifies. The backend's behavior means a monitor explicitly configured for a
// self-signed target silently loses its expiry samples — the certificate is exactly what an
// operator wants to watch there — and capture is auxiliary either way, so it cannot widen what
// the check accepts.
func (c *httpChecker) tlsDetails(ctx context.Context, target *url.URL, conf httpConfig) map[string]any {
	if target.Scheme != "https" {
		return nil
	}
	host := target.Hostname()
	port := target.Port()
	if port == "" {
		port = "443"
	}
	dialCtx, cancel := context.WithTimeout(ctx, httpSeconds(conf.timeout()))
	defer cancel()

	conn, err := c.dialContext(dialCtx, "tcp", net.JoinHostPort(host, port))
	if err != nil {
		return nil
	}
	//nolint:gosec // G402: see the TLSClientConfig comment in request.
	tlsConn := tls.Client(conn, &tls.Config{
		ServerName:         host,
		InsecureSkipVerify: !conf.verifyTLS(),
		MinVersion:         tls.VersionTLS10,
	})
	defer tlsConn.Close()
	if err := tlsConn.HandshakeContext(dialCtx); err != nil {
		return nil
	}
	certs := tlsConn.ConnectionState().PeerCertificates
	if len(certs) == 0 {
		return nil
	}
	leaf := certs[0]
	expires := leaf.NotAfter.UTC()
	// Python's timedelta.days floors toward negative infinity, so an already-expired
	// certificate reports a negative day count rather than rounding back up toward zero.
	days := int(math.Floor(expires.Sub(time.Now().UTC()).Hours() / 24))
	return map[string]any{"tls": map[string]any{
		"subject_cn": httpCommonName(leaf.Subject.CommonName),
		"issuer_cn":  httpCommonName(leaf.Issuer.CommonName),
		// `datetime.isoformat()` on a UTC-aware datetime, which renders "+00:00", not "Z".
		"expires_at":     expires.Format("2006-01-02T15:04:05-07:00"),
		"days_remaining": days,
	}}
}

// httpCommonName mirrors `_rdn_map(...).get("commonName")`: a certificate without one yields
// None, not an empty string.
func httpCommonName(name string) any {
	if name == "" {
		return nil
	}
	return name
}

func httpCertDays(details map[string]any) (float64, bool) {
	tlsDetails, ok := details["tls"].(map[string]any)
	if !ok {
		return 0, false
	}
	days, ok := tlsDetails["days_remaining"].(int)
	if !ok {
		return 0, false
	}
	return float64(days), true
}

// httpWithAvail prepends the avail sample, mirroring collect_http's `samples.insert(0, ...)`.
// The order is part of the parity contract: avail, latency_ms, http_status, cert_days_remaining.
func httpWithAvail(samples []frame.ProbeSample, value float64) []frame.ProbeSample {
	out := make([]frame.ProbeSample, 0, len(samples)+1)
	out = append(out, frame.ProbeSample{Metric: "avail", Value: value})
	return append(out, samples...)
}

// httpStatusAccepted mirrors `_status_accepted`, down to the details that look like accidents and
// are not: an empty list falls back to 200-299, a bare entry must be all digits, and "-500"
// partitions into an empty low bound and is skipped rather than read as "at most 500".
func httpStatusAccepted(status int, ranges []string) bool {
	if len(ranges) == 0 {
		ranges = httpDefaultStatusRanges
	}
	for _, entry := range ranges {
		entry = strings.TrimSpace(entry)
		if low, high, found := strings.Cut(entry, "-"); found {
			lowBound, lowErr := strconv.Atoi(strings.TrimSpace(low))
			highBound, highErr := strconv.Atoi(strings.TrimSpace(high))
			if lowErr != nil || highErr != nil {
				continue
			}
			if lowBound <= status && status <= highBound {
				return true
			}
			continue
		}
		if httpIsDigits(entry) {
			if code, err := strconv.Atoi(entry); err == nil && code == status {
				return true
			}
		}
	}
	return false
}

func httpIsDigits(value string) bool {
	if value == "" {
		return false
	}
	for _, r := range value {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// httpJSONPath mirrors `_json_path`: a dotted path whose segments may carry `[idx]` subscripts,
// resolving to nil (Python's None) the moment the shape stops matching.
//
// The body is decoded with UseNumber so a JSON integer keeps its literal spelling. Python's json
// module produces `int` for `3` and `str(3)` is `"3"`; a float64 would render `3` as well but
// `3.0` as `3`, and the expected-value comparison is textual.
func httpJSONPath(body, path string) any {
	decoder := json.NewDecoder(strings.NewReader(body))
	decoder.UseNumber()
	var document any
	if err := decoder.Decode(&document); err != nil {
		return nil
	}
	current := document
	for _, part := range strings.Split(strings.ReplaceAll(path, "]", ""), ".") {
		for _, segment := range strings.Split(part, "[") {
			if segment == "" {
				continue
			}
			switch container := current.(type) {
			case map[string]any:
				current = container[segment]
			case []any:
				if !httpIsDigits(strings.TrimPrefix(segment, "-")) {
					return nil
				}
				index, err := strconv.Atoi(segment)
				if err != nil {
					return nil
				}
				if index < 0 {
					index += len(container)
				}
				if index < 0 || index >= len(container) {
					current = nil
					continue
				}
				current = container[index]
			default:
				return nil
			}
		}
	}
	return current
}

// httpPyStr renders a decoded JSON value the way Python's `str()` does, which is what
// collect_http compares against: `str(value) != str(expected)`.
func httpPyStr(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	return httpPyRepr(value)
}

// httpPyRepr renders a value the way Python's `repr()` does, for the `{value!r}` slots in
// collect_http's messages. Containers are rendered with their keys sorted: Python would use
// insertion order, which a Go map cannot preserve, and a monitor asserting on a whole object
// rather than a scalar is outside what the message contract is there to pin.
func httpPyRepr(value any) string {
	switch typed := value.(type) {
	case nil:
		return "None"
	case string:
		return httpPyQuote(typed)
	case bool:
		if typed {
			return "True"
		}
		return "False"
	case json.Number:
		return typed.String()
	case float64:
		return httpPyFloat(typed)
	case int:
		return strconv.Itoa(typed)
	case []any:
		parts := make([]string, 0, len(typed))
		for _, item := range typed {
			parts = append(parts, httpPyRepr(item))
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		parts := make([]string, 0, len(keys))
		for _, key := range keys {
			parts = append(parts, httpPyQuote(key)+": "+httpPyRepr(typed[key]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	default:
		return fmt.Sprintf("%v", typed)
	}
}

// httpPyQuote mirrors Python's string repr, including its quote choice: single quotes unless the
// text contains one and no double quote.
func httpPyQuote(text string) string {
	quote := "'"
	if strings.Contains(text, "'") && !strings.Contains(text, `"`) {
		quote = `"`
	}
	var builder strings.Builder
	builder.WriteString(quote)
	for _, r := range text {
		switch r {
		case '\\':
			builder.WriteString(`\\`)
		case '\n':
			builder.WriteString(`\n`)
		case '\r':
			builder.WriteString(`\r`)
		case '\t':
			builder.WriteString(`\t`)
		default:
			if string(r) == quote {
				builder.WriteString(`\` + quote)
				continue
			}
			builder.WriteRune(r)
		}
	}
	builder.WriteString(quote)
	return builder.String()
}

// httpPyFloat renders a float the way Python's repr does — shortest round-tripping form, with a
// trailing ".0" on an integral value. `f"{latency}ms"` is the reason: `round(1.0, 2)` prints as
// "1.0" there, and "1ms" would not match the backend's message.
func httpPyFloat(value float64) string {
	text := strconv.FormatFloat(value, 'g', -1, 64)
	if !strings.ContainsAny(text, ".eEni") {
		text += ".0"
	}
	return text
}

// httpRound2 mirrors `round(x, 2)` closely enough for a latency: Python rounds half to even and
// Go rounds half away from zero, which can only differ on an exact .xx5 microsecond tie.
func httpRound2(value float64) float64 {
	return math.Round(value*100) / 100
}

func httpSeconds(value float64) time.Duration {
	return time.Duration(value * float64(time.Second))
}

// httpRefusalMessage names what was refused without ever naming the URL.
func httpRefusalMessage(what, host string, decision netscope.Decision) string {
	refused := host
	if decision.Address != "" {
		refused = decision.Address
	}
	return fmt.Sprintf("probe: the %s %s is outside the agent's approved scope (%s)", what, refused, decision.Reason)
}

// httpExceptionName is the Go stand-in for `type(exc).__name__` in collect_http's
// `f"request failed: {type(exc).__name__}"`.
//
// It is a classification rather than the Go error's own text for two reasons. The message travels
// into probe.result and the monitor's history, and a Go transport error stringifies to
// `Get "https://user:secret@host/": ...` — the URL D-10 says may carry credentials. And the
// backend's names come from httpx's exception hierarchy, so a `*url.Error` on the wire would make
// the same failure read differently depending on which vantage ran it.
func httpExceptionName(err error) string {
	var netErr net.Error
	switch {
	case errors.Is(err, errHTTPTooManyRedirects):
		return "TooManyRedirects"
	case errors.Is(err, context.DeadlineExceeded):
		return "TimeoutException"
	case errors.As(err, &netErr) && netErr.Timeout():
		return "TimeoutException"
	default:
		// httpx raises ConnectError for refused connections, unresolvable names and TLS
		// verification failures alike.
		return "ConnectError"
	}
}
