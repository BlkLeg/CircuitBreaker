"""The ORM models, split by bounded context.

This was one 3,030-line module holding 86 classes, which meant every feature
change collided in the same file. It is a package now, and ``from app.db.models
import Hardware`` still works — 292 modules do exactly that, and no table,
column or migration changed when it was split.

Importing this package imports every model module, which is not optional:
``migrations/env.py`` reads ``Base.metadata`` through it and the test fixtures
build the schema with ``create_all``, so a model that is defined but never
imported is a table that silently does not exist in either.
"""

from app.db.models.agents import (
    Agent,
    AgentCapabilityGrant,
    AgentCapabilityReadiness,
    AgentEnrollmentToken,
    AgentEvent,
    AgentHostSample,
    AgentHostSampleHourly,
    AgentNetwork,
)
from app.db.models.audit import (
    AuditLog,
    Log,
    PendingAuditLog,
)
from app.db.models.auth import (
    APIToken,
    OAuthState,
    User,
    UserIcon,
    UserInvite,
    UserSession,
)
from app.db.models.common import (
    Doc,
    EntityDoc,
    EntityTag,
    Tag,
)
from app.db.models.compute import (
    Category,
    ComputeUnit,
    Environment,
)
from app.db.models.credentials import (
    Certificate,
    Credential,
    IntegrationConfig,
)
from app.db.models.discovery import (
    DiscoveryProfile,
    ListenerEvent,
    ProxmoxDiscoverRun,
    ScanJob,
    ScanLog,
    ScanResult,
)
from app.db.models.external import (
    ExternalNode,
    ExternalNodeNetwork,
    ServiceExternalNode,
)
from app.db.models.hardware import (
    Hardware,
    HardwareCluster,
    HardwareClusterMember,
    HardwareConnection,
)
from app.db.models.integrations import (
    Integration,
    IntegrationMonitor,
    IntegrationMonitorEvent,
)
from app.db.models.intel import (
    CapacityForecast,
    CVEEntry,
    FlapIncident,
    ResourceEfficiencyRecommendation,
)
from app.db.models.kb import (
    KbHostname,
    KbOui,
)
from app.db.models.monitors import (
    HardwareMonitor,
    MonitorDailyStats,
    MonitorEvent,
    MonitorItem,
    MonitorProbeRun,
    UptimeEvent,
)
from app.db.models.networks import (
    VLAN,
    ComputeNetwork,
    HardwareNetwork,
    IPAddress,
    Network,
    NetworkPeer,
    Site,
)
from app.db.models.notifications import (
    NotificationRoute,
    NotificationSink,
)
from app.db.models.privacy import (
    NetworkPrivacySnapshot,
    PrivacyFindingIgnore,
    PrivacyScoreHistory,
)
from app.db.models.services import (
    MiscItem,
    Service,
    ServiceDependency,
    ServiceMisc,
    ServiceStorage,
    Storage,
)
from app.db.models.settings import (
    AppSettings,
    DeviceRole,
    Onboarding,
)
from app.db.models.telemetry import (
    HardwareLiveMetric,
    LiveMetric,
    TelemetryTimeseries,
)
from app.db.models.tenants import (
    Tenant,
    tenant_members,
)
from app.db.models.topology import (
    GraphLayout,
    MapPinnedEntity,
    NodeRelation,
    Topology,
    TopologyEdge,
    TopologyNode,
)

# `FailedMessage` lives outside this package (`models_failed_message`) because
# the JetStream work it belongs to is parked. It is imported here for the same
# reason as everything above: a model this package never imports is a table
# Alembic autogenerate and `create_all` both miss.
from app.db.models_failed_message import FailedMessage
from app.db.session import Base

__all__ = [
    "APIToken",
    "Agent",
    "AgentCapabilityGrant",
    "AgentCapabilityReadiness",
    "AgentEnrollmentToken",
    "AgentEvent",
    "AgentHostSample",
    "AgentHostSampleHourly",
    "AgentNetwork",
    "AppSettings",
    "AuditLog",
    "Base",
    "CVEEntry",
    "CapacityForecast",
    "Category",
    "Certificate",
    "ComputeNetwork",
    "ComputeUnit",
    "Credential",
    "DeviceRole",
    "DiscoveryProfile",
    "Doc",
    "EntityDoc",
    "EntityTag",
    "Environment",
    "ExternalNode",
    "ExternalNodeNetwork",
    "FailedMessage",
    "FlapIncident",
    "GraphLayout",
    "Hardware",
    "HardwareCluster",
    "HardwareClusterMember",
    "HardwareConnection",
    "HardwareLiveMetric",
    "HardwareMonitor",
    "HardwareNetwork",
    "IPAddress",
    "Integration",
    "IntegrationConfig",
    "IntegrationMonitor",
    "IntegrationMonitorEvent",
    "KbHostname",
    "KbOui",
    "ListenerEvent",
    "LiveMetric",
    "Log",
    "MapPinnedEntity",
    "MiscItem",
    "MonitorDailyStats",
    "MonitorEvent",
    "MonitorItem",
    "MonitorProbeRun",
    "Network",
    "NetworkPeer",
    "NetworkPrivacySnapshot",
    "NodeRelation",
    "NotificationRoute",
    "NotificationSink",
    "OAuthState",
    "Onboarding",
    "PendingAuditLog",
    "PrivacyFindingIgnore",
    "PrivacyScoreHistory",
    "ProxmoxDiscoverRun",
    "ResourceEfficiencyRecommendation",
    "ScanJob",
    "ScanLog",
    "ScanResult",
    "Service",
    "ServiceDependency",
    "ServiceExternalNode",
    "ServiceMisc",
    "ServiceStorage",
    "Site",
    "Storage",
    "Tag",
    "TelemetryTimeseries",
    "Tenant",
    "Topology",
    "TopologyEdge",
    "TopologyNode",
    "UptimeEvent",
    "User",
    "UserIcon",
    "UserInvite",
    "UserSession",
    "VLAN",
    "tenant_members",
]
