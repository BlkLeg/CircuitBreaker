package frame

import (
	"encoding/json"
	"fmt"
	"time"
)

// FrameVersion is the only wire protocol version this package's encoder/decoder
// currently understands, mirroring apps/backend/src/app/schemas/agent_frame.py's
// FRAME_VERSION. Receivers on both sides reject a decoded Frame whose V differs
// from this as an unsupported-version frame (see internal/link's inbound sequence
// guard and agent_link.py's receive_frame).
const FrameVersion = 1

// Frame is the wire envelope for every agent<->server message, nested inside
// the Noise-encrypted channel. v1 — see specs/2026-07-26-cb-agent-design.md §3.4.
type Frame struct {
	V       int             `json:"v"`
	Type    string          `json:"type"`
	Seq     uint64          `json:"seq"`
	TS      time.Time       `json:"ts"`
	Payload json.RawMessage `json:"payload"`
}

func Encode(f Frame) ([]byte, error) {
	data, err := json.Marshal(f)
	if err != nil {
		return nil, fmt.Errorf("frame: encode: %w", err)
	}
	return data, nil
}

func Decode(data []byte) (Frame, error) {
	var f Frame
	if err := json.Unmarshal(data, &f); err != nil {
		return Frame{}, fmt.Errorf("frame: decode: %w", err)
	}
	return f, nil
}

// Frame type constants — agent -> server.
const (
	TypeHello               = "hello"
	TypeHeartbeat           = "heartbeat"
	TypeTelemetryHost       = "telemetry.host"
	TypeProbeResult         = "probe.result"
	TypeDiscoveryFinding    = "discovery.finding"
	TypeCapabilityViolation = "capability.violation"
	TypeCapabilityReadiness = "capability.readiness"
	TypeLog                 = "log"
	TypeUninstall           = "uninstall"
	// TypeUpdateStatus reports one self-update transition point the server
	// can't otherwise observe (download-start, swap-success, failure,
	// rollback — queue-time is already server-side). Additive-only
	// protocol-v1 addition (Task 24), mirroring
	// apps/backend/src/app/schemas/agent_frame.py's TYPE_UPDATE_STATUS.
	TypeUpdateStatus = "update.status"
)

// Frame type constants — server -> agent.
const (
	TypeHelloAck         = "hello.ack"
	TypeCapabilitiesSet  = "capabilities.set"
	TypeProbeAssign      = "probe.assign"
	TypeDiscoveryRequest = "discovery.request"
	TypeKeyRotate        = "key.rotate"
	TypeUpdate           = "update"
	TypeDisconnect       = "disconnect"
	TypePing             = "ping"
)

// Frame type constants — bidirectional (either side may send it about its own cipher).
const (
	TypeTransportRekey = "transport.rekey"
)

// allFrameTypes lists every frame type constant declared above. Go cannot
// enumerate untyped string constants at runtime, so this slice is the manual
// mirror that TestCorpus_CoversEveryDeclaredFrameType iterates: adding a
// constant above without adding it here is the one way to escape the Go half
// of the corpus coverage gate. That is why the Go half is only a fast local
// signal — apps/backend/tests/test_agent_frame_conformance.py enumerates its
// module's TYPE_* attributes reflectively and is the authoritative gate.
var allFrameTypes = []string{
	TypeHello,
	TypeHeartbeat,
	TypeTelemetryHost,
	TypeProbeResult,
	TypeDiscoveryFinding,
	TypeCapabilityViolation,
	TypeCapabilityReadiness,
	TypeLog,
	TypeUninstall,
	TypeUpdateStatus,
	TypeHelloAck,
	TypeCapabilitiesSet,
	TypeProbeAssign,
	TypeDiscoveryRequest,
	TypeKeyRotate,
	TypeUpdate,
	TypeDisconnect,
	TypePing,
	TypeTransportRekey,
}

// controlFrameTypes are the frame types that must never reach the outbound
// spool (internal/spool): link-protocol control traffic, plus the heartbeat
// liveness signal, none of which is host data the spool exists to buffer
// through an outage (spec §4.4). This is deliberately a deny-list rather than
// an allow-list of known data types: every type not named here — including
// telemetry/probe/discovery/log payloads Slice 2+ has not introduced yet —
// classifies as a data frame, so internal/link's spool wiring needs no code
// change to pick up a future slice's new data frame type (Global
// Constraints: "wire the mechanism ... so it activates automatically once
// Slice 2+ introduces data frames").
var controlFrameTypes = map[string]bool{
	TypeHello:               true,
	TypeHeartbeat:           true,
	TypeCapabilityReadiness: true,
	TypeUninstall:           true,
	TypeHelloAck:            true,
	TypeCapabilitiesSet:     true,
	TypeProbeAssign:         true,
	TypeDiscoveryRequest:    true,
	TypeKeyRotate:           true,
	TypeUpdate:              true,
	TypeDisconnect:          true,
	TypePing:                true,
	TypeTransportRekey:      true,
}

// IsDataFrame reports whether typ is a data frame eligible for the outbound
// spool, as opposed to heartbeat/control traffic which must never reach the
// spool's write path. See controlFrameTypes' doc comment for why this is a
// deny-list.
func IsDataFrame(typ string) bool {
	return !controlFrameTypes[typ]
}

// Payload shapes below are the structured wire format for a subset of frame types. They are
// schema/codec only: nothing in this package parses Frame.Payload into these types
// automatically, and no rekey/rotation *behavior* lives here (see Frame.Payload's callers in
// internal/link and internal/enroll, and the corresponding backend handlers). Callers that want
// the typed form decode Frame.Payload into these structs themselves; the conformance corpus in
// conformance_test.go pins their wire shape against apps/backend/src/app/schemas/agent_frame.py.

// Readiness reports one collector's ability to run, carried in HelloPayload.Readiness and in
// CapabilityReadinessPayload.Readiness — see specs/2026-07-26-cb-agent-design.md §4.3.
//
// State is exactly one of ready | degraded | unavailable | disabled. That set is closed:
// apps/backend/src/app/services/agent_telemetry.py's ingest_readiness is authoritative and rejects
// anything else as a protocol violation.
type Readiness struct {
	Collector   string   `json:"collector"`
	State       string   `json:"state"` // ready | degraded | unavailable | disabled
	Reason      string   `json:"reason,omitempty"`
	Remediation string   `json:"remediation,omitempty"`
	Missing     []string `json:"missing,omitempty"`
}

type CapabilityGrant struct {
	Enabled bool            `json:"enabled"`
	Config  json.RawMessage `json:"config,omitempty"`
}

// HelloPayload is the agent -> server `hello` payload's structured shape
// (specs/2026-07-26-cb-agent-design.md §3.4, §4.3, §4.6). Every field is optional so an
// old-shaped hello — including today's empty `{}` payload — still decodes: absent fields take
// their Go zero value rather than failing decode.
type HelloPayload struct {
	DevicePK         string      `json:"device_pk,omitempty"`
	Hostname         string      `json:"hostname,omitempty"`
	MachineIDHash    string      `json:"machine_id_hash,omitempty"`
	OS               string      `json:"os,omitempty"`
	OSVersion        string      `json:"os_version,omitempty"`
	Arch             string      `json:"arch,omitempty"`
	AgentVersion     string      `json:"agent_version,omitempty"`
	PrimaryMACs      []string    `json:"primary_macs,omitempty"`
	Readiness        []Readiness `json:"readiness,omitempty"`
	SpoolDepth       int         `json:"spool_depth,omitempty"`
	CapabilitySchema int         `json:"capability_schema,omitempty"`
}

// HelloAckPayload is the server -> agent `hello.ack` payload's structured shape for the
// post-enrollment link-establishment handshake (specs/2026-07-26-cb-agent-design.md §4.2: the
// server "re-sends the authoritative set on every hello.ack"). The enrollment socket
// (WS /api/agents/enroll) also emits `hello.ack` frames for pairing-code/status messages with a
// different, untyped payload shape (see ws_agents.py's `_ack_bytes`); this struct models only
// the link ack. All fields are optional/zero-valued when absent.
type HelloAckPayload struct {
	Accepted     bool                       `json:"accepted,omitempty"`
	Reason       string                     `json:"reason,omitempty"`
	ServerTime   *time.Time                 `json:"server_time,omitempty"`
	Capabilities map[string]json.RawMessage `json:"capabilities,omitempty"`
	AgentID      int64                      `json:"agent_id,omitempty"`
}

type CapabilityReadinessPayload struct {
	Readiness []Readiness `json:"readiness"`
}

// HeartbeatPayload is the agent -> server `heartbeat` payload (D-12),
// mirroring apps/backend/src/app/schemas/agent_frame.py's HeartbeatPayload.
// It reports the live outbound-spool backlog so the server — and the Agent
// Detail catch-up indicator — can see a drain in progress and see it finish,
// without waiting for a reconnect to refresh hello's at-connect snapshot.
//
// Additive by design: an older server ignores the unknown keys, and an older
// agent sends `{}`, which still validates on the server side (both fields
// are optional-with-default there).
//
// Neither field carries `omitempty`, and that is load-bearing rather than an
// oversight. A current agent must emit `{"spool_depth":0,"spool_bytes":0}`
// once its backlog clears, or the server's columns stay pinned at the last
// non-zero value and the indicator never clears. With `omitempty`, an empty
// spool and an agent that predates this struct would both send `{}` — making
// "clear the indicator" and "never invent a 0 for an old agent" mutually
// exclusive. The empty payload is therefore reserved to mean exactly one
// thing: this agent does not report spool state.
//
// HelloPayload.SpoolDepth keeps its `omitempty` for the opposite reason:
// hello is the at-connect snapshot, and the heartbeat is what clears the
// indicator.
type HeartbeatPayload struct {
	SpoolDepth int   `json:"spool_depth"`
	SpoolBytes int64 `json:"spool_bytes"`
}

type HostSummary struct {
	CPUPct            *float64 `json:"cpu_pct,omitempty"`
	Load1             *float64 `json:"load_1,omitempty"`
	Load5             *float64 `json:"load_5,omitempty"`
	Load15            *float64 `json:"load_15,omitempty"`
	LogicalCPUs       *int     `json:"logical_cpus,omitempty"`
	MemTotalBytes     *uint64  `json:"mem_total_bytes,omitempty"`
	MemUsedBytes      *uint64  `json:"mem_used_bytes,omitempty"`
	MemAvailableBytes *uint64  `json:"mem_available_bytes,omitempty"`
	MemPct            *float64 `json:"mem_pct,omitempty"`
	SwapTotalBytes    *uint64  `json:"swap_total_bytes,omitempty"`
	SwapUsedBytes     *uint64  `json:"swap_used_bytes,omitempty"`
	SwapPct           *float64 `json:"swap_pct,omitempty"`
	RootDiskPct       *float64 `json:"root_disk_pct,omitempty"`
	NetRXBPS          *float64 `json:"net_rx_bps,omitempty"`
	NetTXBPS          *float64 `json:"net_tx_bps,omitempty"`
	MaxTempC          *float64 `json:"max_temp_c,omitempty"`
	UptimeS           *float64 `json:"uptime_s,omitempty"`
	BootTimeUnixS     *uint64  `json:"boot_time_unix_s,omitempty"`
}

type HostTelemetryPayload struct {
	Schema       int              `json:"schema"`
	SampleID     string           `json:"sample_id"`
	Status       string           `json:"status"`
	Summary      HostSummary      `json:"summary"`
	Filesystems  []map[string]any `json:"filesystems"`
	Disks        []map[string]any `json:"disks"`
	Interfaces   []map[string]any `json:"interfaces"`
	Temperatures []map[string]any `json:"temperatures"`
	Docker       any              `json:"docker"`
}

// TransportRekeyPayload announces a Noise cipher rekey for one direction of the link.
// Direction is relative to the sender: "outbound" is the sender's send cipher, "inbound" is
// its receive cipher. Generation is a per-direction, per-session counter the sender increments
// each rekey, letting the receiver tell rekey announcements apart. Generations are strictly
// sequential from 1 per direction per connection. internal/link drives the 15-minute timing and
// the cipher swap; app/api/ws_agents.py does the same for the server->agent direction.
type TransportRekeyPayload struct {
	Direction  string `json:"direction"` // "inbound" | "outbound"
	Generation uint64 `json:"generation"`
}

// UpdateStatusPayload is the agent -> server `update.status` payload's
// structured shape (Task 24), mirroring
// apps/backend/src/app/schemas/agent_frame.py's UpdateStatusPayload. Phase is
// one of "started"/"succeeded"/"failed"/"rolled_back"; Error is only ever set
// alongside "failed".
type UpdateStatusPayload struct {
	Version string `json:"version"`
	Phase   string `json:"phase"` // "started" | "succeeded" | "failed" | "rolled_back"
	Error   string `json:"error,omitempty"`
}

// KeyRotatePayload carries a pending device-key or server-key rotation: the kind of key being
// rotated, the successor public key material, and when the rotation must complete by. This is
// schema only — Tasks 27/28 wire the rotation state machine.
type KeyRotatePayload struct {
	Kind        string    `json:"kind"` // "device" | "server"
	SuccessorPK string    `json:"successor_pk"`
	Expiry      time.Time `json:"expiry"`
}
