import json
from pathlib import Path

import pytest

from app.api import ws_agents
from app.schemas import agent_frame
from app.schemas.agent_frame import (
    TYPE_CAPABILITIES_SET,
    TYPE_CAPABILITY_READINESS,
    TYPE_DISCOVERY_FINDING,
    TYPE_DISCOVERY_REQUEST,
    TYPE_HEARTBEAT,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    TYPE_KEY_ROTATE,
    TYPE_PROBE_ASSIGN,
    TYPE_PROBE_RESULT,
    TYPE_TELEMETRY_HOST,
    TYPE_TRANSPORT_REKEY,
    TYPE_UNINSTALL,
    TYPE_UPDATE,
    TYPE_UPDATE_STATUS,
    AgentFrame,
    CapabilityReadinessPayload,
    HeartbeatPayload,
    HelloAckPayload,
    HelloPayload,
    HostTelemetryPayload,
    KeyRotatePayload,
    TransportRekeyPayload,
    UpdateStatusPayload,
)

_CORPUS_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "agent_frame_corpus.json"

# Maps a frame type to its structured payload model, mirroring
# apps/agent/internal/frame/conformance_test.go's TestCorpus_TypedPayloadsDecode switch. Frame
# types with no typed payload model are left untyped (AgentFrame.payload stays a plain dict).
_PAYLOAD_MODEL_FOR_TYPE = {
    TYPE_HELLO: HelloPayload,
    TYPE_HELLO_ACK: HelloAckPayload,
    TYPE_TRANSPORT_REKEY: TransportRekeyPayload,
    TYPE_KEY_ROTATE: KeyRotatePayload,
    TYPE_UPDATE_STATUS: UpdateStatusPayload,
    TYPE_TELEMETRY_HOST: HostTelemetryPayload,
    TYPE_CAPABILITY_READINESS: CapabilityReadinessPayload,
    TYPE_HEARTBEAT: HeartbeatPayload,
}


def _load_corpus() -> list[dict]:
    return json.loads(_CORPUS_PATH.read_text())


@pytest.mark.parametrize("entry", _load_corpus(), ids=lambda e: e["description"])
def test_corpus_decodes_and_round_trips(entry):
    raw = json.dumps(entry["json"])
    decoded = AgentFrame.model_validate_json(raw)

    assert decoded.v == 1
    assert decoded.type

    reencoded = decoded.model_dump_json()
    redecoded = AgentFrame.model_validate_json(reencoded)

    assert redecoded.type == decoded.type
    assert redecoded.seq == decoded.seq
    assert redecoded.ts == decoded.ts


@pytest.mark.parametrize("entry", _load_corpus(), ids=lambda e: e["description"])
def test_corpus_typed_payloads_decode_and_round_trip(entry):
    """For every corpus entry whose frame type has a structured payload model, validate the
    payload against that model and round-trip it. Old-shaped and partial payloads (e.g. the
    pre-existing enrollment-flavored hello.ack entries, or hello's empty/partial fixtures) must
    validate without error — that's the backward-compatibility guarantee this test pins,
    matching the Go side's TestCorpus_TypedPayloadsDecode."""
    frame = entry["json"]
    model = _PAYLOAD_MODEL_FOR_TYPE.get(frame["type"])
    if model is None:
        pytest.skip(f"no typed payload model for frame type {frame['type']!r}")

    first = model.model_validate(frame["payload"])
    reencoded = first.model_dump_json()
    second = model.model_validate_json(reencoded)

    assert second == first


# Declared frame types that legitimately have no wire fixture in the corpus yet. This is an
# explicitly shrinking allow-list: every entry is a visible, reviewable exemption, and the
# slice that introduces a type's wire traffic must delete its entry in the same commit that
# adds the fixture. Mirrors apps/agent/internal/frame/conformance_test.go's pendingCorpusTypes.
#
#   * probe.assign / probe.result           -- removed by slice 3 (remote probe). Slice 3 also
#     introduces ``probe.cancel``, deliberately NOT pre-exempted here: a new constant must ship
#     with a fixture or fail this gate.
#   * discovery.request / discovery.finding -- removed by slice 4 (local discovery).
#   * update / uninstall                    -- server->agent command frames with no structured
#     payload of their own yet; whichever task gives them one adds the fixture.
PENDING_CORPUS_TYPES = {
    TYPE_PROBE_ASSIGN,
    TYPE_PROBE_RESULT,
    TYPE_DISCOVERY_REQUEST,
    TYPE_DISCOVERY_FINDING,
    TYPE_UPDATE,
    TYPE_UNINSTALL,
}


def _declared_frame_types() -> set[str]:
    """Every ``TYPE_*`` constant declared by app.schemas.agent_frame, enumerated reflectively so
    a newly added constant cannot escape the coverage gate."""
    return {
        value
        for name, value in vars(agent_frame).items()
        if name.startswith("TYPE_") and isinstance(value, str)
    }


def test_corpus_covers_every_declared_frame_type():
    """The authoritative half of the cross-language corpus coverage gate.

    apps/agent/internal/frame/conformance_test.go runs the same check against a hand-maintained
    ``allFrameTypes`` slice, which a new constant can escape; this half enumerates the module's
    attributes at runtime, so it cannot be escaped. The assertion is an *equality*, so a stale
    ``PENDING_CORPUS_TYPES`` entry that is no longer a declared type fails just as loudly as an
    uncovered type.
    """
    declared = _declared_frame_types()
    corpus_types = {entry["json"]["type"] for entry in _load_corpus()}

    assert PENDING_CORPUS_TYPES <= declared, (
        "PENDING_CORPUS_TYPES contains entries that are not declared frame types: "
        f"{sorted(PENDING_CORPUS_TYPES - declared)}"
    )
    assert not (corpus_types & PENDING_CORPUS_TYPES), (
        "these frame types now have corpus fixtures and must be removed from "
        f"PENDING_CORPUS_TYPES: {sorted(corpus_types & PENDING_CORPUS_TYPES)}"
    )
    assert corpus_types | PENDING_CORPUS_TYPES == declared


def _corpus_entries_of_type(frame_type: str) -> list[dict]:
    return [entry for entry in _load_corpus() if entry["json"]["type"] == frame_type]


@pytest.mark.parametrize(
    "entry", _corpus_entries_of_type(TYPE_CAPABILITIES_SET), ids=lambda e: e["description"]
)
def test_corpus_grant_payloads_are_accepted_in_both_wire_forms(entry):
    """Every corpus `capabilities.set` payload must survive both agent wire shapes.

    ``ws_agents._wire_grants`` is the single downgrade point: a schema-2 agent receives the
    structured ``{enabled, config}`` grants verbatim, while an agent advertising
    ``capability_schema < 2`` (including one that omits the field entirely) receives bare
    booleans. The Go side pins the other half — apps/agent/internal/frame/conformance_test.go's
    TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate feeds the same payloads through the
    real internal/capability decoder.
    """
    grants = entry["json"]["payload"]

    assert ws_agents._wire_grants(grants, capability_schema=2) == grants

    legacy = ws_agents._wire_grants(grants, capability_schema=1)
    assert set(legacy) == set(grants)
    for name, value in legacy.items():
        assert isinstance(value, bool), f"{name} did not collapse to a bare boolean"
        original = grants[name]
        expected = original if isinstance(original, bool) else bool(original.get("enabled"))
        assert value is expected


def test_hello_absent_capability_schema_defaults_to_legacy():
    """An absent ``capability_schema`` means "this agent predates capability schema 2".

    Python defaults it to 1; Go's zero value for the same absent field is 0
    (pinned by apps/agent/internal/frame/conformance_test.go's
    TestHelloPayload_AbsentCapabilitySchemaDecodesToZeroAndMeansLegacy). The asymmetry is
    deliberate and safe because every consumer tests ``>= 2``, never ``== 1`` — see
    ``ws_agents._wire_grants``. Do not "fix" it by defaulting Python to 0: 1 is the real first
    schema version, and this model is what the server reads from the hello.
    """
    assert HelloPayload.model_validate({}).capability_schema == 1
    assert HelloPayload.model_validate({}).capability_schema < 2
    assert HelloPayload.model_validate({"capability_schema": 2}).capability_schema == 2

    schema_2_entries = [
        entry
        for entry in _corpus_entries_of_type(TYPE_HELLO)
        if entry["json"]["payload"].get("capability_schema") == 2
    ]
    assert schema_2_entries, "corpus must cover a schema-2 hello negotiation"


def test_heartbeat_empty_payload_is_distinguishable_from_an_explicit_zero_backlog():
    """D-12's whole point, pinned on the Python side.

    The Go struct carries no ``omitempty``, so a current agent always emits
    both keys — ``{"spool_depth": 0, "spool_bytes": 0}`` once its backlog
    clears. That makes an empty ``{}`` payload an exact test for "this agent
    predates spool reporting", which is what
    ``agent_registry.record_spool_stats``'s callers gate on via
    ``model_fields_set``. Both shapes must validate; only the explicit one
    may report presence.
    """
    old_agent = HeartbeatPayload.model_validate({})
    assert old_agent.spool_depth == 0
    assert old_agent.spool_bytes == 0
    assert "spool_depth" not in old_agent.model_fields_set

    drained = HeartbeatPayload.model_validate({"spool_depth": 0, "spool_bytes": 0})
    assert "spool_depth" in drained.model_fields_set
    assert drained == old_agent  # equal by value, distinguishable by fields_set

    backlog = HeartbeatPayload.model_validate({"spool_depth": 137, "spool_bytes": 262144})
    assert (backlog.spool_depth, backlog.spool_bytes) == (137, 262144)

    corpus_payloads = [
        entry["json"]["payload"] for entry in _corpus_entries_of_type(TYPE_HEARTBEAT)
    ]
    assert {} in corpus_payloads, "corpus must keep the old-shaped empty heartbeat"
    assert any(p.get("spool_depth") for p in corpus_payloads), (
        "corpus must cover a heartbeat carrying a real backlog"
    )
