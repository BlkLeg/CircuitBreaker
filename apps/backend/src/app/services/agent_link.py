"""Frame decode -> capability check -> dispatch. No domain logic lives here —
telemetry lands in telemetry_service, probe results in the monitoring
engine's result path, discovery findings in discovery_import_service (slices
2-4). This module only transports and authenticates (spec §1.2)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from app.db.models import Agent
from app.schemas.agent_frame import (
    TYPE_DISCOVERY_FINDING,
    TYPE_HEARTBEAT,
    TYPE_LOG,
    TYPE_PROBE_RESULT,
    TYPE_TELEMETRY_HOST,
    AgentFrame,
)
from app.services import agent_registry

_logger = logging.getLogger(__name__)

# Frame types requiring no grant are transport-level (hello/heartbeat/log/
# capability.violation) and are simply absent from this map.
CAPABILITY_FOR_TYPE: dict[str, str] = {
    TYPE_TELEMETRY_HOST: "host_telemetry",
    TYPE_PROBE_RESULT: "remote_probe",
    TYPE_DISCOVERY_FINDING: "local_discovery",
}

Handler = Callable[[Session, Agent, AgentFrame], Awaitable[None]]


async def _handle_heartbeat(db: Session, agent: Agent, frame: AgentFrame) -> None:
    import socket

    await agent_registry.refresh_presence_heartbeat(db, agent.id, worker=socket.gethostname())


async def _handle_log(db: Session, agent: Agent, frame: AgentFrame) -> None:
    _logger.info("agent %s: %s", agent.id, frame.payload)


_HANDLERS: dict[str, Handler] = {
    TYPE_HEARTBEAT: _handle_heartbeat,
    TYPE_LOG: _handle_log,
}


async def dispatch_frame(db: Session, agent: Agent, frame: AgentFrame) -> None:
    required = CAPABILITY_FOR_TYPE.get(frame.type)
    if required is not None and not agent_registry.grants_dict(db, agent.id).get(required, False):
        agent_registry.record_event(
            db,
            agent.id,
            "capability_violation",
            detail={"frame_type": frame.type},
        )
        db.commit()
        return

    handler = _HANDLERS.get(frame.type)
    if handler is not None:
        await handler(db, agent, frame)
        db.commit()
