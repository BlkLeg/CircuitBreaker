"""Docker API exposes durable admission and source state without raw endpoints."""

from unittest.mock import Mock, patch

import pytest

from app.db.models import DockerSource, Service


@pytest.mark.asyncio
async def test_manual_sync_returns_durable_run_id(
    client, auth_headers, db_session, app_cfg, monkeypatch
) -> None:
    monkeypatch.delenv("CB_DOCKER_HOST", raising=False)
    with patch("app.services.docker_discovery.run_source_sync", Mock()) as execute:
        response = await client.post("/api/v1/discovery/docker/sync", headers=auth_headers)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert len(body["run_id"]) == 32
    execute.assert_called_once_with(body["source_id"], body["run_id"])

    fetched = await client.get(
        f"/api/v1/discovery/docker/runs/{body['run_id']}", headers=auth_headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_source_reads_never_return_raw_socket_path(
    client, auth_headers, app_cfg, monkeypatch
) -> None:
    monkeypatch.delenv("CB_DOCKER_HOST", raising=False)

    response = await client.get("/api/v1/discovery/docker/sources", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()[0]["endpoint_hint"] == "local Docker socket"
    assert "/var/run/docker.sock" not in response.text


@pytest.mark.asyncio
async def test_source_container_read_is_scoped_and_carries_parent_provenance(
    client, auth_headers, db_session, app_cfg
) -> None:
    source = DockerSource(
        identity="api-source",
        name="Docker",
        connection_kind="socket",
        endpoint_hint="local Docker socket",
        enabled=True,
        revision=1,
        parent_provenance="unresolved",
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(
        Service(
            name="api",
            slug="docker-api-source",
            docker_source_id=source.id,
            docker_container_id="container-native-id",
            docker_image="api:latest",
            docker_network_ids=["network-native-id"],
            docker_parent_provenance="manual",
            is_docker_container=True,
            status="running",
        )
    )
    db_session.commit()

    response = await client.get(
        f"/api/v1/discovery/docker/sources/{source.id}/containers",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": response.json()[0]["id"],
            "source_id": source.id,
            "native_id": "container-native-id",
            "name": "api",
            "image": "api:latest",
            "status": "running",
            "ip_address": None,
            "workload_key": None,
            "network_ids": ["network-native-id"],
            "parent_type": None,
            "parent_id": None,
            "parent_provenance": "manual",
            "last_seen_at": None,
        }
    ]
