package frame

import (
	"encoding/json"
	"testing"
	"time"
)

func TestEncodeDecode_RoundTrips(t *testing.T) {
	original := Frame{
		V:       1,
		Type:    "heartbeat",
		Seq:     42,
		TS:      time.Date(2026, 7, 27, 12, 0, 0, 0, time.UTC),
		Payload: json.RawMessage(`{"ok":true}`),
	}

	data, err := Encode(original)
	if err != nil {
		t.Fatalf("Encode() error = %v", err)
	}

	decoded, err := Decode(data)
	if err != nil {
		t.Fatalf("Decode() error = %v", err)
	}
	if decoded.Type != "heartbeat" || decoded.Seq != 42 || decoded.V != 1 {
		t.Errorf("decoded = %+v, want type=heartbeat seq=42 v=1", decoded)
	}
	if !decoded.TS.Equal(original.TS) {
		t.Errorf("TS = %v, want %v", decoded.TS, original.TS)
	}
}

func TestDecode_RejectsMalformedJSON(t *testing.T) {
	if _, err := Decode([]byte("not json")); err == nil {
		t.Fatal("expected error decoding malformed frame, got nil")
	}
}
