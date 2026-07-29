package frame

import (
	"encoding/json"
	"fmt"
	"time"
)

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
