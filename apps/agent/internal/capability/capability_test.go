package capability

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/netscope"
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

// --- Task 5: the remote_probe configuration schema (design §3) -------------

// TestNormalizeRemoteProbeConfig_DefaultsAndBounds mirrors the backend's
// test_defaults_match_the_design_document and test_max_concurrent_out_of_range_raises.
// The bounds are a cross-language constant: an agent that accepted a limit the
// server rejects (or vice versa) would run a concurrency the operator never
// approved and could not see.
func TestNormalizeRemoteProbeConfig_DefaultsAndBounds(t *testing.T) {
	g := New(t.TempDir())
	if _, err := g.ApplyGrants(json.RawMessage(`{"remote_probe":true}`)); err != nil {
		t.Fatal(err)
	}
	cfg, enabled := g.RemoteProbeConfig()
	if !enabled {
		t.Fatal("RemoteProbeConfig() enabled = false, want true")
	}
	if !reflect.DeepEqual(cfg, DefaultRemoteProbeConfig()) {
		t.Fatalf("bare-boolean grant config = %+v, want the package default %+v", cfg, DefaultRemoteProbeConfig())
	}
	if cfg.MaxConcurrent != 20 || cfg.ScopeMode != netscope.ScopeModeDirectPrivate {
		t.Errorf("DefaultRemoteProbeConfig() = %+v, want max_concurrent 20 and the direct_private policy", cfg)
	}

	for _, limit := range []int{MinProbeConcurrent, 20, MaxProbeConcurrent} {
		payload := json.RawMessage(fmt.Sprintf(`{"remote_probe":{"enabled":true,"config":{"max_concurrent":%d}}}`, limit))
		faults, err := g.ApplyGrants(payload)
		if err != nil || len(faults) != 0 {
			t.Fatalf("ApplyGrants(max_concurrent=%d) = %v, %v, want accepted", limit, faults, err)
		}
		if cfg, _ := g.RemoteProbeConfig(); cfg.MaxConcurrent != limit {
			t.Errorf("RemoteProbeConfig().MaxConcurrent = %d, want %d", cfg.MaxConcurrent, limit)
		}
	}
	for _, limit := range []int{0, -1, 101} {
		payload := json.RawMessage(fmt.Sprintf(`{"remote_probe":{"enabled":true,"config":{"max_concurrent":%d}}}`, limit))
		faults, err := g.ApplyGrants(payload)
		if err != nil {
			t.Fatalf("ApplyGrants() error = %v, want nil (a per-capability fault is not a frame failure)", err)
		}
		if got := faultNames(faults); len(got) != 1 || got[0] != "remote_probe" {
			t.Fatalf("ApplyGrants(max_concurrent=%d) faults = %v, want exactly one naming remote_probe", limit, faults)
		}
	}

	// An unknown policy is the server telling this build about a mode it cannot
	// evaluate. Faulting is the only outcome that reaches an operator; running
	// on with a mode netscope would derive nothing from is a silent dark probe.
	faults, err := g.ApplyGrants(json.RawMessage(`{"remote_probe":{"enabled":true,"config":{"scope_mode":"anything_routable"}}}`))
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "remote_probe" {
		t.Fatalf("ApplyGrants(unknown scope_mode) faults = %v, want exactly one naming remote_probe", faults)
	}
}

// TestNormalizeRemoteProbeConfig_InvalidConfigKeepsEnabledAndPreviousConfig is
// the per-capability isolation contract (D-6) applied to the new normalizer:
// registering one must not need decode() to learn anything about it.
func TestNormalizeRemoteProbeConfig_InvalidConfigKeepsEnabledAndPreviousConfig(t *testing.T) {
	g := New(t.TempDir())
	valid := json.RawMessage(`{"remote_probe":{"enabled":true,"config":{"max_concurrent":50,"additional_cidrs":["10.9.0.0/24"]}},"host_telemetry":true}`)
	if _, err := g.ApplyGrants(valid); err != nil {
		t.Fatal(err)
	}

	faults, err := g.ApplyGrants(json.RawMessage(`{"remote_probe":{"enabled":true,"config":{"max_concurrent":0}},"host_telemetry":true}`))
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "remote_probe" {
		t.Fatalf("ApplyGrants() faults = %v, want exactly one naming remote_probe", faults)
	}
	if !g.Allowed("host_telemetry") {
		t.Error("Allowed(host_telemetry) = false, want true — an unrelated capability was discarded")
	}
	cfg, enabled := g.RemoteProbeConfig()
	if !enabled {
		t.Error("RemoteProbeConfig() enabled = false, want the server's enabled flag honored despite the bad config")
	}
	if cfg.MaxConcurrent != 50 || !reflect.DeepEqual(cfg.AdditionalCIDRs, []string{"10.9.0.0/24"}) {
		t.Fatalf("invalid update replaced the last valid config: %+v", cfg)
	}
}

// TestRemoteProbeConfig_LocalEditsAreOverwrittenByServerGrant pins §3's "scope
// and grant configuration are never host-editable". grants.json is a cache, not
// a control surface: a host-side edit widening the scope survives only until the
// next capabilities.set, and leaves nothing behind on disk when it does.
func TestRemoteProbeConfig_LocalEditsAreOverwrittenByServerGrant(t *testing.T) {
	dir := t.TempDir()
	edited := `{"remote_probe":{"enabled":true,"config":{"max_concurrent":100,"additional_cidrs":["203.0.113.0/24"],"additional_hostnames":["*.example.com"]}}}`
	if err := os.WriteFile(filepath.Join(dir, grantsFilename), []byte(edited), 0o600); err != nil {
		t.Fatalf("seed grants.json: %v", err)
	}

	g := New(dir)
	if _, err := g.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v", err)
	}

	server := json.RawMessage(`{"remote_probe":{"enabled":true,"config":{"max_concurrent":20,"additional_cidrs":["10.9.0.0/24"]}}}`)
	if _, err := g.ApplyGrants(server); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}

	cfg, _ := g.RemoteProbeConfig()
	if cfg.MaxConcurrent != 20 {
		t.Errorf("RemoteProbeConfig().MaxConcurrent = %d, want 20 — a local edit outlived the server grant", cfg.MaxConcurrent)
	}
	if !reflect.DeepEqual(cfg.AdditionalCIDRs, []string{"10.9.0.0/24"}) {
		t.Errorf("RemoteProbeConfig().AdditionalCIDRs = %v, want only the server's entry", cfg.AdditionalCIDRs)
	}
	if len(cfg.AdditionalHostnames) != 0 {
		t.Errorf("RemoteProbeConfig().AdditionalHostnames = %v, want none — the server's grant named none", cfg.AdditionalHostnames)
	}

	onDisk, err := os.ReadFile(filepath.Join(dir, grantsFilename))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(onDisk, []byte("203.0.113.0/24")) || bytes.Contains(onDisk, []byte("example.com")) {
		t.Errorf("grants.json still carries the host-side edit: %s", onDisk)
	}
}

// --- Slice 4 Task 3: the local_discovery configuration schema (plan §1) -----

// TestNormalizeLocalDiscoveryConfig_DefaultsAndBounds mirrors the backend's
// test_defaults_match_the_plan_document and test_numeric_bounds_are_enforced.
// The bounds are a cross-language constant for the same reason remote_probe's
// are: an agent that accepted a ceiling the server rejects would run a scan
// wider than any operator approved, and nothing would say so.
func TestNormalizeLocalDiscoveryConfig_DefaultsAndBounds(t *testing.T) {
	g := New(t.TempDir())
	if _, err := g.ApplyGrants(json.RawMessage(`{"local_discovery":true}`)); err != nil {
		t.Fatal(err)
	}
	cfg, enabled := g.LocalDiscoveryConfig()
	if !enabled {
		t.Fatal("LocalDiscoveryConfig() enabled = false, want true")
	}
	if !reflect.DeepEqual(cfg, DefaultLocalDiscoveryConfig()) {
		t.Fatalf("bare-boolean grant config = %+v, want the package default %+v", cfg, DefaultLocalDiscoveryConfig())
	}
	want := DefaultLocalDiscoveryConfig()
	if want.MaxAddressesPerJob != 1024 || want.MaxConcurrentHosts != 64 ||
		want.HostTimeoutMS != 1500 || want.JobTimeoutSeconds != 300 ||
		want.ScopeMode != netscope.ScopeModeDirectPrivate {
		t.Errorf("DefaultLocalDiscoveryConfig() = %+v, does not match plan §1", want)
	}
	if !reflect.DeepEqual(want.TCPPorts, []int{22, 53, 80, 443, 445, 3389, 8000, 8080, 8443}) {
		t.Errorf("DefaultLocalDiscoveryConfig().TCPPorts = %v, does not match plan §1", want.TCPPorts)
	}

	for _, tc := range []struct {
		key      string
		accepted []int
		rejected []int
	}{
		{"max_addresses_per_job", []int{MinDiscoveryAddresses, 1024, MaxDiscoveryAddresses}, []int{0, -1, MaxDiscoveryAddresses + 1}},
		{"max_concurrent_hosts", []int{MinDiscoveryHosts, 64, MaxDiscoveryHosts}, []int{0, -1, MaxDiscoveryHosts + 1}},
		{"host_timeout_ms", []int{MinDiscoveryHostTimeoutMS, 1500, MaxDiscoveryHostTimeoutMS}, []int{MinDiscoveryHostTimeoutMS - 1, 0, MaxDiscoveryHostTimeoutMS + 1}},
		{"job_timeout_seconds", []int{MinDiscoveryJobSeconds, 300, MaxDiscoveryJobSeconds}, []int{MinDiscoveryJobSeconds - 1, 0, MaxDiscoveryJobSeconds + 1}},
	} {
		for _, value := range tc.accepted {
			payload := json.RawMessage(fmt.Sprintf(`{"local_discovery":{"enabled":true,"config":{%q:%d}}}`, tc.key, value))
			faults, err := g.ApplyGrants(payload)
			if err != nil || len(faults) != 0 {
				t.Fatalf("ApplyGrants(%s=%d) = %v, %v, want accepted", tc.key, value, faults, err)
			}
		}
		for _, value := range tc.rejected {
			payload := json.RawMessage(fmt.Sprintf(`{"local_discovery":{"enabled":true,"config":{%q:%d}}}`, tc.key, value))
			faults, err := g.ApplyGrants(payload)
			if err != nil {
				t.Fatalf("ApplyGrants() error = %v, want nil (a per-capability fault is not a frame failure)", err)
			}
			if got := faultNames(faults); len(got) != 1 || got[0] != "local_discovery" {
				t.Fatalf("ApplyGrants(%s=%d) faults = %v, want exactly one naming local_discovery", tc.key, value, faults)
			}
		}
	}
}

// TestNormalizeLocalDiscoveryConfig_PortSet pins the half of the grant that
// bounds what the collector may touch at all. A port the server did not name is
// not scannable, so an unbounded or out-of-range set is a fault rather than
// something to clamp quietly.
func TestNormalizeLocalDiscoveryConfig_PortSet(t *testing.T) {
	g := New(t.TempDir())

	if _, err := g.ApplyGrants(json.RawMessage(`{"local_discovery":{"enabled":true,"config":{"tcp_ports":[443,22,443,80]}}}`)); err != nil {
		t.Fatal(err)
	}
	cfg, _ := g.LocalDiscoveryConfig()
	// Deduplicated and ordered, matching the server's normalizer: the two sides
	// compare port sets, and [443,22] vs [22,443] must not read as a change.
	if !reflect.DeepEqual(cfg.TCPPorts, []int{22, 80, 443}) {
		t.Errorf("TCPPorts = %v, want [22 80 443]", cfg.TCPPorts)
	}

	// An explicitly empty set is a real instruction ("do not port-scan"), not an
	// absent key, and must not be replaced by the defaults.
	if _, err := g.ApplyGrants(json.RawMessage(`{"local_discovery":{"enabled":true,"config":{"tcp_ports":[]}}}`)); err != nil {
		t.Fatal(err)
	}
	if cfg, _ := g.LocalDiscoveryConfig(); len(cfg.TCPPorts) != 0 {
		t.Errorf("TCPPorts = %v, want an empty set to survive normalization", cfg.TCPPorts)
	}

	tooMany, _ := json.Marshal(makeRange(1, MaxDiscoveryPorts+2))
	for _, bad := range []string{`[0]`, `[65536]`, `[-1]`, string(tooMany)} {
		payload := json.RawMessage(fmt.Sprintf(`{"local_discovery":{"enabled":true,"config":{"tcp_ports":%s}}}`, bad))
		faults, err := g.ApplyGrants(payload)
		if err != nil {
			t.Fatalf("ApplyGrants() error = %v, want nil", err)
		}
		if got := faultNames(faults); len(got) != 1 || got[0] != "local_discovery" {
			t.Fatalf("ApplyGrants(tcp_ports=%s) faults = %v, want exactly one naming local_discovery", bad, faults)
		}
	}
}

// TestLocalDiscoveryConfig_UnknownScopeModeFaults mirrors remote_probe's: a
// policy this build cannot evaluate must surface as a degraded capability, not
// as a scan that silently derives nothing.
func TestLocalDiscoveryConfig_UnknownScopeModeFaults(t *testing.T) {
	g := New(t.TempDir())
	faults, err := g.ApplyGrants(json.RawMessage(`{"local_discovery":{"enabled":true,"config":{"scope_mode":"everything"}}}`))
	if err != nil {
		t.Fatalf("ApplyGrants() error = %v, want nil", err)
	}
	if got := faultNames(faults); len(got) != 1 || got[0] != "local_discovery" {
		t.Fatalf("faults = %v, want exactly one naming local_discovery", faults)
	}
}

// TestLocalDiscoveryConfig_ServerOnlyKeysAreCarried checks that
// auto_discovery_paused round-trips without faulting. It is a server-side
// scheduling control that the agent has no use for; rejecting it would fault a
// perfectly valid grant, and dropping it would make the cached snapshot differ
// from what the server believes it sent.
func TestLocalDiscoveryConfig_ServerOnlyKeysAreCarried(t *testing.T) {
	g := New(t.TempDir())
	payload := json.RawMessage(`{"local_discovery":{"enabled":true,"config":{"auto_discovery_paused":true,"max_concurrent_hosts":8}}}`)
	faults, err := g.ApplyGrants(payload)
	if err != nil || len(faults) != 0 {
		t.Fatalf("ApplyGrants() = %v, %v, want accepted", faults, err)
	}
	cfg, _ := g.LocalDiscoveryConfig()
	if !cfg.AutoDiscoveryPaused || cfg.MaxConcurrentHosts != 8 {
		t.Errorf("LocalDiscoveryConfig() = %+v, want the paused flag carried and the host limit applied", cfg)
	}
}

func makeRange(low, high int) []int {
	out := make([]int, 0, high-low)
	for i := low; i < high; i++ {
		out = append(out, i)
	}
	return out
}
