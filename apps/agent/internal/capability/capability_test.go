package capability

import (
	"encoding/json"
	"testing"
)

func TestGate_DefaultDenyForUnknownCapability(t *testing.T) {
	g := New(t.TempDir())
	if g.Allowed("host_telemetry") {
		t.Error("Allowed() = true for a capability never granted, want false (default-deny)")
	}
}

func TestGate_ApplyGrantsThenAllowed(t *testing.T) {
	g := New(t.TempDir())
	payload, _ := json.Marshal(map[string]bool{"host_telemetry": true, "remote_probe": false})

	if err := g.ApplyGrants(payload); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	if !g.Allowed("host_telemetry") {
		t.Error("Allowed(host_telemetry) = false, want true")
	}
	if g.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = true, want false")
	}
	if g.Allowed("local_discovery") {
		t.Error("Allowed(local_discovery) = true, want false (never granted)")
	}
}

func TestGate_PersistsAcrossRestartViaLoadCached(t *testing.T) {
	dir := t.TempDir()
	first := New(dir)
	payload, _ := json.Marshal(map[string]bool{"host_telemetry": true})
	if err := first.ApplyGrants(payload); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}

	second := New(dir)
	if err := second.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v", err)
	}
	if !second.Allowed("host_telemetry") {
		t.Error("cached grant not restored after LoadCached()")
	}
}

func TestGate_LoadCached_NoOpWhenFileMissing(t *testing.T) {
	g := New(t.TempDir())
	if err := g.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v, want nil on first run with no grants.json yet", err)
	}
	if g.Allowed("host_telemetry") {
		t.Error("Allowed() = true with no cached grants, want false")
	}
}
