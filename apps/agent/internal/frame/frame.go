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
	TypeProbeCancel      = "probe.cancel"
	TypeDiscoveryRequest = "discovery.request"
	TypeDiscoveryCancel  = "discovery.cancel"
	TypeKeyRotate        = "key.rotate"
	// TypeTLSPinRotate advertises the TLS trust policy this server is about
	// to start serving, ahead of the certificate actually changing, so the
	// agent can accept either the current or the successor leaf across the
	// cutover. Distinct from TypeKeyRotate: that frame rotates Noise
	// identity keys and its `kind` is closed over "device"/"server", while
	// this one rotates the transport-layer trust policy underneath them.
	TypeTLSPinRotate = "tls.pin.rotate"
	TypeUpdate       = "update"
	TypeDisconnect   = "disconnect"
	TypePing         = "ping"
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
	TypeProbeCancel,
	TypeDiscoveryRequest,
	TypeDiscoveryCancel,
	TypeKeyRotate,
	TypeTLSPinRotate,
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
	TypeProbeCancel:         true,
	TypeDiscoveryRequest:    true,
	TypeDiscoveryCancel:     true,
	TypeKeyRotate:           true,
	TypeTLSPinRotate:        true,
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

// NetworkFacts is one of the agent host's directly connected networks, carried in
// HelloPayload.Networks (D-1). Addrs are CIDR strings taken straight from the interface's own
// addresses ("10.0.0.5/24", "fd00::1/64"), i.e. the host address *with* its prefix length —
// that prefix is what makes the network "directly connected" and is the only input the slice-3
// scope evaluator needs. Flags carries net.Flags' own vocabulary ("up", "broadcast",
// "pointtopoint", ...) as a list rather than net.Flags.String()'s "|"-joined form, so a consumer
// tests membership instead of substring-matching.
//
// These are facts, not policy: which of them end up in an agent's effective probe scope is
// decided server-side. Reporting an address the evaluator will exclude is correct.
type NetworkFacts struct {
	Name  string   `json:"name"`
	Flags []string `json:"flags,omitempty"`
	Addrs []string `json:"addrs,omitempty"`
}

// HelloPayload is the agent -> server `hello` payload's structured shape
// (specs/2026-07-26-cb-agent-design.md §3.4, §4.3, §4.6). Every field is optional so an
// old-shaped hello — including today's empty `{}` payload — still decodes: absent fields take
// their Go zero value rather than failing decode.
type HelloPayload struct {
	DevicePK         string         `json:"device_pk,omitempty"`
	Hostname         string         `json:"hostname,omitempty"`
	MachineIDHash    string         `json:"machine_id_hash,omitempty"`
	OS               string         `json:"os,omitempty"`
	OSVersion        string         `json:"os_version,omitempty"`
	Arch             string         `json:"arch,omitempty"`
	AgentVersion     string         `json:"agent_version,omitempty"`
	PrimaryMACs      []string       `json:"primary_macs,omitempty"`
	Readiness        []Readiness    `json:"readiness,omitempty"`
	SpoolDepth       int            `json:"spool_depth,omitempty"`
	CapabilitySchema int            `json:"capability_schema,omitempty"`
	Networks         []NetworkFacts `json:"networks,omitempty"`

	// TLSPinKind reports which TLS trust policy this connection's handshake
	// actually matched — "current" or "successor" — so the server can show
	// an operator how much of the fleet has already accepted an advertised
	// successor certificate. Purely observational, and omitted entirely by
	// agents predating the tls.pin.rotate mechanism.
	TLSPinKind string `json:"tls_pin_kind,omitempty"`

	// TLSPinSuccessorReady reports whether this agent has durably persisted
	// an advertised successor trust policy, and so would survive a cutover
	// to it. Distinct from TLSPinKind, and it is this field the server's
	// activation gate reads: until the server actually serves the successor
	// every reachable agent matches the *current* policy, so convergence
	// keyed on a successor match could never be reached before the change
	// it is supposed to gate. Omitted by agents predating the mechanism.
	TLSPinSuccessorReady bool `json:"tls_pin_successor_ready,omitempty"`
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

// CapabilityReadinessPayload is the agent -> server `capability.readiness` payload.
//
// Networks is the same shape as HelloPayload.Networks and exists so an agent can refresh its
// directly connected networks *mid-session* (Slice 4 D-8). Hello carries them only at connect,
// so without this a subnet that appeared on this host would not become discoverable until the
// next reconnect — which may be days.
//
// It deliberately carries no `omitempty`, for the same reason HeartbeatPayload's spool fields do
// not: an agent that has lost every interface must be able to send `[]`, and Go would drop that,
// leaving the server to read an absent key as "no report" and stand on a stale, wider-than-
// reality scope forever. The server gates persistence on the key's *presence*, not its
// truthiness.
type CapabilityReadinessPayload struct {
	Readiness []Readiness    `json:"readiness"`
	Networks  []NetworkFacts `json:"networks"`
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

	// TLSPinSuccessorReady repeats hello's field of the same name on every
	// heartbeat, and that repetition is the point rather than redundancy.
	//
	// hello is sent once per connection, so an agent holding a live socket
	// when a `tls.pin.rotate` arrives has no way to say it applied the
	// policy until it next reconnects — which may be days. The server's
	// certificate-activation gate waits on exactly that signal, so without
	// this the operator watches `unconverged` sit at the fleet size while
	// every agent is in fact ready, and the only way through is to force.
	//
	// Repeating rather than acking once is deliberate: an ack is one frame
	// that can be lost with nothing to retry it, whereas this re-asserts the
	// truth every heartbeat interval, which is the same durability
	// reasoning behind resending the rotation frame on every hello.ack.
	TLSPinSuccessorReady bool `json:"tls_pin_successor_ready"`
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

// TLSPinRotatePayload mirrors apps/backend/src/app/schemas/agent_frame.py's
// TLSPinRotatePayload field-for-field: the TLS trust policy the server is
// about to start serving. Mode is "self_signed" (SuccessorPin is the base64
// SHA-256 SPKI digest of the successor leaf) or "public" (SuccessorPin is
// empty and the agent falls back to the system CA store). Expiry bounds how
// long both policies stay acceptable.
type TLSPinRotatePayload struct {
	Mode         string    `json:"mode"`
	SuccessorPin string    `json:"successor_pin"`
	Expiry       time.Time `json:"expiry"`
}

// ProbeAssignPayload is the server -> agent `probe.assign` payload (§4): exactly one remote check,
// fully specified, mirroring apps/backend/src/app/schemas/agent_frame.py's ProbeAssignPayload.
//
// RunID is the server-minted 32-hex token that is the *only* identifier a result may be posted
// against — a leaked monitor id buys nothing. Config is the monitor's complete validated
// configuration and therefore carries HTTP credentials when the monitor has them (D-10), which is
// why it is left as raw JSON rather than a typed struct: this package must not become somewhere
// a secret can accidentally be logged, compared or persisted. The runtime holds it for the life
// of the run and nothing else.
//
// ScheduledAt/DeadlineAt are RFC3339 and non-pointer: an assignment without a deadline is not
// dispatchable, and the backend always stamps both with .isoformat().
type ProbeAssignPayload struct {
	RunID       string          `json:"run_id"`
	MonitorID   int64           `json:"monitor_id"`
	CheckType   string          `json:"check_type"` // icmp | tcp | http | dns
	Host        string          `json:"host"`
	Config      json.RawMessage `json:"config,omitempty"`
	ScheduledAt time.Time       `json:"scheduled_at"`
	DeadlineAt  time.Time       `json:"deadline_at"`
}

// ProbeCancelPayload is the server -> agent `probe.cancel` payload (§4), sent when a monitor is
// paused, deleted, reassigned, has its capability disabled, or the agent is revoked. Reason is
// advisory: cancellation is best-effort and the backend stays authoritative, rejecting any result
// that arrives for a run it has already closed.
type ProbeCancelPayload struct {
	RunID  string `json:"run_id"`
	Reason string `json:"reason,omitempty"`
}

// ProbeSample is one observation from a completed check, mirroring
// apps/backend/src/app/services/monitoring/collectors.Sample so a remote result reaches the
// shared result service in the same shape a server-executed one does. ErrorReason is the
// collectors' own per-sample annotation ("http_error", "dns_error"); it is audit metadata
// persisted only in monitor_probe_runs.result_metadata (D-8), never in telemetry_timeseries.
type ProbeSample struct {
	Metric      string  `json:"metric"`
	Value       float64 `json:"value"`
	ErrorReason string  `json:"error_reason,omitempty"`
}

// ProbeResultPayload is the agent -> server `probe.result` payload (§4), mirroring
// apps/backend/src/app/schemas/agent_frame.py's ProbeResultPayload.
//
// Outcome is closed: "completed" (a real target result, feed the state machine),
// "execution_error" (the agent could not perform the probe), "cancelled", or "rejected"
// (invalid, unauthorized, out-of-scope or capacity-limited assignment). Only "completed" says
// anything about the target — the other three must preserve its last known state, which is why
// Up is meaningless outside "completed" rather than a fallback DOWN.
//
// Up carries no `omitempty`, for the same reason HeartbeatPayload's spool fields do not: false
// is the observation a DOWN target produces, and Go would drop it, leaving the server to read an
// absent key as its own default. The empty value must stay reserved for "field not sent at all".
//
// Details is bounded at 64 KiB and Msg at 2000 characters by the server-side handler, and neither
// may ever carry a response body, an Authorization header, a token or a password.
type ProbeResultPayload struct {
	RunID      string         `json:"run_id"`
	MonitorID  int64          `json:"monitor_id"`
	Outcome    string         `json:"outcome"` // completed | execution_error | cancelled | rejected
	Up         bool           `json:"up"`
	StartedAt  time.Time      `json:"started_at"`
	FinishedAt time.Time      `json:"finished_at"`
	Samples    []ProbeSample  `json:"samples,omitempty"`
	Msg        string         `json:"msg,omitempty"`
	Details    map[string]any `json:"details,omitempty"`
}

// Slice 4 plan §4's bounds. Declared alongside the structs rather than left to the collector so
// the encoder and the server's pydantic models are reading the same numbers — a bound only one
// side knows about is one the other has no reason to respect.
const (
	MaxDiscoveryTargets    = 16
	MaxDiscoveryPorts      = 32
	MaxDiscoveryEvidence   = 16
	MaxDiscoveryOpenPorts  = 64
	MaxDiscoveryBannerRune = 512
	MaxDiscoveryMsgRunes   = 2000
)

// The closed `kind` vocabulary for a discovery finding. A host finding describes one address; a
// summary is the dispatch's single terminal frame. Both travel as the same frame type so the
// summary rides the spool with the findings it closes, which is what makes replay after an
// outage idempotent rather than a job that never finishes.
const (
	DiscoveryKindHost    = "host"
	DiscoveryKindSummary = "summary"
)

// Discovery summary outcomes, mirroring ProbeResultPayload.Outcome's closed set.
const (
	DiscoveryOutcomeCompleted      = "completed"
	DiscoveryOutcomeExecutionError = "execution_error"
	DiscoveryOutcomeCancelled      = "cancelled"
	DiscoveryOutcomeRejected       = "rejected"
)

// DiscoveryRequestPayload is the server -> agent `discovery.request` payload (plan §4), mirroring
// apps/backend/src/app/schemas/agent_frame.py's DiscoveryRequestPayload.
//
// One bounded, one-shot scan. Every limit here is *also* checked by the agent against its own
// grant before it opens a socket — the backend deriving a target and the agent accepting one are
// independent checks on purpose, so a backend bug cannot widen what an agent will actually scan.
//
// ScopeVersion is the netscope.Scope.Version in force when the request was built. The agent
// re-derives its own and refuses a mismatch: plan §2 requires an active request to be cancelled
// when scope changes incompatibly, and a version is what makes that decidable without shipping
// the whole CIDR list on every dispatch.
type DiscoveryRequestPayload struct {
	DispatchID         string    `json:"dispatch_id"`
	ScanJobID          int64     `json:"scan_job_id"`
	Targets            []string  `json:"targets,omitempty"`
	Methods            []string  `json:"methods,omitempty"`
	TCPPorts           []int     `json:"tcp_ports,omitempty"`
	HostTimeoutMS      int       `json:"host_timeout_ms"`
	MaxConcurrentHosts int       `json:"max_concurrent_hosts"`
	ScopeVersion       string    `json:"scope_version"`
	DeadlineAt         time.Time `json:"deadline_at"`
}

// DiscoveryCancelPayload is the server -> agent `discovery.cancel` payload (plan §4), sent when
// the job is cancelled, its profile disabled, scope changed incompatibly, the capability
// disabled, or the agent revoked. Reason is advisory: cancellation is best-effort and the
// backend stays authoritative, rejecting any finding that arrives for a dispatch it has already
// closed.
type DiscoveryCancelPayload struct {
	DispatchID string `json:"dispatch_id"`
	Reason     string `json:"reason,omitempty"`
}

// DiscoveryOpenPort is one reachable TCP port on a discovered host. Banner is an untrusted
// observation — whatever bytes the service sent first, control characters stripped and truncated
// to MaxDiscoveryBannerRune here rather than on the server, because ScanResult.banner is an
// unbounded Text column and the wire cap is the only one there is.
type DiscoveryOpenPort struct {
	Port     int    `json:"port"`
	Protocol string `json:"protocol,omitempty"`
	Banner   string `json:"banner,omitempty"`
}

// DiscoveryFindingPayload is the agent -> server `discovery.finding` payload (plan §4), mirroring
// apps/backend/src/app/schemas/agent_frame.py's DiscoveryFindingPayload.
//
// Kind is closed: "host" describes one discovered address, "summary" is the dispatch's single
// terminal frame carrying counts and outcome. A summary has its own FindingID for the same reason
// every host finding does — spool replay must be idempotent, and the frame that *closes* a job is
// exactly the one an outage is most likely to duplicate.
//
// FindingID is chosen here but replay-stable by construction (a digest of dispatch/kind/address),
// which is what turns the server's uq_scan_results_job_finding into an idempotency key rather
// than a race. It is bounded to the width of that String(64) column.
//
// Terminal carries no `omitempty`, for the same reason ProbeResultPayload.Up does not: false is
// the value every host finding sends, and an absent key must never be read as its own default.
//
// Every string here is an untrusted observation: Hostname is a PTR answer from a resolver this
// host does not control, Banner is whatever bytes a service chose to send, MACAddress is whatever
// the neighbor cache held. None of them may reach Hardware without review on the server side.
type DiscoveryFindingPayload struct {
	DispatchID string              `json:"dispatch_id"`
	ScanJobID  int64               `json:"scan_job_id"`
	FindingID  string              `json:"finding_id"`
	Kind       string              `json:"kind"`
	ObservedAt time.Time           `json:"observed_at"`
	IPAddress  string              `json:"ip_address,omitempty"`
	MACAddress string              `json:"mac_address,omitempty"`
	Hostname   string              `json:"hostname,omitempty"`
	OpenPorts  []DiscoveryOpenPort `json:"open_ports,omitempty"`
	Evidence   []string            `json:"evidence,omitempty"`
	Terminal   bool                `json:"terminal"`

	// Summary fields. Absent on a host finding; a host finding that carried them is ignored by
	// the server rather than rejected, since they say nothing about the address.
	Outcome          string `json:"outcome,omitempty"`
	HostsFound       *int   `json:"hosts_found,omitempty"`
	AddressesScanned *int   `json:"addresses_scanned,omitempty"`
	Msg              string `json:"msg,omitempty"`
	ErrorCode        string `json:"error_code,omitempty"`
}
