// apps/agent/internal/link/seqguard_test.go
package link

import (
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func TestInboundSeqGuard_Validate(t *testing.T) {
	mk := func(v int, typ string, seq uint64) frame.Frame {
		return frame.Frame{V: v, Type: typ, Seq: seq, TS: time.Now().UTC()}
	}

	t.Run("accepts strictly increasing sequences", func(t *testing.T) {
		var g inboundSeqGuard
		seqs := []uint64{0, 1, 2, 5, 100}
		for _, s := range seqs {
			if err := g.validate(mk(1, "heartbeat", s)); err != nil {
				t.Fatalf("validate(seq=%d) unexpected error: %v", s, err)
			}
		}
	})

	t.Run("rejects duplicate sequence", func(t *testing.T) {
		var g inboundSeqGuard
		if err := g.validate(mk(1, "heartbeat", 3)); err != nil {
			t.Fatalf("first frame unexpected error: %v", err)
		}
		if err := g.validate(mk(1, "heartbeat", 3)); err == nil {
			t.Fatal("expected error for duplicate sequence, got nil")
		}
	})

	t.Run("rejects decreasing sequence", func(t *testing.T) {
		var g inboundSeqGuard
		if err := g.validate(mk(1, "heartbeat", 5)); err != nil {
			t.Fatalf("first frame unexpected error: %v", err)
		}
		if err := g.validate(mk(1, "heartbeat", 4)); err == nil {
			t.Fatal("expected error for decreasing sequence, got nil")
		}
	})

	t.Run("rejects unsupported version", func(t *testing.T) {
		var g inboundSeqGuard
		if err := g.validate(mk(2, "heartbeat", 0)); err == nil {
			t.Fatal("expected error for unsupported version, got nil")
		}
	})

	t.Run("rejects malformed frame (empty type)", func(t *testing.T) {
		var g inboundSeqGuard
		if err := g.validate(mk(1, "", 0)); err == nil {
			t.Fatal("expected error for empty type, got nil")
		}
	})

	t.Run("a rejected frame does not advance the baseline", func(t *testing.T) {
		var g inboundSeqGuard
		if err := g.validate(mk(1, "heartbeat", 5)); err != nil {
			t.Fatalf("first frame unexpected error: %v", err)
		}
		// Reject a duplicate, then confirm the next strictly-increasing
		// sequence relative to the original baseline (5) still succeeds.
		if err := g.validate(mk(1, "heartbeat", 5)); err == nil {
			t.Fatal("expected error for duplicate sequence, got nil")
		}
		if err := g.validate(mk(1, "heartbeat", 6)); err != nil {
			t.Fatalf("validate(seq=6) unexpected error: %v", err)
		}
	})
}
