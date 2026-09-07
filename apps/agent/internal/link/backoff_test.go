package link

import (
	"testing"
	"time"
)

func TestBackoffBaseDuration_DoublesUpToCap(t *testing.T) {
	cases := []struct {
		attempt int
		want    time.Duration
	}{
		{0, 1 * time.Second},
		{1, 2 * time.Second},
		{2, 4 * time.Second},
		{3, 8 * time.Second},
		{20, 5 * time.Minute}, // capped
	}
	for _, c := range cases {
		if got := backoffBaseDuration(c.attempt); got != c.want {
			t.Errorf("backoffBaseDuration(%d) = %v, want %v", c.attempt, got, c.want)
		}
	}
}

func TestBackoffDelay_StaysWithinBaseToBasePlusQuarter(t *testing.T) {
	for attempt := 0; attempt < 10; attempt++ {
		base := backoffBaseDuration(attempt)
		for i := 0; i < 20; i++ {
			d := backoffDelay(attempt)
			if d < base || d > base+base/4+1 {
				t.Errorf("backoffDelay(%d) = %v, want in [%v, %v]", attempt, d, base, base+base/4)
			}
		}
	}
}

// The unreachable ladder is unchanged, so the two tests above still pin it.
// These cover what is new: a second, non-exponential ladder, and a counter that
// resets on acceptance rather than on surviving an arbitrary window.

func TestFastBackoff_ClimbsThenHoldsForever(t *testing.T) {
	want := []time.Duration{
		250 * time.Millisecond,
		500 * time.Millisecond,
		1 * time.Second,
		2 * time.Second,
		4 * time.Second,
		8 * time.Second,
	}
	for attempt, expect := range want {
		if got := fastBackoffBaseDuration(attempt); got != expect {
			t.Errorf("fastBackoffBaseDuration(%d) = %v, want %v", attempt, got, expect)
		}
	}
	// The hold is the point: a host that is answering will answer again, so
	// there is nothing to be gained by escalating into the minutes the way the
	// unreachable ladder does.
	for _, attempt := range []int{len(want), len(want) + 1, 50, 5000} {
		if got := fastBackoffBaseDuration(attempt); got != fastBackoffHold {
			t.Errorf("fastBackoffBaseDuration(%d) = %v, want the %v hold", attempt, got, fastBackoffHold)
		}
	}
	if got := fastBackoffBaseDuration(-1); got != want[0] {
		t.Errorf("fastBackoffBaseDuration(-1) = %v, want the floor %v", got, want[0])
	}
}

// The regression this whole change exists for: a server restart used to walk
// the exponential ladder into the minutes, so recovery was decided by which
// rung the agent happened to be standing on. On the coming-back ladder the
// worst case is the hold.
func TestBackoffState_ComingBackNeverExceedsTheHold(t *testing.T) {
	var b backoffState
	for i := 0; i < 40; i++ {
		delay := b.next(runOutcome{class: classComingBack})
		if delay > fastBackoffHold+fastBackoffHold/4+1 {
			t.Fatalf("attempt #%d: delay = %v, want <= the jittered %v hold", i, delay, fastBackoffHold)
		}
	}
}

func TestBackoffState_LaddersAndResets(t *testing.T) {
	fast0 := fastBackoffBaseDuration(0)

	t.Run("an accepted hello.ack resets the ladder without needing to survive a window", func(t *testing.T) {
		var b backoffState
		b.next(runOutcome{class: classUnreachable})
		b.next(runOutcome{class: classUnreachable})
		if b.attempt != 2 {
			t.Fatalf("setup: attempt = %d, want 2", b.attempt)
		}
		// Accepted, then dropped after a healthy interval. The old code kept
		// climbing unless the run also survived 30s.
		delay := b.next(runOutcome{class: classComingBack, reachedHelloAck: true, upFor: time.Minute})
		if b.attempt != 1 {
			t.Errorf("attempt = %d, want the ladder reset to 1", b.attempt)
		}
		if delay < fast0 || delay > fast0+fast0/4+1 {
			t.Errorf("delay = %v, want the coming-back floor %v", delay, fast0)
		}
	})

	t.Run("switching class restarts that class's ladder rather than inheriting a rung", func(t *testing.T) {
		var b backoffState
		for i := 0; i < 8; i++ { // climb the unreachable ladder to its cap
			b.next(runOutcome{class: classUnreachable})
		}
		delay := b.next(runOutcome{class: classComingBack})
		if delay < fast0 || delay > fast0+fast0/4+1 {
			t.Errorf("delay = %v, want the coming-back floor %v — an unreachable host that "+
				"starts answering must not inherit the slow ladder's rung", delay, fast0)
		}
	})

	t.Run("a flapping link is forced onto the slow ladder", func(t *testing.T) {
		var b backoffState
		flap := runOutcome{class: classComingBack, reachedHelloAck: true, upFor: time.Second}
		for i := 0; i < flapThreshold; i++ {
			b.next(flap)
		}
		if b.class != classUnreachable {
			t.Fatalf("class = %v, want %v after %d flaps", b.class, classUnreachable, flapThreshold)
		}
		// And a healthy session clears the count again.
		b.next(runOutcome{class: classComingBack, reachedHelloAck: true, upFor: time.Minute})
		if b.flapCount != 0 {
			t.Errorf("flapCount = %d, want 0 after a session that outlived the flap window", b.flapCount)
		}
	})

	t.Run("a refusal uses its own per-reason delay and leaves the ladder alone", func(t *testing.T) {
		var b backoffState
		b.next(runOutcome{class: classUnreachable})
		before := b.attempt

		delay := b.next(runOutcome{class: classRefused, refusal: errPendingApproval})
		if b.attempt != before {
			t.Errorf("attempt = %d, want it untouched at %d — a refusal is not a ladder position",
				b.attempt, before)
		}
		want := refusedDelay(errPendingApproval)
		if delay < want || delay > want+want/4+1 {
			t.Errorf("delay = %v, want ~%v", delay, want)
		}
		// Approval is worth asking about far more often than revocation.
		if refusedDelay(errPendingApproval) >= refusedDelay(errRevoked) {
			t.Error("pending approval should be retried more eagerly than a revocation")
		}
	})
}
