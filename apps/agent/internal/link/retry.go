// apps/agent/internal/link/retry.go
package link

import "time"

// RetrySchedule exports backoffState's reconnect ladder for the one caller
// outside this package that needs the identical schedule: cmd/cb-agent's
// first-enrollment retry loop (retryEnroll), which cannot reach
// backoffState/classifyFailure directly — they are unexported — and must
// not grow a second, independently-tuned copy of the same numbers. See
// backoffState's doc comment for why there is exactly one ladder in this
// package; this type is that ladder, not a new one.
//
// It does not cover an authoritative refusal: enroll.Run's "rejected" and
// "revoked" arrive as plain errors from a wire message Run itself decodes
// (the enrollment status frame), not through the hello.ack reason code
// classifyFailure's isRefusalError inspects, so a caller must recognise
// those itself (with errors.Is against enroll.ErrRejected/ErrRevoked) and
// use EnrollRefusalDelay for that attempt instead of calling Next.
type RetrySchedule struct {
	state backoffState
}

// NewRetrySchedule returns a schedule starting at attempt 0 on the
// coming-back ladder — backoffState's zero value, and the same starting
// assumption Run itself makes: the first thing a freshly started agent does
// is dial a server it has every reason to expect is there.
func NewRetrySchedule() *RetrySchedule {
	return &RetrySchedule{}
}

// Next classifies err through the same table Run's own reconnect loop uses
// (classifyFailure) and returns how long to wait before the next attempt,
// advancing the schedule's internal counters for the following call.
//
// reachedHelloAck is always passed as false: enrollment has no notion of a
// session that was accepted and then dropped, only a single dial-and-wait
// per attempt, so the flap detection and "was this session ever accepted"
// distinctions that field exists for do not apply here.
func (r *RetrySchedule) Next(err error) time.Duration {
	class := classifyFailure(err, false)
	return r.state.next(runOutcome{class: class})
}

// EnrollRefusalDelay is the wait after enroll.Run reports an authoritative
// "rejected" or "revoked" — an operator's decision, not an outage, so
// neither ladder in this package applies (see refusedDelay's doc comment,
// which this mirrors). It returns the same jittered 30-minute wait
// refusedDelay uses for its own errRevoked/errRejected branch, so that
// number is written down exactly once in the tree even though enroll's
// refusal is a distinct error type from link's.
func EnrollRefusalDelay() time.Duration {
	return jittered(refusedDelay(errRejected))
}
