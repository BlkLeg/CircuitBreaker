"""The agent protocol v1 frame envelope — defined once here and in
apps/agent/internal/frame/frame.go, nowhere else, per
specs/2026-07-26-cb-agent-design.md §1's `agent_link.py` boundary note."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

FRAME_VERSION = 1

# agent -> server
TYPE_HELLO = "hello"
TYPE_HEARTBEAT = "heartbeat"
TYPE_TELEMETRY_HOST = "telemetry.host"
TYPE_PROBE_RESULT = "probe.result"
TYPE_DISCOVERY_FINDING = "discovery.finding"
TYPE_CAPABILITY_VIOLATION = "capability.violation"
TYPE_LOG = "log"
TYPE_UNINSTALL = "uninstall"

# server -> agent
TYPE_HELLO_ACK = "hello.ack"
TYPE_CAPABILITIES_SET = "capabilities.set"
TYPE_PROBE_ASSIGN = "probe.assign"
TYPE_DISCOVERY_REQUEST = "discovery.request"
TYPE_KEY_ROTATE = "key.rotate"
TYPE_UPDATE = "update"
TYPE_DISCONNECT = "disconnect"
TYPE_PING = "ping"


class AgentFrame(BaseModel):
    v: int = FRAME_VERSION
    type: str
    seq: int = 0
    ts: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
