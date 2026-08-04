// apps/agent/internal/capability/capability.go
package capability

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

const grantsFilename = "grants.json"

// Gate is the in-agent capability gate — grants arrive only over the link
// (spec §4.2) and are cached here solely so a restart while disconnected
// doesn't go dark. The server re-sends the authoritative set on every
// reconnect and this cache is overwritten, never edited locally.
type Gate struct {
	mu     sync.RWMutex
	grants map[string]bool
	path   string
}

func New(stateDir string) *Gate {
	return &Gate{grants: map[string]bool{}, path: filepath.Join(stateDir, grantsFilename)}
}

func (g *Gate) LoadCached() error {
	data, err := os.ReadFile(g.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("capability: read %s: %w", g.path, err)
	}
	var grants map[string]bool
	if err := json.Unmarshal(data, &grants); err != nil {
		return fmt.Errorf("capability: parse %s: %w", g.path, err)
	}
	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()
	return nil
}

func (g *Gate) ApplyGrants(payload json.RawMessage) error {
	var grants map[string]bool
	if err := json.Unmarshal(payload, &grants); err != nil {
		return fmt.Errorf("capability: unmarshal grants: %w", err)
	}

	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()

	data, err := json.Marshal(grants)
	if err != nil {
		return fmt.Errorf("capability: marshal grants: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(g.path), 0o700); err != nil {
		return fmt.Errorf("capability: create state dir: %w", err)
	}
	if err := os.WriteFile(g.path, data, 0o600); err != nil {
		return fmt.Errorf("capability: write %s: %w", g.path, err)
	}
	return nil
}

// Allowed is default-deny: anything not explicitly granted true is refused.
func (g *Gate) Allowed(capability string) bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return g.grants[capability]
}

// Grants returns a snapshot copy of the full current grant set — for callers
// that need the whole set (e.g. the runtime status writer) rather than one
// capability via Allowed. The copy is safe to hold onto: it is never mutated
// by the Gate after being returned.
func (g *Gate) Grants() map[string]bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	out := make(map[string]bool, len(g.grants))
	for k, v := range g.grants {
		out[k] = v
	}
	return out
}
