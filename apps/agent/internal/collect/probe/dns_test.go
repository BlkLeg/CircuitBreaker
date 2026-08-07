package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/miekg/dns"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// dnsHarnessElapsed is what the injected clock reports for every lookup: 12.34 ms is chosen
// because round(12.34, 2) is exactly 12.34 in both languages, so a message assertion can be a
// literal rather than a tolerance.
const dnsHarnessElapsed = 12340 * time.Microsecond

// dnsHarnessResolver is the system resolver every harness reports. It sits inside testScope's
// 10.20.0.0/24 so the scope check is not silently doing the work of the test.
const dnsHarnessResolver = "10.20.0.53"

// dnsHarness answers a dnsChecker's resolver traffic in-process and records what it was asked.
// No test in this file may touch a real resolver: the point of the parity suite is that the
// record strings, sample order and message text are pinned, not that DNS works.
type dnsHarness struct {
	checker *dnsChecker

	mu        sync.Mutex
	servers   []string
	timeouts  []time.Duration
	questions []dns.Question

	// answers is the reply's answer section; rcode and err force the two failure shapes.
	answers []dns.RR
	rcode   int
	err     error

	elapsed time.Duration
}

func newDNSHarness(t *testing.T, mutate ...func(*dnsHarness)) *dnsHarness {
	t.Helper()
	h := &dnsHarness{rcode: dns.RcodeSuccess, elapsed: dnsHarnessElapsed}
	for _, m := range mutate {
		m(h)
	}
	var clockCalls int
	base := time.Unix(1770000000, 0).UTC()
	h.checker = &dnsChecker{
		deps: Deps{
			Scope: testScope,
			Resolve: func(context.Context, string) ([]string, error) {
				return nil, errors.New("probe test: no test may reach the real resolver")
			},
		},
		exchange:      h.exchange,
		systemServers: func() ([]string, error) { return []string{dnsHarnessResolver}, nil },
		now: func() time.Time {
			clockCalls++
			if clockCalls == 1 {
				return base
			}
			return base.Add(h.elapsed)
		},
	}
	return h
}

func (h *dnsHarness) exchange(_ context.Context, msg *dns.Msg, server string, timeout time.Duration) (*dns.Msg, error) {
	h.mu.Lock()
	h.servers = append(h.servers, server)
	h.timeouts = append(h.timeouts, timeout)
	h.questions = append(h.questions, msg.Question...)
	answers, rcode, err := h.answers, h.rcode, h.err
	h.mu.Unlock()
	if err != nil {
		return nil, err
	}
	reply := new(dns.Msg)
	reply.SetReply(msg)
	reply.Rcode = rcode
	reply.Answer = answers
	return reply, nil
}

func (h *dnsHarness) exchanges() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.servers)
}

func dnsConfigJSON(t *testing.T, fields map[string]any) json.RawMessage {
	t.Helper()
	if fields == nil {
		return nil
	}
	raw, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("encoding the dns config: %v", err)
	}
	return raw
}

func mustRR(t *testing.T, text string) dns.RR {
	t.Helper()
	rr, err := dns.NewRR(text)
	if err != nil {
		t.Fatalf("parsing %q: %v", text, err)
	}
	return rr
}

func dnsARecords(t *testing.T, values ...string) []dns.RR {
	t.Helper()
	out := make([]dns.RR, 0, len(values))
	for _, value := range values {
		out = append(out, mustRR(t, fmt.Sprintf("example.com.\t300\tIN\tA\t%s", value)))
	}
	return out
}

func recordsOf(t *testing.T, outcome Outcome) []string {
	t.Helper()
	raw, ok := outcome.Details["records"]
	if !ok {
		t.Fatalf("details carry no records key: %#v", outcome.Details)
	}
	records, ok := raw.([]string)
	if !ok {
		t.Fatalf("records is %T, want []string", raw)
	}
	return records
}

// TestDNS_AllTenRecordTypesResolve pins every record type §5 names, and pins the record *string*
// form for each: these are what land in details and what expected_values is matched against, so
// a drift from dnspython's str(rdata) silently breaks every expected-value assertion an operator
// has already written. The four types after MX are also why github.com/miekg/dns is a dependency
// at all — net.Resolver cannot query SOA or CAA.
func TestDNS_AllTenRecordTypesResolve(t *testing.T) {
	cases := []struct {
		recordType string
		qtype      uint16
		rr         string
		want       string
	}{
		{"A", dns.TypeA, "example.com.\t300\tIN\tA\t10.20.0.9", "10.20.0.9"},
		{"AAAA", dns.TypeAAAA, "example.com.\t300\tIN\tAAAA\tfd20::9", "fd20::9"},
		{"CNAME", dns.TypeCNAME, "www.example.com.\t300\tIN\tCNAME\texample.com.", "example.com."},
		{"MX", dns.TypeMX, "example.com.\t300\tIN\tMX\t10 mail.example.com.", "10 mail.example.com."},
		{"TXT", dns.TypeTXT, "example.com.\t300\tIN\tTXT\t\"v=spf1 -all\"", "\"v=spf1 -all\""},
		{"NS", dns.TypeNS, "example.com.\t300\tIN\tNS\tns1.example.com.", "ns1.example.com."},
		{
			"SOA", dns.TypeSOA,
			"example.com.\t300\tIN\tSOA\tns1.example.com. hostmaster.example.com. 2026080701 7200 3600 1209600 3600",
			"ns1.example.com. hostmaster.example.com. 2026080701 7200 3600 1209600 3600",
		},
		{"PTR", dns.TypePTR, "9.0.20.10.in-addr.arpa.\t300\tIN\tPTR\thost.example.com.", "host.example.com."},
		{
			"SRV", dns.TypeSRV,
			"_sip._tcp.example.com.\t300\tIN\tSRV\t10 60 5060 sip.example.com.",
			"10 60 5060 sip.example.com.",
		},
		{"CAA", dns.TypeCAA, "example.com.\t300\tIN\tCAA\t0 issue \"letsencrypt.org\"", "0 issue \"letsencrypt.org\""},
	}

	for _, tc := range cases {
		t.Run(tc.recordType, func(t *testing.T) {
			h := newDNSHarness(t, func(h *dnsHarness) { h.answers = []dns.RR{mustRR(t, tc.rr)} })
			outcome, err := h.checker.Check(
				context.Background(), "example.com",
				dnsConfigJSON(t, map[string]any{"record_type": tc.recordType}),
			)
			if err != nil {
				t.Fatalf("Check returned an execution error: %v", err)
			}
			if !outcome.Up {
				t.Fatalf("outcome is DOWN for a successful %s lookup: %+v", tc.recordType, outcome)
			}
			if got := h.questions[0].Qtype; got != tc.qtype {
				t.Fatalf("queried qtype %d, want %d", got, tc.qtype)
			}
			if got := h.questions[0].Name; got != "example.com." {
				t.Fatalf("queried name %q, want the fully qualified %q", got, "example.com.")
			}
			if got := recordsOf(t, outcome); len(got) != 1 || got[0] != tc.want {
				t.Fatalf("records = %#v, want [%q]", got, tc.want)
			}
			wantMsg := fmt.Sprintf("%s: 1 record(s) in 12.34ms", tc.recordType)
			if outcome.Msg != wantMsg {
				t.Fatalf("msg = %q, want %q", outcome.Msg, wantMsg)
			}
		})
	}
}

// TestDNS_ExpectedValueMatchingIsSubstringAnyOfAny pins collect_dns's
// `any(any(e in r for r in records) for e in expected)`. Substring, not equality, and satisfied
// by *one* expected value matching *one* record — anything stricter turns a working monitor DOWN
// the moment it is moved from the server vantage to an agent.
func TestDNS_ExpectedValueMatchingIsSubstringAnyOfAny(t *testing.T) {
	cases := []struct {
		name     string
		records  []string
		expected []string
		wantUp   bool
	}{
		{"exact single record", []string{"10.20.0.9"}, []string{"10.20.0.9"}, true},
		{"substring of a record", []string{"10.20.0.9"}, []string{"10.20.0."}, true},
		{"matches the second record", []string{"10.20.0.9", "10.20.0.10"}, []string{"0.10"}, true},
		{"second expected value matches", []string{"10.20.0.9"}, []string{"zzz", "0.9"}, true},
		{"no expected value matches", []string{"10.20.0.9"}, []string{"10.20.0.99"}, false},
		{"record is a substring of the expectation", []string{"10.20.0.9"}, []string{"10.20.0.90"}, false},
		{"empty expectation asserts nothing", []string{"10.20.0.9"}, nil, true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, tc.records...) })
			cfg := map[string]any{"record_type": "A"}
			if tc.expected != nil {
				cfg["expected_values"] = tc.expected
			}
			outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, cfg))
			if err != nil {
				t.Fatalf("Check returned an execution error: %v", err)
			}
			if outcome.Up != tc.wantUp {
				t.Fatalf("up = %v, want %v (msg %q)", outcome.Up, tc.wantUp, outcome.Msg)
			}
		})
	}
}

// TestDNS_MismatchRewritesAvailToZeroAndKeepsDetails pins the exact shape collect_dns produces
// for a mismatch: the resolution *succeeded*, so latency is still reported, the records are still
// carried for the audit row, and only samples[0] is rewritten in place. Dropping the latency
// sample or the details would make an expected-value failure indistinguishable from a lookup
// failure in the monitor history.
func TestDNS_MismatchRewritesAvailToZeroAndKeepsDetails(t *testing.T) {
	h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
	outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
		"record_type":     "A",
		"expected_values": []string{"10.20.0.99"},
	}))
	if err != nil {
		t.Fatalf("Check returned an execution error: %v", err)
	}
	if outcome.Up {
		t.Fatalf("a mismatch must be DOWN: %+v", outcome)
	}
	want := []frame.ProbeSample{
		{Metric: "avail", Value: 0},
		{Metric: "latency_ms", Value: 12.34},
	}
	if len(outcome.Samples) != len(want) {
		t.Fatalf("samples = %#v, want %#v", outcome.Samples, want)
	}
	for i, sample := range outcome.Samples {
		if sample != want[i] {
			t.Fatalf("sample %d = %#v, want %#v", i, sample, want[i])
		}
	}
	if outcome.Samples[0].ErrorReason != "" {
		t.Fatalf("a mismatch is not a lookup error: %q", outcome.Samples[0].ErrorReason)
	}
	if got := recordsOf(t, outcome); len(got) != 1 || got[0] != "10.20.0.9" {
		t.Fatalf("details lost the records on mismatch: %#v", got)
	}
}

// TestDNS_MessageStringsMatchBackendExactly pins the three message forms byte for byte against
// collect_dns. They are literals, generated from the backend's own f-strings, because msg is
// rendered in the monitor UI and compared in alert text: a Go-flavored "12.34ms" vs Python's
// "12.34ms" is the kind of difference that only shows up as a diff in an operator's screenshot.
func TestDNS_MessageStringsMatchBackendExactly(t *testing.T) {
	t.Run("success", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9", "10.20.0.10") })
		outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, nil))
		if err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		if outcome.Msg != "A: 2 record(s) in 12.34ms" {
			t.Fatalf("msg = %q", outcome.Msg)
		}
	})

	// Python renders a whole-millisecond float as "12.0"; Go's shortest float form renders "12".
	// This case exists solely to keep that difference from reaching the wire.
	t.Run("success with a whole millisecond latency", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) {
			h.answers = dnsARecords(t, "10.20.0.9")
			h.elapsed = 12 * time.Millisecond
		})
		outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, nil))
		if err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		if outcome.Msg != "A: 1 record(s) in 12.0ms" {
			t.Fatalf("msg = %q, want %q", outcome.Msg, "A: 1 record(s) in 12.0ms")
		}
	})

	t.Run("record type is uppercased", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) {
			h.answers = []dns.RR{mustRR(t, "example.com.\t300\tIN\tAAAA\tfd20::9")}
		})
		outcome, err := h.checker.Check(context.Background(), "example.com",
			dnsConfigJSON(t, map[string]any{"record_type": "aaaa"}))
		if err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		if outcome.Msg != "AAAA: 1 record(s) in 12.34ms" {
			t.Fatalf("msg = %q", outcome.Msg)
		}
	})

	// The Python list repr is load-bearing: `f"{records}"` on a list[str] renders single-quoted
	// elements separated by ", ", which is not what Go's %v does.
	t.Run("mismatch", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
		outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
			"expected_values": []string{"10.20.0.99"},
		}))
		if err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		want := "A records ['10.20.0.9'] did not match expected ['10.20.0.99']"
		if outcome.Msg != want {
			t.Fatalf("msg = %q, want %q", outcome.Msg, want)
		}
	})

	t.Run("mismatch renders records containing quotes", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) {
			h.answers = []dns.RR{mustRR(t, "example.com.\t300\tIN\tTXT\t\"v=spf1 -all\"")}
		})
		outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
			"record_type":     "TXT",
			"expected_values": []string{"v=spf2"},
		}))
		if err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		want := `TXT records ['"v=spf1 -all"'] did not match expected ['v=spf2']`
		if outcome.Msg != want {
			t.Fatalf("msg = %q, want %q", outcome.Msg, want)
		}
	})

	t.Run("lookup failure", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.rcode = dns.RcodeNameError })
		outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, nil))
		if err != nil {
			t.Fatalf("a lookup failure describes the target, not the agent: %v", err)
		}
		want := "A lookup failed: The DNS query name does not exist: example.com."
		if outcome.Msg != want {
			t.Fatalf("msg = %q, want %q", outcome.Msg, want)
		}
	})

	t.Run("lookup failure carries the underlying error", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.err = errors.New("dial udp: connection refused") })
		outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, nil))
		if err != nil {
			t.Fatalf("a lookup failure describes the target, not the agent: %v", err)
		}
		if !strings.HasPrefix(outcome.Msg, "A lookup failed: ") {
			t.Fatalf("msg = %q, want the %q form", outcome.Msg, "{RT} lookup failed: {exc}")
		}
		if !strings.Contains(outcome.Msg, "dial udp: connection refused") {
			t.Fatalf("msg = %q, want it to carry the underlying failure", outcome.Msg)
		}
	})
}

// TestDNS_DetailsCarryStringifiedRecords pins D-8's audit payload: details is exactly
// {"records": [str(r) …]} and survives JSON encoding as an array of strings, because that is
// what monitor_probe_runs.result_metadata stores and what the backend's own collector produces.
func TestDNS_DetailsCarryStringifiedRecords(t *testing.T) {
	h := newDNSHarness(t, func(h *dnsHarness) {
		h.answers = []dns.RR{
			mustRR(t, "example.com.\t300\tIN\tMX\t10 mail.example.com."),
			mustRR(t, "example.com.\t300\tIN\tMX\t20 backup.example.com."),
		}
	})
	outcome, err := h.checker.Check(context.Background(), "example.com",
		dnsConfigJSON(t, map[string]any{"record_type": "MX"}))
	if err != nil {
		t.Fatalf("Check returned an execution error: %v", err)
	}
	if len(outcome.Details) != 1 {
		t.Fatalf("details = %#v, want exactly one key", outcome.Details)
	}
	encoded, err := json.Marshal(outcome.Details)
	if err != nil {
		t.Fatalf("encoding details: %v", err)
	}
	want := `{"records":["10 mail.example.com.","20 backup.example.com."]}`
	if string(encoded) != want {
		t.Fatalf("details = %s, want %s", encoded, want)
	}
}

// TestDNS_CustomResolverDestinationIsScopeChecked pins §3's "DNS resolver destinations are
// validated like other network targets". A monitor's resolver is an operator-supplied address the
// agent is about to send packets to, so an unchecked one would be a hole straight through the
// scope evaluator — point it at the metadata service and the agent dials it.
func TestDNS_CustomResolverDestinationIsScopeChecked(t *testing.T) {
	t.Run("in scope resolver is used verbatim", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
		if _, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
			"resolver": "10.20.0.60",
		})); err != nil {
			t.Fatalf("an in-scope resolver must be usable: %v", err)
		}
		if got := h.servers[0]; got != "10.20.0.60:53" {
			t.Fatalf("queried %q, want %q", got, "10.20.0.60:53")
		}
	})

	t.Run("custom port is applied to the resolver", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
		if _, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
			"resolver": "10.20.0.60",
			"port":     5353,
		})); err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		if got := h.servers[0]; got != "10.20.0.60:5353" {
			t.Fatalf("queried %q, want %q", got, "10.20.0.60:5353")
		}
	})

	for _, tc := range []struct {
		name     string
		resolver string
	}{
		{"public resolver is out of scope", "8.8.8.8"},
		{"loopback resolver is special use", "127.0.0.1"},
		{"cloud metadata resolver is special use", "169.254.169.254"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
			outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
				"resolver": tc.resolver,
			}))
			if err == nil {
				t.Fatalf("resolver %s was accepted: %+v", tc.resolver, outcome)
			}
			if !strings.Contains(err.Error(), tc.resolver) {
				t.Fatalf("error %q does not name the refused resolver", err)
			}
			if h.exchanges() != 0 {
				t.Fatalf("an out-of-scope resolver was still queried %d time(s)", h.exchanges())
			}
		})
	}

	// dnspython's Resolver.nameservers setter rejects a non-address outright, which surfaces as
	// an execution error rather than a target DOWN. Mirroring that keeps a typo in the resolver
	// field from reading as an outage.
	t.Run("a non-address resolver is an execution error", func(t *testing.T) {
		h := newDNSHarness(t)
		if _, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, map[string]any{
			"resolver": "ns1.example.com",
		})); err == nil {
			t.Fatal("a hostname resolver must not be accepted")
		}
		if h.exchanges() != 0 {
			t.Fatalf("a non-address resolver was still queried %d time(s)", h.exchanges())
		}
	})
}

// TestDNS_DefaultsAreRecordTypeAPortFiftyThreeTimeoutFive pins the parity contract's defaults.
// They come from collect_dns's params.get calls, not from DnsConfig: schemas/monitor.py persists
// model_dump(exclude_unset=True), so a stored config is usually sparse and an empty one is the
// common case rather than an edge case.
func TestDNS_DefaultsAreRecordTypeAPortFiftyThreeTimeoutFive(t *testing.T) {
	for _, tc := range []struct {
		name string
		cfg  json.RawMessage
	}{
		{"absent config", nil},
		{"empty config", json.RawMessage(`{}`)},
		{"json null config", json.RawMessage(`null`)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
			outcome, err := h.checker.Check(context.Background(), "example.com", tc.cfg)
			if err != nil {
				t.Fatalf("Check returned an execution error: %v", err)
			}
			if !outcome.Up {
				t.Fatalf("outcome is DOWN: %+v", outcome)
			}
			if got := h.questions[0].Qtype; got != dns.TypeA {
				t.Fatalf("qtype = %d, want A (%d)", got, dns.TypeA)
			}
			if got := h.servers[0]; got != dnsHarnessResolver+":53" {
				t.Fatalf("server = %q, want %q", got, dnsHarnessResolver+":53")
			}
			if got := h.timeouts[0]; got != 5*time.Second {
				t.Fatalf("timeout = %s, want 5s", got)
			}
			if got := outcome.Msg; !strings.HasPrefix(got, "A: ") {
				t.Fatalf("msg = %q, want the default record type A", got)
			}
		})
	}

	t.Run("configured timeout overrides the default", func(t *testing.T) {
		h := newDNSHarness(t, func(h *dnsHarness) { h.answers = dnsARecords(t, "10.20.0.9") })
		if _, err := h.checker.Check(context.Background(), "example.com",
			dnsConfigJSON(t, map[string]any{"timeout": 1.5})); err != nil {
			t.Fatalf("Check returned an execution error: %v", err)
		}
		if got := h.timeouts[0]; got != 1500*time.Millisecond {
			t.Fatalf("timeout = %s, want 1.5s", got)
		}
	})
}

// TestDNS_LookupFailureEmitsDNSErrorReason pins the per-sample annotation collect_dns attaches on
// failure. error_reason is audit metadata that lives only in monitor_probe_runs.result_metadata
// (D-8), and it is the only thing distinguishing "the resolver did not answer" from "the target
// is DOWN" once the sample reaches the shared result service.
func TestDNS_LookupFailureEmitsDNSErrorReason(t *testing.T) {
	for _, tc := range []struct {
		name    string
		mutate  func(*dnsHarness)
		wantMsg string
	}{
		{
			"nxdomain",
			func(h *dnsHarness) { h.rcode = dns.RcodeNameError },
			"A lookup failed: The DNS query name does not exist: example.com.",
		},
		{
			"no answer of the requested type",
			func(h *dnsHarness) {
				h.answers = []dns.RR{mustRR(t, "example.com.\t300\tIN\tAAAA\tfd20::9")}
			},
			"A lookup failed: The DNS response does not contain an answer to the question: example.com. IN A",
		},
		{
			"server failure",
			func(h *dnsHarness) { h.rcode = dns.RcodeServerFailure },
			"",
		},
		{
			"transport failure",
			func(h *dnsHarness) { h.err = errors.New("i/o timeout") },
			"",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newDNSHarness(t, tc.mutate)
			outcome, err := h.checker.Check(context.Background(), "example.com", dnsConfigJSON(t, nil))
			if err != nil {
				t.Fatalf("a lookup failure is a target observation, not an execution error: %v", err)
			}
			if outcome.Up {
				t.Fatalf("a lookup failure must be DOWN: %+v", outcome)
			}
			want := []frame.ProbeSample{{Metric: "avail", Value: 0, ErrorReason: "dns_error"}}
			if len(outcome.Samples) != 1 || outcome.Samples[0] != want[0] {
				t.Fatalf("samples = %#v, want %#v", outcome.Samples, want)
			}
			if outcome.Details != nil {
				t.Fatalf("a failed lookup carries no details: %#v", outcome.Details)
			}
			if tc.wantMsg != "" && outcome.Msg != tc.wantMsg {
				t.Fatalf("msg = %q, want %q", outcome.Msg, tc.wantMsg)
			}
			if !strings.HasPrefix(outcome.Msg, "A lookup failed: ") {
				t.Fatalf("msg = %q, want the %q form", outcome.Msg, "{RT} lookup failed: {exc}")
			}
		})
	}
}

// TestDNS_CancellationIsAnExecutionErrorNotTargetDown keeps the run's own deadline and
// probe.cancel out of the target's history. A cancelled or deadline-exceeded run must reach the
// runtime as an error so it becomes `cancelled`/`execution_error`; folding it into the dns_error
// branch would write avail=0 and report a DOWN nobody observed.
func TestDNS_CancellationIsAnExecutionErrorNotTargetDown(t *testing.T) {
	h := newDNSHarness(t, func(h *dnsHarness) { h.err = errors.New("context canceled") })
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := h.checker.Check(ctx, "example.com", dnsConfigJSON(t, nil)); !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", err)
	}
}
