package frame

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/netscope"
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
			case TypeTelemetryHost:
				roundTripHostTelemetryPayload(t, decoded.Payload)
			case TypeCapabilityReadiness:
				roundTripCapabilityReadinessPayload(t, decoded.Payload)
			case TypeHeartbeat:
				roundTripHeartbeatPayload(t, decoded.Payload)
			case TypeProbeAssign:
				roundTripProbeAssignPayload(t, decoded.Payload)
			case TypeProbeCancel:
				roundTripProbeCancelPayload(t, decoded.Payload)
			case TypeProbeResult:
				roundTripProbeResultPayload(t, decoded.Payload)
			case TypeDiscoveryRequest:
				roundTripDiscoveryRequestPayload(t, decoded.Payload)
			case TypeDiscoveryCancel:
				roundTripDiscoveryCancelPayload(t, decoded.Payload)
			case TypeDiscoveryFinding:
				roundTripDiscoveryFindingPayload(t, decoded.Payload)
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
	compareNetworkFacts(t, raw, first.Networks, second.Networks)
}

// compareNetworkFacts pins the Task 1 `networks` field. Every json tag it depends on — the outer
// `networks` and each inner one — is spelled literally in wireNetworks below and asserted against
// what NetworkFacts decoded, so the check is against the fixture and not against Go's own
// re-encode: a mistyped tag at any level leaves the field zero on *both* sides, which a
// first-vs-second comparison alone would call a clean round trip. That is not a theoretical
// hazard — the Python half drops unknown keys silently (pydantic's default extra="ignore"), so a
// tag only Go agrees with is exactly how `addrs`, the one field the rest of Slice 3 consumes,
// would arrive empty on the backend with this cross-language gate green.
func compareNetworkFacts(t *testing.T, raw json.RawMessage, first, second []NetworkFacts) {
	t.Helper()
	// The tags here are the assertion; do not replace them with NetworkFacts.
	type wireNetworks struct {
		Name  string   `json:"name"`
		Flags []string `json:"flags"`
		Addrs []string `json:"addrs"`
	}
	var wire struct {
		Networks []wireNetworks `json:"networks"`
	}
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("hello payload networks decode error = %v", err)
	}
	if len(wire.Networks) != len(first) {
		t.Fatalf("HelloPayload.Networks decoded %d entries from a fixture carrying %d — check the json tag", len(first), len(wire.Networks))
	}
	if len(first) != len(second) {
		t.Fatalf("HelloPayload.Networks length round-trip mismatch: got %d, want %d", len(second), len(first))
	}
	for i := range first {
		if first[i].Name != wire.Networks[i].Name {
			t.Errorf("HelloPayload.Networks[%d].Name = %q, fixture carries %q — check the json tag", i, first[i].Name, wire.Networks[i].Name)
		}
		if !slicesEqualIgnoringNil(first[i].Flags, wire.Networks[i].Flags) {
			t.Errorf("HelloPayload.Networks[%d].Flags = %v, fixture carries %v — check the json tag", i, first[i].Flags, wire.Networks[i].Flags)
		}
		if !slicesEqualIgnoringNil(first[i].Addrs, wire.Networks[i].Addrs) {
			t.Errorf("HelloPayload.Networks[%d].Addrs = %v, fixture carries %v — check the json tag", i, first[i].Addrs, wire.Networks[i].Addrs)
		}
		if first[i].Name != second[i].Name {
			t.Errorf("HelloPayload.Networks[%d].Name round-trip mismatch: got %q, want %q", i, second[i].Name, first[i].Name)
		}
		// Same nil-vs-empty tolerance as PrimaryMACs above: omitempty drops a present-but-empty
		// array on re-encode.
		if !slicesEqualIgnoringNil(first[i].Flags, second[i].Flags) {
			t.Errorf("HelloPayload.Networks[%d].Flags round-trip mismatch: got %v, want %v", i, second[i].Flags, first[i].Flags)
		}
		if !slicesEqualIgnoringNil(first[i].Addrs, second[i].Addrs) {
			t.Errorf("HelloPayload.Networks[%d].Addrs round-trip mismatch: got %v, want %v", i, second[i].Addrs, first[i].Addrs)
		}
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
	if !rawJSONMapsEqual(t, first.Capabilities, second.Capabilities) {
		t.Errorf("HelloAckPayload.Capabilities round-trip mismatch: got %s, want %s",
			rawJSONMapString(first.Capabilities), rawJSONMapString(second.Capabilities))
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

// roundTripHeartbeatPayload pins D-12's wire shape. Both the old-shaped `{}`
// heartbeat and the spool-reporting one must decode; re-encoding must always
// emit both keys, zeros included, because an empty payload is reserved to
// mean "this agent does not report spool state" (see HeartbeatPayload's doc
// comment and agent_registry.record_spool_stats' presence gate).
func roundTripHeartbeatPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first HeartbeatPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("HeartbeatPayload decode error = %v", err)
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("HeartbeatPayload encode error = %v", err)
	}
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(reencoded, &keys); err != nil {
		t.Fatalf("HeartbeatPayload re-decode as map error = %v", err)
	}
	for _, key := range []string{"spool_depth", "spool_bytes"} {
		if _, ok := keys[key]; !ok {
			t.Errorf("re-encoded HeartbeatPayload %s omits %q — neither field may carry omitempty", reencoded, key)
		}
	}
	var second HeartbeatPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("HeartbeatPayload re-decode error = %v", err)
	}
	if first != second {
		t.Errorf("HeartbeatPayload round-trip mismatch: got %+v, want %+v", second, first)
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

// roundTripProbeAssignPayload pins the §4 assignment shape. As in compareNetworkFacts above,
// every json tag is re-declared literally in a reference struct and asserted against what
// ProbeAssignPayload actually decoded, because a mistyped tag leaves the field zero on *both*
// sides of a first-vs-second comparison and reads as a clean round trip. `config` is the field
// that makes this worth the duplication: silently losing it turns an authenticated HTTPS check
// with a keyword assertion into an unauthenticated bare GET, which no round-trip comparison and
// no pydantic model on the far side (extra keys are dropped without complaint) would notice.
func roundTripProbeAssignPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	// The tags here are the assertion; do not replace them with ProbeAssignPayload.
	var wire struct {
		RunID       string          `json:"run_id"`
		MonitorID   int64           `json:"monitor_id"`
		CheckType   string          `json:"check_type"`
		Host        string          `json:"host"`
		Config      json.RawMessage `json:"config"`
		ScheduledAt time.Time       `json:"scheduled_at"`
		DeadlineAt  time.Time       `json:"deadline_at"`
	}
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("probe.assign reference decode error = %v", err)
	}

	var first ProbeAssignPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("ProbeAssignPayload decode error = %v", err)
	}
	if first.RunID != wire.RunID || first.MonitorID != wire.MonitorID ||
		first.CheckType != wire.CheckType || first.Host != wire.Host {
		t.Errorf("ProbeAssignPayload = %+v, fixture carries %+v — check the json tags", first, wire)
	}
	if !first.ScheduledAt.Equal(wire.ScheduledAt) || !first.DeadlineAt.Equal(wire.DeadlineAt) {
		t.Errorf("ProbeAssignPayload timestamps = %v/%v, fixture carries %v/%v — check the json tags",
			first.ScheduledAt, first.DeadlineAt, wire.ScheduledAt, wire.DeadlineAt)
	}
	if !jsonValuesEqual(t, first.Config, wire.Config) {
		t.Errorf("ProbeAssignPayload.Config = %s, fixture carries %s — check the json tag", first.Config, wire.Config)
	}
	if first.Host == "" {
		t.Error("Host is empty — an assignment with no destination is not dispatchable")
	}

	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("ProbeAssignPayload encode error = %v", err)
	}
	var second ProbeAssignPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("ProbeAssignPayload re-decode error = %v", err)
	}
	if first.RunID != second.RunID || first.MonitorID != second.MonitorID ||
		first.CheckType != second.CheckType || first.Host != second.Host {
		t.Errorf("ProbeAssignPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	if !first.ScheduledAt.Equal(second.ScheduledAt) || !first.DeadlineAt.Equal(second.DeadlineAt) {
		t.Errorf("ProbeAssignPayload timestamp round-trip mismatch: got %v/%v, want %v/%v",
			second.ScheduledAt, second.DeadlineAt, first.ScheduledAt, first.DeadlineAt)
	}
	if !jsonValuesEqual(t, first.Config, second.Config) {
		t.Errorf("ProbeAssignPayload.Config round-trip mismatch: got %s, want %s", second.Config, first.Config)
	}
}

func roundTripProbeCancelPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first ProbeCancelPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("ProbeCancelPayload decode error = %v", err)
	}
	if first.RunID == "" {
		t.Error("RunID is empty — a cancellation names exactly one run")
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("ProbeCancelPayload encode error = %v", err)
	}
	var second ProbeCancelPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("ProbeCancelPayload re-decode error = %v", err)
	}
	if first != second {
		t.Errorf("ProbeCancelPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
}

// probeOutcomes is the closed outcome vocabulary from §4, mirroring monitor_probe_runs.outcome.
// Anything else is a protocol violation the server rejects rather than a new kind of result.
var probeOutcomes = map[string]bool{
	"completed": true, "execution_error": true, "cancelled": true, "rejected": true,
}

// roundTripProbeResultPayload pins the §4 result shape, including the two properties this frame
// cannot be trusted without: `samples` must survive by name (same silent-drop hazard as
// probe.assign's config — losing them would feed the monitor state machine an empty result while
// every round-trip comparison stays green), and `up` must be re-encoded even when false, since
// false is what a DOWN target reports and an omitted key on the server side reads as "no
// opinion" rather than "down".
func roundTripProbeResultPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	// The tags here are the assertion; do not replace them with ProbeResultPayload/ProbeSample.
	var wire struct {
		RunID     string `json:"run_id"`
		MonitorID int64  `json:"monitor_id"`
		Outcome   string `json:"outcome"`
		Up        bool   `json:"up"`
		Samples   []struct {
			Metric      string  `json:"metric"`
			Value       float64 `json:"value"`
			ErrorReason string  `json:"error_reason"`
		} `json:"samples"`
		Msg     string          `json:"msg"`
		Details json.RawMessage `json:"details"`
	}
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("probe.result reference decode error = %v", err)
	}

	var first ProbeResultPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("ProbeResultPayload decode error = %v", err)
	}
	if !probeOutcomes[first.Outcome] {
		t.Errorf("Outcome = %q, want one of completed/execution_error/cancelled/rejected", first.Outcome)
	}
	if first.RunID != wire.RunID || first.MonitorID != wire.MonitorID ||
		first.Outcome != wire.Outcome || first.Up != wire.Up || first.Msg != wire.Msg {
		t.Errorf("ProbeResultPayload = %+v, fixture carries %+v — check the json tags", first, wire)
	}
	if len(first.Samples) != len(wire.Samples) {
		t.Fatalf("ProbeResultPayload.Samples decoded %d entries from a fixture carrying %d — check the json tag",
			len(first.Samples), len(wire.Samples))
	}
	for i := range wire.Samples {
		if first.Samples[i].Metric != wire.Samples[i].Metric ||
			first.Samples[i].Value != wire.Samples[i].Value ||
			first.Samples[i].ErrorReason != wire.Samples[i].ErrorReason {
			t.Errorf("ProbeResultPayload.Samples[%d] = %+v, fixture carries %+v — check the json tags",
				i, first.Samples[i], wire.Samples[i])
		}
	}
	if (len(first.Details) == 0) != (len(wire.Details) == 0) {
		t.Errorf("ProbeResultPayload.Details presence = %v, fixture carries %v — check the json tag",
			len(first.Details) > 0, len(wire.Details) > 0)
	}

	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("ProbeResultPayload encode error = %v", err)
	}
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(reencoded, &keys); err != nil {
		t.Fatalf("ProbeResultPayload re-decode as map error = %v", err)
	}
	if _, ok := keys["up"]; !ok {
		t.Errorf("re-encoded ProbeResultPayload %s omits \"up\" — the field may not carry omitempty", reencoded)
	}

	var second ProbeResultPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("ProbeResultPayload re-decode error = %v", err)
	}
	if first.RunID != second.RunID || first.MonitorID != second.MonitorID ||
		first.Outcome != second.Outcome || first.Up != second.Up || first.Msg != second.Msg {
		t.Errorf("ProbeResultPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	if !first.StartedAt.Equal(second.StartedAt) || !first.FinishedAt.Equal(second.FinishedAt) {
		t.Errorf("ProbeResultPayload timestamp round-trip mismatch: got %v/%v, want %v/%v",
			second.StartedAt, second.FinishedAt, first.StartedAt, first.FinishedAt)
	}
	if !reflect.DeepEqual(first.Samples, second.Samples) {
		t.Errorf("ProbeResultPayload.Samples round-trip mismatch: got %+v, want %+v", second.Samples, first.Samples)
	}
	if !reflect.DeepEqual(first.Details, second.Details) {
		t.Errorf("ProbeResultPayload.Details round-trip mismatch: got %#v, want %#v", second.Details, first.Details)
	}
}

// jsonValuesEqual compares two raw JSON documents by decoded value rather than by bytes: the
// corpus is hand-formatted, so re-marshalling reflows whitespace and a byte comparison would
// report a spurious mismatch for any non-scalar value.
func jsonValuesEqual(t *testing.T, a, b json.RawMessage) bool {
	t.Helper()
	var ad, bd any
	if len(a) > 0 {
		if err := json.Unmarshal(a, &ad); err != nil {
			t.Fatalf("decode %s = %v", a, err)
		}
	}
	if len(b) > 0 {
		if err := json.Unmarshal(b, &bd); err != nil {
			t.Fatalf("decode %s = %v", b, err)
		}
	}
	return reflect.DeepEqual(ad, bd)
}

// pendingCorpusTypes are the declared frame types that legitimately have no wire fixture in
// fixtures/agent_frame_corpus.json yet. It is an explicitly shrinking allow-list: every entry
// is a visible, reviewable exemption, and the slice that introduces a type's wire traffic must
// delete its entry in the same commit that adds the fixture.
//
//   - update / uninstall               — server->agent command frames with no structured
//     payload of their own yet; whichever task gives them one adds the fixture.
//
// discovery.request / discovery.cancel / discovery.finding left this list in slice 4, in the same
// commit that added their fixtures.
//
// probe.assign / probe.cancel / probe.result left this list in slice 3, in the same commit that
// added their fixtures. probe.cancel was never on it: a constant declared without a fixture must
// fail this gate on arrival, which is the property the list exists to preserve.
var pendingCorpusTypes = []string{
	TypeUpdate,
	TypeUninstall,
}

// TestCorpus_CoversEveryDeclaredFrameType fails on any declared frame type that is neither
// exercised by the corpus nor named in pendingCorpusTypes.
//
// This Go half is a fast local signal only: allFrameTypes is a hand-maintained mirror of the
// constants, so a constant added without a matching allFrameTypes entry escapes it. The
// authoritative gate is test_corpus_covers_every_declared_frame_type in
// apps/backend/tests/test_agent_frame_conformance.py, which enumerates its module's TYPE_*
// attributes reflectively and asserts set equality.
func TestCorpus_CoversEveryDeclaredFrameType(t *testing.T) {
	inCorpus := map[string]bool{}
	for _, entry := range loadCorpus(t) {
		decoded, err := Decode(entry.JSON)
		if err != nil {
			t.Fatalf("Decode(%q) error = %v", entry.Description, err)
		}
		inCorpus[decoded.Type] = true
	}

	declared := map[string]bool{}
	for i, typ := range allFrameTypes {
		if typ == "" {
			t.Fatalf("allFrameTypes[%d] is empty", i)
		}
		declared[typ] = true
	}

	pending := map[string]bool{}
	for _, typ := range pendingCorpusTypes {
		if !declared[typ] {
			t.Errorf("pendingCorpusTypes entry %q is not a declared frame type — stale or misspelled", typ)
		}
		pending[typ] = true
	}

	for _, typ := range allFrameTypes {
		if !inCorpus[typ] && !pending[typ] {
			t.Errorf("frame type %q has no fixture in fixtures/agent_frame_corpus.json and is not in pendingCorpusTypes", typ)
		}
	}

	for typ := range pending {
		if inCorpus[typ] {
			t.Errorf("frame type %q now has a corpus fixture — remove it from pendingCorpusTypes", typ)
		}
	}
}

func roundTripHostTelemetryPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first HostTelemetryPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("HostTelemetryPayload decode error = %v", err)
	}
	if first.Schema != 1 {
		t.Errorf("Schema = %d, want 1", first.Schema)
	}
	switch first.Status {
	case "healthy", "degraded":
	default:
		t.Errorf("Status = %q, want healthy or degraded", first.Status)
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("HostTelemetryPayload encode error = %v", err)
	}
	var second HostTelemetryPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("HostTelemetryPayload re-decode error = %v", err)
	}
	if first.Schema != second.Schema || first.SampleID != second.SampleID || first.Status != second.Status {
		t.Errorf("HostTelemetryPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	compareHostSummary(t, first.Summary, second.Summary)
	compareItemList(t, "Filesystems", first.Filesystems, second.Filesystems)
	compareItemList(t, "Disks", first.Disks, second.Disks)
	compareItemList(t, "Interfaces", first.Interfaces, second.Interfaces)
	compareItemList(t, "Temperatures", first.Temperatures, second.Temperatures)
	if !reflect.DeepEqual(first.Docker, second.Docker) {
		t.Errorf("HostTelemetryPayload.Docker round-trip mismatch: got %#v, want %#v", second.Docker, first.Docker)
	}
}

// compareHostSummary compares every HostSummary field reflectively rather than by name, so a
// field added to the struct is covered by this test the moment it exists. Each field is checked
// for *both* nilness and value: HostSummary is all-omitempty pointers, where "absent" and "zero"
// are different facts about the host (a missing sensor vs. a reading of 0), and the backend
// distinguishes them (schemas/agent_frame.py types summary as dict[str, int | float]).
func compareHostSummary(t *testing.T, first, second HostSummary) {
	t.Helper()
	fv, sv := reflect.ValueOf(first), reflect.ValueOf(second)
	typ := fv.Type()
	for i := range typ.NumField() {
		name := typ.Field(i).Name
		a, b := fv.Field(i), sv.Field(i)
		if a.Kind() != reflect.Pointer {
			t.Fatalf("HostSummary.%s has kind %s, want a pointer field", name, a.Kind())
		}
		if a.IsNil() != b.IsNil() {
			t.Errorf("HostSummary.%s nilness round-trip mismatch: got nil=%v, want nil=%v", name, b.IsNil(), a.IsNil())
			continue
		}
		if a.IsNil() {
			continue
		}
		if !reflect.DeepEqual(a.Elem().Interface(), b.Elem().Interface()) {
			t.Errorf("HostSummary.%s round-trip mismatch: got %v, want %v", name, b.Elem().Interface(), a.Elem().Interface())
		}
	}
}

func compareItemList(t *testing.T, field string, first, second []map[string]any) {
	t.Helper()
	if len(first) != len(second) {
		t.Errorf("HostTelemetryPayload.%s length round-trip mismatch: got %d, want %d", field, len(second), len(first))
		return
	}
	if len(first) > 0 && !reflect.DeepEqual(first, second) {
		t.Errorf("HostTelemetryPayload.%s round-trip mismatch: got %#v, want %#v", field, second, first)
	}
}

// readinessStates is the exact readiness vocabulary, mirroring
// apps/backend/src/app/services/agent_telemetry.py's ingest_readiness — anything else is an
// InvalidHostTelemetry protocol violation server-side.
var readinessStates = map[string]bool{"ready": true, "degraded": true, "unavailable": true, "disabled": true}

func roundTripCapabilityReadinessPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first CapabilityReadinessPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("CapabilityReadinessPayload decode error = %v", err)
	}
	for i, item := range first.Readiness {
		if item.Collector == "" {
			t.Errorf("Readiness[%d].Collector is empty", i)
		}
		if !readinessStates[item.State] {
			t.Errorf("Readiness[%d].State = %q, want one of ready/degraded/unavailable/disabled", i, item.State)
		}
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("CapabilityReadinessPayload encode error = %v", err)
	}
	var second CapabilityReadinessPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("CapabilityReadinessPayload re-decode error = %v", err)
	}
	if len(first.Readiness) != len(second.Readiness) {
		t.Fatalf("CapabilityReadinessPayload.Readiness length round-trip mismatch: got %d, want %d", len(second.Readiness), len(first.Readiness))
	}
	if len(first.Readiness) > 0 && !reflect.DeepEqual(first.Readiness, second.Readiness) {
		t.Errorf("CapabilityReadinessPayload.Readiness round-trip mismatch: got %+v, want %+v", second.Readiness, first.Readiness)
	}
}

// serverSampleIDRe is the expression the backend enforces at
// apps/backend/src/app/services/agent_telemetry.py's _SAMPLE_ID. A corpus sample_id that does
// not match it would be rejected as InvalidHostTelemetry on arrival.
var serverSampleIDRe = regexp.MustCompile(`^[0-9a-f]{32}$`)

func TestCorpus_HostTelemetrySampleIDMatchesServerRegex(t *testing.T) {
	seen := 0
	for _, entry := range loadCorpus(t) {
		decoded, err := Decode(entry.JSON)
		if err != nil {
			t.Fatalf("Decode(%q) error = %v", entry.Description, err)
		}
		if decoded.Type != TypeTelemetryHost {
			continue
		}
		seen++
		t.Run(entry.Description, func(t *testing.T) {
			var payload HostTelemetryPayload
			if err := json.Unmarshal(decoded.Payload, &payload); err != nil {
				t.Fatalf("HostTelemetryPayload decode error = %v", err)
			}
			if !serverSampleIDRe.MatchString(payload.SampleID) {
				t.Errorf("SampleID = %q, want match for %s", payload.SampleID, serverSampleIDRe)
			}
		})
	}
	if seen == 0 {
		t.Fatal("no telemetry.host corpus entries found")
	}
}

// TestCorpus_HostTelemetrySummaryHasNoNulls pins that no summary value is JSON null: the
// backend types summary as dict[str, int | float]
// (apps/backend/src/app/schemas/agent_frame.py's HostTelemetryPayload), which rejects null. An
// unavailable metric must be *omitted* from the object, never sent as null — which is exactly
// what HostSummary's all-omitempty pointer fields produce.
func TestCorpus_HostTelemetrySummaryHasNoNulls(t *testing.T) {
	seen := 0
	for _, entry := range loadCorpus(t) {
		decoded, err := Decode(entry.JSON)
		if err != nil {
			t.Fatalf("Decode(%q) error = %v", entry.Description, err)
		}
		if decoded.Type != TypeTelemetryHost {
			continue
		}
		seen++
		t.Run(entry.Description, func(t *testing.T) {
			var payload struct {
				Summary map[string]json.RawMessage `json:"summary"`
			}
			if err := json.Unmarshal(decoded.Payload, &payload); err != nil {
				t.Fatalf("summary decode error = %v", err)
			}
			if len(payload.Summary) == 0 {
				t.Fatal("summary is empty")
			}
			for key, value := range payload.Summary {
				var number float64
				if err := json.Unmarshal(value, &number); err != nil {
					t.Errorf("summary[%q] = %s, want a JSON number (never null)", key, value)
				}
			}
		})
	}
	if seen == 0 {
		t.Fatal("no telemetry.host corpus entries found")
	}
}

// grantExpectation is the expected post-ApplyGrants state of a capability.Gate for one corpus
// entry carrying a grant object. hostConfig is nil when Gate.HostConfig() must report !ok.
// faults names the capabilities ApplyGrants must report as GrantFaults (D-6) — empty for a
// payload the decoder can honor verbatim.
type grantExpectation struct {
	allowed    map[string]bool
	hostConfig *capability.HostConfig
	faults     []string
}

// corpusGrantExpectations is keyed by corpus entry description (the corpus is append-only, so
// descriptions are stable identifiers). Every corpus entry that carries a grant object must
// have an entry here — TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate fails on a missing
// one, so a new grant fixture cannot be added without stating what the real decoder should make
// of it.
var corpusGrantExpectations = map[string]grantExpectation{
	"capabilities.set — mixed grants": {
		allowed:    map[string]bool{"host_telemetry": true, "remote_probe": false, "local_discovery": false},
		hostConfig: &capability.HostConfig{IntervalS: 30, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: true},
	},
	"hello.ack — link establishment, accepted with authoritative grants": {
		allowed:    map[string]bool{"host_telemetry": true, "remote_probe": false, "local_discovery": false},
		hostConfig: &capability.HostConfig{IntervalS: 30, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: true},
	},
	"hello.ack — structured {enabled, config} grants for a schema-2 agent": {
		allowed:    map[string]bool{"host_telemetry": true, "remote_probe": false, "local_discovery": false},
		hostConfig: &capability.HostConfig{IntervalS: 60, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: false, IncludeVirtual: false, IncludeDocker: true},
	},
	"capabilities.set — structured grants with host_telemetry config": {
		allowed:    map[string]bool{"host_telemetry": true, "remote_probe": true, "local_discovery": false},
		hostConfig: &capability.HostConfig{IntervalS: 15, IncludeFilesystems: true, IncludeDisks: false, IncludeNetwork: true, IncludeTemperatures: true, IncludeVirtual: true, IncludeDocker: true},
	},
	// The mixed entry pins capability.decode's per-key fallback: remote_probe/local_discovery
	// arrive as bare booleans while host_telemetry arrives as a {enabled, config} object whose
	// config names only two of the seven keys — the rest must come from DefaultHostConfig.
	"capabilities.set — mixed legacy boolean and structured grants": {
		allowed:    map[string]bool{"host_telemetry": true, "remote_probe": false, "local_discovery": true},
		hostConfig: &capability.HostConfig{IntervalS: 120, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: true, IncludeVirtual: false, IncludeDocker: true},
	},
	// D-6 on the wire: host_telemetry.interval_s is below capability.MinHostInterval, so that
	// one capability faults — it keeps the server's enabled flag and falls back to the package
	// default config (this gate has no prior valid config to retain) — while remote_probe in
	// the same frame still applies. Before Task 12 the whole payload was rejected and neither
	// capability landed.
	"capabilities.set — invalid host_telemetry interval alongside a valid remote_probe grant": {
		allowed:    map[string]bool{"host_telemetry": true, "remote_probe": true},
		hostConfig: &capability.HostConfig{IntervalS: 30, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: true},
		faults:     []string{"host_telemetry"},
	},
}

// TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate feeds every corpus grant object through
// the real internal/capability decoder rather than a test-local copy, so the corpus exercises
// production behavior: bare-boolean and structured grants, per-key config fallback, and the
// resulting Allowed()/HostConfig() state an agent would actually run with.
func TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate(t *testing.T) {
	checked := map[string]bool{}
	for _, entry := range loadCorpus(t) {
		decoded, err := Decode(entry.JSON)
		if err != nil {
			t.Fatalf("Decode(%q) error = %v", entry.Description, err)
		}
		var grants json.RawMessage
		switch decoded.Type {
		case TypeCapabilitiesSet:
			grants = decoded.Payload
		case TypeHelloAck:
			var ack struct {
				Capabilities json.RawMessage `json:"capabilities"`
			}
			if err := json.Unmarshal(decoded.Payload, &ack); err != nil {
				t.Fatalf("hello.ack decode error = %v", err)
			}
			if len(ack.Capabilities) == 0 {
				continue
			}
			grants = ack.Capabilities
		default:
			continue
		}

		t.Run(entry.Description, func(t *testing.T) {
			want, ok := corpusGrantExpectations[entry.Description]
			if !ok {
				t.Fatalf("corpus entry carries grants but has no corpusGrantExpectations entry — add one")
			}
			checked[entry.Description] = true

			gate := capability.New(t.TempDir())
			faults, err := gate.ApplyGrants(grants)
			if err != nil {
				t.Fatalf("ApplyGrants() error = %v", err)
			}
			gotFaults := make([]string, 0, len(faults))
			for _, f := range faults {
				gotFaults = append(gotFaults, f.Capability)
				if f.Reason == "" {
					t.Errorf("GrantFault for %q has an empty Reason", f.Capability)
				}
			}
			if !reflect.DeepEqual(gotFaults, want.faults) && !(len(gotFaults) == 0 && len(want.faults) == 0) {
				t.Errorf("ApplyGrants() faults = %v, want %v", gotFaults, want.faults)
			}
			for name, allowed := range want.allowed {
				if got := gate.Allowed(name); got != allowed {
					t.Errorf("Allowed(%q) = %v, want %v", name, got, allowed)
				}
			}
			cfg, cfgOK := gate.HostConfig()
			if (want.hostConfig != nil) != cfgOK {
				t.Fatalf("HostConfig() ok = %v, want %v", cfgOK, want.hostConfig != nil)
			}
			if want.hostConfig != nil && cfg != *want.hostConfig {
				t.Errorf("HostConfig() = %+v, want %+v", cfg, *want.hostConfig)
			}
		})
	}
	for description := range corpusGrantExpectations {
		if !checked[description] {
			t.Errorf("corpusGrantExpectations entry %q matches no corpus entry — stale or misspelled", description)
		}
	}
}

// TestHelloPayload_AbsentCapabilitySchemaDecodesToZeroAndMeansLegacy documents a deliberate
// cross-language asymmetry: Go's zero value for the absent `capability_schema` field is 0, while
// apps/backend/src/app/schemas/agent_frame.py's HelloPayload declares
// `capability_schema: int = 1` (pinned there by test_hello_absent_capability_schema_defaults_to_legacy).
// Both mean the same thing — "this agent predates capability schema 2" — so every consumer of
// the decoded value must treat 0 and 1 identically as legacy, exactly as
// apps/backend/src/app/api/ws_agents.py's _wire_grants does with its `>= 2` test. Do not
// "fix" this by defaulting Go to 1: the zero value is what an absent field decodes to, and
// making that indistinguishable from an explicit 1 would hide a schema downgrade.
func TestHelloPayload_AbsentCapabilitySchemaDecodesToZeroAndMeansLegacy(t *testing.T) {
	var absent HelloPayload
	if err := json.Unmarshal([]byte(`{}`), &absent); err != nil {
		t.Fatalf("HelloPayload decode error = %v", err)
	}
	if absent.CapabilitySchema != 0 {
		t.Errorf("CapabilitySchema = %d, want 0 for an absent field", absent.CapabilitySchema)
	}
	if absent.CapabilitySchema >= 2 {
		t.Error("an absent capability_schema must not be treated as schema 2 or later")
	}

	var present HelloPayload
	if err := json.Unmarshal([]byte(`{"capability_schema": 2}`), &present); err != nil {
		t.Fatalf("HelloPayload decode error = %v", err)
	}
	if present.CapabilitySchema != 2 {
		t.Errorf("CapabilitySchema = %d, want 2", present.CapabilitySchema)
	}
}

// rawJSONMapsEqual compares two json.RawMessage maps by decoded *value*, not by raw bytes: a
// grant object that arrives pretty-printed in the corpus re-marshals compact, so a byte
// comparison would report a spurious mismatch for any non-scalar capability value.
func rawJSONMapsEqual(t *testing.T, a, b map[string]json.RawMessage) bool {
	t.Helper()
	if len(a) != len(b) {
		return false
	}
	for key, av := range a {
		bv, ok := b[key]
		if !ok {
			return false
		}
		var ad, bd any
		if err := json.Unmarshal(av, &ad); err != nil {
			t.Fatalf("decode capabilities[%q] = %v", key, err)
		}
		if err := json.Unmarshal(bv, &bd); err != nil {
			t.Fatalf("re-decode capabilities[%q] = %v", key, err)
		}
		if !reflect.DeepEqual(ad, bd) {
			return false
		}
	}
	return true
}

func rawJSONMapString(m map[string]json.RawMessage) string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = string(v)
	}
	return fmt.Sprintf("%v", out)
}

// discoveryKinds and discoveryOutcomes are the closed vocabularies from plan §4. Listing them
// here rather than reaching for the constants is deliberate: the point is to catch a *renamed*
// constant, which a test that reads the constant cannot do.
var discoveryKinds = map[string]bool{"host": true, "summary": true}

var discoveryOutcomes = map[string]bool{
	"completed": true, "execution_error": true, "cancelled": true, "rejected": true,
}

func roundTripDiscoveryRequestPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first DiscoveryRequestPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("DiscoveryRequestPayload decode error = %v", err)
	}
	if len(first.DispatchID) != 32 {
		t.Errorf("DispatchID = %q, want exactly 32 hex characters", first.DispatchID)
	}
	if first.ScanJobID == 0 {
		t.Error("ScanJobID is zero — a request always names the job it belongs to")
	}
	// The version is what lets the agent refuse a request whose authorization has moved since it
	// was built (plan §2). A request without one cannot be checked at all.
	if first.ScopeVersion == "" {
		t.Error("ScopeVersion is empty — the agent could not detect an incompatible scope change")
	}
	if first.DeadlineAt.IsZero() {
		t.Error("DeadlineAt is zero — an undeadlined scan cannot be expired")
	}
	if len(first.Targets) > MaxDiscoveryTargets || len(first.TCPPorts) > MaxDiscoveryPorts {
		t.Errorf("fixture exceeds the plan §4 bounds: %d targets, %d ports",
			len(first.Targets), len(first.TCPPorts))
	}

	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("DiscoveryRequestPayload encode error = %v", err)
	}
	var second DiscoveryRequestPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("DiscoveryRequestPayload re-decode error = %v", err)
	}
	// Compared field-wise rather than with DeepEqual: `omitempty` drops a present-but-empty JSON
	// array on re-encode, so `"tcp_ports": []` decodes to a non-nil empty slice and comes back
	// nil. Both mean "do not port-scan", which is the same instruction — the same reason
	// HelloPayload.PrimaryMACs is compared this way.
	if first.DispatchID != second.DispatchID || first.ScanJobID != second.ScanJobID ||
		first.HostTimeoutMS != second.HostTimeoutMS ||
		first.MaxConcurrentHosts != second.MaxConcurrentHosts ||
		first.ScopeVersion != second.ScopeVersion || !first.DeadlineAt.Equal(second.DeadlineAt) {
		t.Errorf("DiscoveryRequestPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	if !slicesEqualIgnoringNil(first.Targets, second.Targets) ||
		!slicesEqualIgnoringNil(first.Methods, second.Methods) {
		t.Errorf("DiscoveryRequestPayload list round-trip mismatch: got %+v, want %+v", second, first)
	}
	if len(first.TCPPorts) != len(second.TCPPorts) {
		t.Errorf("TCPPorts round-trip mismatch: got %v, want %v", second.TCPPorts, first.TCPPorts)
	}
	for i := range first.TCPPorts {
		if first.TCPPorts[i] != second.TCPPorts[i] {
			t.Errorf("TCPPorts[%d] = %d, want %d", i, second.TCPPorts[i], first.TCPPorts[i])
		}
	}
}

func roundTripDiscoveryCancelPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first DiscoveryCancelPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("DiscoveryCancelPayload decode error = %v", err)
	}
	if len(first.DispatchID) != 32 {
		t.Errorf("DispatchID = %q, want exactly 32 hex characters", first.DispatchID)
	}
	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("DiscoveryCancelPayload encode error = %v", err)
	}
	var second DiscoveryCancelPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("DiscoveryCancelPayload re-decode error = %v", err)
	}
	if first != second {
		t.Errorf("DiscoveryCancelPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
}

func roundTripDiscoveryFindingPayload(t *testing.T, raw json.RawMessage) {
	t.Helper()
	var first DiscoveryFindingPayload
	if err := json.Unmarshal(raw, &first); err != nil {
		t.Fatalf("DiscoveryFindingPayload decode error = %v", err)
	}
	if len(first.DispatchID) != 32 {
		t.Errorf("DispatchID = %q, want exactly 32 hex characters", first.DispatchID)
	}
	// Without a finding id there is no idempotency key, so a spooled batch replayed after an
	// outage would double every result it carries.
	if first.FindingID == "" || len(first.FindingID) > 64 {
		t.Errorf("FindingID = %q, want 1-64 characters (the width of its String(64) column)",
			first.FindingID)
	}
	if !discoveryKinds[first.Kind] {
		t.Errorf("Kind = %q, not in the closed vocabulary", first.Kind)
	}
	if first.Kind == DiscoveryKindSummary {
		if !first.Terminal {
			t.Error("a summary must be terminal — it is the frame that closes the dispatch")
		}
		if !discoveryOutcomes[first.Outcome] {
			t.Errorf("summary Outcome = %q, not in the closed vocabulary", first.Outcome)
		}
	} else if first.IPAddress == "" {
		t.Error("a host finding with no address describes nothing")
	}
	if len(first.OpenPorts) > MaxDiscoveryOpenPorts || len(first.Evidence) > MaxDiscoveryEvidence {
		t.Errorf("fixture exceeds the plan §4 bounds: %d ports, %d evidence entries",
			len(first.OpenPorts), len(first.Evidence))
	}
	for _, port := range first.OpenPorts {
		if len([]rune(port.Banner)) > MaxDiscoveryBannerRune {
			t.Errorf("banner on port %d exceeds %d runes", port.Port, MaxDiscoveryBannerRune)
		}
	}

	reencoded, err := json.Marshal(first)
	if err != nil {
		t.Fatalf("DiscoveryFindingPayload encode error = %v", err)
	}
	var second DiscoveryFindingPayload
	if err := json.Unmarshal(reencoded, &second); err != nil {
		t.Fatalf("DiscoveryFindingPayload re-decode error = %v", err)
	}
	if first.DispatchID != second.DispatchID || first.ScanJobID != second.ScanJobID ||
		first.FindingID != second.FindingID || first.Kind != second.Kind ||
		!first.ObservedAt.Equal(second.ObservedAt) || first.IPAddress != second.IPAddress ||
		first.MACAddress != second.MACAddress || first.Hostname != second.Hostname ||
		first.Terminal != second.Terminal || first.Outcome != second.Outcome ||
		first.Msg != second.Msg || first.ErrorCode != second.ErrorCode {
		t.Errorf("DiscoveryFindingPayload round-trip mismatch: got %+v, want %+v", second, first)
	}
	if !slicesEqualIgnoringNil(first.Evidence, second.Evidence) {
		t.Errorf("Evidence round-trip mismatch: got %v, want %v", second.Evidence, first.Evidence)
	}
	if !reflect.DeepEqual(first.OpenPorts, second.OpenPorts) &&
		!(len(first.OpenPorts) == 0 && len(second.OpenPorts) == 0) {
		t.Errorf("OpenPorts round-trip mismatch: got %+v, want %+v", second.OpenPorts, first.OpenPorts)
	}
	// The two counts are pointers precisely so "0 hosts found" is distinguishable from "this is
	// not a summary"; a value type would make an execution_error summary indistinguishable from a
	// host finding on the server side.
	if !intPtrEqual(first.HostsFound, second.HostsFound) ||
		!intPtrEqual(first.AddressesScanned, second.AddressesScanned) {
		t.Errorf("summary counts round-trip mismatch: got %+v, want %+v", second, first)
	}
}

func intPtrEqual(a, b *int) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

// TestCorpus_DiscoveryFindingCarriesTerminalFalseExplicitly pins the one field whose Go zero
// value is a legitimate observation. Terminal must not gain an `omitempty`: every host finding
// sends false, and dropping the key would leave the server reading an absent field as its own
// default — the same trap ProbeResultPayload.Up documents.
func TestCorpus_DiscoveryFindingCarriesTerminalFalseExplicitly(t *testing.T) {
	encoded, err := json.Marshal(DiscoveryFindingPayload{
		DispatchID: "7c2e5a91b4d3406f8a1e9c7d05b2f36a",
		FindingID:  "abcd",
		Kind:       DiscoveryKindHost,
		IPAddress:  "10.0.0.9",
	})
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(encoded, &fields); err != nil {
		t.Fatal(err)
	}
	if _, ok := fields["terminal"]; !ok {
		t.Error("terminal was dropped from the encoded payload — it must carry no omitempty")
	}
}

// TestCorpus_ReadinessNetworksSurviveAnEmptyList is D-8's load-bearing half: an agent that has
// lost every interface must be able to say so. With `omitempty` the empty list would vanish and
// the server would keep standing on a stale, wider-than-reality scope forever.
func TestCorpus_ReadinessNetworksSurviveAnEmptyList(t *testing.T) {
	encoded, err := json.Marshal(CapabilityReadinessPayload{Networks: []NetworkFacts{}})
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(encoded, &fields); err != nil {
		t.Fatal(err)
	}
	if _, ok := fields["networks"]; !ok {
		t.Error("networks was dropped from the encoded payload — it must carry no omitempty")
	}
}

// TestCorpus_NetworkFactsCarryNothingButNameFlagsAndAddrs is D-8's other half, and it is a
// privacy guard rather than a wire-shape one.
//
// `networks` is the only structured host inventory the agent volunteers on a *periodic* frame, so
// it is the field a future contributor will reach for when the UI wants "just one more thing"
// about an interface. Plan §6 draws the line: no routing-table secrets, no Wi-Fi SSIDs, no DNS
// search domains, no interface counters — none of which any capability requires today. Nothing
// else in the suite would fail if one of them were added, because an additive field round-trips
// perfectly and every existing corpus entry keeps passing.
//
// The assertion walks the struct type rather than a marshalled instance on purpose: a new field
// tagged `omitempty` and left at its zero value would be invisible in the encoded key set, and
// that is exactly how such a field gets added.
func TestCorpus_NetworkFactsCarryNothingButNameFlagsAndAddrs(t *testing.T) {
	want := []string{"name", "flags", "addrs"}

	typ := reflect.TypeOf(NetworkFacts{})
	got := make([]string, 0, typ.NumField())
	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i)
		name, _, _ := strings.Cut(field.Tag.Get("json"), ",")
		if name == "" {
			// An untagged exported field still marshals, under its Go name.
			name = field.Name
		}
		got = append(got, name)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("NetworkFacts marshals %v, want exactly %v — plan §6 forbids reporting routing "+
			"tables, SSIDs, DNS search domains and interface counters on this frame", got, want)
	}

	// And the encoding really does say those names: a tag typo would satisfy the walk above while
	// putting a key on the wire that record_network_facts cannot read.
	encoded, err := json.Marshal(NetworkFacts{
		Name:  "eth0",
		Flags: []string{"up", "broadcast"},
		Addrs: []string{"10.20.0.5/24"},
	})
	if err != nil {
		t.Fatal(err)
	}
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(encoded, &keys); err != nil {
		t.Fatal(err)
	}
	if len(keys) != len(want) {
		t.Fatalf("encoded NetworkFacts %s has %d keys, want exactly %v", encoded, len(keys), want)
	}
	for _, name := range want {
		if _, ok := keys[name]; !ok {
			t.Errorf("encoded NetworkFacts %s omits %q — check the json tag", encoded, name)
		}
	}
}

// TestCorpus_CapabilityViolationReasonsAreTheEvaluatorsOwn consumes the corpus's
// capability.violation fixtures from the Go side.
//
// This package declares TypeCapabilityViolation but no payload struct for it, and inventing one
// here would mirror nothing: the only emitter is probe.Runtime.emitCapabilityViolation, which
// marshals an anonymous {frame_type, reason} pair whose reason is netscope's own Decision.Reason.
// So the cross-language contract worth pinning is not a round-trip — it is that the bytes both
// languages read carry only reasons this agent's evaluator can actually produce.
// apps/backend/src/app/schemas/agent_frame.py's CAPABILITY_VIOLATION_REASONS is a closed
// vocabulary and agent_link._handle_capability_violation drops anything outside it with no write,
// so a fixture naming free prose is not a lenient fixture: it is a frame the server receives and
// never records, which is the one signal that the backend is dispatching out-of-scope work.
func TestCorpus_CapabilityViolationReasonsAreTheEvaluatorsOwn(t *testing.T) {
	// Every netscope reason that can describe a refusal. Two are deliberately absent, mirroring
	// the backend frozenset: ReasonInScope is an acceptance and can never describe one, and
	// ReasonUnresolvedHostname is a name that resolved to nothing, which the runtime reports as
	// an execution error and explicitly does not raise a violation for.
	refusals := map[string]bool{
		netscope.ReasonSpecialUse:           true,
		netscope.ReasonExcluded:             true,
		netscope.ReasonEmptyScope:           true,
		netscope.ReasonOutOfScope:           true,
		netscope.ReasonInvalidDestination:   true,
		netscope.ReasonPrefixTooWide:        true,
		netscope.ReasonNotDirectlyConnected: true,
	}
	declared := map[string]bool{}
	for _, typ := range allFrameTypes {
		declared[typ] = true
	}

	seen := map[string]bool{}
	for _, entry := range loadCorpus(t) {
		decoded, err := Decode(entry.JSON)
		if err != nil {
			t.Fatalf("Decode(%q) error = %v", entry.Description, err)
		}
		if decoded.Type != TypeCapabilityViolation {
			continue
		}
		// The exact shape emitCapabilityViolation encodes. The fixtures' optional address and
		// detail keys are ignored here on purpose: no agent code path reads them back, and the
		// backend model is where their bounds live.
		var payload struct {
			FrameType string `json:"frame_type"`
			Reason    string `json:"reason"`
		}
		if err := json.Unmarshal(decoded.Payload, &payload); err != nil {
			t.Fatalf("%q: decode capability.violation payload: %v", entry.Description, err)
		}
		if !refusals[payload.Reason] {
			t.Errorf("%q: reason %q is not one of netscope's refusal reasons — the backend's "+
				"closed vocabulary drops it and writes no audit row", entry.Description, payload.Reason)
		}
		// An absent frame_type is a real shape: the reason is the security signal. A *present*
		// one must name a frame this protocol declares, or it is prose being smuggled into an
		// audit row.
		if payload.FrameType != "" && !declared[payload.FrameType] {
			t.Errorf("%q: frame_type %q is not a declared frame type", entry.Description, payload.FrameType)
		}
		seen[payload.Reason] = true
	}

	if len(seen) == 0 {
		t.Fatal("the corpus carries no capability.violation fixture")
	}
	for reason := range refusals {
		if !seen[reason] {
			t.Errorf("no corpus fixture reports %q — test_capability_violation_payloads_survive_"+
				"the_typed_model_by_name asserts set equality over the same vocabulary, so the "+
				"backend half fails on the same gap", reason)
		}
	}
}
