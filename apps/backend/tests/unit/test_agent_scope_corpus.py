"""Drives `fixtures/agent_scope_corpus.json` through the backend scope evaluator.

The corpus is shared with `apps/agent/internal/netscope`: §3 requires the backend
and the agent to enforce scope independently, which is only a safety property if
the two enforce the *same* scope. A rule that exists on one side only shows up
here or in the Go twin as a decision mismatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.agent_scope import derive_scope, evaluate

_CORPUS_PATH = Path(__file__).resolve().parents[4] / "fixtures" / "agent_scope_corpus.json"


def _load_corpus() -> list[dict]:
    return json.loads(_CORPUS_PATH.read_text())


@pytest.mark.parametrize("entry", _load_corpus(), ids=lambda e: e["description"])
def test_every_corpus_case_matches_the_evaluator(entry):
    scope = derive_scope(entry["facts"], entry["config"])
    destination = entry["destination"]

    decision = evaluate(scope, destination["host"], resolved=destination.get("resolved"))

    assert decision.allowed is (entry["expected"] == "allow")
    assert decision.reason == entry["reason"]
