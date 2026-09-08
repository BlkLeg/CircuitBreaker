"""Structured, side-effect-free Docker daemon enumeration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from requests.exceptions import Timeout as RequestsTimeout

from app.schemas.docker import (
    DockerConnectionConfig,
    DockerContainerObservation,
    DockerEnumeration,
    DockerNetworkObservation,
    DockerOutcome,
)
from app.services.discovery_safe import docker_client

_TIMEOUT_ERRORS = (TimeoutError, RequestsTimeout)


def _network_type(name: str, driver: str) -> str:
    if driver == "overlay":
        return "overlay"
    if driver == "host":
        return "host"
    if driver == "bridge":
        return "bridge"
    return "custom"


def _safe_ipam(attrs: dict[str, Any]) -> tuple[str | None, str | None]:
    configs = attrs.get("IPAM", {}).get("Config", []) or []
    first = configs[0] if configs and isinstance(configs[0], dict) else {}
    return first.get("Subnet") or None, first.get("Gateway") or None


def _workload_key(labels: dict[str, str]) -> str | None:
    project = labels.get("com.docker.compose.project")
    service = labels.get("com.docker.compose.service")
    number = labels.get("com.docker.compose.container-number")
    if not project or not service or not number:
        return None
    return f"compose:{project}:{service}:{number}"


def _container_observation(container: Any) -> DockerContainerObservation:
    attrs = container.attrs if isinstance(container.attrs, dict) else {}
    network_settings = attrs.get("NetworkSettings", {}) or {}
    attached = network_settings.get("Networks", {}) or {}
    networks: list[str] = []
    primary_ip = network_settings.get("IPAddress") or None
    for value in attached.values():
        if not isinstance(value, dict):
            continue
        native_id = value.get("NetworkID")
        if native_id:
            networks.append(str(native_id))
        if not primary_ip and value.get("IPAddress"):
            primary_ip = str(value["IPAddress"])
    raw_labels = attrs.get("Config", {}).get("Labels", {}) or {}
    labels = (
        {str(key): str(value) for key, value in raw_labels.items()}
        if isinstance(raw_labels, dict)
        else {}
    )
    tags = getattr(getattr(container, "image", None), "tags", None) or []
    image = str(tags[0]) if tags else None
    native_id = str(container.id)
    name = str(getattr(container, "name", "") or f"container-{native_id[:12]}")
    return DockerContainerObservation(
        native_id=native_id,
        short_id=str(getattr(container, "short_id", "") or native_id[:12]),
        name=name.lstrip("/"),
        image=image,
        status=str(getattr(container, "status", "unknown") or "unknown"),
        ip_address=primary_ip,
        labels=labels,
        workload_key=_workload_key(labels),
        network_ids=networks,
    )


def enumerate_docker(config: DockerConnectionConfig) -> DockerEnumeration:
    """Enumerate both resource classes with explicit completeness and safe errors."""
    attempted_at = datetime.now(UTC)
    containers: list[DockerContainerObservation] = []
    networks: list[DockerNetworkObservation] = []
    containers_complete = False
    networks_complete = False
    daemon_id: str | None = None
    failures: list[str] = []
    try:
        with docker_client(config.base_url, timeout=20) as client:
            try:
                info = client.info()
                if isinstance(info, dict) and info.get("ID"):
                    daemon_id = str(info["ID"])
            except _TIMEOUT_ERRORS:
                failures.append("daemon_info_timeout")
            except Exception:
                # Daemon identity enriches diagnostics; it is not coverage.
                daemon_id = None
            try:
                for network in client.networks.list():
                    attrs = network.attrs if isinstance(network.attrs, dict) else {}
                    name = str(getattr(network, "name", "") or "unnamed-network")
                    driver = str(attrs.get("Driver") or "")
                    kind = _network_type(name, driver)
                    if kind not in config.network_types:
                        continue
                    subnet, gateway = _safe_ipam(attrs)
                    networks.append(
                        DockerNetworkObservation(
                            native_id=str(network.id),
                            name=name,
                            driver=driver or None,
                            network_type=kind,
                            subnet=subnet,
                            gateway=gateway,
                            scope=str(attrs.get("Scope") or "") or None,
                        )
                    )
                networks_complete = True
            except _TIMEOUT_ERRORS:
                failures.append("network_enumeration_timeout")
            except Exception:
                failures.append("network_enumeration_failed")
            try:
                containers = [
                    _container_observation(container)
                    for container in client.containers.list(all=True)
                ]
                containers_complete = True
            except _TIMEOUT_ERRORS:
                failures.append("container_enumeration_timeout")
            except Exception:
                failures.append("container_enumeration_failed")
    except _TIMEOUT_ERRORS:
        failures = ["daemon_timeout"]
    except Exception:
        failures = ["daemon_unreachable"]

    if containers_complete and networks_complete:
        outcome: DockerOutcome = "success"
        reason_code = None
        safe_message = None
    elif containers_complete or networks_complete:
        outcome = "partial"
        reason_code = failures[0] if failures else "partial_enumeration"
        safe_message = "Docker returned only part of the requested inventory."
    else:
        outcome = "failed"
        reason_code = failures[0] if failures else "enumeration_failed"
        safe_message = "The configured Docker daemon could not be enumerated."

    return DockerEnumeration(
        source_identity=config.identity,
        daemon_id=daemon_id,
        outcome=outcome,
        containers_complete=containers_complete,
        networks_complete=networks_complete,
        attempted_at=attempted_at,
        completed_at=datetime.now(UTC),
        containers=containers,
        networks=networks,
        reason_code=reason_code,
        safe_message=safe_message,
    )
