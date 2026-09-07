import json
from pathlib import Path

import pytest

from app.api import ws_agents
from app.schemas import agent_frame
from app.schemas.agent_frame import (
    CAPABILITY_VIOLATION_REASONS,
    DISCOVERY_KIND_SUMMARY,
    DISCOVERY_KINDS,
    MAX_VIOLATION_ADDRESS_CHARS,
    MAX_VIOLATION_DETAIL_CHARS,
    TYPE_CAPABILITIES_SET,
    TYPE_CAPABILITY_READINESS,
    TYPE_CAPABILITY_VIOLATION,
    TYPE_DATA_ACK,
    TYPE_DISCOVERY_CANCEL,
    TYPE_DISCOVERY_FINDING,
    TYPE_DISCOVERY_REQUEST,
    TYPE_HEARTBEAT,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    TYPE_KEY_ROTATE,
    TYPE_PROBE_ASSIGN,
    TYPE_PROBE_CANCEL,
    TYPE_PROBE_RESULT,
    TYPE_TELEMETRY_HOST,
    TYPE_TLS_PIN_ROTATE,
    TYPE_TRANSPORT_REKEY,
    TYPE_UNINSTALL,
    TYPE_UPDATE,
    TYPE_UPDATE_STATUS,
    AgentFrame,
    CapabilityReadinessPayload,
    CapabilityViolationPayload,
    DataAckPayload,
    DiscoveryCancelPayload,
    DiscoveryFindingPayload,
    DiscoveryRequestPayload,
    HeartbeatPayload,
    HelloAckPayload,
    HelloPayload,
    HostTelemetryPayload,
    KeyRotatePayload,
    ProbeAssignPayload,
    ProbeCancelPayload,
    ProbeResultPayload,
    TLSPinRotatePayload,
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
    TYPE_CAPABILITY_VIOLATION: CapabilityViolationPayload,
    TYPE_HEARTBEAT: HeartbeatPayload,
    TYPE_PROBE_ASSIGN: ProbeAssignPayload,
    TYPE_PROBE_CANCEL: ProbeCancelPayload,
    TYPE_PROBE_RESULT: ProbeResultPayload,
    TYPE_DISCOVERY_REQUEST: DiscoveryRequestPayload,
    TYPE_DISCOVERY_CANCEL: DiscoveryCancelPayload,
    TYPE_DISCOVERY_FINDING: DiscoveryFindingPayload,
    TYPE_TLS_PIN_ROTATE: TLSPinRotatePayload,
    TYPE_DATA_ACK: DataAckPayload,
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
#   * update / uninstall                    -- server->agent command frames with no structured
#     payload of their own yet; whichever task gives them one adds the fixture.
#
# discovery.request / discovery.cancel / discovery.finding left this list in slice 4, in the same
# commit that added their fixtures.
#
# probe.assign / probe.cancel / probe.result left this list in slice 3, in the same commit that
# added their fixtures. ``probe.cancel`` was never on it: a constant declared without a fixture
# must fail this gate on arrival, which is the property the list exists to preserve.
PENDING_CORPUS_TYPES = {
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


def test_hello_networks_survive_the_typed_payload_by_name():
    """The `networks` field has to be asserted by name, not just round-tripped.

    Pydantic ignores unknown keys, so a model that never declared ``networks`` drops the
    agent's whole network report in silence and ``test_corpus_typed_payloads_decode_and_round_trip``
    above still passes — both sides of its comparison are equally empty. This is the Python half
    of the Task 1 wire contract; the Go half is compareNetworkFacts in
    apps/agent/internal/frame/conformance_test.go, against the same fixture.
    """
    carrying = [
        entry
        for entry in _corpus_entries_of_type(TYPE_HELLO)
        if entry["json"]["payload"].get("networks")
    ]
    assert carrying, "corpus must cover a hello carrying directly connected network facts"

    for entry in carrying:
        wire = entry["json"]["payload"]["networks"]
        payload = HelloPayload.model_validate(entry["json"]["payload"])
        assert [facts.model_dump() for facts in payload.networks] == wire
        assert HelloPayload.model_validate_json(payload.model_dump_json()) == payload

    # Optional on both sides: an agent predating the field and one with nothing directly
    # connected are both valid, and neither is distinguishable from the other by value.
    assert HelloPayload.model_validate({}).networks == []
    assert HelloPayload.model_validate({"networks": []}).networks == []


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


def test_spool_eviction_group_is_present_absent_not_zero_valued():
    """Phase 3, and the same rule D-12 set for the backlog, applied to the
    counters that say history was *permanently destroyed*.

    The Go side carries no ``omitempty`` on any of the four, so a current
    agent always emits them — explicit ``0`` with ``null`` bounds when it has
    destroyed nothing. An agent that predates the group omits them entirely.
    Only presence separates "confirmed clean" from "never said", and writing a
    fabricated 0 for the second would claim a confirmation that never
    happened. Both ``hello`` and ``heartbeat`` carry the group, because
    eviction happens while the agent is disconnected and the reconnect is the
    first moment this server can learn of it at all.
    """
    for model in (HeartbeatPayload, HelloPayload):
        old_agent = model.model_validate({})
        assert old_agent.spool_evicted_frames == 0
        assert old_agent.spool_evicted_oldest_ts is None
        assert "spool_evicted_frames" not in old_agent.model_fields_set

        clean = model.model_validate(
            {
                "spool_evicted_frames": 0,
                "spool_evicted_bytes": 0,
                "spool_evicted_oldest_ts": None,
                "spool_evicted_newest_ts": None,
            }
        )
        assert "spool_evicted_frames" in clean.model_fields_set
        assert clean.spool_evicted_oldest_ts is None

        lossy = model.model_validate(
            {
                "spool_evicted_frames": 9412,
                "spool_evicted_bytes": 33554432,
                "spool_evicted_oldest_ts": "2026-09-01T00:00:00Z",
                "spool_evicted_newest_ts": "2026-09-03T18:30:00Z",
            }
        )
        assert lossy.spool_evicted_frames == 9412
        assert lossy.spool_evicted_bytes == 33554432
        assert lossy.spool_evicted_oldest_ts is not None
        assert lossy.spool_evicted_newest_ts is not None
        assert model.model_validate_json(lossy.model_dump_json()) == lossy

    heartbeats = [entry["json"]["payload"] for entry in _corpus_entries_of_type(TYPE_HEARTBEAT)]
    assert any(p.get("spool_evicted_frames") for p in heartbeats), (
        "corpus must cover a heartbeat reporting destroyed history"
    )
    assert any("spool_evicted_frames" in p and not p["spool_evicted_frames"] for p in heartbeats), (
        "corpus must cover a heartbeat reporting eviction state with nothing destroyed"
    )
    hellos = [entry["json"]["payload"] for entry in _corpus_entries_of_type(TYPE_HELLO)]
    assert any(p.get("spool_evicted_frames") for p in hellos), (
        "corpus must cover hello's at-connect eviction snapshot"
    )


def test_data_ack_watermark_survives_the_typed_model_by_name():
    """The delivery watermark, asserted by name against the fixture.

    ``seq`` is the entire payload, and pydantic drops unknown keys — so a
    model that misspelled it would validate every real ack into ``seq=0``,
    ``test_corpus_typed_payloads_decode_and_round_trip`` would still pass
    (both sides of its comparison equally zero), and the agent would be told
    that nothing had ever been handled. Its spool would then never commit
    anything and would grow until its cap evicted the oldest observations —
    the exact loss the acknowledgement exists to prevent, caused by the
    acknowledgement itself.

    The corpus covers the top of the range because ``seq`` is a ``uint64`` on
    the Go side and a Python ``int`` here: a watermark that saturated or
    wrapped on the way through would commit frames the server never handled.
    """
    entries = _corpus_entries_of_type(TYPE_DATA_ACK)
    assert entries, "corpus must cover data.ack"

    for entry in entries:
        wire = entry["json"]["payload"]
        assert "seq" in wire, "a data.ack fixture without a `seq` is not a watermark"
        payload = DataAckPayload.model_validate(wire)
        assert payload.seq == wire["seq"]
        assert DataAckPayload.model_validate_json(payload.model_dump_json()) == payload

    seqs = {entry["json"]["payload"]["seq"] for entry in entries}
    assert 0 in seqs, "corpus must cover a watermark of 0 — nothing handled yet on this connection"
    assert max(seqs) == 2**64 - 1, (
        "corpus must cover the top of the uint64 range the Go side declares"
    )


def test_data_ack_negotiation_flags_default_to_unsupported():
    """Absent means "does not support acknowledged delivery", on both frames.

    This is the opposite convention from the ``spool_evicted_*`` group, and
    deliberately so. Those need an explicit 0 on the wire because absent means
    "cannot report", which is a different fact from "nothing was destroyed".
    Here absent and False are the *same* fact — an agent that predates the
    mechanism does not support acks, and a server that predates it does not
    send them — so both sides carry ``omitempty``/a plain default and the safe
    answer is the default one.

    Getting this backwards in either direction is a live hazard: a server that
    read an absent ``ack_data`` as True would send ``data.ack`` frames to an
    agent that has no idea what they are, and an agent that read an absent
    ``data_ack`` as True would wait forever for acknowledgements that are
    never coming and drain nothing.
    """
    assert HelloPayload.model_validate({}).ack_data is False
    assert HelloPayload.model_validate({"ack_data": True}).ack_data is True
    assert HelloAckPayload.model_validate({}).data_ack is False
    assert HelloAckPayload.model_validate({"accepted": True}).data_ack is False
    assert HelloAckPayload.model_validate({"data_ack": True}).data_ack is True

    hellos = [entry["json"]["payload"] for entry in _corpus_entries_of_type(TYPE_HELLO)]
    assert any(p.get("ack_data") for p in hellos), (
        "corpus must cover an agent asking for acknowledged delivery"
    )
    assert any("ack_data" not in p for p in hellos), (
        "corpus must keep a hello from an agent that predates the negotiation"
    )
    acks = [entry["json"]["payload"] for entry in _corpus_entries_of_type(TYPE_HELLO_ACK)]
    assert any(p.get("data_ack") for p in acks), (
        "corpus must cover a server granting acknowledged delivery"
    )
    assert any("data_ack" not in p for p in acks), (
        "corpus must keep a hello.ack from a server that predates the negotiation"
    )


def test_probe_payloads_survive_the_typed_models_by_name():
    """The probe payloads' collection fields have to be asserted by name, not just round-tripped.

    Pydantic drops unknown keys, so a model that misspelled ``samples`` validates a real result
    into an empty one and ``test_corpus_typed_payloads_decode_and_round_trip`` above still
    passes — both sides of its comparison are equally empty. For ``probe.result`` that silently
    feeds the monitor state machine a check with no observations; for ``probe.assign`` it
    silently strips the credentials and assertions the check is supposed to run with. Same
    hazard, and same guard, as ``test_hello_networks_survive_the_typed_payload_by_name``; the Go
    half is roundTripProbeAssignPayload/roundTripProbeResultPayload against the same fixtures.
    """
    assignments = _corpus_entries_of_type(TYPE_PROBE_ASSIGN)
    assert assignments, "corpus must cover probe.assign"
    for entry in assignments:
        wire = entry["json"]["payload"]
        payload = ProbeAssignPayload.model_validate(wire)
        assert payload.config == wire["config"]
        assert (payload.run_id, payload.monitor_id, payload.check_type, payload.host) == (
            wire["run_id"],
            wire["monitor_id"],
            wire["check_type"],
            wire["host"],
        )

    results = _corpus_entries_of_type(TYPE_PROBE_RESULT)
    assert results, "corpus must cover probe.result"
    for entry in results:
        wire = entry["json"]["payload"]
        payload = ProbeResultPayload.model_validate(wire)
        assert [sample.model_dump(exclude_none=True) for sample in payload.samples] == wire.get(
            "samples", []
        )
        assert payload.details == wire.get("details")
        assert payload.up is wire["up"]

    # Every §4 outcome is exercised, so a model that narrowed the vocabulary fails here rather
    # than in whichever slice-3 task first emits the outcome it dropped.
    assert {entry["json"]["payload"]["outcome"] for entry in results} == {
        "completed",
        "execution_error",
        "cancelled",
        "rejected",
    }
    assert any(entry["json"]["payload"]["up"] is False for entry in results), (
        "corpus must cover a result reporting a DOWN target"
    )


def test_discovery_payloads_survive_the_typed_models_by_name():
    """The discovery payloads' collection and summary fields asserted by name.

    Same hazard as ``test_probe_payloads_survive_the_typed_models_by_name``:
    pydantic drops unknown keys, so a model that misspelled ``open_ports`` or
    ``evidence`` validates a real finding into an empty one and the round-trip
    test above still passes — both sides of its comparison are equally empty.
    For a finding that means a discovered host silently loses every port it was
    listening on; for a summary it means the frame that *closes* a job arrives
    with no outcome and the job never finalizes.
    """
    requests = _corpus_entries_of_type(TYPE_DISCOVERY_REQUEST)
    assert requests, "corpus must cover discovery.request"
    for entry in requests:
        wire = entry["json"]["payload"]
        payload = DiscoveryRequestPayload.model_validate(wire)
        assert payload.targets == wire["targets"]
        assert payload.methods == wire["methods"]
        assert payload.tcp_ports == wire["tcp_ports"]
        assert (payload.dispatch_id, payload.scan_job_id, payload.scope_version) == (
            wire["dispatch_id"],
            wire["scan_job_id"],
            wire["scope_version"],
        )
        assert (payload.host_timeout_ms, payload.max_concurrent_hosts) == (
            wire["host_timeout_ms"],
            wire["max_concurrent_hosts"],
        )

    cancels = _corpus_entries_of_type(TYPE_DISCOVERY_CANCEL)
    assert cancels, "corpus must cover discovery.cancel"
    assert any("reason" not in e["json"]["payload"] for e in cancels), (
        "corpus must cover a cancel with no reason — it is advisory, not required"
    )
    for entry in cancels:
        wire = entry["json"]["payload"]
        payload = DiscoveryCancelPayload.model_validate(wire)
        assert payload.dispatch_id == wire["dispatch_id"]
        assert payload.reason == wire.get("reason")

    findings = _corpus_entries_of_type(TYPE_DISCOVERY_FINDING)
    assert findings, "corpus must cover discovery.finding"
    for entry in findings:
        wire = entry["json"]["payload"]
        payload = DiscoveryFindingPayload.model_validate(wire)
        assert [port.model_dump(exclude_none=True) for port in payload.open_ports] == wire.get(
            "open_ports", []
        )
        assert payload.evidence == wire.get("evidence", [])
        assert payload.terminal is wire["terminal"]
        assert (payload.ip_address, payload.mac_address, payload.hostname) == (
            wire.get("ip_address"),
            wire.get("mac_address"),
            wire.get("hostname"),
        )
        if payload.kind == DISCOVERY_KIND_SUMMARY:
            assert payload.outcome == wire["outcome"]
            assert payload.hosts_found == wire["hosts_found"]
            assert payload.addresses_scanned == wire["addresses_scanned"]

    # Both `kind` values and every summary outcome are exercised, so a model that
    # narrowed either vocabulary fails here rather than in whichever task first
    # emits the value it dropped.
    assert {e["json"]["payload"]["kind"] for e in findings} == DISCOVERY_KINDS
    assert {
        e["json"]["payload"]["outcome"]
        for e in findings
        if e["json"]["payload"]["kind"] == DISCOVERY_KIND_SUMMARY
    } == {"completed", "execution_error", "cancelled", "rejected"}
    assert any(e["json"]["payload"]["terminal"] is False for e in findings), (
        "corpus must cover a non-terminal finding — false is the value every host finding sends"
    )


def test_readiness_networks_survive_the_typed_payload_by_name():
    """D-8's mid-session network refresh, asserted the same way hello's is.

    An explicit empty list is a real report ("this agent has lost every
    interface") and must survive validation as an empty list rather than being
    conflated with an absent key — the caller distinguishes them through
    ``model_fields_set``, and only a present key narrows a live scope.
    """
    entries = [
        e
        for e in _corpus_entries_of_type(TYPE_CAPABILITY_READINESS)
        if "networks" in e["json"]["payload"]
    ]
    assert entries, "corpus must cover a readiness frame carrying networks"

    for entry in entries:
        wire = entry["json"]["payload"]
        payload = CapabilityReadinessPayload.model_validate(wire)
        assert "networks" in payload.model_fields_set
        assert [{"name": n.name, "flags": n.flags, "addrs": n.addrs} for n in payload.networks] == [
            {"name": n["name"], "flags": n.get("flags", []), "addrs": n.get("addrs", [])}
            for n in wire["networks"]
        ]

    assert any(e["json"]["payload"]["networks"] == [] for e in entries), (
        "corpus must cover an explicitly empty networks list — it is what narrows a stale scope"
    )
    # And an old-shaped frame must still validate, leaving the last report standing.
    legacy = CapabilityReadinessPayload.model_validate({"readiness": []})
    assert "networks" not in legacy.model_fields_set


def test_capability_violation_payloads_survive_the_typed_model_by_name():
    """The one inbound frame no capability grant gates, pinned on the wire.

    ``agent_link._handle_capability_violation`` drops whatever this model
    refuses, so a corpus fixture outside the closed vocabulary is not a
    backward-compatibility case like hello's partial payloads — it is a frame
    that reaches the server and writes nothing. Asserting the reasons as a set
    makes the vocabulary itself part of the fixture's contract: a model that
    narrows it, or an agent that begins emitting a reason the model never
    learned, fails here rather than in whichever task first sends it.

    The optional fields are asserted by name for the reason
    ``test_hello_networks_survive_the_typed_payload_by_name`` gives: pydantic
    ignores unknown keys, so a misspelled ``address`` or ``detail`` silently
    strips the destination an operator needs from the audit row while the
    round-trip test above still passes, both sides of its comparison equally
    empty.
    """
    entries = _corpus_entries_of_type(TYPE_CAPABILITY_VIOLATION)
    assert entries, "corpus must cover capability.violation"

    for entry in entries:
        wire = entry["json"]["payload"]
        payload = CapabilityViolationPayload.model_validate(wire)
        assert (payload.reason, payload.address, payload.detail) == (
            wire["reason"],
            wire.get("address"),
            wire.get("detail"),
        )
        # An absent `frame_type` is a real shape, not a malformed one: the reason is
        # the security signal, so the field defaults rather than rejecting.
        assert payload.frame_type == wire.get("frame_type", "")

    assert {e["json"]["payload"]["reason"] for e in entries} == CAPABILITY_VIOLATION_REASONS
    assert any("frame_type" not in e["json"]["payload"] for e in entries), (
        "corpus must cover a violation that names no frame"
    )
    # Both bounds are exercised exactly, not approached: one character wider and the
    # payload is refused and the row never written, so fixtures that stayed short would
    # not notice either cap moving. The address bound is a full IPv6 literal, which is
    # the widest untrusted value this frame may carry.
    assert (
        max(len(e["json"]["payload"].get("detail") or "") for e in entries)
        == MAX_VIOLATION_DETAIL_CHARS
    )
    assert (
        max(len(e["json"]["payload"].get("address") or "") for e in entries)
        == MAX_VIOLATION_ADDRESS_CHARS
    )
