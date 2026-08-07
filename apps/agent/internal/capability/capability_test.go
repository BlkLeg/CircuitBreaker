package capability

import (
	"encoding/json"
	"os"
	"path/filepath"
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

	if _, err := g.ApplyGrants(payload); err != nil {
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
	if _, err := first.ApplyGrants(payload); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}

	second := New(dir)
	if _, err := second.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v", err)
	}
	if !second.Allowed("host_telemetry") {
		t.Error("cached grant not restored after LoadCached()")
	}
}

func TestGate_Grants_ReturnsIndependentSnapshot(t *testing.T) {
	g := New(t.TempDir())
	payload, _ := json.Marshal(map[string]bool{"host_telemetry": true, "remote_probe": false})
	if _, err := g.ApplyGrants(payload); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}

	snap := g.Grants()
	if !snap["host_telemetry"] || snap["remote_probe"] {
		t.Errorf("Grants() = %+v, want {host_telemetry:true, remote_probe:false}", snap)
	}

	// Mutating the returned map must not affect the Gate's internal state.
	snap["host_telemetry"] = false
	if !g.Allowed("host_telemetry") {
		t.Error("mutating the Grants() snapshot changed the Gate's own state")
	}
}

func TestGate_Grants_EmptyWhenNoneApplied(t *testing.T) {
	g := New(t.TempDir())
	if got := g.Grants(); len(got) != 0 {
		t.Errorf("Grants() = %+v, want empty map before any ApplyGrants call", got)
	}
}

func TestGate_LoadCached_NoOpWhenFileMissing(t *testing.T) {
	g := New(t.TempDir())
	if _, err := g.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v, want nil on first run with no grants.json yet", err)
	}
	if g.Allowed("host_telemetry") {
		t.Error("Allowed() = true with no cached grants, want false")
	}
}

// --- Task 12: per-capability grant fault isolation (D-6) ------------------

// faultNames reduces a fault list to the capability names it blames, so a test
// can assert on the blame without pinning an error string.
func faultNames(faults []GrantFault) []string {
	out := make([]string, 0, len(faults))
	for _, f := range faults {
		out = append(out, f.Capability)
	}
	return out
}

// TestApplyGrants_InvalidHostConfigDoesNotBlockOtherCapabilities pins the core
// of D-6: one capability's bad config is that capability's problem. Before this
// change decode() returned (nil, err) for the whole snapshot, so a typo in
// host_telemetry.interval_s silently discarded the remote_probe and
// local_discovery grants that arrived in the same frame.
func TestApplyGrants_InvalidHostConfigDoesNotBlockOtherCapabilities(t *testing.T) {
	g := New(t.TempDir())
	payload := json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":9}},"remote_probe":{"enabled":true},"local_discovery":true}`)

	faults, err := g.ApplyGrants(payload)
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil (a per-capability fault is not a frame failure)", err)
	}
	if !g.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = false, want true — an unrelated capability was discarded")
	}
	if !g.Allowed("local_discovery") {
		t.Error("Allowed(local_discovery) = false, want true — an unrelated capability was discarded")
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "host_telemetry" {
		t.Fatalf("ApplyGrants() faults = %v, want exactly one naming host_telemetry", faults)
	}
	if faults[0].Reason == "" {
		t.Error("GrantFault.Reason is empty, want the normalization failure it reports")
	}
}

// TestApplyGrants_InvalidHostConfigRetainsLastValidConfig supersedes the old
// TestGateStructuredHostConfigDefaultsAndRejectsInvalidWithoutReplacing, which
// passed only because the *entire* apply was rejected. The slice-2 contract is
// "invalid server configuration is rejected without replacing the last valid
// configuration" — per capability, and keeping the server's enabled flag.
func TestApplyGrants_InvalidHostConfigRetainsLastValidConfig(t *testing.T) {
	g := New(t.TempDir())
	valid := json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":45,"include_docker":true}}}`)
	if _, err := g.ApplyGrants(valid); err != nil {
		t.Fatal(err)
	}
	cfg, enabled := g.HostConfig()
	if !enabled || cfg.IntervalS != 45 || !cfg.IncludeDocker || !cfg.IncludeNetwork {
		t.Fatalf("HostConfig() = %+v, %v", cfg, enabled)
	}

	faults, err := g.ApplyGrants(json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":9}}}`))
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "host_telemetry" {
		t.Fatalf("ApplyGrants() faults = %v, want exactly one naming host_telemetry", faults)
	}
	cfg, enabled = g.HostConfig()
	if !enabled {
		t.Error("HostConfig() enabled = false, want the server's enabled flag honored despite the bad config")
	}
	if cfg.IntervalS != 45 || !cfg.IncludeDocker {
		t.Fatalf("invalid update replaced last valid config: %+v", cfg)
	}
}

// TestApplyGrants_InvalidHostConfigWithNoPriorValidFallsBackToDefault covers the
// other half of the carry-over rule: with nothing valid to retain, the package
// default stands in — the capability keeps running, just not as requested.
func TestApplyGrants_InvalidHostConfigWithNoPriorValidFallsBackToDefault(t *testing.T) {
	g := New(t.TempDir())

	faults, err := g.ApplyGrants(json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":1000}}}`))
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "host_telemetry" {
		t.Fatalf("ApplyGrants() faults = %v, want exactly one naming host_telemetry", faults)
	}
	cfg, enabled := g.HostConfig()
	if !enabled {
		t.Error("HostConfig() enabled = false, want true (the server said enabled)")
	}
	if cfg != DefaultHostConfig() {
		t.Errorf("HostConfig() = %+v, want the package default %+v", cfg, DefaultHostConfig())
	}
	if cfg.IntervalS != 30 {
		t.Errorf("HostConfig().IntervalS = %d, want 30", cfg.IntervalS)
	}
}

// TestApplyGrants_StructurallyBrokenGrantIsFailClosedNotFatal pins the one case
// where the enabled flag itself is unknowable: the grant is installed as
// Grant{Enabled: false}, and the rest of the snapshot still applies.
func TestApplyGrants_StructurallyBrokenGrantIsFailClosedNotFatal(t *testing.T) {
	g := New(t.TempDir())

	faults, err := g.ApplyGrants(json.RawMessage(`{"remote_probe":"nonsense","host_telemetry":true}`))
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}
	if !g.Allowed("host_telemetry") {
		t.Error("Allowed(host_telemetry) = false, want true")
	}
	if g.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = true, want false (fail closed on an unreadable grant)")
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "remote_probe" {
		t.Fatalf("ApplyGrants() faults = %v, want exactly one naming remote_probe", faults)
	}
}

// TestApplyGrants_NonObjectPayloadStillErrorsAndLeavesSnapshotIntact reserves
// the error return for a payload that is not a grant map at all — there is no
// per-capability information to salvage, so nothing is persisted or installed.
func TestApplyGrants_NonObjectPayloadStillErrorsAndLeavesSnapshotIntact(t *testing.T) {
	g := New(t.TempDir())
	if _, err := g.ApplyGrants(json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":45}}}`)); err != nil {
		t.Fatal(err)
	}

	faults, err := g.ApplyGrants(json.RawMessage(`[1,2,3]`))
	if err == nil {
		t.Fatal("ApplyGrants([1,2,3]) error = nil, want a decode error")
	}
	if len(faults) != 0 {
		t.Errorf("ApplyGrants() faults = %v, want none for an undecodable payload", faults)
	}
	cfg, enabled := g.HostConfig()
	if !enabled || cfg.IntervalS != 45 {
		t.Errorf("HostConfig() = %+v, %v after an undecodable payload, want the previous snapshot intact", cfg, enabled)
	}
}

// TestLoadCached_OneCorruptGrantKeepsTheRest covers the face the review omitted:
// LoadCached shared the all-or-nothing decode, so a single invalid *cached*
// grant made a restarted agent forget every capability it had.
func TestLoadCached_OneCorruptGrantKeepsTheRest(t *testing.T) {
	dir := t.TempDir()
	cached := `{"remote_probe":{"enabled":true},"host_telemetry":{"enabled":true,"config":{"interval_s":0}}}`
	if err := os.WriteFile(filepath.Join(dir, grantsFilename), []byte(cached), 0o600); err != nil {
		t.Fatalf("seed grants.json: %v", err)
	}

	g := New(dir)
	faults, err := g.LoadCached()
	if err != nil {
		t.Fatalf("LoadCached() error = %v, want nil", err)
	}
	if !g.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = false after LoadCached, want true — a restart dropped a valid grant")
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "host_telemetry" {
		t.Fatalf("LoadCached() faults = %v, want exactly one naming host_telemetry", faults)
	}
	cfg, enabled := g.HostConfig()
	if !enabled || cfg != DefaultHostConfig() {
		t.Errorf("HostConfig() = %+v, %v, want the package default and the cached enabled flag", cfg, enabled)
	}
}

// TestApplyGrants_PersistsEffectiveNotRejectedConfig states the persistence
// rule explicitly: grants.json carries the *effective* configuration (retained
// or defaulted), never a verbatim copy of a rejected server payload, so a
// restart runs exactly what the live process was running. The divergence from
// the server's request is reconciled by the fault report, not by mirroring bad
// input onto disk.
func TestApplyGrants_PersistsEffectiveNotRejectedConfig(t *testing.T) {
	dir := t.TempDir()
	first := New(dir)
	if _, err := first.ApplyGrants(json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":45}}}`)); err != nil {
		t.Fatal(err)
	}
	if _, err := first.ApplyGrants(json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":9}}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}

	second := New(dir)
	if _, err := second.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v", err)
	}
	cfg, enabled := second.HostConfig()
	if !enabled || cfg.IntervalS != 45 {
		t.Errorf("HostConfig() after restart = %+v, %v, want the retained interval 45", cfg, enabled)
	}
}
