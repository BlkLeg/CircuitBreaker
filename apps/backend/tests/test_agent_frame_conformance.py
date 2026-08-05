import json
from pathlib import Path

import pytest

from app.schemas.agent_frame import (
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    TYPE_KEY_ROTATE,
    TYPE_TRANSPORT_REKEY,
    TYPE_UPDATE_STATUS,
    AgentFrame,
    HelloAckPayload,
    HelloPayload,
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
