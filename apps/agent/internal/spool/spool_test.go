package spool

import (
	"encoding/json"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func testFrame(seq uint64) frame.Frame {
	return frame.Frame{V: 1, Type: "telemetry.host", Seq: seq, TS: time.Now().UTC(), Payload: json.RawMessage(`{}`)}
}

func TestEnqueueDrain_FIFO(t *testing.T) {
	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	for i := uint64(0); i < 3; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if got := s.Len(); got != 3 {
		t.Errorf("Len() = %d, want 3", got)
	}

	for i := uint64(0); i < 3; i++ {
		f, ok, err := s.Drain()
		if err != nil {
			t.Fatalf("Drain() error = %v", err)
		}
		if !ok {
			t.Fatalf("Drain() ok = false at i=%d, want true", i)
		}
		if f.Seq != i {
			t.Errorf("Drain() seq = %d, want %d (FIFO order)", f.Seq, i)
		}
	}

	_, ok, err := s.Drain()
	if err != nil {
		t.Fatalf("Drain() on empty spool error = %v", err)
	}
	if ok {
		t.Error("Drain() ok = true on empty spool, want false")
	}
}

func TestEnqueue_DropsOldestWhenOverCap(t *testing.T) {
	// A tiny cap that fits only a couple of frames, to exercise eviction
	// without a 64MB fixture.
	const tinyCap = 300
	s, err := Open(t.TempDir(), tinyCap)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	for i := uint64(0); i < 10; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	size, err := s.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if size > tinyCap {
		t.Errorf("SizeBytes() = %d, want <= %d after eviction", size, tinyCap)
	}

	f, ok, err := s.Drain()
	if err != nil || !ok {
		t.Fatalf("Drain() = (%v, %v, %v), want a frame present", f, ok, err)
	}
	if f.Seq == 0 {
		t.Error("Drain() returned seq=0 — oldest frame should have been evicted, not the newest")
	}
}

func TestOpen_RecoversExistingQueueAfterReopen(t *testing.T) {
	dir := t.TempDir()
	first, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if err := first.Enqueue(testFrame(1)); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}

	second, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	defer second.Close()
	if got := second.Len(); got != 1 {
		t.Errorf("Len() after reopen = %d, want 1 (unclean-shutdown recovery)", got)
	}
}
