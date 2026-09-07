package link

import (
	"math/rand"
	"time"
)

const (
	backoffBase = 1 * time.Second
	backoffMax  = 5 * time.Minute
)

// backoffBaseDuration doubles per attempt, capped at backoffMax. Pure and
// deterministic so it's unit-testable without jitter noise.
//
// This is the *unreachable* ladder. It is unchanged, and it is still the right
// answer for a host that is genuinely off the network: there is nothing to be
// gained by asking a dead network every second, and a fleet that does costs the
// one server least able to absorb it.
func backoffBaseDuration(attempt int) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	if attempt > 20 { // 1s * 2^20 already exceeds backoffMax many times over
		return backoffMax
	}
	d := backoffBase * time.Duration(int64(1)<<uint(attempt))
	if d > backoffMax || d <= 0 {
		return backoffMax
	}
	return d
}

// The coming-back ladder: a short climb, then a permanent hold.
//
// It holds rather than escalating because escalation only ever made sense as a
// guess about *why* the peer was silent. Once the failure is classified, the
// guess is unnecessary: a host that is answering — a restart, a warming worker,
// a graceful close — will answer again shortly, and the only question is how
// long we are willing to wait to find out. Fifteen seconds against a server
// measured to be ready ~20-35s after a restart means the first or second poll
// of the hold catches it, every time, instead of the old ladder's coin flip
// between 36 seconds and twenty minutes.
var fastBackoffSteps = []time.Duration{
	250 * time.Millisecond,
	500 * time.Millisecond,
	1 * time.Second,
	2 * time.Second,
	4 * time.Second,
	8 * time.Second,
}

const fastBackoffHold = 15 * time.Second

// fastBackoffBaseDuration indexes fastBackoffSteps and then holds. Pure, for
// the same reason backoffBaseDuration is.
func fastBackoffBaseDuration(attempt int) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	if attempt >= len(fastBackoffSteps) {
		return fastBackoffHold
	}
	return fastBackoffSteps[attempt]
}

// ladderBaseDuration picks the ladder for a class. classRefused never reaches
// here — Run answers it from refusedDelay, which is per-reason.
func ladderBaseDuration(class failureClass, attempt int) time.Duration {
	if class == classComingBack {
		return fastBackoffBaseDuration(attempt)
	}
	return backoffBaseDuration(attempt)
}

// jittered adds up to 25% on top of a base duration. Applied to both ladders:
// at the 15s hold that is up to 3.75s of fleet spread, which is exactly the
// thundering-herd protection a cold-starting server needs from a fleet that is
// now, deliberately, all knocking at once.
func jittered(base time.Duration) time.Duration {
	return base + time.Duration(rand.Int63n(int64(base/4)+1))
}

// backoffDelay adds up to 25% jitter on top of the base duration.
func backoffDelay(attempt int) time.Duration {
	return jittered(backoffBaseDuration(attempt))
}

// How short a session has to be, and how many in a row, before a link that
// keeps being accepted and then dropping is treated as broken rather than as a
// series of honest reconnects.
const (
	flapWindow    = 5 * time.Second
	flapThreshold = 3
)

// runOutcome is what one runOnce reports back to the retry loop.
//
// It replaces a bare `stable bool`. The old flag conflated three separate
// questions — were we accepted, did we last long enough, and what went wrong —
// and answered the ladder with only the middle one.
type runOutcome struct {
	// reachedHelloAck: the server accepted this session at all.
	reachedHelloAck bool
	// upFor: how long the run lasted after that acceptance. Zero if never accepted.
	upFor time.Duration
	// class: which ladder the next attempt should use.
	class failureClass
	// refusal: the sentinel from an authoritative refusal, when class is
	// classRefused. Nil otherwise.
	refusal error
}

// backoffState tracks the reconnect-attempt counter across Run's retry loop,
// per failure class.
//
// The counter used to reset only after a run stayed up for 30 seconds past its
// hello.ack. That window was meant to stop a flapping link from being rewarded
// with a fast retry, but it punished every honest reconnect too: an agent that
// reconnected and then lost the link again at 29 seconds resumed the ladder
// wherever the previous outage had left it, which is how a link that flapped
// through an outage ended up pinned at five and six minute waits with the
// server sitting there answering.
//
// So: reset on any accepted hello.ack, and guard the flapping case directly by
// counting consecutive sub-flapWindow sessions instead. Three in a row and the
// ladder is forced slow — a floor that a healthy agent never touches.
//
// The zero value is ready to use, starting at attempt 0 on the coming-back
// ladder: the first thing a freshly started agent does is dial a server it has
// every reason to expect is there.
type backoffState struct {
	attempt   int
	class     failureClass
	flapCount int
}

// next reports the delay to wait before the next reconnect attempt and advances
// the counter for the following call.
func (b *backoffState) next(o runOutcome) time.Duration {
	// An authoritative refusal is not a ladder position. Answer it directly and
	// leave the counters alone, so that whatever was happening before the
	// server started refusing us is still there if it stops.
	if o.class == classRefused {
		return jittered(refusedDelay(o.refusal))
	}

	// A class change restarts *that class's* ladder. Twenty minutes of
	// unreachable followed by a clean 1012 has to start at 250ms, not inherit
	// the five-minute rung the other ladder had climbed to.
	if o.class != b.class {
		b.class = o.class
		b.attempt = 0
	}

	if o.reachedHelloAck {
		if o.upFor < flapWindow {
			b.flapCount++
		} else {
			b.flapCount = 0
		}
		// Reset unless the link is flapping — a server that accepts us and then
		// drops us three times inside five seconds is one we should stop
		// sprinting at.
		if b.flapCount < flapThreshold {
			b.attempt = 0
		} else {
			b.class = classUnreachable
		}
	}

	delay := jittered(ladderBaseDuration(b.class, b.attempt))
	b.attempt++
	return delay
}
