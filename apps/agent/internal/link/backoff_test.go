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
