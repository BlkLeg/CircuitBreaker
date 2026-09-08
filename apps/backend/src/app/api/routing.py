"""The API route table: every router this application mounts, and where.

Split out of ``app.main`` because it is a table, not logic — 400 lines that
change whenever a feature is added and never for any other reason. Keeping it
next to app construction meant every new endpoint touched the same file as the
startup sequence and the middleware stack.

Order matters in one direction only: the SPA fallback in ``api.static_spa``
claims ``GET /{full_path:path}``, so it is registered by ``main`` after this
function returns, never from inside it.
"""

from fastapi import Depends, FastAPI

from app.api import (
    auth,
    auth_oauth,
    bootstrap,
    catalog,
    categories,
    clusters,
    compute_units,
    docs,
    environments,
    external_nodes,
    graph,
    hardware,
    inventory,
    logs,
    misc,
    networks,
    search,
    services,
    storage,
    windscribe,
)
from app.api import failed_messages as failed_messages_api
from app.api import integrations as integrations_api
from app.api import intel as intel_api
from app.api import maps as maps_api
from app.api import (
    tags as tags_api,
)
from app.api import telemetry as telemetry_api
from app.api.admin import router as admin_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_db import router as admin_db_router
from app.api.admin_users import router as admin_users_router
from app.api.agents import binary_router as agents_binary_router
from app.api.agents import router as agents_router
from app.api.assets import router as assets_router
from app.api.branding import public_router as branding_public_router
from app.api.branding import router as branding_router
from app.api.capabilities import router as capabilities_router
from app.api.certificates import router as certificates_router
from app.api.cve import router as cve_router
from app.api.discovery import router as discovery_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.integration_provider import router as integration_provider_router
from app.api.inventory_transfer import router as inventory_transfer_router
from app.api.ip_check import router as ip_check_router
from app.api.ipam import ipam_router, site_router, vlan_router
from app.api.kb import router as kb_router
from app.api.metric_alerts import router as metric_alerts_router
from app.api.metrics import router as metrics_router
from app.api.monitor import router as monitor_router
from app.api.notifications import router as notifications_router
from app.api.proxmox import router as proxmox_router
from app.api.security_status import router as security_router
from app.api.settings import router as settings_router
from app.api.system import router as system_router
from app.api.tenants import router as tenants_router
from app.api.timezones import router as timezones_router
from app.api.topologies import router as topologies_router
from app.api.vault import router as vault_router
from app.api.ws_agents import authenticated_router as ws_agents_authenticated_router
from app.api.ws_agents import unauthenticated_router as ws_agents_unauthenticated_router
from app.api.ws_discovery import router as ws_discovery_router
from app.api.ws_monitors import router as ws_monitors_router
from app.api.ws_telemetry import router as ws_telemetry_router
from app.api.ws_topology import router as ws_topology_router
from app.core.security import require_auth

_V1 = "/api/v1"


def include_all_routers(app: FastAPI) -> None:
    """Mount every API router on `app`, with its prefix, tags and auth gate."""
    app.include_router(
        hardware.router,
        prefix=f"{_V1}/hardware",
        tags=["hardware"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        hardware.hw_conn_router,
        prefix=f"{_V1}",
        tags=["hardware"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        compute_units.router,
        prefix=f"{_V1}/compute-units",
        tags=["compute-units"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        services.router,
        prefix=f"{_V1}/services",
        tags=["services"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        storage.router,
        prefix=f"{_V1}/storage",
        tags=["storage"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        networks.router,
        prefix=f"{_V1}/networks",
        tags=["networks"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        misc.router,
        prefix=f"{_V1}/misc",
        tags=["misc"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        windscribe.router,
        prefix=f"{_V1}",
        tags=["windscribe"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        docs.router,
        prefix=f"{_V1}/docs",
        tags=["docs"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        graph.router,
        prefix=f"{_V1}/graph",
        tags=["graph"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        search.router,
        prefix=f"{_V1}/search",
        tags=["search"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        inventory.router,
        prefix=f"{_V1}/inventory",
        tags=["inventory"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        logs.router,
        prefix=f"{_V1}/logs",
        tags=["logs"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        auth.user_me_router,
        prefix=f"{_V1}/users",
        tags=["users"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        auth.users_router,
        prefix=f"{_V1}/users",
        tags=["users"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(auth.router, prefix=f"{_V1}/auth", tags=["auth"])
    app.include_router(
        clusters.router,
        prefix=f"{_V1}/hardware-clusters",
        tags=["clusters"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        external_nodes.router,
        prefix=f"{_V1}/external-nodes",
        tags=["external-nodes"],
        dependencies=[Depends(require_auth)],
    )
    # Relationship deletes address a link by its own id, so they mount at the API
    # root rather than under /external-nodes/{node_id}. Same auth dependency as the
    # router above — the routes themselves also carry require_write_auth.
    app.include_router(
        external_nodes.relations_router,
        prefix=_V1,
        tags=["external-nodes"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(bootstrap.router, prefix=f"{_V1}/bootstrap", tags=["bootstrap"])
    app.include_router(
        catalog.router,
        prefix=f"{_V1}/catalog",
        tags=["catalog"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        telemetry_api.router,
        prefix=f"{_V1}/hardware",
        tags=["telemetry"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        telemetry_api.router,
        prefix=f"{_V1}/telemetry",
        tags=["telemetry"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        categories.router,
        prefix=f"{_V1}/categories",
        tags=["categories"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        environments.router,
        prefix=f"{_V1}/environments",
        tags=["environments"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        discovery_router,
        prefix=f"{_V1}/discovery",
        tags=["discovery"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        ws_discovery_router,
        prefix=f"{_V1}/discovery",
        tags=["discovery-ws"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        ws_telemetry_router,
        prefix=f"{_V1}/telemetry",
        tags=["telemetry-ws"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        ws_monitors_router,
        prefix=f"{_V1}/monitors",
        tags=["monitors-ws"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        ws_topology_router,
        prefix=f"{_V1}/topology",
        tags=["topology-ws"],
        dependencies=[Depends(require_auth)],
    )
    # Deliberately WITHOUT dependencies=[Depends(require_auth)] — the Noise IK
    # handshake performed inside /enroll (and /link, added later) is this
    # router's authentication. Every other WS router in this file requires a
    # session; this one must not.
    app.include_router(
        ws_agents_unauthenticated_router,
        prefix=f"{_V1}/agents",
        tags=["agents-ws"],
    )
    app.include_router(
        ws_agents_authenticated_router,
        prefix=f"{_V1}/agents",
        tags=["agents-ws"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        agents_router,
        prefix=f"{_V1}/agents",
        tags=["agents"],
        dependencies=[Depends(require_auth)],
    )
    # Unauthenticated — the agent has no user session; integrity comes from the
    # SHA-256 delivered over the Noise-encrypted link, not from route auth.
    app.include_router(
        agents_binary_router,
        prefix=f"{_V1}/agents",
        tags=["agents-binary"],
    )
    app.include_router(
        ip_check_router,
        prefix=f"{_V1}",
        tags=["ip-check"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        settings_router,
        prefix=f"{_V1}/settings",
        tags=["settings"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        system_router,
        prefix=f"{_V1}/system",
        tags=["system"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        branding_public_router,
        prefix=f"{_V1}/branding",
        tags=["branding"],
    )
    app.include_router(
        branding_router,
        prefix=f"{_V1}/branding",
        tags=["branding"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        assets_router,
        prefix=f"{_V1}/assets",
        tags=["assets"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        kb_router,
        prefix=f"{_V1}/kb",
        tags=["kb"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        admin_router,
        prefix=f"{_V1}/admin",
        tags=["admin"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        inventory_transfer_router,
        prefix=f"{_V1}/inventory-transfer",
        tags=["inventory-transfer"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        admin_audit_router,
        prefix=f"{_V1}/admin",
        tags=["admin-audit"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        admin_users_router,
        prefix=f"{_V1}",
        tags=["admin-users"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        admin_db_router,
        prefix=f"{_V1}/admin",
        tags=["admin-db"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        security_router,
        prefix=f"{_V1}/security",
        tags=["security"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        vault_router,
        prefix=f"{_V1}",
        tags=["vault"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        metrics_router,
        prefix=f"{_V1}/metrics",
        tags=["metrics"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        timezones_router,
        prefix=f"{_V1}/timezones",
        tags=["timezones"],
        dependencies=[Depends(require_auth)],
    )

    app.include_router(
        tags_api.router,
        prefix=f"{_V1}/tags",
        tags=["tags"],
        dependencies=[Depends(require_auth)],
    )

    app.include_router(
        capabilities_router,
        prefix=f"{_V1}/capabilities",
        tags=["capabilities"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        certificates_router,
        prefix=f"{_V1}/certificates",
        tags=["certificates"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        cve_router,
        prefix=f"{_V1}/cve",
        tags=["cve"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        metric_alerts_router,
        prefix=f"{_V1}/monitors/alert-rules",
        tags=["metric-alerts"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        monitor_router,
        prefix=f"{_V1}/monitors",
        tags=["monitors"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        events_router,
        prefix=f"{_V1}/events",
        tags=["events"],
        dependencies=[Depends(require_auth)],
    )

    app.include_router(
        notifications_router,
        prefix=f"{_V1}/notifications",
        tags=["notifications"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(auth_oauth.router, prefix=f"{_V1}", tags=["oauth"])
    app.include_router(
        integration_provider_router,
        prefix=f"{_V1}/integrations",
        tags=["integrations"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        proxmox_router,
        prefix=f"{_V1}/integrations/proxmox",
        tags=["proxmox"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        tenants_router,
        prefix=f"{_V1}/tenants",
        tags=["tenants"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        topologies_router,
        prefix=f"{_V1}/topologies",
        tags=["topologies"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        ipam_router,
        prefix=f"{_V1}/ipam",
        tags=["ipam"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        vlan_router,
        prefix=f"{_V1}/vlans",
        tags=["vlans"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        site_router,
        prefix=f"{_V1}/sites",
        tags=["sites"],
        dependencies=[Depends(require_auth)],
    )
    app.include_router(
        integrations_api.router,
        prefix=f"{_V1}/integrations",
        tags=["integrations"],
        dependencies=[Depends(require_auth)],
    )

    app.include_router(
        intel_api.router,
        prefix=f"{_V1}/intel",
        tags=["intelligence"],
        dependencies=[Depends(require_auth)],
    )

    app.include_router(
        maps_api.router,
        prefix=f"{_V1}/maps",
        tags=["maps"],
        dependencies=[Depends(require_auth)],
    )

    # Parked JetStream work (route F14). `require_auth` here and `require_role("admin")`
    # on each route: the rows carry raw payloads from the producing system, so the
    # per-route admin gate is the security boundary, not the mount.
    app.include_router(
        failed_messages_api.router,
        prefix=f"{_V1}/failed-messages",
        tags=["failed-messages"],
        dependencies=[Depends(require_auth)],
    )

    # ── Health probes ──────────────────────────────────────────────────────────
    # Unauthenticated by design: the container HEALTHCHECK, nginx and the frontend
    # connectivity poll all read these before any session exists. What they may
    # disclose is decided inside the handlers, not by a mount-level dependency.
    app.include_router(health_router, prefix=_V1)
