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

// Payload shapes below are the structured wire format for a subset of frame types. They are
// schema/codec only: nothing in this package parses Frame.Payload into these types
// automatically, and no rekey/rotation *behavior* lives here (see Frame.Payload's callers in
// internal/link and internal/enroll, and the corresponding backend handlers). Callers that want
// the typed form decode Frame.Payload into these structs themselves; the conformance corpus in
// conformance_test.go pins their wire shape against apps/backend/src/app/schemas/agent_frame.py.

// Readiness reports one collector's ability to run, carried in HelloPayload.Readiness — see
// specs/2026-07-26-cb-agent-design.md §4.3.
type Readiness struct {
	Collector   string   `json:"collector"`
	State       string   `json:"state"` // ready | degraded | unavailable
	Reason      string   `json:"reason,omitempty"`
	Remediation string   `json:"remediation,omitempty"`
	Missing     []string `json:"missing,omitempty"`
}

// HelloPayload is the agent -> server `hello` payload's structured shape
// (specs/2026-07-26-cb-agent-design.md §3.4, §4.3, §4.6). Every field is optional so an
// old-shaped hello — including today's empty `{}` payload — still decodes: absent fields take
// their Go zero value rather than failing decode.
type HelloPayload struct {
	DevicePK      string      `json:"device_pk,omitempty"`
	Hostname      string      `json:"hostname,omitempty"`
	MachineIDHash string      `json:"machine_id_hash,omitempty"`
	OS            string      `json:"os,omitempty"`
	OSVersion     string      `json:"os_version,omitempty"`
	Arch          string      `json:"arch,omitempty"`
	AgentVersion  string      `json:"agent_version,omitempty"`
	PrimaryMACs   []string    `json:"primary_macs,omitempty"`
	Readiness     []Readiness `json:"readiness,omitempty"`
	SpoolDepth    int         `json:"spool_depth,omitempty"`
}

// HelloAckPayload is the server -> agent `hello.ack` payload's structured shape for the
// post-enrollment link-establishment handshake (specs/2026-07-26-cb-agent-design.md §4.2: the
// server "re-sends the authoritative set on every hello.ack"). The enrollment socket
// (WS /api/agents/enroll) also emits `hello.ack` frames for pairing-code/status messages with a
// different, untyped payload shape (see ws_agents.py's `_ack_bytes`); this struct models only
// the link ack. All fields are optional/zero-valued when absent.
type HelloAckPayload struct {
	Accepted     bool            `json:"accepted,omitempty"`
	Reason       string          `json:"reason,omitempty"`
	ServerTime   *time.Time      `json:"server_time,omitempty"`
	Capabilities map[string]bool `json:"capabilities,omitempty"`
	AgentID      int64           `json:"agent_id,omitempty"`
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
