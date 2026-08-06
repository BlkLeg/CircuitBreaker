package capability

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

const grantsFilename = "grants.json"

const (
	MinHostInterval = 10
	MaxHostInterval = 900
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

func decode(payload []byte) (Snapshot, error) {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(payload, &raw); err != nil {
		return nil, fmt.Errorf("capability: unmarshal grants: %w", err)
	}
	out := make(Snapshot, len(raw))
	for name, value := range raw {
		var enabled bool
		if err := json.Unmarshal(value, &enabled); err == nil {
			out[name] = normalize(name, Grant{Enabled: enabled})
			continue
		}
		var grant Grant
		if err := json.Unmarshal(value, &grant); err != nil {
			return nil, fmt.Errorf("capability: invalid grant %q: %w", name, err)
		}
		if name == "host_telemetry" {
			cfg, err := normalizeHostConfig(grant.Config)
			if err != nil {
				return nil, err
			}
			grant.Config, _ = json.Marshal(cfg)
		}
		out[name] = normalize(name, grant)
	}
	return out, nil
}

func normalize(name string, grant Grant) Grant {
	if name == "host_telemetry" && len(grant.Config) == 0 {
		grant.Config, _ = json.Marshal(DefaultHostConfig())
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

func (g *Gate) LoadCached() error {
	data, err := os.ReadFile(g.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("capability: read %s: %w", g.path, err)
	}
	grants, err := decode(data)
	if err != nil {
		return fmt.Errorf("capability: parse %s: %w", g.path, err)
	}
	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()
	return nil
}

func (g *Gate) ApplyGrants(payload json.RawMessage) error {
	grants, err := decode(payload)
	if err != nil {
		return err
	}
	data, err := json.Marshal(grants)
	if err != nil {
		return fmt.Errorf("capability: marshal grants: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(g.path), 0o700); err != nil {
		return fmt.Errorf("capability: create state dir: %w", err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(g.path), ".grants-*")
	if err != nil {
		return fmt.Errorf("capability: create temporary grants: %w", err)
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpName, g.path); err != nil {
		return fmt.Errorf("capability: replace %s: %w", g.path, err)
	}
	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()
	select {
	case g.changed <- struct{}{}:
	default:
	}
	return nil
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

func (g *Gate) HostConfig() (HostConfig, bool) {
	grant, ok := g.Grant("host_telemetry")
	if !ok || !grant.Enabled {
		return HostConfig{}, false
	}
	cfg, err := normalizeHostConfig(grant.Config)
	return cfg, err == nil
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
