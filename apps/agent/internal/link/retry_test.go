// apps/agent/internal/link/retry_test.go
package link

import (
	"errors"
	"syscall"
	"testing"

	"github.com/gorilla/websocket"
)

func TestRetrySchedule_ClassifiesAndAdvancesLikeTheReconnectLoop(t *testing.T) {
	sched := NewRetrySchedule()
	base0 := backoffBaseDuration(0)
	base1 := backoffBaseDuration(1)

	// An unreachable-class error (syscall.ECONNREFUSED) walks the exponential
	// ladder, exactly as Run's own reconnect loop would classify it.
	d0 := sched.Next(syscall.ECONNREFUSED)
	if d0 < base0 || d0 > base0+base0/4+1 {
		t.Fatalf("Next() first delay = %v, want in [%v, %v]", d0, base0, base0+base0/4)
	}
	d1 := sched.Next(syscall.ECONNREFUSED)
	if d1 < base1 || d1 > base1+base1/4+1 {
		t.Fatalf("Next() second delay = %v, want in [%v, %v]", d1, base1, base1+base1/4)
	}
}

func TestRetrySchedule_ComingBackClassNeverExceedsTheHold(t *testing.T) {
	// websocket.ErrBadHandshake is classifyFailure's "nginx is up, the app
	// behind it isn't yet" signature — the canonical mono-image restart, and
	// exactly the shape of failure a server that is still coming up presents
	// to a dialing enroll.Run.
	sched := NewRetrySchedule()
	for i := 0; i < 20; i++ {
		d := sched.Next(websocket.ErrBadHandshake)
		if d > fastBackoffHold+fastBackoffHold/4+1 {
			t.Fatalf("attempt #%d: Next() = %v, want <= the jittered %v hold", i, d, fastBackoffHold)
		}
	}
}

func TestEnrollRefusalDelay_MatchesRefusedDelaysOwnRevokedRejectedBranch(t *testing.T) {
	want := refusedDelay(errRejected)
	for i := 0; i < 20; i++ {
		got := EnrollRefusalDelay()
		if got < want || got > want+want/4+1 {
			t.Fatalf("EnrollRefusalDelay() = %v, want in [%v, %v]", got, want, want+want/4)
		}
	}
	// errRevoked shares the same branch in refusedDelay, so the two must
	// agree exactly (before jitter) — otherwise link and enroll would answer
	// an identical kind of refusal with two different numbers.
	if refusedDelay(errRejected) != refusedDelay(errRevoked) {
		t.Fatal("refusedDelay(errRejected) != refusedDelay(errRevoked); EnrollRefusalDelay would only cover one of them")
	}
}

func TestRetrySchedule_OrdinaryErrorsAlwaysProduceAPositiveDelay(t *testing.T) {
	sched := NewRetrySchedule()
	if d := sched.Next(errors.New("some ordinary error")); d <= 0 {
		t.Fatalf("Next() = %v, want a positive delay", d)
	}
}
