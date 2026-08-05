package frame

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
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

// TestCorpus_TypedPayloadsDecode additionally decodes every corpus entry's payload into its
// structured Go type (where one exists), pinning the extended hello/hello.ack shapes plus the
// new transport.rekey and key.rotate payloads against the same corpus used by
// test_agent_frame_conformance.py. Old-shaped and partial payloads (e.g. the pre-existing
// enrollment-flavored hello.ack entries, or hello's empty/partial fixtures) must decode without
// error — that's the backward-compatibility guarantee this test pins.
func TestCorpus_TypedPayloadsDecode(t *testing.T) {
	for _, entry := range loadCorpus(t) {
		t.Run(entry.Description, func(t *testing.T) {
			decoded, err := Decode(entry.JSON)
			if err != nil {
				t.Fatalf("Decode() error = %v", err)
			}
			switch decoded.Type {
			case TypeHello:
				roundTripHelloPayload(t, decoded.Payload)
			case TypeHelloAck:
				roundTripHelloAckPayload(t, decoded.Payload)
			case TypeTransportRekey:
				roundTripTransportRekeyPayload(t, decoded.Payload)
			case TypeKeyRotate:
				roundTripKeyRotatePayload(t, decoded.Payload)
			case TypeUpdateStatus:
				roundTripUpdateStatusPayload(t, decoded.Payload)
			}
		})
	}
}

func roundTripHelloPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first HelloPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("HelloPayload decode error = %v", err)
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("HelloPayload encode error = %v", err)
	}
	var second HelloPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("HelloPayload re-decode error = %v", err)
	}
	if first.DevicePK != second.DevicePK || first.Hostname != second.Hostname ||
		first.MachineIDHash != second.MachineIDHash || first.OS != second.OS ||
		first.OSVersion != second.OSVersion || first.Arch != second.Arch ||
		first.AgentVersion != second.AgentVersion || first.SpoolDepth != second.SpoolDepth {
		t.Errorf("HelloPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	// omitempty drops a present-but-empty JSON array on re-encode, so a corpus entry with an
	// explicit "primary_macs": [] decodes to a non-nil empty slice while the re-decode comes
	// back nil — both mean "no MACs reported", so slice comparisons treat nil and empty alike.
	if !slicesEqualIgnoringNil(first.PrimaryMACs, second.PrimaryMACs) {
		t.Errorf("HelloPayload.PrimaryMACs round-trip mismatch: got %v, want %v", second.PrimaryMACs, first.PrimaryMACs)
	}
	if len(first.Readiness) != len(second.Readiness) || (len(first.Readiness) > 0 && !reflect.DeepEqual(first.Readiness, second.Readiness)) {
		t.Errorf("HelloPayload.Readiness round-trip mismatch: got %+v, want %+v", second.Readiness, first.Readiness)
	}
}

func slicesEqualIgnoringNil(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func roundTripHelloAckPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first HelloAckPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("HelloAckPayload decode error = %v", err)
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("HelloAckPayload encode error = %v", err)
	}
	var second HelloAckPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("HelloAckPayload re-decode error = %v", err)
	}
	if first.Accepted != second.Accepted || first.Reason != second.Reason || first.AgentID != second.AgentID {
		t.Errorf("HelloAckPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	if !reflect.DeepEqual(first.Capabilities, second.Capabilities) {
		t.Errorf("HelloAckPayload.Capabilities round-trip mismatch: got %+v, want %+v", second.Capabilities, first.Capabilities)
	}
	if (first.ServerTime == nil) != (second.ServerTime == nil) {
		t.Fatalf("HelloAckPayload.ServerTime nilness mismatch: got %v, want %v", second.ServerTime, first.ServerTime)
	}
	if first.ServerTime != nil && !first.ServerTime.Equal(*second.ServerTime) {
		t.Errorf("HelloAckPayload.ServerTime round-trip mismatch: got %v, want %v", second.ServerTime, first.ServerTime)
	}
}

func roundTripTransportRekeyPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first TransportRekeyPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("TransportRekeyPayload decode error = %v", err)
	}
	if first.Direction != "inbound" && first.Direction != "outbound" {
		t.Errorf("Direction = %q, want inbound or outbound", first.Direction)
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("TransportRekeyPayload encode error = %v", err)
	}
	var second TransportRekeyPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("TransportRekeyPayload re-decode error = %v", err)
	}
	if first != second {
		t.Errorf("TransportRekeyPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
}

func roundTripUpdateStatusPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first UpdateStatusPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("UpdateStatusPayload decode error = %v", err)
	}
	switch first.Phase {
	case "started", "succeeded", "failed", "rolled_back":
	default:
		t.Errorf("Phase = %q, want one of started/succeeded/failed/rolled_back", first.Phase)
	}
	if first.Version == "" {
		t.Error("Version is empty")
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("UpdateStatusPayload encode error = %v", err)
	}
	var second UpdateStatusPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("UpdateStatusPayload re-decode error = %v", err)
	}
	if first != second {
		t.Errorf("UpdateStatusPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
}

func roundTripKeyRotatePayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first KeyRotatePayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("KeyRotatePayload decode error = %v", err)
	}
	if first.Kind != "device" && first.Kind != "server" {
		t.Errorf("Kind = %q, want device or server", first.Kind)
	}
	if first.SuccessorPK == "" {
		t.Error("SuccessorPK is empty")
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("KeyRotatePayload encode error = %v", err)
	}
	var second KeyRotatePayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("KeyRotatePayload re-decode error = %v", err)
	}
	if first.Kind != second.Kind || first.SuccessorPK != second.SuccessorPK {
		t.Errorf("KeyRotatePayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	if !first.Expiry.Equal(second.Expiry) {
		t.Errorf("KeyRotatePayload.Expiry round-trip mismatch: got %v, want %v", second.Expiry, first.Expiry)
	}
}
