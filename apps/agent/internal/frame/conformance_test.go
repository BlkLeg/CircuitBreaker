package frame

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/capability"
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

// pendingCorpusTypes are the declared frame types that legitimately have no wire fixture in
// fixtures/agent_frame_corpus.json yet. It is an explicitly shrinking allow-list: every entry
// is a visible, reviewable exemption, and the slice that introduces a type's wire traffic must
// delete its entry in the same commit that adds the fixture.
//
//   - probe.assign / probe.result      — removed by slice 3 (remote probe).
//     Slice 3 also introduces `probe.cancel`, which is deliberately NOT pre-exempted here: a
//     new constant must ship with a fixture or fail this gate.
//   - discovery.request / discovery.finding — removed by slice 4 (local discovery).
//   - update / uninstall               — server->agent command frames with no structured
//     payload of their own yet; whichever task gives them one adds the fixture.
var pendingCorpusTypes = []string{
	TypeProbeAssign,
	TypeProbeResult,
	TypeDiscoveryRequest,
	TypeDiscoveryFinding,
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
