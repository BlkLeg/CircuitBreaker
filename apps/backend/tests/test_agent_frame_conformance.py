import json
from pathlib import Path

import pytest

from app.schemas.agent_frame import AgentFrame

_CORPUS_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "agent_frame_corpus.json"


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
