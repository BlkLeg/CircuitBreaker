package frame

import (
	"encoding/json"
	"reflect"
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

func TestHelloPayload_MissingFieldsDecodeToZeroValues(t *testing.T) {
	tests := []struct {
		name string
		json string
		want HelloPayload
	}{
		{
			name: "empty object",
			json: `{}`,
			want: HelloPayload{},
		},
		{
			name: "hostname only",
			json: `{"hostname":"box1.local"}`,
			want: HelloPayload{Hostname: "box1.local"},
		},
		{
			name: "all fields",
			json: `{"device_pk":"ab12","hostname":"box1.local","machine_id_hash":"deadbeef",` +
				`"os":"linux","os_version":"6.1","arch":"amd64","agent_version":"0.1.0",` +
				`"primary_macs":["aa:bb:cc:dd:ee:ff"],` +
				`"readiness":[{"collector":"host.docker","state":"ready"}],"spool_depth":3}`,
			want: HelloPayload{
				DevicePK: "ab12", Hostname: "box1.local", MachineIDHash: "deadbeef",
				OS: "linux", OSVersion: "6.1", Arch: "amd64", AgentVersion: "0.1.0",
				PrimaryMACs: []string{"aa:bb:cc:dd:ee:ff"},
				Readiness:   []Readiness{{Collector: "host.docker", State: "ready"}},
				SpoolDepth:  3,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var got HelloPayload
			if err := json.Unmarshal([]byte(tt.json), &got); err != nil {
				t.Fatalf("Unmarshal() error = %v", err)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Unmarshal() = %+v, want %+v", got, tt.want)
			}
		})
	}
}

func TestTransportRekeyPayload_EncodeDecode(t *testing.T) {
	tests := []struct {
		name    string
		payload TransportRekeyPayload
	}{
		{name: "outbound", payload: TransportRekeyPayload{Direction: "outbound", Generation: 1}},
		{name: "inbound, large generation", payload: TransportRekeyPayload{Direction: "inbound", Generation: 9999}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := json.Marshal(tt.payload)
			if err != nil {
				t.Fatalf("Marshal() error = %v", err)
			}
			var got TransportRekeyPayload
			if err := json.Unmarshal(data, &got); err != nil {
				t.Fatalf("Unmarshal() error = %v", err)
			}
			if got != tt.payload {
				t.Errorf("round-trip = %+v, want %+v", got, tt.payload)
			}
		})
	}
}

func TestKeyRotatePayload_EncodeDecode(t *testing.T) {
	tests := []struct {
		name    string
		payload KeyRotatePayload
	}{
		{
			name: "device key rotation",
			payload: KeyRotatePayload{
				Kind: "device", SuccessorPK: "ef01ab23cd45",
				Expiry: time.Date(2026, 8, 3, 12, 35, 0, 0, time.UTC),
			},
		},
		{
			name: "server key rotation",
			payload: KeyRotatePayload{
				Kind: "server", SuccessorPK: "1234567890ab",
				Expiry: time.Date(2026, 8, 10, 0, 0, 0, 0, time.UTC),
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := json.Marshal(tt.payload)
			if err != nil {
				t.Fatalf("Marshal() error = %v", err)
			}
			var got KeyRotatePayload
			if err := json.Unmarshal(data, &got); err != nil {
				t.Fatalf("Unmarshal() error = %v", err)
			}
			if got.Kind != tt.payload.Kind || got.SuccessorPK != tt.payload.SuccessorPK {
				t.Errorf("round-trip = %+v, want %+v", got, tt.payload)
			}
			if !got.Expiry.Equal(tt.payload.Expiry) {
				t.Errorf("Expiry round-trip = %v, want %v", got.Expiry, tt.payload.Expiry)
			}
		})
	}
}

// TestIsDataFrame_ControlAndHeartbeatTypesReturnFalse locks in the deny-list:
// every frame type that carries link-protocol control traffic or the
// heartbeat liveness signal must never be classified as a data frame, since
// internal/link uses IsDataFrame to decide what's eligible for the outbound
// spool (spec: heartbeat/control frames must never reach the spool's write
// path).
func TestIsDataFrame_ControlAndHeartbeatTypesReturnFalse(t *testing.T) {
	controlTypes := []string{
		TypeHello, TypeHeartbeat, TypeCapabilityReadiness, TypeUninstall,
		TypeHelloAck, TypeCapabilitiesSet, TypeProbeAssign, TypeProbeCancel,
		TypeDiscoveryRequest, TypeDiscoveryCancel,
		TypeKeyRotate, TypeTLSPinRotate, TypeUpdate, TypeDisconnect, TypePing,
		TypeTransportRekey,
	}
	for _, typ := range controlTypes {
		if IsDataFrame(typ) {
			t.Errorf("IsDataFrame(%q) = true, want false (control/heartbeat frame)", typ)
		}
	}

	// The list above is hand-written on purpose — it is the independent
	// statement of which types must never be spooled, and deriving it from
	// controlFrameTypes would make the loop assert `!m[t]` against `m` and
	// prove nothing. What it cannot do on its own is notice an omission: a
	// slice that adds a control frame and forgets this literal leaves the new
	// type's spool-ineligibility completely unasserted, and the suite stays
	// green. That is how TypeDiscoveryCancel (Slice 4) and
	// TypeCapabilityReadiness (Slice 2) both came to be missing here. So the
	// literal stays the expectation and this makes forgetting it fail loudly.
	named := make(map[string]bool, len(controlTypes))
	for _, typ := range controlTypes {
		named[typ] = true
	}
	for typ := range controlFrameTypes {
		if !named[typ] {
			t.Errorf("control frame type %q is in controlFrameTypes but unasserted here — add it to controlTypes", typ)
		}
	}
}

// TestIsDataFrame_KnownAndUnknownDataTypesReturnTrue verifies the classifier
// is a deny-list, not an allow-list: today's real data-frame constants
// (Slice 2+ payloads not yet produced anywhere) and a made-up type neither
// this package nor any slice has ever defined both classify as data frames.
// That's the point — the mechanism must activate automatically for whatever
// data frame type a future slice introduces, without a code change here.
func TestIsDataFrame_KnownAndUnknownDataTypesReturnTrue(t *testing.T) {
	dataTypes := []string{
		TypeTelemetryHost, TypeProbeResult, TypeDiscoveryFinding, TypeCapabilityViolation, TypeLog,
		"test.fakedata", // fake, test-only type — never a real Slice 1-4 payload
	}
	for _, typ := range dataTypes {
		if !IsDataFrame(typ) {
			t.Errorf("IsDataFrame(%q) = false, want true (data frame)", typ)
		}
	}
}

func TestHelloAckPayload_ServerTimeOmittedWhenNil(t *testing.T) {
	payload := HelloAckPayload{Accepted: true, AgentID: 7}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("Marshal() error = %v", err)
	}
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if _, present := raw["server_time"]; present {
		t.Errorf("server_time present in %s, want omitted when nil", data)
	}

	var got HelloAckPayload
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if got.ServerTime != nil {
		t.Errorf("ServerTime = %v, want nil", got.ServerTime)
	}
	if !got.Accepted || got.AgentID != 7 {
		t.Errorf("round-trip = %+v, want Accepted=true AgentID=7", got)
	}
}

// TestProbeResultPayload_FalseUpSurvivesRoundTrip pins the one field in the result payload where
// omitempty would be a correctness bug rather than a cosmetic choice. A DOWN target reports
// up=false, and Go's omitempty drops a false bool entirely — the server would then read the
// absent key as its own default and a genuine outage would arrive as "no opinion". Same
// reasoning as HeartbeatPayload's spool fields: the zero value here is a fact about the target,
// not the absence of one.
func TestProbeResultPayload_FalseUpSurvivesRoundTrip(t *testing.T) {
	payload := ProbeResultPayload{
		RunID:      "3f9c1a7be04d42a1b8e6c05d7f1a2b3c",
		MonitorID:  42,
		Outcome:    "completed",
		Up:         false,
		StartedAt:  time.Date(2026, 8, 7, 18, 0, 11, 0, time.UTC),
		FinishedAt: time.Date(2026, 8, 7, 18, 0, 12, 8000000, time.UTC),
		Samples:    []ProbeSample{{Metric: "avail", Value: 0, ErrorReason: "http_error"}},
		Msg:        "request failed: ConnectTimeout",
	}

	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("Marshal() error = %v", err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if _, present := raw["up"]; !present {
		t.Fatalf("up absent from %s, want an explicit false", data)
	}
	if string(raw["up"]) != "false" {
		t.Errorf("up = %s, want false", raw["up"])
	}

	var got ProbeResultPayload
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if got.Up {
		t.Error("Up = true after round-trip, want false")
	}
	if !reflect.DeepEqual(got.Samples, payload.Samples) {
		t.Errorf("Samples round-trip = %+v, want %+v", got.Samples, payload.Samples)
	}
	if got.RunID != payload.RunID || got.MonitorID != payload.MonitorID ||
		got.Outcome != payload.Outcome || got.Msg != payload.Msg {
		t.Errorf("round-trip = %+v, want %+v", got, payload)
	}
	if !got.StartedAt.Equal(payload.StartedAt) || !got.FinishedAt.Equal(payload.FinishedAt) {
		t.Errorf("timestamp round-trip = %v/%v, want %v/%v",
			got.StartedAt, got.FinishedAt, payload.StartedAt, payload.FinishedAt)
	}
}
