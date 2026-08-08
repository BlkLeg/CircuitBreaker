package discover

import (
	"context"
	"go/ast"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// validatorDispatchID is 32 lowercase hex characters, the shape the backend mints and
// DiscoveryRequestPayload requires.
const validatorDispatchID = "3f9a1c7e2b8d4056a1c3e5f70b2d4986"

// validatorNow is the clock every case below is judged against, so a deadline case is decided by
// the request rather than by how long the suite took to get here.
var validatorNow = time.Date(2026, 8, 8, 12, 0, 0, 0, time.UTC)

// grantConfig is one agent's `local_discovery` grant: an eth0 that is attached to 10.20.0.0/24,
// plus one routed /24 an administrator added by hand. The two halves are what the routed-override
// case below turns on — 192.168.50.0/24 is in scope and is *not* a segment this host is on.
//
// The ceiling and the port list are narrowed from the defaults so a case can exceed them without
// naming a /18 or a port nobody would ever grant.
func grantConfig() capability.LocalDiscoveryConfig {
	cfg := capability.DefaultLocalDiscoveryConfig()
	cfg.MaxAddressesPerJob = 128
	cfg.TCPPorts = []int{22, 443}
	cfg.AdditionalCIDRs = []string{"192.168.50.0/24"}
	return cfg
}

// grantScope derives the scope the agent itself would hold under grantConfig. Derived rather than
// written out, because the request's scope_version has to be the version this derivation produces
// and a hand-written one would only ever pin the test's own arithmetic.
func grantScope() netscope.Scope {
	return netscope.Derive(
		[]netscope.InterfaceFacts{{
			Name:  "eth0",
			Flags: []string{"up", "broadcast"},
			Addrs: []string{"10.20.0.5/24"},
		}},
		grantConfig().Config,
	)
}

// grantedRequest is a request every field of which the grant above permits: a /25 of the attached
// segment, at exactly the address ceiling, on the granted ports, with a live deadline. Each case
// mutates exactly one thing, so a rejection can only be the thing it changed.
func grantedRequest(mutate ...func(*frame.DiscoveryRequestPayload)) frame.DiscoveryRequestPayload {
	payload := frame.DiscoveryRequestPayload{
		DispatchID:         validatorDispatchID,
		ScanJobID:          481,
		Targets:            []string{"10.20.0.0/25"},
		Methods:            []string{MethodNeighborCache, MethodICMP, MethodTCPConnect, MethodReverseDNS},
		TCPPorts:           []int{22, 443},
		HostTimeoutMS:      200,
		MaxConcurrentHosts: 4,
		ScopeVersion:       grantScope().Version,
		DeadlineAt:         validatorNow.Add(20 * time.Second),
	}
	for _, m := range mutate {
		m(&payload)
	}
	return payload
}

func testValidator() Validator {
	return NewValidator(grantConfig(), func() time.Time { return validatorNow })
}

// validatorCase is one request the validator has to decide. scope is nil for every case that runs
// against the agent's own derived scope; the one case that cannot be expressed that way supplies
// its own (see "in scope but attached to nothing").
type validatorCase struct {
	name     string
	scope    func() netscope.Scope
	mutate   func(*frame.DiscoveryRequestPayload)
	wantCode string
}

func (c validatorCase) run(t *testing.T) Rejection {
	t.Helper()
	scope := grantScope
	if c.scope != nil {
		scope = c.scope
	}
	mutate := c.mutate
	if mutate == nil {
		mutate = func(*frame.DiscoveryRequestPayload) {}
	}
	return testValidator()(grantedRequest(mutate), scope())
}

// rejectionCases is every way a request can be refused. They are kept in one table because the
// property that matters most is across rows rather than within one: no two causes may be
// reported under the same code, or the backend's error_reason cannot tell an operator which
// limit they hit.
func rejectionCases() []validatorCase {
	return []validatorCase{
		{
			name:     "an unknown method",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.Methods = []string{MethodICMP, "syn_scan"} },
			wantCode: ErrorCodeUnknownMethod,
		},
		{
			// Not a rejection this package decides: the code is netscope's own reason, carried
			// through verbatim. A parallel vocabulary here would be a second scope evaluator
			// wearing a different hat.
			name:     "a target the agent was never attached to",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.Targets = []string{"10.99.0.0/24"} },
			wantCode: netscope.ReasonOutOfScope,
		},
		{
			name:     "a target overlapping special-use space",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.Targets = []string{"169.254.0.0/24"} },
			wantCode: netscope.ReasonSpecialUse,
		},
		{
			name:     "a target wider than the hard prefix ceiling",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.Targets = []string{"10.0.0.0/8"} },
			wantCode: netscope.ReasonPrefixTooWide,
		},
		{
			// netscope.Derive only ever fills Networks from the directly connected and the
			// administrator-approved halves, so this scope cannot come from Derive — which is
			// exactly the case the check exists for. A target that reached the allow list some
			// other way is authorized by nothing this host can corroborate, and §7 requires the
			// agent to re-check attachment at execution time rather than trust the derivation.
			name: "a target in scope but attached to nothing",
			scope: func() netscope.Scope {
				return netscope.Scope{Networks: []string{"10.30.0.0/24"}, Version: "d15c0nnec7ed"}
			},
			mutate: func(p *frame.DiscoveryRequestPayload) {
				p.Targets = []string{"10.30.0.0/25"}
				p.ScopeVersion = "d15c0nnec7ed"
			},
			wantCode: ErrorCodeNotDirectlyConnected,
		},
		{
			name:     "more addresses than the grant allows in one job",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.Targets = []string{"10.20.0.0/24"} },
			wantCode: ErrorCodeAddressLimit,
		},
		{
			name:     "a port outside the grant",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.TCPPorts = []int{22, 3389} },
			wantCode: ErrorCodePortNotGranted,
		},
		{
			name:     "a deadline that has already passed",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.DeadlineAt = validatorNow.Add(-time.Second) },
			wantCode: ErrorCodeDeadlinePassed,
		},
		{
			name:     "no deadline at all",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.DeadlineAt = time.Time{} },
			wantCode: ErrorCodeDeadlinePassed,
		},
		{
			name:     "an uppercase dispatch id",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.DispatchID = strings.ToUpper(validatorDispatchID) },
			wantCode: ErrorCodeMalformedDispatchID,
		},
		{
			name:     "a short dispatch id",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.DispatchID = validatorDispatchID[:31] },
			wantCode: ErrorCodeMalformedDispatchID,
		},
		{
			name:     "a dispatch id that is not hex",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.DispatchID = "zzzzzzzz2b8d4056a1c3e5f70b2d4986" },
			wantCode: ErrorCodeMalformedDispatchID,
		},
		{
			name:     "no dispatch id",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.DispatchID = "" },
			wantCode: ErrorCodeMalformedDispatchID,
		},
		{
			name:     "a scope version the agent no longer holds",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.ScopeVersion = "0f5a1e" },
			wantCode: ErrorCodeScopeVersionMismatch,
		},
		{
			name:     "no scope version",
			mutate:   func(p *frame.DiscoveryRequestPayload) { p.ScopeVersion = "" },
			wantCode: ErrorCodeScopeVersionMismatch,
		},
	}
}

func TestValidator_RefusesEveryOutOfGrantRequest(t *testing.T) {
	for _, tc := range rejectionCases() {
		t.Run(tc.name, func(t *testing.T) {
			rejection := tc.run(t)

			if !rejection.Rejected() {
				t.Fatalf("Rejection = %+v, want a refusal", rejection)
			}
			if rejection.Code != tc.wantCode {
				t.Errorf("Code = %q, want %q (msg %q)", rejection.Code, tc.wantCode, rejection.Msg)
			}
			// The message reaches an operator through ScanJob.error_reason and the agent's own
			// log. An empty one leaves them with a code and nothing to act on; a multi-line one
			// forges a second log record out of a server-supplied string.
			if rejection.Msg == "" {
				t.Error("Msg is empty; the code alone does not say which value was refused")
			}
			if strings.ContainsAny(rejection.Msg, "\r\n") {
				t.Errorf("Msg = %q spans more than one line", rejection.Msg)
			}
		})
	}
}

// TestValidator_AcceptsWhatTheGrantPermits covers the two shapes of a permitted target. The
// routed one is the load-bearing case: plan §2 lets an administrator add a routed subnet and §3
// scopes the directly-connected requirement to automatically derived targets, so a prefix that is
// in additional_cidrs but on no segment of this host must still run.
func TestValidator_AcceptsWhatTheGrantPermits(t *testing.T) {
	for _, tc := range []struct {
		name   string
		target string
	}{
		{name: "a directly connected target", target: "10.20.0.0/25"},
		{name: "a routed target an administrator approved", target: "192.168.50.128/25"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rejection := testValidator()(
				grantedRequest(func(p *frame.DiscoveryRequestPayload) { p.Targets = []string{tc.target} }),
				grantScope(),
			)
			if rejection.Rejected() {
				t.Fatalf("Rejection = %+v, want an acceptance", rejection)
			}
			if rejection != (Rejection{}) {
				t.Errorf("an acceptance carries %+v; the zero value is the whole contract", rejection)
			}
		})
	}

	// Without this the routed case above would pass just as well if the override were being read
	// as a directly connected network, and the exemption it is meant to prove would be untested.
	if netscope.NetworkIsDirectlyConnected(grantScope(), "192.168.50.128/25") {
		t.Fatal("192.168.50.128/25 reads as directly connected; the routed case proves nothing")
	}
}

// TestValidator_ReportsEachCauseUnderItsOwnCode is the property the table exists for. A backend
// that maps error_code onto ScanJob.error_reason can only tell an operator which limit they hit
// while distinct causes carry distinct codes.
func TestValidator_ReportsEachCauseUnderItsOwnCode(t *testing.T) {
	// The three codes below are each one cause wearing several shapes: a dispatch id can be
	// malformed four ways, an absent scope version is a version the agent does not hold, and an
	// absent deadline is a deadline that is not in the future. Every other code must be owned by
	// exactly one row.
	oneCauseManyShapes := map[string]bool{
		ErrorCodeMalformedDispatchID:  true,
		ErrorCodeScopeVersionMismatch: true,
		ErrorCodeDeadlinePassed:       true,
	}

	byCode := make(map[string][]string)
	for _, tc := range rejectionCases() {
		if tc.wantCode == "" {
			t.Errorf("%q expects an empty code, which is how an acceptance is spelled", tc.name)
			continue
		}
		byCode[tc.wantCode] = append(byCode[tc.wantCode], tc.name)
	}
	for code, names := range byCode {
		if len(names) > 1 && !oneCauseManyShapes[code] {
			t.Errorf("%v are distinct causes but all report code %q", names, code)
		}
	}
}

// wideScope is a scope whose one interface is attached to a /21 — 2048 addresses, twice the
// default ceiling. It exists only for the zero-grant test below: grantScope()'s /24 cannot express
// a target that is simultaneously in scope, directly connected, and over
// DefaultLocalDiscoveryConfig().MaxAddressesPerJob, and without such a target the fallback's
// *value* is unpinned.
func wideScope() netscope.Scope {
	return netscope.Derive(
		[]netscope.InterfaceFacts{{
			Name:  "eth0",
			Flags: []string{"up", "broadcast"},
			Addrs: []string{"10.20.0.5/21"},
		}},
		netscope.Config{ScopeMode: netscope.ScopeModeDirectPrivate},
	)
}

// TestValidator_ToleratesAZeroGrant pins the direction a missing bound falls *and the value it
// falls to*. A grant that decoded to zeros must not read as "no ceiling and no port restriction" —
// the same reason Options.hostTimeout refuses to treat a zero as unbounded.
//
// The ceiling is pinned from both sides deliberately. Asserting only that some in-ceiling job is
// accepted would hold just as well if the fallback were replaced by an effectively unbounded
// value, which is the one substitution that turns a malformed grant into an unbounded sweep — so
// the rejection half below is the load-bearing one.
func TestValidator_ToleratesAZeroGrant(t *testing.T) {
	validate := NewValidator(capability.LocalDiscoveryConfig{}, func() time.Time { return validatorNow })

	rejection := validate(grantedRequest(), grantScope())
	if rejection.Code != ErrorCodePortNotGranted {
		t.Errorf("Code = %q, want %q — an empty tcp_ports list grants no port", rejection.Code, ErrorCodePortNotGranted)
	}

	// And the address ceiling falls back to the documented default rather than to zero, which
	// would refuse every request.
	rejection = validate(grantedRequest(func(p *frame.DiscoveryRequestPayload) { p.TCPPorts = nil }), grantScope())
	if rejection.Rejected() {
		t.Errorf("Rejection = %+v, want a 128-address job inside the default ceiling to be accepted", rejection)
	}

	// The two halves of the ceiling itself, expressed as prefixes of the scope's own /21 so the
	// only thing separating them is their address count. A /22 is exactly
	// DefaultLocalDiscoveryConfig().MaxAddressesPerJob addresses and a /21 is twice it, so
	// together they pin the fallback to that number rather than to "some number".
	def := capability.DefaultLocalDiscoveryConfig().MaxAddressesPerJob
	if count := netscope.AddressCount([]string{"10.20.0.0/22"}); count != uint64(def) {
		t.Fatalf("10.20.0.0/22 covers %d addresses, want the default ceiling %d — this test's arithmetic has drifted", count, def)
	}

	atCeiling := grantedRequest(func(p *frame.DiscoveryRequestPayload) {
		p.TCPPorts = nil
		p.Targets = []string{"10.20.0.0/22"}
		p.ScopeVersion = wideScope().Version
	})
	if rejection := validate(atCeiling, wideScope()); rejection.Rejected() {
		t.Errorf("Rejection = %+v, want a job of exactly %d addresses to be accepted under a zero grant",
			rejection, def)
	}

	overCeiling := grantedRequest(func(p *frame.DiscoveryRequestPayload) {
		p.TCPPorts = nil
		p.Targets = []string{"10.20.0.0/21"}
		p.ScopeVersion = wideScope().Version
	})
	rejection = validate(overCeiling, wideScope())
	if rejection.Code != ErrorCodeAddressLimit {
		t.Fatalf("Code = %q, want %q — a zero grant must fall back to the documented ceiling of %d, not to no ceiling at all",
			rejection.Code, ErrorCodeAddressLimit, def)
	}
	// The refusal has to name the ceiling it applied, or an operator cannot tell a fallback that
	// landed on the default from one that landed somewhere else entirely.
	if !strings.Contains(rejection.Msg, strconv.Itoa(def)) {
		t.Errorf("Msg = %q, want it to name the ceiling %d that was applied", rejection.Msg, def)
	}
}

// TestValidator_PerformsNoNetworkIO is plan §7's "validate before opening a socket", asserted
// rather than assumed: a request is refused on what it says, never on what the network answers.
//
// net.DefaultResolver is the one dialer a validator could plausibly reach on its own — a
// hostname target, a PTR lookup, a net.Dial with a name in it all end up here — so it is
// replaced with one that fails the test the moment anything asks it to open a connection.
//
// Swapping the package global is safe only because no test in this package calls t.Parallel; a
// future one must not be this test's neighbour.
func TestValidator_PerformsNoNetworkIO(t *testing.T) {
	original := net.DefaultResolver
	t.Cleanup(func() { net.DefaultResolver = original })
	net.DefaultResolver = &net.Resolver{
		PreferGo: true,
		Dial: func(_ context.Context, network, address string) (net.Conn, error) {
			t.Errorf("validation dialed %s/%s; a request is judged on what it says", network, address)
			return nil, net.ErrClosed
		},
	}

	for _, tc := range rejectionCases() {
		t.Run(tc.name, func(t *testing.T) { tc.run(t) })
	}
	t.Run("an accepted request", func(t *testing.T) {
		if rejection := testValidator()(grantedRequest(), grantScope()); rejection.Rejected() {
			t.Fatalf("Rejection = %+v, want an acceptance", rejection)
		}
	})
}

// validatorSourceImports is everything validate.go may import. None of these can open a socket,
// which is what makes the assertion above more than a resolver check: net.Dial to an IP literal
// never touches net.DefaultResolver, so only the import set rules it out.
var validatorSourceImports = map[string]bool{
	"fmt":     true,
	"strings": true,
	"time":    true,
	"circuitbreaker.dev/cb-agent/internal/capability": true,
	"circuitbreaker.dev/cb-agent/internal/frame":      true,
	"circuitbreaker.dev/cb-agent/internal/netscope":   true,
}

func TestValidatorSourceCannotOpenASocket(t *testing.T) {
	fset, files := parsePackageSources(t)

	file, ok := files["validate.go"]
	if !ok {
		t.Fatal("validate.go is not part of this package; the guard asserts nothing")
	}
	for _, spec := range file.Imports {
		path, err := strconv.Unquote(spec.Path.Value)
		if err != nil {
			t.Fatalf("unquote import %s: %v", spec.Path.Value, err)
		}
		if !validatorSourceImports[path] {
			t.Errorf("%s: validate.go imports %q, which is not on the no-I/O allowlist",
				fset.Position(spec.Pos()), path)
		}
	}

	// A validator that grew a goroutine would be doing work with a lifetime of its own, which is
	// the other way network activity gets in without an import that looks like it.
	ast.Inspect(file, func(node ast.Node) bool {
		if _, ok := node.(*ast.GoStmt); ok {
			t.Errorf("%s: validate.go starts a goroutine; validation is a pure decision",
				fset.Position(node.Pos()))
		}
		return true
	})
}
