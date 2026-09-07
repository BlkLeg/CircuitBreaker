package link

import (
	"errors"
	"fmt"
	"io"
	"net"
	"syscall"
	"testing"

	"github.com/gorilla/websocket"
)

// The table is the design. Each row is a failure the agent actually sees in the
// field, and the class decides whether recovery takes a quarter of a second or
// walks up to five minutes — which, before this existed, was the difference
// between a 36-second reconnect and a twenty-minute one for the same restart.
func TestClassifyFailure(t *testing.T) {
	cases := []struct {
		name            string
		err             error
		reachedHelloAck bool
		want            failureClass
	}{
		// ── The server is coming back ────────────────────────────────────────
		{"close 1012 service restart", &websocket.CloseError{Code: websocket.CloseServiceRestart}, true, classComingBack},
		{"close 1001 going away", &websocket.CloseError{Code: websocket.CloseGoingAway}, true, classComingBack},
		{"close 1000 normal", &websocket.CloseError{Code: websocket.CloseNormalClosure}, true, classComingBack},
		{"close 1011 internal error — up, and erroring", &websocket.CloseError{Code: websocket.CloseInternalServerErr}, true, classComingBack},
		{"close 1013 try again later — the rate gate, incl. Redis not yet up", &websocket.CloseError{Code: websocket.CloseTryAgainLater}, false, classComingBack},
		{"bad handshake — nginx up, app still starting", websocket.ErrBadHandshake, false, classComingBack},
		{"wrapped bad handshake", fmt.Errorf("link: dial: %w", websocket.ErrBadHandshake), false, classComingBack},
		{"hello.ack timeout — socket accepted, server stalled", errHelloAckTimeout, false, classComingBack},

		// ── Ambiguous without knowing whether we were ever accepted ──────────
		{"close 1006 after acceptance is a peer that vanished", &websocket.CloseError{Code: websocket.CloseAbnormalClosure}, true, classComingBack},
		{"close 1006 before acceptance is a broken path", &websocket.CloseError{Code: websocket.CloseAbnormalClosure}, false, classUnreachable},
		{"EOF after acceptance", io.EOF, true, classComingBack},
		{"EOF before acceptance", io.EOF, false, classUnreachable},
		{"ECONNRESET after acceptance", fmt.Errorf("read: %w", syscall.ECONNRESET), true, classComingBack},
		{"ECONNRESET before acceptance", fmt.Errorf("read: %w", syscall.ECONNRESET), false, classUnreachable},

		// ── Genuinely unreachable ────────────────────────────────────────────
		{
			// Unauthenticated, so it never earns the fast ladder however
			// plainly it implies the server is up: a forged close frame must
			// not be able to point a fleet at one server every 250ms.
			"close 1008 policy violation stays slow even after acceptance",
			&websocket.CloseError{Code: websocket.ClosePolicyViolation}, true, classUnreachable,
		},
		{"read timeout — 60s of silence is a partition", errReadTimeout, true, classUnreachable},
		{"no route to host", fmt.Errorf("dial tcp: %w", syscall.EHOSTUNREACH), false, classUnreachable},
		{"network unreachable", fmt.Errorf("dial tcp: %w", syscall.ENETUNREACH), false, classUnreachable},
		{"connection refused", fmt.Errorf("dial tcp: %w", syscall.ECONNREFUSED), false, classUnreachable},
		{"DNS failure", &net.DNSError{Err: "no such host", Name: "cb.local", IsNotFound: true}, false, classUnreachable},
		{"an unrecognised error takes the conservative ladder", errors.New("something new"), false, classUnreachable},

		// ── Authoritative refusals ───────────────────────────────────────────
		{"unknown device", errUnknownDevice, false, classRefused},
		{"pending approval", errPendingApproval, false, classRefused},
		{"revoked", errRevoked, false, classRefused},
		{"rejected", errRejected, false, classRefused},
		{"a wrapped refusal is still a refusal", fmt.Errorf("link: %w", errRevoked), false, classRefused},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := classifyFailure(c.err, c.reachedHelloAck); got != c.want {
				t.Errorf("classifyFailure(%v, reachedHelloAck=%v) = %v, want %v",
					c.err, c.reachedHelloAck, got, c.want)
			}
		})
	}
}

func TestClassifyFailure_NilIsNotAFailure(t *testing.T) {
	if got := classifyFailure(nil, true); got != classComingBack {
		t.Errorf("classifyFailure(nil) = %v, want %v", got, classComingBack)
	}
}

func TestRefusalError_MapsWireReasonsAndIgnoresUnknownOnes(t *testing.T) {
	for reason, want := range map[string]error{
		reasonUnknownDevice:   errUnknownDevice,
		reasonPendingApproval: errPendingApproval,
		reasonRevoked:         errRevoked,
		reasonRejected:        errRejected,
	} {
		if got := refusalError(reason); !errors.Is(got, want) {
			t.Errorf("refusalError(%q) = %v, want %v", reason, got, want)
		}
	}
	// A refusal we cannot interpret must not be guessed at — it falls through
	// to the ordinary ladder rather than picking a policy at random.
	for _, reason := range []string{"", "something_new", "UNKNOWN_DEVICE"} {
		if got := refusalError(reason); got != nil {
			t.Errorf("refusalError(%q) = %v, want nil", reason, got)
		}
	}
}
