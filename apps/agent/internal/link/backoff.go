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

// backoffDelay adds up to 25% jitter on top of the base duration.
func backoffDelay(attempt int) time.Duration {
	base := backoffBaseDuration(attempt)
	jitter := time.Duration(rand.Int63n(int64(base/4) + 1))
	return base + jitter
}

// backoffState tracks the reconnect-attempt counter across Run's retry
// loop. Each runOnce reports whether its connection was ever "stable" —
// i.e. it received an accepted hello.ack and then stayed up for at least
// stabilityWindow before disconnecting. A stable run resets the counter to
// the floor before computing its delay, so the next reconnect starts the
// 1s-5m jittered progression over again rather than continuing from
// wherever a prior run of failures left off; an unstable run (one that
// never got past handshake/hello, was rejected, or dropped before the
// stability window elapsed) continues that progression. The zero value is
// ready to use, starting at attempt 0.
type backoffState struct {
	attempt int
}

// next reports the delay to wait before the next reconnect attempt and
// advances the counter for the following call.
func (b *backoffState) next(stable bool) time.Duration {
	if stable {
		b.attempt = 0
	}
	delay := backoffDelay(b.attempt)
	b.attempt++
	return delay
}
