package frame

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type corpusEntry struct {
	Description string          `json:"description"`
	JSON        json.RawMessage `json:"json"`
}

func loadCorpus(t *testing.T) []corpusEntry {
	t.Helper()
	// apps/agent/internal/frame -> repo root is four levels up.
	path := filepath.Join("..", "..", "..", "..", "fixtures", "agent_frame_corpus.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read corpus: %v", err)
	}
	var entries []corpusEntry
	if err := json.Unmarshal(data, &entries); err != nil {
		t.Fatalf("unmarshal corpus: %v", err)
	}
	return entries
}

func TestCorpus_DecodesAndRoundTrips(t *testing.T) {
	for _, entry := range loadCorpus(t) {
		t.Run(entry.Description, func(t *testing.T) {
			decoded, err := Decode(entry.JSON)
			if err != nil {
				t.Fatalf("Decode() error = %v", err)
			}
			if decoded.V != 1 {
				t.Errorf("V = %d, want 1", decoded.V)
			}
			if decoded.Type == "" {
				t.Error("Type is empty")
			}

			reencoded, err := Encode(decoded)
			if err != nil {
				t.Fatalf("Encode() error = %v", err)
			}
			redecoded, err := Decode(reencoded)
			if err != nil {
				t.Fatalf("re-Decode() error = %v", err)
			}
			if redecoded.Type != decoded.Type || redecoded.Seq != decoded.Seq {
				t.Errorf("round-trip mismatch: got %+v, want %+v", redecoded, decoded)
			}
			if !redecoded.TS.Equal(decoded.TS) {
				t.Errorf("round-trip TS mismatch: got %v, want %v", redecoded.TS, decoded.TS)
			}
		})
	}
}
