package link

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"net"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
)

// failureClass is what the reconnect ladder is chosen from.
//
// The distinction this draws is the whole reason a server restart used to cost
// twenty minutes. The old loop had one exponential progression and fed every
// failure into it, so "the service you were just talking to is restarting and
// will be back in thirty seconds" and "this host has been off the network for
// an hour" were answered with the same escalating wait. Since the ladder only
// ever grew, whichever rung it happened to be standing on when the server
// returned *was* the recovery time — 36 seconds if you were lucky, five minutes
// if you were not.
type failureClass int

const (
	// classComingBack: something answered, and it is the thing we want. A
	// restart, a warming worker, a graceful close. Redial quickly and keep
	// redialing quickly — escalating buys nothing against a host that is up.
	classComingBack failureClass = iota

	// classUnreachable: the host or the path to it is gone. Escalate, because
	// retrying at LAN speed against a dead network is pure noise.
	classUnreachable

	// classRefused: the server authoritatively refused this identity inside the
	// encrypted channel. Neither ladder applies — see refusedLadder, which is
	// chosen per reason.
	classRefused
)

// errHelloAckTimeout ends a run whose socket was accepted and whose Noise
// handshake completed, but which never got an accepted hello.ack.
//
// Without it that wait inherits the 60s read deadline, so a server still
// warming its connection pool costs a full minute *and* — because the run never
// reached hello.ack — advances the backoff as though it had failed outright.
var errHelloAckTimeout = errors.New("link: no accepted hello.ack within the hello deadline")

// errAckStall ends a run in which data frames sat on the wire for
// ackStallTimeout without a single `data.ack` releasing any of them.
//
// It is distinct from errReadTimeout on purpose. A server that has gone
// silent trips the 60s read deadline and is a partition; a server that is
// still reading the socket and answering pings — so the read deadline keeps
// being refreshed — but is not acknowledging anything is a fault in the
// server, and 45s is short enough to reach that conclusion first. Ending the
// connection commits nothing, so everything in flight is re-sent on the next
// one.
var errAckStall = errors.New("link: server stopped acknowledging data frames")

// The reasons a server can refuse an identity, as sentinels so the ladder can
// tell "approve me" from "you are not welcome here". The wire values are the
// `reason` string on a hello.ack with accepted:false.
var (
	errUnknownDevice   = errors.New("link: server does not recognise this device")
	errPendingApproval = errors.New("link: waiting for an operator to approve this device")
	errRevoked         = errors.New("link: this device's enrolment was revoked")
	errRejected        = errors.New("link: this device's enrolment was rejected")
)

// Wire reason codes, mirrored server-side.
const (
	reasonUnknownDevice   = "unknown_device"
	reasonPendingApproval = "pending_approval"
	reasonRevoked         = "revoked"
	reasonRejected        = "rejected"
)

// refusalError maps a hello.ack rejection reason onto a sentinel. An
// unrecognised reason returns nil: a refusal we cannot interpret must not be
// guessed at, and falls through to the ordinary ladder.
func refusalError(reason string) error {
	switch reason {
	case reasonUnknownDevice:
		return errUnknownDevice
	case reasonPendingApproval:
		return errPendingApproval
	case reasonRevoked:
		return errRevoked
	case reasonRejected:
		return errRejected
	}
	return nil
}

func isRefusalError(err error) bool {
	return errors.Is(err, errUnknownDevice) ||
		errors.Is(err, errPendingApproval) ||
		errors.Is(err, errRevoked) ||
		errors.Is(err, errRejected)
}

// refusedDelay is the wait after an authoritative refusal. Neither ordinary
// ladder fits: the server is up and answering, so the unreachable ladder is
// wrong, but the answer is "no", so the fast ladder would be a storm.
//
// Approval is the one worth checking often — an operator clicking Approve
// should not wait five minutes to see the agent come up.
func refusedDelay(err error) time.Duration {
	switch {
	case errors.Is(err, errPendingApproval):
		return 30 * time.Second
	case errors.Is(err, errRevoked), errors.Is(err, errRejected):
		return 30 * time.Minute
	default: // errUnknownDevice
		return 5 * time.Minute
	}
}

func (c failureClass) String() string {
	switch c {
	case classComingBack:
		return "coming-back"
	case classUnreachable:
		return "unreachable"
	case classRefused:
		return "refused"
	}
	return "unknown"
}

// closeCodeClass maps a WebSocket close code onto a class. Split out so the
// table reads as a table.
//
// 1008 (policy violation) is deliberately *unreachable* rather than
// coming-back, even though the server is plainly up to have sent it. A close
// frame is unauthenticated — anything on the path can forge one — and a fast
// ladder against a peer that is refusing us is a reconnect storm aimed at the
// one server least able to absorb it. The authenticated `hello.ack` rejection
// is what carries a refusal we act on quickly; this code alone never earns it.
func closeCodeClass(code int, reachedHelloAck bool) (failureClass, bool) {
	switch code {
	case websocket.CloseNormalClosure, // 1000
		websocket.CloseGoingAway,         // 1001
		websocket.CloseInternalServerErr, // 1011 — up, and erroring; it will be back
		websocket.CloseServiceRestart,    // 1012 — says so on the tin
		websocket.CloseTryAgainLater:     // 1013 — rate gate, incl. Redis not yet up
		return classComingBack, true
	case websocket.CloseAbnormalClosure: // 1006
		// The same code means "a healthy session vanished" or "the path never
		// worked", and only whether we were ever accepted tells them apart.
		if reachedHelloAck {
			return classComingBack, true
		}
		return classUnreachable, true
	case websocket.ClosePolicyViolation: // 1008
		return classUnreachable, true
	}
	return classUnreachable, false
}

// classifyFailure decides which ladder the next reconnect uses.
//
// One call site, in Run, against the error runOnce returned — which is the sole
// producer of dial, read and write errors alike, so every path is covered
// without duplicating the table. reachedHelloAck reports whether *this* run was
// ever accepted by the server; several errors are ambiguous without it.
func classifyFailure(err error, reachedHelloAck bool) failureClass {
	if err == nil {
		return classComingBack
	}

	// A refusal we can act on beats everything else: it arrived inside the
	// Noise channel, so unlike a close code it cannot have been forged by the
	// path.
	if isRefusalError(err) {
		return classRefused
	}

	var closeErr *websocket.CloseError
	if errors.As(err, &closeErr) {
		if class, ok := closeCodeClass(closeErr.Code, reachedHelloAck); ok {
			return class
		}
	}

	// Something answered the HTTP upgrade and said no: nginx is listening and
	// the app behind it is still starting. The canonical mono-image restart.
	if errors.Is(err, websocket.ErrBadHandshake) {
		return classComingBack
	}

	// The socket was accepted and Noise completed, then the server stalled —
	// a cold connection pool on a server that is otherwise up.
	if errors.Is(err, errHelloAckTimeout) {
		return classComingBack
	}

	// A peer that resets or hangs up on a session it had already accepted is
	// restarting. One that does it before accepting us is a broken path.
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) ||
		errors.Is(err, syscall.ECONNRESET) || errors.Is(err, syscall.EPIPE) {
		if reachedHelloAck {
			return classComingBack
		}
		return classUnreachable
	}

	// Sixty seconds of silence is a partition, not a restart — a restarting
	// server closes the socket rather than going quiet.
	if errors.Is(err, errReadTimeout) {
		return classUnreachable
	}

	// An ack stall is the opposite evidence: the server answered the socket
	// and kept answering it, and only its ingest path stopped moving. That is
	// something that is up and having a bad minute — a saturated worker, a
	// database that is failing over — so redial quickly, exactly as for a
	// restart. Escalating would only lengthen the outage of a host we can
	// demonstrably reach.
	if errors.Is(err, errAckStall) {
		return classComingBack
	}

	// A pin mismatch is an operator problem. Hammering helps nobody and
	// obscures the log line that explains it. tlsdial reports one as a plain
	// fmt.Errorf out of VerifyPeerCertificate, which surfaces here as a TLS
	// handshake error; the unmatched-default below is the same class anyway, so
	// this arm exists to be explicit rather than to change the answer.
	var certErr *tls.CertificateVerificationError
	var authErr x509.UnknownAuthorityError
	if errors.As(err, &certErr) || errors.As(err, &authErr) {
		return classUnreachable
	}

	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return classUnreachable
	}

	if errors.Is(err, syscall.ECONNREFUSED) ||
		errors.Is(err, syscall.EHOSTUNREACH) ||
		errors.Is(err, syscall.ENETUNREACH) ||
		errors.Is(err, syscall.ENETDOWN) ||
		errors.Is(err, syscall.EHOSTDOWN) ||
		errors.Is(err, syscall.ETIMEDOUT) {
		return classUnreachable
	}

	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return classUnreachable
	}

	// Unmatched failures take the slow ladder on purpose: an unrecognised error
	// is the case we understand least, and the conservative ladder is the one
	// that cannot turn a misunderstanding into a storm.
	return classUnreachable
}
