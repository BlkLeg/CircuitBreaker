package netscope

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// corpusEntry mirrors fixtures/agent_scope_corpus.json's entry shape, which
// apps/backend/tests/unit/test_agent_scope_corpus.py drives through the backend evaluator.
type corpusEntry struct {
	Description string           `json:"description"`
	Facts       []InterfaceFacts `json:"facts"`
	Config      Config           `json:"config"`
	Destination struct {
		Host     string   `json:"host"`
		CIDR     string   `json:"cidr"`
		Resolved []string `json:"resolved"`
	} `json:"destination"`
	Expected string `json:"expected"`
	Reason   string `json:"reason"`
}

func loadScopeCorpus(t *testing.T) []corpusEntry {
	t.Helper()
	// apps/agent/internal/netscope -> repo root is four levels up.
	path := filepath.Join("..", "..", "..", "..", "fixtures", "agent_scope_corpus.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read corpus: %v", err)
	}
	var entries []corpusEntry
	if err := json.Unmarshal(data, &entries); err != nil {
		t.Fatalf("unmarshal corpus: %v", err)
	}
	if len(entries) == 0 {
		t.Fatal("corpus is empty")
	}
	return entries
}

// TestScopeCorpus_MatchesEveryCase is the gate on §3's "enforce scope independently": two
// evaluators are a safety property only while they agree, so a rule that exists on one side
// only surfaces here as a decision mismatch rather than as a hole nobody notices.
func TestScopeCorpus_MatchesEveryCase(t *testing.T) {
	for _, entry := range loadScopeCorpus(t) {
		t.Run(entry.Description, func(t *testing.T) {
			scope := Derive(entry.Facts, entry.Config)

			// A corpus entry names either a single destination (host) or a whole target
			// prefix (cidr). Slice 4 dispatches prefixes rather than addresses, so
			// NetworkInScope has to sit under the same cross-language gate as Evaluate —
			// otherwise the one rule set both languages agree on covers only half of what
			// actually authorizes work.
			var decision Decision
			if entry.Destination.CIDR != "" {
				decision = NetworkInScope(scope, entry.Destination.CIDR)
			} else {
				decision = Evaluate(scope, entry.Destination.Host, entry.Destination.Resolved)
			}

			if want := entry.Expected == "allow"; decision.Allowed != want {
				t.Errorf("Allowed = %v, want %v (reason %q)", decision.Allowed, want, decision.Reason)
			}
			if decision.Reason != entry.Reason {
				t.Errorf("Reason = %q, want %q", decision.Reason, entry.Reason)
			}
		})
	}
}
