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

// TestBackoffState_ResetsOnStableAdvancesOnFailure simulates Run's retry
// loop calling backoffState.next once per completed connection attempt,
// feeding it a scripted sequence of "was this run stable (reached an
// accepted hello.ack)?" outcomes. It asserts both the resulting attempt
// counter (drives the next call's floor) and that the returned delay
// itself falls within the jittered bounds for that attempt — i.e. a
// stable run truly resets progression to the 1s floor rather than merely
// resetting some unrelated bookkeeping value, and consecutive failures
// keep progressing exactly as backoffBaseDuration/backoffDelay already do.
func TestBackoffState_ResetsOnStableAdvancesOnFailure(t *testing.T) {
	cases := []struct {
		name        string
		stable      []bool
		wantAttempt []int // b.attempt after each call, in order
	}{
		{
			name:        "three consecutive failures progress the exponential counter",
			stable:      []bool{false, false, false},
			wantAttempt: []int{1, 2, 3},
		},
		{
			name:        "a stable run resets to the floor even mid-progression, then failures resume climbing",
			stable:      []bool{false, false, true, false},
			wantAttempt: []int{1, 2, 1, 2},
		},
		{
			name:        "repeated stability keeps the counter pinned at the floor",
			stable:      []bool{true, true, true},
			wantAttempt: []int{1, 1, 1},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var b backoffState
			for i, stable := range c.stable {
				delay := b.next(stable)
				if b.attempt != c.wantAttempt[i] {
					t.Errorf("call #%d next(%v): attempt = %d, want %d", i, stable, b.attempt, c.wantAttempt[i])
				}
				usedAttempt := c.wantAttempt[i] - 1 // the pre-increment attempt backoffDelay was computed against
				wantBase := backoffBaseDuration(usedAttempt)
				if delay < wantBase || delay > wantBase+wantBase/4+1 {
					t.Errorf("call #%d next(%v): delay = %v, want in [%v, %v]", i, stable, delay, wantBase, wantBase+wantBase/4)
				}
			}
		})
	}
}
