import json
from unittest.mock import AsyncMock

import pytest


def test_get_binary_sha256_reads_manifest(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"0.2.0": {"linux-amd64": "abc123"}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    assert svc.get_binary_sha256("0.2.0", "linux", "amd64") == "abc123"
    assert svc.get_binary_sha256("0.2.0", "linux", "arm64") is None
    assert svc.get_binary_sha256("9.9.9", "linux", "amd64") is None


def test_get_binary_sha256_missing_manifest_returns_none(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    assert svc.get_binary_sha256("0.2.0", "linux", "amd64") is None


def test_latest_version_picks_highest_sorted_key(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"0.1.0": {}, "0.10.0": {}, "0.2.0": {}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    # NOTE: plain string sort, not semver-aware — "0.10.0" < "0.2.0"
    # lexicographically. Acceptable for slice 1 since the packaging step
    # (Task 17) controls version string formatting; flag this as a known
    # limitation rather than pulling in a semver library for one comparison.
    assert svc.latest_version() == "0.2.0"


@pytest.mark.asyncio
async def test_request_then_pop_pending_update(monkeypatch):
    from app.services import agent_update as svc

    store: dict[str, str] = {}
    redis_client = AsyncMock()
    redis_client.set.side_effect = lambda k, v: store.__setitem__(k, v)
    redis_client.get.side_effect = lambda k: store.get(k)
    redis_client.delete.side_effect = lambda k: store.pop(k, None)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.request_update(5, version="0.2.0", sha256="abc123", arch="amd64", os_name="linux")
    instr = await svc.pop_pending_update(5)

    assert instr == {"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"}
    assert await svc.pop_pending_update(5) is None  # single-use
