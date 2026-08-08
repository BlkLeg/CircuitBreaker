# apps/backend/tests/services/test_monitor_probe_stream.py
"""D-3: `mon.probe.remote` rides its own MONITOR_PROBE work-queue stream.

`ensure_monitor_poll_stream()` swallows "already in use" at debug level, so adding a
subject to MONITOR_POLL's list would silently never apply to an already-deployed
stream and every publish to the new subject would fail. These tests pin the split.
"""

import ast
import asyncio
from pathlib import Path

import app.core.nats_client as nats_client_mod
from app.core.nats_client import NATSClient
from app.core.subjects import MONITOR_POLL_ITEM, MONITOR_PROBE_REMOTE


class _FakeJetStream:
    def __init__(self) -> None:
        self.streams: list[dict] = []

    async def add_stream(self, **kwargs):
        self.streams.append(kwargs)
        return object()


def _client_with_fake_js() -> tuple[NATSClient, _FakeJetStream]:
    client = NATSClient(url="nats://unused:4222")
    js = _FakeJetStream()
    client._js = js
    client._connected = True
    return client, js


def test_ensure_monitor_probe_stream_declares_a_separate_work_queue_stream():
    from nats.js.api import RetentionPolicy

    client, js = _client_with_fake_js()

    asyncio.run(client.ensure_monitor_probe_stream())

    assert len(js.streams) == 1
    decl = js.streams[0]
    assert decl["name"] == "MONITOR_PROBE"
    assert decl["subjects"] == [MONITOR_PROBE_REMOTE]
    assert decl["subjects"] == ["mon.probe.remote"]
    assert decl["retention"] == RetentionPolicy.WORK_QUEUE
    # An assignment older than its deadline must not surface minutes late.
    assert decl["max_age"] == 60


def test_ensure_monitor_probe_stream_max_age_is_env_tunable(monkeypatch):
    monkeypatch.setenv("CB_MONITOR_PROBE_MAX_AGE_S", "17")
    client, js = _client_with_fake_js()

    asyncio.run(client.ensure_monitor_probe_stream())

    assert js.streams[0]["max_age"] == 17


def test_ensure_monitor_probe_stream_is_a_no_op_while_disconnected():
    client, js = _client_with_fake_js()
    client._connected = False

    asyncio.run(client.ensure_monitor_probe_stream())

    assert js.streams == []


def test_ensure_monitor_probe_stream_swallows_already_in_use():
    client, _js = _client_with_fake_js()

    class _Boom:
        async def add_stream(self, **kwargs):
            raise Exception("stream name already in use")

    client._js = _Boom()

    asyncio.run(client.ensure_monitor_probe_stream())  # must not raise


def test_monitor_probe_remote_is_not_added_to_the_monitor_poll_subject_list():
    client, js = _client_with_fake_js()

    asyncio.run(client.ensure_monitor_poll_stream())

    assert len(js.streams) == 1
    poll = js.streams[0]
    assert poll["name"] == "MONITOR_POLL"
    assert poll["subjects"] == [MONITOR_POLL_ITEM]
    assert MONITOR_PROBE_REMOTE not in poll["subjects"]


def test_probe_stream_is_ensured_alongside_the_poll_stream_on_connect():
    """Every site that ensures MONITOR_POLL must also ensure MONITOR_PROBE."""
    source = Path(nats_client_mod.__file__).read_text()
    poll_sites = source.count("ensure_monitor_poll_stream()")
    probe_sites = source.count("ensure_monitor_probe_stream()")
    # The `async def ensure_..._stream(self)` lines carry `(self)`, so only calls match.
    assert poll_sites >= 2, "expected the connect and reconnect ensure sites"
    assert probe_sites == poll_sites

    from app.workers import monitor_scheduler

    worker_source = Path(monitor_scheduler.__file__).read_text()
    assert "ensure_monitor_probe_stream()" in worker_source


def _hardcoded_subject_literals(module: Path) -> bool:
    """True if `module` names the subject as a code literal rather than importing it.

    Docstrings and comments are exempt on purpose: the constraint is that no call site
    may carry its own copy of the subject, and prose describing which subject a worker
    consumes is not a second declaration that can drift out of sync with the first.
    """
    tree = ast.parse(module.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return any(
        node.value == MONITOR_PROBE_REMOTE and id(node) not in docstrings
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_subject_constant_is_not_hardcoded_at_any_call_site():
    src = Path(nats_client_mod.__file__).resolve().parents[1]
    assert src.name == "app"
    owner = src / "core" / "subjects.py"

    offenders = sorted(
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if "__pycache__" not in path.parts and path != owner and _hardcoded_subject_literals(path)
    )
    assert offenders == [], f"subject literal must live only in core/subjects.py: {offenders}"
    assert 'MONITOR_PROBE_REMOTE = "mon.probe.remote"' in owner.read_text()
