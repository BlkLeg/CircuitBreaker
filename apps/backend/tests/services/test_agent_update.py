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


def test_latest_version_picks_highest_semver_not_lexicographic(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"0.1.0": {}, "0.10.0": {}, "0.2.0": {}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    # Semver-aware: 0.10.0 is the highest version even though a plain
    # string sort would put "0.10.0" before "0.2.0" ("1" < "2").
    assert svc.latest_version() == "0.10.0"


def test_latest_version_picks_1_10_0_over_1_9_0(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"1.9.0": {}, "1.10.0": {}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    assert svc.latest_version() == "1.10.0"


def test_latest_version_filters_by_os_and_arch(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {
        "1.9.0": {"linux-amd64": "aaa", "linux-arm64": "bbb"},
        # 1.10.0 is the globally-highest version but never shipped a
        # windows/arm64 build — an agent reporting that os/arch must not be
        # offered it.
        "1.10.0": {"linux-amd64": "ccc"},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    assert svc.latest_version(os_name="linux", arch="amd64") == "1.10.0"
    # Highest version *compatible* with arm64 is 1.9.0, since 1.10.0 has no
    # linux-arm64 entry.
    assert svc.latest_version(os_name="linux", arch="arm64") == "1.9.0"


def test_latest_version_returns_none_for_incompatible_os_arch(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"1.9.0": {"linux-amd64": "aaa"}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    assert svc.latest_version(os_name="windows", arch="arm64") is None


def test_semver_key_orders_numerically_not_lexicographically():
    from app.services import agent_update as svc

    versions = ["1.9.0", "1.10.0", "1.2.0", "0.9.9"]
    assert sorted(versions, key=svc.semver_key) == ["0.9.9", "1.2.0", "1.9.0", "1.10.0"]


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
