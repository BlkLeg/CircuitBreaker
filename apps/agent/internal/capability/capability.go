package capability

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync"

	"circuitbreaker.dev/cb-agent/internal/netscope"
)

const grantsFilename = "grants.json"

// Bounds are a cross-language constant: they must stay byte-identical to the
// backend's CAPABILITY_DEFINITIONS normalizers, or an agent accepts a setting
// the server rejects and runs a configuration no operator ever approved.
const (
	MinHostInterval = 10
	MaxHostInterval = 900

	MinProbeConcurrent = 1
	MaxProbeConcurrent = 100

	MinDiscoveryAddresses     = 1
	MaxDiscoveryAddresses     = 4096
	MinDiscoveryHosts         = 1
	MaxDiscoveryHosts         = 256
	MinDiscoveryHostTimeoutMS = 100
	MaxDiscoveryHostTimeoutMS = 10_000
	MinDiscoveryJobSeconds    = 30
	MaxDiscoveryJobSeconds    = 1800
	MaxDiscoveryPorts         = 32
)

type HostConfig struct {
	IntervalS           int  `json:"interval_s"`
	IncludeFilesystems  bool `json:"include_filesystems"`
	IncludeDisks        bool `json:"include_disks"`
	IncludeNetwork      bool `json:"include_network"`
	IncludeTemperatures bool `json:"include_temperatures"`
	IncludeVirtual      bool `json:"include_virtual"`
	IncludeDocker       bool `json:"include_docker"`
}

func DefaultHostConfig() HostConfig {
	return HostConfig{IntervalS: 30, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: true}
}

// RemoteProbeConfig is the server's normalized `remote_probe` grant config.
//
// The scope half is netscope.Config embedded rather than restated: its fields
// promote to the same flat JSON the server sends, and there is exactly one Go
// declaration of what a scope is — the same "one scope evaluator" rule that
// keeps this package from growing a CIDR opinion of its own.
type RemoteProbeConfig struct {
	MaxConcurrent int `json:"max_concurrent"`
	netscope.Config
}

func DefaultRemoteProbeConfig() RemoteProbeConfig {
	return RemoteProbeConfig{MaxConcurrent: 20, Config: netscope.Config{ScopeMode: netscope.ScopeModeDirectPrivate}}
}

// LocalDiscoveryConfig is the server's normalized `local_discovery` grant config
// (Slice 4 plan §1).
//
// The scope half is netscope.Config embedded for the same reason
// RemoteProbeConfig embeds it: there is exactly one Go declaration of what a
// scope is. Note it carries no AdditionalHostnames in practice — discovery
// targets are prefixes, and the server's normalizer rejects the key outright —
// but the field promotes from the embed and is simply never populated.
//
// AutoDiscoveryPaused is a *server-side* scheduling control that pauses this
// agent's automatic per-subnet profiles. The agent has no use for it; it is
// carried rather than rejected so a valid grant does not fault, and rather than
// dropped so the cached snapshot matches what the server believes it sent.
type LocalDiscoveryConfig struct {
	MaxAddressesPerJob  int   `json:"max_addresses_per_job"`
	MaxConcurrentHosts  int   `json:"max_concurrent_hosts"`
	TCPPorts            []int `json:"tcp_ports"`
	HostTimeoutMS       int   `json:"host_timeout_ms"`
	JobTimeoutSeconds   int   `json:"job_timeout_seconds"`
	AutoDiscoveryPaused bool  `json:"auto_discovery_paused"`
	netscope.Config
}

func DefaultLocalDiscoveryConfig() LocalDiscoveryConfig {
	return LocalDiscoveryConfig{
		MaxAddressesPerJob: 1024,
		MaxConcurrentHosts: 64,
		TCPPorts:           []int{22, 53, 80, 443, 445, 3389, 8000, 8080, 8443},
		HostTimeoutMS:      1500,
		JobTimeoutSeconds:  300,
		Config:             netscope.Config{ScopeMode: netscope.ScopeModeDirectPrivate},
	}
}

type Grant struct {
	Enabled bool            `json:"enabled"`
	Config  json.RawMessage `json:"config,omitempty"`
}

type Snapshot map[string]Grant

// Gate stores immutable, server-authoritative capability snapshots. The cache
// exists only to keep an agent useful while disconnected; it is never a local
// source of authority.
type Gate struct {
	mu      sync.RWMutex
	grants  Snapshot
	path    string
	changed chan struct{}
}

func New(stateDir string) *Gate {
	return &Gate{grants: Snapshot{}, path: filepath.Join(stateDir, grantsFilename), changed: make(chan struct{}, 1)}
}

// GrantFault records that one capability in a grant payload could not be
// honored as sent. It is deliberately not an error: per D-6 a fault isolates to
// its own capability, and the rest of the snapshot still applies.
type GrantFault struct {
	Capability string
	Reason     string
}

// configNormalizers is the Go mirror of the backend's CAPABILITY_DEFINITIONS
// registry: one entry per capability that has a structured config, mapping the
// server's raw config onto the effective, fully-defaulted config the agent will
// actually run with. A normalizer must accept an empty/absent config and return
// that capability's defaults.
//
// A new capability registers itself here rather than editing decode — that is
// what keeps per-capability isolation from being re-broken by the next slice.
var configNormalizers = map[string]func(json.RawMessage) (json.RawMessage, error){
	"host_telemetry":  normalizeHostConfigRaw,
	"remote_probe":    normalizeRemoteProbeConfigRaw,
	"local_discovery": normalizeLocalDiscoveryConfigRaw,
}

func normalizeHostConfigRaw(raw json.RawMessage) (json.RawMessage, error) {
	cfg, err := normalizeHostConfig(raw)
	if err != nil {
		return nil, err
	}
	return json.Marshal(cfg)
}

func normalizeRemoteProbeConfigRaw(raw json.RawMessage) (json.RawMessage, error) {
	cfg, err := normalizeRemoteProbeConfig(raw)
	if err != nil {
		return nil, err
	}
	return json.Marshal(cfg)
}

func normalizeLocalDiscoveryConfigRaw(raw json.RawMessage) (json.RawMessage, error) {
	cfg, err := normalizeLocalDiscoveryConfig(raw)
	if err != nil {
		return nil, err
	}
	return json.Marshal(cfg)
}

// decode turns a grant payload into the snapshot the agent will run with, plus
// the per-capability faults it had to work around. previous is the currently
// installed snapshot, consulted only to carry over the last valid config for a
// capability whose new config fails normalization.
//
// The error return is reserved *solely* for a payload that is not a grant map
// at all — there is no per-capability information to salvage from that, so the
// caller must leave the installed snapshot untouched. Every other problem is a
// GrantFault:
//
//   - a bare boolean is always applied verbatim;
//   - a grant object that will not unmarshal is installed fail-closed as
//     Grant{Enabled: false}, because its enabled flag is unknowable;
//   - a config that fails its normalizer keeps the server's enabled flag and
//     carries over previous[name]'s config if that still validates, else the
//     capability's package default;
//   - a capability with no registered normalizer passes through untouched.
func decode(payload []byte, previous Snapshot) (Snapshot, []GrantFault, error) {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(payload, &raw); err != nil {
		return nil, nil, fmt.Errorf("capability: unmarshal grants: %w", err)
	}
	out := make(Snapshot, len(raw))
	var faults []GrantFault
	for name, value := range raw {
		var enabled bool
		if err := json.Unmarshal(value, &enabled); err == nil {
			out[name] = normalize(name, Grant{Enabled: enabled})
			continue
		}
		var grant Grant
		if err := json.Unmarshal(value, &grant); err != nil {
			faults = append(faults, GrantFault{Capability: name, Reason: fmt.Sprintf("unreadable grant object: %v", err)})
			out[name] = Grant{Enabled: false}
			continue
		}
		normalizer, ok := configNormalizers[name]
		if !ok {
			out[name] = grant
			continue
		}
		cfg, err := normalizer(grant.Config)
		if err != nil {
			faults = append(faults, GrantFault{Capability: name, Reason: err.Error()})
			grant.Config = retainedConfig(name, previous, normalizer)
			out[name] = grant
			continue
		}
		grant.Config = cfg
		out[name] = grant
	}
	// Map iteration is randomized; faults drive readiness rows, so they are
	// ordered to keep the resulting report stable across applies.
	sort.Slice(faults, func(i, j int) bool { return faults[i].Capability < faults[j].Capability })
	return out, faults, nil
}

// retainedConfig is the carry-over rule for a capability whose new config was
// rejected: the last config that is still valid, else the package default.
func retainedConfig(name string, previous Snapshot, normalizer func(json.RawMessage) (json.RawMessage, error)) json.RawMessage {
	if prev, ok := previous[name]; ok && len(prev.Config) > 0 {
		if cfg, err := normalizer(prev.Config); err == nil {
			return cfg
		}
	}
	cfg, err := normalizer(nil)
	if err != nil {
		return nil
	}
	return cfg
}

// normalize fills in a capability's default config for a grant that carried
// none — the bare-boolean wire form. Grants that carry a config go through
// their normalizer in decode instead, which defaults the same way.
func normalize(name string, grant Grant) Grant {
	if normalizer, ok := configNormalizers[name]; ok && len(grant.Config) == 0 {
		if cfg, err := normalizer(nil); err == nil {
			grant.Config = cfg
		}
	}
	return grant
}

func normalizeHostConfig(raw json.RawMessage) (HostConfig, error) {
	cfg := DefaultHostConfig()
	if len(bytes.TrimSpace(raw)) != 0 && !bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			return HostConfig{}, fmt.Errorf("capability: invalid host_telemetry config: %w", err)
		}
		apply := func(key string, target any) error {
			v, ok := fields[key]
			if !ok {
				return nil
			}
			if err := json.Unmarshal(v, target); err != nil {
				return fmt.Errorf("capability: invalid host_telemetry.%s", key)
			}
			return nil
		}
		if err := apply("interval_s", &cfg.IntervalS); err != nil {
			return HostConfig{}, err
		}
		for key, target := range map[string]*bool{"include_filesystems": &cfg.IncludeFilesystems, "include_disks": &cfg.IncludeDisks, "include_network": &cfg.IncludeNetwork, "include_temperatures": &cfg.IncludeTemperatures, "include_virtual": &cfg.IncludeVirtual, "include_docker": &cfg.IncludeDocker} {
			if err := apply(key, target); err != nil {
				return HostConfig{}, err
			}
		}
	}
	if cfg.IntervalS < MinHostInterval || cfg.IntervalS > MaxHostInterval {
		return HostConfig{}, fmt.Errorf("capability: host_telemetry.interval_s must be between %d and %d", MinHostInterval, MaxHostInterval)
	}
	return cfg, nil
}

// normalizeRemoteProbeConfig mirrors the backend's
// _normalize_remote_probe_config, minus its CIDR and hostname parsing: those
// entries were validated at write time, and netscope.Derive already drops a
// malformed one and refuses a /0, so re-parsing here would only add a second
// place for the two languages to disagree about what a scope entry means.
//
// An unknown scope_mode *is* rejected. netscope.Derive would fail closed on it
// and derive nothing, which is safe but silent; a fault reports the capability
// as degraded, which is the only form an operator ever sees.
func normalizeRemoteProbeConfig(raw json.RawMessage) (RemoteProbeConfig, error) {
	cfg := DefaultRemoteProbeConfig()
	if len(bytes.TrimSpace(raw)) != 0 && !bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			return RemoteProbeConfig{}, fmt.Errorf("capability: invalid remote_probe config: %w", err)
		}
		apply := func(key string, target any) error {
			v, ok := fields[key]
			if !ok {
				return nil
			}
			if err := json.Unmarshal(v, target); err != nil {
				return fmt.Errorf("capability: invalid remote_probe.%s", key)
			}
			return nil
		}
		if err := apply("max_concurrent", &cfg.MaxConcurrent); err != nil {
			return RemoteProbeConfig{}, err
		}
		if err := apply("scope_mode", &cfg.ScopeMode); err != nil {
			return RemoteProbeConfig{}, err
		}
		for key, target := range map[string]*[]string{"additional_cidrs": &cfg.AdditionalCIDRs, "excluded_cidrs": &cfg.ExcludedCIDRs, "additional_hostnames": &cfg.AdditionalHostnames} {
			if err := apply(key, target); err != nil {
				return RemoteProbeConfig{}, err
			}
		}
	}
	if cfg.MaxConcurrent < MinProbeConcurrent || cfg.MaxConcurrent > MaxProbeConcurrent {
		return RemoteProbeConfig{}, fmt.Errorf("capability: remote_probe.max_concurrent must be between %d and %d", MinProbeConcurrent, MaxProbeConcurrent)
	}
	if cfg.ScopeMode != netscope.ScopeModeDirectPrivate {
		return RemoteProbeConfig{}, fmt.Errorf("capability: remote_probe.scope_mode %q is not a policy this build can evaluate", cfg.ScopeMode)
	}
	return cfg, nil
}

// normalizeLocalDiscoveryConfig mirrors the backend's
// _normalize_local_discovery_config, minus its CIDR parsing — for the same
// reason normalizeRemoteProbeConfig omits it: those entries were validated at
// write time and netscope.Derive already drops a malformed one, so re-parsing
// here would only add a second place for the two languages to disagree.
//
// Every numeric bound *is* re-checked. These are what the collector actually
// runs with, and an agent that accepted a ceiling the server rejects would scan
// wider than any operator approved with nothing anywhere saying so.
//
// An explicitly empty tcp_ports list survives: it is a real instruction ("do not
// port-scan"), not an absent key, so it must not be replaced by the defaults.
// That is why the presence test is `_, ok := fields[key]` rather than a length
// check on the decoded slice.
func normalizeLocalDiscoveryConfig(raw json.RawMessage) (LocalDiscoveryConfig, error) {
	cfg := DefaultLocalDiscoveryConfig()
	if len(bytes.TrimSpace(raw)) != 0 && !bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			return LocalDiscoveryConfig{}, fmt.Errorf("capability: invalid local_discovery config: %w", err)
		}
		apply := func(key string, target any) error {
			v, ok := fields[key]
			if !ok {
				return nil
			}
			if err := json.Unmarshal(v, target); err != nil {
				return fmt.Errorf("capability: invalid local_discovery.%s", key)
			}
			return nil
		}
		for key, target := range map[string]*int{
			"max_addresses_per_job": &cfg.MaxAddressesPerJob,
			"max_concurrent_hosts":  &cfg.MaxConcurrentHosts,
			"host_timeout_ms":       &cfg.HostTimeoutMS,
			"job_timeout_seconds":   &cfg.JobTimeoutSeconds,
		} {
			if err := apply(key, target); err != nil {
				return LocalDiscoveryConfig{}, err
			}
		}
		if err := apply("auto_discovery_paused", &cfg.AutoDiscoveryPaused); err != nil {
			return LocalDiscoveryConfig{}, err
		}
		if err := apply("scope_mode", &cfg.ScopeMode); err != nil {
			return LocalDiscoveryConfig{}, err
		}
		for key, target := range map[string]*[]string{"additional_cidrs": &cfg.AdditionalCIDRs, "excluded_cidrs": &cfg.ExcludedCIDRs} {
			if err := apply(key, target); err != nil {
				return LocalDiscoveryConfig{}, err
			}
		}
		if _, ok := fields["tcp_ports"]; ok {
			cfg.TCPPorts = []int{}
			if err := apply("tcp_ports", &cfg.TCPPorts); err != nil {
				return LocalDiscoveryConfig{}, err
			}
		}
	}

	for _, bound := range []struct {
		name  string
		value int
		low   int
		high  int
	}{
		{"max_addresses_per_job", cfg.MaxAddressesPerJob, MinDiscoveryAddresses, MaxDiscoveryAddresses},
		{"max_concurrent_hosts", cfg.MaxConcurrentHosts, MinDiscoveryHosts, MaxDiscoveryHosts},
		{"host_timeout_ms", cfg.HostTimeoutMS, MinDiscoveryHostTimeoutMS, MaxDiscoveryHostTimeoutMS},
		{"job_timeout_seconds", cfg.JobTimeoutSeconds, MinDiscoveryJobSeconds, MaxDiscoveryJobSeconds},
	} {
		if bound.value < bound.low || bound.value > bound.high {
			return LocalDiscoveryConfig{}, fmt.Errorf(
				"capability: local_discovery.%s must be between %d and %d", bound.name, bound.low, bound.high)
		}
	}

	if len(cfg.TCPPorts) > MaxDiscoveryPorts {
		return LocalDiscoveryConfig{}, fmt.Errorf(
			"capability: local_discovery.tcp_ports must name at most %d ports", MaxDiscoveryPorts)
	}
	for _, port := range cfg.TCPPorts {
		if port < 1 || port > 65535 {
			return LocalDiscoveryConfig{}, fmt.Errorf(
				"capability: local_discovery.tcp_ports entry %d is not a port number", port)
		}
	}
	// Deduplicated and ordered, matching the server's normalizer: the two sides
	// compare port sets, and [443,22] against [22,443] must not read as a change.
	cfg.TCPPorts = sortedUniqueInts(cfg.TCPPorts)

	if cfg.ScopeMode != netscope.ScopeModeDirectPrivate {
		return LocalDiscoveryConfig{}, fmt.Errorf(
			"capability: local_discovery.scope_mode %q is not a policy this build can evaluate", cfg.ScopeMode)
	}
	return cfg, nil
}

func sortedUniqueInts(values []int) []int {
	seen := make(map[int]struct{}, len(values))
	out := make([]int, 0, len(values))
	for _, v := range values {
		if _, dup := seen[v]; dup {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	sort.Ints(out)
	return out
}

// LoadCached restores the on-disk grant cache. Faults isolate exactly as they
// do in ApplyGrants: a single unreadable cached grant must not make a restarted
// agent forget every capability it had. The returned faults are the daemon's to
// re-report on its first connection.
func (g *Gate) LoadCached() ([]GrantFault, error) {
	data, err := os.ReadFile(g.path)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("capability: read %s: %w", g.path, err)
	}
	grants, faults, err := decode(data, nil)
	if err != nil {
		return nil, fmt.Errorf("capability: parse %s: %w", g.path, err)
	}
	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()
	return faults, nil
}

// ApplyGrants installs and persists a server grant payload, returning the
// per-capability faults it had to work around. Faults are not failures: the
// resulting snapshot is persisted and installed even when some capabilities
// faulted, so the good ones land. Only a payload that is not a grant map at all
// returns a non-nil error, and that leaves the installed snapshot untouched.
//
// grants.json therefore carries the *effective* configuration — retained or
// defaulted — not a verbatim copy of the server's payload, so a restart runs
// exactly what this process was running. The divergence from what the server
// asked for is reconciled by the returned faults (reported as
// capability.<name> = degraded), never by mirroring rejected input onto disk.
func (g *Gate) ApplyGrants(payload json.RawMessage) ([]GrantFault, error) {
	grants, faults, err := decode(payload, g.Snapshot())
	if err != nil {
		return nil, err
	}
	data, err := json.Marshal(grants)
	if err != nil {
		return nil, fmt.Errorf("capability: marshal grants: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(g.path), 0o700); err != nil {
		return nil, fmt.Errorf("capability: create state dir: %w", err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(g.path), ".grants-*")
	if err != nil {
		return nil, fmt.Errorf("capability: create temporary grants: %w", err)
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return nil, err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return nil, err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return nil, err
	}
	if err := tmp.Close(); err != nil {
		return nil, err
	}
	if err := os.Rename(tmpName, g.path); err != nil {
		return nil, fmt.Errorf("capability: replace %s: %w", g.path, err)
	}
	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()
	select {
	case g.changed <- struct{}{}:
	default:
	}
	return faults, nil
}

func (g *Gate) Allowed(name string) bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return g.grants[name].Enabled
}

func (g *Gate) Grant(name string) (Grant, bool) {
	g.mu.RLock()
	defer g.mu.RUnlock()
	v, ok := g.grants[name]
	if ok {
		v.Config = append(json.RawMessage(nil), v.Config...)
	}
	return v, ok
}

// HostConfig returns the effective host_telemetry config, and whether the
// capability is granted at all. It does no validation: decode is the sole
// validation point, so a stored config is valid by construction — it is either
// a config that passed normalizeHostConfig, the last one that did, or the
// package default. The old silent ok=false on a stored-invalid config took a
// monitored host dark with no signal anywhere; that path no longer exists.
func (g *Gate) HostConfig() (HostConfig, bool) {
	grant, ok := g.Grant("host_telemetry")
	if !ok || !grant.Enabled {
		return HostConfig{}, false
	}
	cfg := DefaultHostConfig()
	if len(grant.Config) > 0 {
		if err := json.Unmarshal(grant.Config, &cfg); err != nil {
			return DefaultHostConfig(), true
		}
	}
	return cfg, true
}

// RemoteProbeConfig returns the effective remote_probe config, and whether the
// capability is granted at all. Like HostConfig it does no validation — decode
// is the sole validation point, so a stored config is one that passed
// normalizeRemoteProbeConfig, the last one that did, or the package default.
//
// The config it returns is the *server's*, always: grants.json is a cache that
// keeps a disconnected agent useful, never a local source of authority, so a
// host-side edit to the scope survives exactly until the next capabilities.set.
func (g *Gate) RemoteProbeConfig() (RemoteProbeConfig, bool) {
	grant, ok := g.Grant("remote_probe")
	if !ok || !grant.Enabled {
		return RemoteProbeConfig{}, false
	}
	cfg := DefaultRemoteProbeConfig()
	if len(grant.Config) > 0 {
		if err := json.Unmarshal(grant.Config, &cfg); err != nil {
			return DefaultRemoteProbeConfig(), true
		}
	}
	return cfg, true
}

// LocalDiscoveryConfig returns the effective `local_discovery` config and
// whether the capability is granted, mirroring RemoteProbeConfig exactly. A
// stored config that will not decode falls back to the package default rather
// than to nothing: the grant is enabled, so refusing to answer would strand the
// collector rather than bound it.
func (g *Gate) LocalDiscoveryConfig() (LocalDiscoveryConfig, bool) {
	grant, ok := g.Grant("local_discovery")
	if !ok || !grant.Enabled {
		return LocalDiscoveryConfig{}, false
	}
	cfg := DefaultLocalDiscoveryConfig()
	if len(grant.Config) > 0 {
		if err := json.Unmarshal(grant.Config, &cfg); err != nil {
			return DefaultLocalDiscoveryConfig(), true
		}
	}
	return cfg, true
}

func (g *Gate) Changes() <-chan struct{} { return g.changed }

func (g *Gate) Snapshot() Snapshot {
	g.mu.RLock()
	defer g.mu.RUnlock()
	out := make(Snapshot, len(g.grants))
	for k, v := range g.grants {
		v.Config = append(json.RawMessage(nil), v.Config...)
		out[k] = v
	}
	return out
}

// Grants preserves the Slice 1 status-file contract.
func (g *Gate) Grants() map[string]bool {
	out := map[string]bool{}
	for k, v := range g.Snapshot() {
		out[k] = v.Enabled
	}
	return out
}
