package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strconv"
	"strings"
	"time"

	"github.com/miekg/dns"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// The DNS collector's defaults. They come from
// app/services/monitoring/collectors/dns_check.py's `params.get(key, default)` calls, not from
// schemas/monitor.py's DnsConfig: `_MonitorBase._validate_config` persists
// `model_dump(exclude_unset=True)`, so a stored config is usually sparse and the collector-side
// values are the ones that actually decide a check. The two agree today and must keep agreeing.
const (
	DefaultDNSRecordType = "A"
	DefaultDNSPort       = 53
	DefaultDNSTimeout    = 5 * time.Second
)

// dnsErrorReason is the per-sample annotation collect_dns attaches to a failed lookup. It is
// audit metadata, persisted only in monitor_probe_runs.result_metadata (D-8).
const dnsErrorReason = "dns_error"

// dnsRecordTypes is the closed set §5 names. Stdlib net.Resolver cannot query SOA or CAA at all,
// which is the whole reason github.com/miekg/dns is a dependency (D-11).
//
// A record type outside this set is a *lookup* failure rather than an execution error, mirroring
// dnspython: `resolver.resolve(host, "FOO")` raises UnknownRdatatype from inside collect_dns's
// try block, so the backend reports it as avail=0 with a dns_error reason.
var dnsRecordTypes = map[string]uint16{
	"A":     dns.TypeA,
	"AAAA":  dns.TypeAAAA,
	"CNAME": dns.TypeCNAME,
	"MX":    dns.TypeMX,
	"TXT":   dns.TypeTXT,
	"NS":    dns.TypeNS,
	"SOA":   dns.TypeSOA,
	"PTR":   dns.TypePTR,
	"SRV":   dns.TypeSRV,
	"CAA":   dns.TypeCAA,
}

// dnsResolvConfPath is where the host's own resolvers are read from when the monitor names none.
// A variable rather than a constant only so a test can point it somewhere harmless.
var dnsResolvConfPath = "/etc/resolv.conf"

// dnsExchange sends one query to one server and returns the reply. Injected so the parity suite
// can pin record strings, sample order and message text without a resolver anywhere near it.
type dnsExchange func(ctx context.Context, msg *dns.Msg, server string, timeout time.Duration) (*dns.Msg, error)

// dnsChecker mirrors collectors/dns_check.py::collect_dns.
//
// The mirror is byte-level on purpose: msg strings are rendered in the monitor UI and compared in
// alert text, and `details.records` is what an operator's `expected_values` were written against.
// A DNS monitor moved from the server vantage to an agent must produce the same history.
type dnsChecker struct {
	deps     Deps
	exchange dnsExchange

	// systemServers reports the resolvers configured on this host, as bare addresses.
	systemServers func() ([]string, error)
	// now is the latency clock. collect_dns measures with time.monotonic() around the whole
	// resolution, retries included, and so does this.
	now func() time.Time
}

func newDNSChecker(deps Deps) Checker {
	return &dnsChecker{
		deps:          deps,
		exchange:      exchangeDNS,
		systemServers: SystemNameservers,
		now:           time.Now,
	}
}

// dnsConfig is the subset of DnsConfig the collector reads. It is decoded over a pre-filled value
// so an absent key keeps its collector default and a sparse stored config behaves exactly as it
// does server-side.
type dnsConfig struct {
	RecordType     string   `json:"record_type"`
	Resolver       string   `json:"resolver"`
	Port           int      `json:"port"`
	ExpectedValues []string `json:"expected_values"`
	Timeout        float64  `json:"timeout"`
}

func parseDNSConfig(raw json.RawMessage) (dnsConfig, error) {
	cfg := dnsConfig{
		RecordType: DefaultDNSRecordType,
		Port:       DefaultDNSPort,
		Timeout:    DefaultDNSTimeout.Seconds(),
	}
	if len(raw) > 0 {
		if err := json.Unmarshal(raw, &cfg); err != nil {
			return dnsConfig{}, fmt.Errorf("dns: the assignment's configuration is unreadable: %w", err)
		}
	}
	// collect_dns uppercases the record type on the way in and again in every message, so the
	// stored casing never reaches the wire.
	cfg.RecordType = strings.ToUpper(strings.TrimSpace(cfg.RecordType))
	if cfg.RecordType == "" {
		cfg.RecordType = DefaultDNSRecordType
	}
	return cfg, nil
}

// Check resolves one record set and reports what it saw.
//
// A returned error means the agent could not perform the check at all — an unreadable config, a
// refused resolver, a cancelled run. Everything the resolver itself said, including NXDOMAIN and
// a timeout, is a *target* observation and comes back as an Outcome with avail=0, exactly as
// collect_dns reports it.
func (c *dnsChecker) Check(ctx context.Context, host string, raw json.RawMessage) (Outcome, error) {
	cfg, err := parseDNSConfig(raw)
	if err != nil {
		return Outcome{}, err
	}
	servers, err := c.resolverServers(cfg)
	if err != nil {
		return Outcome{}, err
	}

	started := c.now()
	records, lookupErr := c.lookup(ctx, host, cfg, servers)
	latency := dnsRound(millisSince(started, c.now()), 2)
	if lookupErr != nil {
		// A cancelled or expired run says nothing about the target. Reporting it as avail=0
		// would write a DOWN nobody observed, so it leaves as an execution error instead.
		if ctxErr := ctx.Err(); ctxErr != nil {
			return Outcome{}, ctxErr
		}
		return Outcome{
			Up:      false,
			Samples: []frame.ProbeSample{{Metric: "avail", Value: 0, ErrorReason: dnsErrorReason}},
			Msg:     fmt.Sprintf("%s lookup failed: %v", cfg.RecordType, lookupErr),
		}, nil
	}

	samples := []frame.ProbeSample{
		{Metric: "avail", Value: 1},
		{Metric: "latency_ms", Value: latency},
	}
	details := map[string]any{"records": records}
	if len(cfg.ExpectedValues) > 0 && !dnsExpectationMet(records, cfg.ExpectedValues) {
		// collect_dns rewrites samples[0] in place: the resolution succeeded, so the latency
		// sample and the records stay, and only availability flips.
		samples[0] = frame.ProbeSample{Metric: "avail", Value: 0}
		return Outcome{
			Up:      false,
			Samples: samples,
			Msg: fmt.Sprintf("%s records %s did not match expected %s",
				cfg.RecordType, dnsPyList(records), dnsPyList(cfg.ExpectedValues)),
			Details: details,
		}, nil
	}
	return Outcome{
		Up:      true,
		Samples: samples,
		Msg: fmt.Sprintf("%s: %d record(s) in %sms",
			cfg.RecordType, len(records), dnsPyFloat(latency)),
		Details: details,
	}, nil
}

// dnsExpectationMet is collect_dns's `any(any(e in r for r in records) for e in expected)`:
// substring, not equality, and satisfied by one expected value matching one record. Anything
// stricter would turn a working monitor DOWN the moment it moved to an agent vantage.
func dnsExpectationMet(records, expected []string) bool {
	for _, want := range expected {
		for _, record := range records {
			if strings.Contains(record, want) {
				return true
			}
		}
	}
	return false
}

// resolverServers decides which nameservers this check may talk to.
//
// §3 requires DNS resolver destinations to be validated like any other network target, and this
// is where that happens: a monitor-supplied resolver is an operator-controlled address the agent
// is about to send packets to, so an unchecked one would be a hole straight through the scope
// evaluator. The *host's own* resolvers are not scope-checked — they are this machine's
// configuration rather than a destination the assignment chose, and the runtime already resolves
// its pre-dial scope check through them.
//
// A non-address resolver is refused rather than resolved, mirroring dnspython: the
// `Resolver.nameservers` setter raises outside collect_dns's try block, so the backend surfaces a
// typo here as an execution error and not as an outage.
func (c *dnsChecker) resolverServers(cfg dnsConfig) ([]string, error) {
	port := strconv.Itoa(cfg.Port)
	if resolver := strings.TrimSpace(cfg.Resolver); resolver != "" {
		address, err := netip.ParseAddr(resolver)
		if err != nil {
			return nil, fmt.Errorf("dns: resolver %q is not an IP address", resolver)
		}
		if decision := netscope.Evaluate(c.deps.Scope(), address.String(), nil); !decision.Allowed {
			return nil, fmt.Errorf("dns: resolver %s is outside the agent's approved scope (%s)",
				address, decision.Reason)
		}
		return []string{net.JoinHostPort(address.String(), port)}, nil
	}

	hosts, err := c.systemServers()
	if err != nil {
		return nil, fmt.Errorf("dns: this host has no usable resolver: %w", err)
	}
	if len(hosts) == 0 {
		return nil, errors.New("dns: this host has no usable resolver")
	}
	servers := make([]string, 0, len(hosts))
	for _, host := range hosts {
		servers = append(servers, net.JoinHostPort(host, port))
	}
	return servers, nil
}

// lookup performs the resolution and returns the record strings in answer order.
//
// The monitor's `timeout` bounds the whole resolution, not each server, mirroring dnspython's
// `resolver.lifetime`. The run's own context still outranks it: an assignment deadline shorter
// than the monitor timeout must stop the check, which is what makes probe.cancel meaningful.
func (c *dnsChecker) lookup(ctx context.Context, host string, cfg dnsConfig, servers []string) ([]string, error) {
	rrtype, ok := dnsRecordTypes[cfg.RecordType]
	if !ok {
		return nil, fmt.Errorf("unknown rdatatype %q", cfg.RecordType)
	}
	name := dns.Fqdn(strings.TrimSpace(host))
	query := new(dns.Msg)
	query.SetQuestion(name, rrtype)
	query.RecursionDesired = true

	timeout := time.Duration(cfg.Timeout * float64(time.Second))
	lookupCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	var lastErr error
	for _, server := range servers {
		reply, err := c.exchange(lookupCtx, query, server, timeout)
		if ctxErr := ctx.Err(); ctxErr != nil {
			return nil, ctxErr
		}
		if err != nil {
			lastErr = err
			continue
		}
		switch reply.Rcode {
		case dns.RcodeSuccess:
			records := dnsAnswerStrings(reply, rrtype)
			if len(records) == 0 {
				// dnspython's NoAnswer: the name exists but carries nothing of this type.
				return nil, fmt.Errorf(
					"The DNS response does not contain an answer to the question: %s IN %s",
					name, cfg.RecordType)
			}
			return records, nil
		case dns.RcodeNameError:
			return nil, fmt.Errorf("The DNS query name does not exist: %s", name)
		default:
			lastErr = errors.New(dns.RcodeToString[reply.Rcode])
		}
	}
	if lastErr == nil {
		lastErr = errors.New("no resolver was reachable")
	}
	// dnspython's NoNameservers, which is what a SERVFAIL or an unreachable resolver becomes.
	return nil, fmt.Errorf("All nameservers failed to answer the query %s IN %s: %v",
		name, cfg.RecordType, lastErr)
}

// dnsAnswerStrings renders the answers of the requested type the way dnspython's Answer iteration
// does: the rdata only, without the owner/TTL/class header, in reply order.
func dnsAnswerStrings(reply *dns.Msg, rrtype uint16) []string {
	records := make([]string, 0, len(reply.Answer))
	for _, rr := range reply.Answer {
		if rr == nil || rr.Header().Rrtype != rrtype {
			continue
		}
		records = append(records, strings.TrimPrefix(rr.String(), rr.Header().String()))
	}
	return records
}

// exchangeDNS is the production transport: UDP first, retried over TCP when the reply is
// truncated, exactly as a stub resolver would.
func exchangeDNS(ctx context.Context, msg *dns.Msg, server string, timeout time.Duration) (*dns.Msg, error) {
	udp := &dns.Client{Timeout: timeout}
	reply, _, err := udp.ExchangeContext(ctx, msg, server)
	if err != nil {
		return nil, err
	}
	if !reply.Truncated {
		return reply, nil
	}
	tcp := &dns.Client{Net: "tcp", Timeout: timeout}
	retried, _, err := tcp.ExchangeContext(ctx, msg, server)
	if err != nil {
		// The truncated answer is still an answer; a TCP fallback that cannot connect must not
		// turn a reachable name into a lookup failure.
		return reply, nil
	}
	return retried, nil
}

// SystemNameservers reads this host's own resolvers. An empty list is reported as such rather
// than defaulted to a public resolver: §5's readiness contract is that DNS is *degraded* when no
// usable resolver is configured, not that the agent silently picks one.
//
// Exported because internal/collect/discover's readiness answers the same question about the same
// file for its reverse-DNS collector. A second reader there would be a second parse of
// resolv.conf that could disagree with this one about the same host.
func SystemNameservers() ([]string, error) {
	cfg, err := dns.ClientConfigFromFile(dnsResolvConfPath)
	if err != nil {
		return nil, err
	}
	return cfg.Servers, nil
}

func millisSince(start, end time.Time) float64 {
	return float64(end.Sub(start)) / float64(time.Millisecond)
}

// dnsRound mirrors Python's round(value, places). Go's strconv rounds to nearest with ties to
// even, which is what CPython's float repr machinery does, so formatting to `places` decimals and
// parsing back lands on the same double Python would produce.
func dnsRound(value float64, places int) float64 {
	rounded, err := strconv.ParseFloat(strconv.FormatFloat(value, 'f', places, 64), 64)
	if err != nil {
		return value
	}
	return rounded
}

// dnsPyFloat renders a float the way a Python f-string does. The difference that matters is the
// whole number: Python's repr of 12.0 is "12.0" and Go's shortest form is "12", which would put a
// different message on the wire for every check that happens to land on a whole millisecond.
func dnsPyFloat(value float64) string {
	text := strconv.FormatFloat(value, 'f', -1, 64)
	if !strings.ContainsAny(text, ".eE") {
		text += ".0"
	}
	return text
}

// dnsPyList renders a []string the way a Python f-string renders a list[str] — `['a', 'b']` —
// because collect_dns's mismatch message interpolates the lists directly and that text is what
// operators read in the monitor history.
func dnsPyList(items []string) string {
	var b strings.Builder
	b.WriteByte('[')
	for i, item := range items {
		if i > 0 {
			b.WriteString(", ")
		}
		b.WriteString(dnsPyStr(item))
	}
	b.WriteByte(']')
	return b.String()
}

// dnsPyStr mirrors Python's repr() of a str: single quotes, switching to double quotes only when
// the value contains a single quote and no double quote. DNS record strings routinely carry
// double quotes (TXT, CAA), so this is the common case rather than an exotic one.
func dnsPyStr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote):
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\\':
			b.WriteString(`\\`)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			b.WriteString(fmt.Sprintf(`\x%02x`, r))
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}
