package discover

import (
	"fmt"
	"strings"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// The machine-readable refusal codes this package owns. They travel to the backend as the
// terminal summary's error_code, which becomes ScanJob.error_reason, so they are constants rather
// than prose: an operator who sees "the job failed" learns nothing, and a message that changed
// wording would silently break whatever the server matched on.
//
// There is deliberately no code here for "out of scope". A target netscope refuses is reported
// under netscope's own reason, unchanged — inventing a parallel vocabulary would be a second
// scope evaluator in everything but name.
const (
	ErrorCodeUnknownMethod       = "unknown_method"
	ErrorCodeAddressLimit        = "address_limit_exceeded"
	ErrorCodePortNotGranted      = "port_not_granted"
	ErrorCodeDeadlinePassed      = "deadline_passed"
	ErrorCodeMalformedDispatchID = "malformed_dispatch_id"

	// ErrorCodeScopeVersionMismatch is D-16's end of the versioned dispatch: the request was
	// built against an authorization this agent no longer holds, so nothing else it claims can
	// be trusted either.
	ErrorCodeScopeVersionMismatch = "scope_version_mismatch"

	// ErrorCodeNotDirectlyConnected is netscope's reason verbatim for the same reason the
	// in-scope refusals are: the rule is netscope's, this package only asks the question.
	ErrorCodeNotDirectlyConnected = netscope.ReasonNotDirectlyConnected
)

// dispatchIDLength is the width the backend mints and its pydantic model requires (32 lowercase
// hex). It is checked rather than normalized because the id is the join key every finding and the
// server's dispatch row share: an id this agent repaired would produce findings the backend
// cannot match to anything.
const dispatchIDLength = 32

// knownMethods is the closed discovery.request method vocabulary (plan §4). A request naming
// anything else is refused wholesale rather than run with the unknown entry dropped: the operator
// asked for evidence this build cannot gather, and silently returning less would read as "nothing
// was there".
var knownMethods = []string{MethodNeighborCache, MethodICMP, MethodTCPConnect, MethodReverseDNS}

// Rejection is a validator's answer. The zero value is an acceptance, so a caller that forgets to
// check one gets the safe reading only when nothing was wrong; every refusal carries a code.
//
// Msg is prose for an operator and Code is what the backend matches on. Msg quotes any
// server-supplied string with %q so a value containing a newline cannot forge a second record in
// the agent's log.
type Rejection struct {
	Code string
	Msg  string
}

// Rejected reports whether this answer refuses the request.
func (r Rejection) Rejected() bool { return r.Code != "" }

// Validator decides whether one discovery.request may run, before anything opens a socket.
//
// The scope is a parameter rather than something the validator closes over because the two move
// independently: the grant changes when the server rewrites it, and the scope changes whenever
// this host's interfaces do. The runtime holds one Validator and hands it whichever scope it has
// derived most recently, which is also what lets a test substitute a stub.
type Validator func(frame.DiscoveryRequestPayload, netscope.Scope) Rejection

// NewValidator binds one `local_discovery` grant into a Validator.
//
// now is the clock the deadline is judged against; nil takes the wall clock in UTC, matching the
// frame's own timestamps.
//
// Nothing in the returned function touches the network. That is the point of the split: plan §7
// requires a request to be refused on what it says, and a validator that resolved a name would
// let a hostile DNS answer decide how long the refusal took and whether it happened at all.
func NewValidator(cfg capability.LocalDiscoveryConfig, now func() time.Time) Validator {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	// A grant that decoded to zeros must mean "the documented bound", never "no bound at all" —
	// the same direction Options.hostTimeout falls, and for the same reason: an unbounded job is
	// what this ceiling exists to prevent. The port list is the deliberate exception; an empty
	// one grants no port, because a port outside the grant is a capability violation rather than
	// a missing default.
	maxAddresses := cfg.MaxAddressesPerJob
	if maxAddresses <= 0 {
		maxAddresses = capability.DefaultLocalDiscoveryConfig().MaxAddressesPerJob
	}
	// Options is this package's single answer to "did the grant list this port", so the check is
	// borrowed rather than restated — two port tests that could drift is exactly how a sweep ends
	// up touching something validation approved on other terms.
	granted := Options{TCPPorts: cfg.TCPPorts}

	return func(req frame.DiscoveryRequestPayload, scope netscope.Scope) Rejection {
		// The dispatch id comes first because it is the only field whose absence makes the
		// refusal itself unreportable: every summary frame is addressed by it.
		if !validDispatchID(req.DispatchID) {
			return Rejection{
				Code: ErrorCodeMalformedDispatchID,
				Msg: fmt.Sprintf("dispatch_id %q is not %d lowercase hex characters",
					req.DispatchID, dispatchIDLength),
			}
		}
		// Then the scope version, because it decides whether the rest of the request is even
		// being read against the authorization it was written against (D-16). Judging the
		// targets first would refuse a stale request under whichever limit it happened to trip.
		if req.ScopeVersion != scope.Version {
			return Rejection{
				Code: ErrorCodeScopeVersionMismatch,
				Msg: fmt.Sprintf("request carries scope version %q, this agent holds %q",
					req.ScopeVersion, scope.Version),
			}
		}
		for _, method := range req.Methods {
			if !knownMethod(method) {
				return Rejection{
					Code: ErrorCodeUnknownMethod,
					Msg:  fmt.Sprintf("method %q is not one of %s", method, strings.Join(knownMethods, ", ")),
				}
			}
		}
		for _, port := range req.TCPPorts {
			if !granted.allowsPort(port) {
				return Rejection{
					Code: ErrorCodePortNotGranted,
					Msg:  fmt.Sprintf("tcp port %d is not in this agent's grant", port),
				}
			}
		}
		// A deadline in the past is refused rather than run and immediately abandoned: the work
		// would produce findings the backend has already stopped accepting.
		if !req.DeadlineAt.After(now()) {
			return Rejection{
				Code: ErrorCodeDeadlinePassed,
				Msg: fmt.Sprintf("deadline_at %s is not in the future",
					req.DeadlineAt.UTC().Format(time.RFC3339)),
			}
		}

		for _, target := range req.Targets {
			// netscope is the one scope evaluator, shared with the backend and pinned to
			// fixtures/agent_scope_corpus.json. Its reason is carried through as the code so the
			// two languages refuse the same target for the same named reason.
			if decision := netscope.NetworkInScope(scope, target); !decision.Allowed {
				return Rejection{
					Code: decision.Reason,
					Msg:  fmt.Sprintf("target %q is not in this agent's scope", target),
				}
			}
			// §7's execution-time re-check, which the backend cannot make on the agent's behalf.
			// The approved half is the exemption plan §2 requires: an administrator may add a
			// routed subnet on purpose, and such a subnet is on no segment this host is attached
			// to, so demanding direct connection would make the override unusable. A target in
			// neither half reached the allow list some other way and is authorized by nothing
			// this host can corroborate.
			if !netscope.NetworkIsDirectlyConnected(scope, target) && !netscope.NetworkIsApproved(scope, target) {
				return Rejection{
					Code: ErrorCodeNotDirectlyConnected,
					Msg: fmt.Sprintf(
						"target %q is neither directly connected nor an approved routed network", target),
				}
			}
		}
		// Last, because AddressCount is only meaningful once every prefix has been through
		// NetworkInScope: it skips an unparseable entry rather than refusing it, so counting
		// first would let a malformed target slip under the ceiling unnoticed.
		if count := netscope.AddressCount(req.Targets); count > uint64(maxAddresses) {
			return Rejection{
				Code: ErrorCodeAddressLimit,
				Msg: fmt.Sprintf("targets cover %d addresses, this agent's grant allows %d",
					count, maxAddresses),
			}
		}
		return Rejection{}
	}
}

func knownMethod(method string) bool {
	for _, known := range knownMethods {
		if method == known {
			return true
		}
	}
	return false
}

// validDispatchID accepts exactly what the backend mints. Lowercase is required rather than
// folded: the id is compared byte-for-byte on both sides, and accepting a case variant here would
// let one dispatch be tracked under two spellings.
func validDispatchID(id string) bool {
	if len(id) != dispatchIDLength {
		return false
	}
	for i := 0; i < len(id); i++ {
		switch c := id[i]; {
		case c >= '0' && c <= '9', c >= 'a' && c <= 'f':
		default:
			return false
		}
	}
	return true
}
