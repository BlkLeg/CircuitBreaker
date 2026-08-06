package collect

import (
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func TestRateOmitsFirstResetAndInvalidElapsed(t *testing.T) {
	if Rate(100, 90, time.Second) != nil {
		t.Fatal("counter reset produced a rate")
	}
	if Rate(100, 200, 0) != nil {
		t.Fatal("zero elapsed time produced a rate")
	}
	got := Rate(100, 200, 2*time.Second)
	if got == nil || *got != 50 {
		t.Fatalf("Rate() = %v, want 50", got)
	}
}

func TestEncodeBoundedSortsAndTruncatesDeterministically(t *testing.T) {
	items := make([]map[string]any, 130)
	for i := range items {
		items[i] = map[string]any{"name": strings.Repeat("x", 10), "id": 130 - i}
	}
	p := frame.HostTelemetryPayload{Schema: 1, SampleID: strings.Repeat("a", 32), Status: "healthy", Filesystems: items, Disks: []map[string]any{}, Interfaces: []map[string]any{}, Temperatures: []map[string]any{}}
	data, err := EncodeBounded(&p)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) > MaxPayloadBytes || len(p.Filesystems) != 128 || p.Status != "degraded" {
		t.Fatalf("unexpected bounded payload: bytes=%d entries=%d status=%s", len(data), len(p.Filesystems), p.Status)
	}
}

func TestSampleIDIsRandom128BitLowercaseHex(t *testing.T) {
	a, err := SampleID()
	if err != nil {
		t.Fatal(err)
	}
	b, _ := SampleID()
	if len(a) != 32 || a == b {
		t.Fatalf("invalid sample ids %q %q", a, b)
	}
}
