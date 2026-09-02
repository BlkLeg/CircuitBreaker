"""A malformed-frame flood must not become one database commit per frame.

`agent_link` already rate-limits its capability-violation path through
`recordable_violation`; `_record_protocol_violation` was the one that did not, so
an agent sending malformed frames in a loop wrote an AgentEvent and committed for
every one of them (route F24).

The throttle is not about disk. It is about the record staying readable: ten
thousand identical rows are the same as no record at all, and they bury the
audit trail an operator would actually need. The repeat count carries what the
extra rows would have.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services import agent_link


def test_repeated_violations_record_once_and_count_the_rest(monkeypatch) -> None:
    calls: list[int] = []

    def fake_recordable(agent_id: int) -> tuple[bool, int]:
        calls.append(agent_id)
        # Mirrors the real window behaviour: the first call inside a window
        # records, the rest are folded into the repeat count.
        return (len(calls) == 1, len(calls))

    monkeypatch.setattr(agent_link.agent_telemetry, "recordable_violation", fake_recordable)

    recorded: list[dict] = []
    monkeypatch.setattr(
        agent_link.agent_registry,
        "record_event",
        lambda db, agent_id, kind, detail: recorded.append(detail),
    )

    db = MagicMock()
    agent = MagicMock()
    agent.id = 7

    for _ in range(5):
        agent_link._record_protocol_violation(db, agent, reason="bad_frame", detail={"frame": "x"})

    assert len(calls) == 5, "every violation must consult the throttle"
    assert len(recorded) == 1, f"expected one recorded event, got {len(recorded)}"
    assert db.commit.call_count == 1, (
        f"expected one commit, got {db.commit.call_count} — an unthrottled write "
        "per malformed frame is exactly F24"
    )
    assert recorded[0]["reason"] == "bad_frame"
    assert recorded[0]["frame"] == "x", "caller-supplied detail must survive the throttle"
    assert recorded[0]["repeated"] == 1, "the recorded event carries the repeat count"


def test_the_suppressed_violations_still_advance_the_repeat_count(monkeypatch) -> None:
    """The second recorded event reports how many were folded into the first.

    Without this the throttle would hide the magnitude of a flood, which is the
    one thing an operator needs from it.
    """
    calls: list[int] = []

    def fake_recordable(agent_id: int) -> tuple[bool, int]:
        calls.append(agent_id)
        # Record on the 1st and 4th, as a real 60s window boundary would.
        return (len(calls) in (1, 4), len(calls))

    monkeypatch.setattr(agent_link.agent_telemetry, "recordable_violation", fake_recordable)
    recorded: list[dict] = []
    monkeypatch.setattr(
        agent_link.agent_registry,
        "record_event",
        lambda db, agent_id, kind, detail: recorded.append(detail),
    )

    db = MagicMock()
    agent = MagicMock()
    agent.id = 3

    for _ in range(5):
        agent_link._record_protocol_violation(db, agent, reason="bad_frame", detail={})

    assert [entry["repeated"] for entry in recorded] == [1, 4]
