package hostinfo

import (
	"runtime"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func TestIdentityReadiness(t *testing.T) {
	tests := []struct {
		name          string
		machineIDHash string
		wantState     string
	}{
		{name: "hash present is ready", machineIDHash: "abc123", wantState: "ready"},
		{name: "empty hash is degraded", machineIDHash: "", wantState: "degraded"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := identityReadiness(tt.machineIDHash)
			if len(got) != 1 {
				t.Fatalf("identityReadiness() returned %d entries, want 1", len(got))
			}
			if got[0].State != tt.wantState {
				t.Errorf("identityReadiness()[0].State = %q, want %q", got[0].State, tt.wantState)
			}
			if got[0].Collector == "" {
				t.Error("identityReadiness()[0].Collector is empty, want a named collector")
			}
			if tt.wantState == "degraded" && got[0].Reason == "" {
				t.Error("identityReadiness()[0].Reason is empty for a degraded state")
			}
		})
	}
}

// TestCollect exercises the real assembly path end-to-end against the actual host — this test
// environment always has a real hostname, architecture, and GOOS, so those are asserted
// precisely (OS in particular must equal runtime.GOOS exactly, never a distro identifier — see
// hostinfo.go's package doc); the machine-id/os-release-derived OSVersion/MAC values are
// environment-dependent so only structural invariants are checked (field wiring is correct;
// nothing panics; the result decodes to the Task 1 schema).
func TestCollect(t *testing.T) {
	got := Collect("1.2.3")

	if got.AgentVersion != "1.2.3" {
		t.Errorf("Collect().AgentVersion = %q, want %q", got.AgentVersion, "1.2.3")
	}
	if got.Arch != runtime.GOARCH {
		t.Errorf("Collect().Arch = %q, want %q", got.Arch, runtime.GOARCH)
	}
	if got.Hostname == "" {
		t.Error("Collect().Hostname is empty, want the real host's hostname")
	}
	if got.OS != runtime.GOOS {
		t.Errorf("Collect().OS = %q, want %q (GOOS-style, per the backend's self-update binary lookup — see hostinfo.go's package doc)", got.OS, runtime.GOOS)
	}
	if len(got.Readiness) != 1 {
		t.Fatalf("Collect().Readiness has %d entries, want 1", len(got.Readiness))
	}
	wantState := "ready"
	if got.MachineIDHash == "" {
		wantState = "degraded"
	}
	if got.Readiness[0].State != wantState {
		t.Errorf("Collect().Readiness[0].State = %q, want %q (MachineIDHash = %q)", got.Readiness[0].State, wantState, got.MachineIDHash)
	}
	if got.SpoolDepth != 0 {
		t.Errorf("Collect().SpoolDepth = %d, want 0 — hostinfo is deliberately spool-agnostic; "+
			"internal/link owns Options.Spool and stamps the real at-connect depth onto the "+
			"payload after calling Collect (D-12)", got.SpoolDepth)
	}

	// Sanity: the result must actually satisfy the Task 1 schema type, not just structurally
	// resemble it.
	var _ frame.HelloPayload = got
}
