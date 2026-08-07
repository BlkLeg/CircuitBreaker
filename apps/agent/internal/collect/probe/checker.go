package probe

import (
	"context"
	"encoding/json"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// The four check types a monitor can be assigned to an agent (§5). They are the wire values the
// backend puts in probe.assign.check_type and the keys of the checker registry below, so they
// are constants in one place rather than string literals in five.
const (
	CheckTypeICMP = "icmp"
	CheckTypeTCP  = "tcp"
	CheckTypeHTTP = "http"
	CheckTypeDNS  = "dns"
)

// Outcome is what a checker observed about its target.
//
// It is deliberately *not* collect.Result: collect.Collector and collect.Result are hard-wired to
// frame.HostTelemetryPayload (collect.EncodeBounded even asserts Schema == 1), so a probe result
// cannot travel through them. Samples/Msg/Details instead mirror the backend's
// app.services.monitoring.collectors.CheckResult field-for-field, which is what lets a remote
// result reach the shared result service in the same shape a server-executed one does.
//
// Up describes the *target*, and only ever means anything when the check actually ran: a checker
// that could not perform its probe at all returns a non-zero error instead, which the runtime
// turns into an `execution_error` outcome preserving the monitor's last known state. Returning
// Outcome{Up: false} for "I could not run" would invert monitor state on every misconfigured
// host — the exact mistake §5 calls out for ICMP.
type Outcome struct {
	Up      bool
	Samples []frame.ProbeSample
	Msg     string
	Details map[string]any
}

// Checker performs exactly one check against host and returns what it saw.
//
// It is a local interface rather than collect.Collector for the reason given on Outcome. cfg is
// the monitor's complete validated configuration exactly as the server sent it, raw: it carries
// HTTP credentials when the monitor has them (D-10), so it is passed through untyped and each
// checker decodes only the keys it needs. Nothing may log it, persist it or echo it back.
//
// A checker must honor ctx: the runtime derives one per run carrying both the assignment's
// deadline and its cancellation, and a checker that ignores it makes probe.cancel useless.
type Checker interface {
	Check(ctx context.Context, host string, cfg json.RawMessage) (Outcome, error)
}

// Resolver maps a hostname to its addresses. Injected everywhere so no test reaches the real
// resolver, and split out as a named type because both the runtime's pre-dial scope check and
// the checkers' own per-hop validation take one.
type Resolver func(ctx context.Context, host string) ([]string, error)

// Deps is what a checker is built with. Scope is a live getter, not a value: the server can push
// a new grant config mid-run, and a checker that captured a scope at construction time would
// keep re-validating HTTP redirect hops against a revoked one.
type Deps struct {
	Scope   func() netscope.Scope
	Resolve Resolver
}

// checkerFactories is the registry: one constructor per check type. A checker registers itself
// here and the runtime picks it up — nothing else needs editing, which is what keeps the four
// checkers from growing four different wiring paths.
var checkerFactories = map[string]func(Deps) Checker{
	CheckTypeICMP: newICMPChecker,
	CheckTypeTCP:  newTCPChecker,
	CheckTypeHTTP: newHTTPChecker,
	CheckTypeDNS:  newDNSChecker,
}

// NewCheckers builds the production checker set. Options.Checkers overrides it wholesale, which
// is the seam every runtime test uses.
func NewCheckers(deps Deps) map[string]Checker {
	out := make(map[string]Checker, len(checkerFactories))
	for name, factory := range checkerFactories {
		out[name] = factory(deps)
	}
	return out
}
