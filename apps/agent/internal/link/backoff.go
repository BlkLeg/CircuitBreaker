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
