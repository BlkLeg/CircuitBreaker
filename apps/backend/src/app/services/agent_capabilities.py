"""The single server-side registry of agent capabilities (Task 14, **D-14**).

`CAPABILITY_DEFINITIONS` is the one place a capability's name, approval
default, default configuration, and config normalizer are declared. It
replaces the four copies this repo used to carry — `agent_registry.
DEFAULT_CAPABILITY_GRANTS` / `HOST_TELEMETRY_DEFAULT_CONFIG`, `schemas/agents.
py`'s `HOST_TELEMETRY_DEFAULTS`, `AgentApprovalModal.jsx`'s `NORMAL_PRESET`,
and `AgentDetailPage.jsx`'s `HOST_DEFAULTS` — the last two of which now read
`GET /api/v1/agents/capability-defaults` instead. Its agent-side mirror is
`apps/agent/internal/capability`'s `configNormalizers`. **A new slice adds
exactly one entry here and one there, and touches nothing else.**

This module imports nothing from `app` (typing/stdlib only) per **D-14**, so
both the service layer (`services/agent_registry.py`) and the schema layer
(`schemas/agents.py`) can import it at module scope with no cycle and without
the schema layer pulling in a DB-touching service.

**Invariant — upgrades never silently enable a new capability on an
already-approved agent.** `default_enabled` is consulted *only* by
`agent_registry.approve_agent`, at the moment grant rows are first written.
A capability with no `agent_capability_grants` row is denied everywhere: no
read path (`grants_dict`, `structured_grants_dict`,
`bulk_structured_grants_dict`) falls back to `default_enabled`, and no
migration may backfill grant rows. Adding an
entry below therefore changes what *future* approvals grant and nothing else.
Pinned by `test_new_registry_entry_is_not_backfilled_onto_already_approved_agents`,
which must never be deleted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class CapabilityDefinition:
    """One capability's server-side contract.

    `normalize` receives the fully merged config (registry defaults, then the
    grant's currently stored config, then whatever the caller supplied) and
    either returns the value to persist or raises `ValueError`.
    """

    name: str
    default_enabled: bool
    default_config: Mapping[str, Any]
    normalize: Callable[[dict[str, Any]], dict[str, Any]]


_HOST_TELEMETRY_DEFAULT_CONFIG: Mapping[str, Any] = MappingProxyType(
    {
        "interval_s": 30,
        "include_filesystems": True,
        "include_disks": True,
        "include_network": True,
        "include_temperatures": True,
        "include_virtual": False,
        "include_docker": False,
    }
)


def _normalize_host_telemetry_config(config: dict[str, Any]) -> dict[str, Any]:
    unknown = set(config) - set(_HOST_TELEMETRY_DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown host telemetry settings: {', '.join(sorted(unknown))}")
    normalized = dict(_HOST_TELEMETRY_DEFAULT_CONFIG) | config
    interval = normalized["interval_s"]
    if isinstance(interval, bool) or not isinstance(interval, int) or not 10 <= interval <= 900:
        raise ValueError("host telemetry interval must be between 10 and 900 seconds")
    if any(not isinstance(normalized[name], bool) for name in normalized if name != "interval_s"):
        raise ValueError("host telemetry include settings must be booleans")
    return normalized


def _reject_unknown_keys(capability: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Normalizer for a capability that has no configurable settings *yet*.

    The allow-set is `default_config`'s own keys, which is empty today for
    `remote_probe` and `local_discovery` — so any config supplied for them is
    rejected rather than silently persisted and shipped to an agent that has
    no idea what to do with it. Slices 3 and 4 replace these entries with real
    defaults plus a real normalizer; nothing else has to change.
    """

    def normalize(config: dict[str, Any]) -> dict[str, Any]:
        allowed = set(CAPABILITY_DEFINITIONS[capability].default_config)
        unknown = set(config) - allowed
        if unknown:
            raise ValueError(f"unknown {capability} settings: {', '.join(sorted(unknown))}")
        return dict(config)

    return normalize


CAPABILITY_DEFINITIONS: dict[str, CapabilityDefinition] = {
    "host_telemetry": CapabilityDefinition(
        name="host_telemetry",
        default_enabled=True,
        default_config=_HOST_TELEMETRY_DEFAULT_CONFIG,
        normalize=_normalize_host_telemetry_config,
    ),
    # D-10: granted-but-idle is the design. `remote_probe` executes nothing
    # until a monitor is explicitly assigned and `local_discovery` is bounded
    # by the `direct_private` derived scope, so approving with `capabilities`
    # omitted grants all three and the approver keeps a per-capability opt-out
    # in the approval modal.
    "remote_probe": CapabilityDefinition(
        name="remote_probe",
        default_enabled=True,
        default_config=MappingProxyType({}),
        normalize=_reject_unknown_keys("remote_probe"),
    ),
    "local_discovery": CapabilityDefinition(
        name="local_discovery",
        default_enabled=True,
        default_config=MappingProxyType({}),
        normalize=_reject_unknown_keys("local_discovery"),
    ),
}


def _grant_parts(value: Any) -> tuple[bool, dict[str, Any]]:
    if isinstance(value, bool):
        return value, {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        raise ValueError("capability grant must be a boolean or {enabled, config} object")
    config = value.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("capability grant config must be an object")
    return value["enabled"], config


def normalize_grant(
    capability: str,
    value: Any,
    *,
    current_config: Mapping[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Resolve one requested grant into `(enabled, config)` ready to persist.

    `value` is either a bare boolean or an `{enabled, config}` object (a dict or
    a `CapabilityGrant` — the wire contract keeps accepting both, indefinitely).
    Config precedence is registry default < `current_config` (the grant row's
    existing config, on an update) < what the caller supplied, and the merged
    result goes through `definition.normalize`.

    **This is the single place a bare-boolean grant acquires its default
    config**, which is why `{"remote_probe": true}` cannot persist `{}` once
    slice 3 gives `remote_probe` real defaults.

    Raises `ValueError` for an unknown capability name or an invalid config;
    the schema layer turns that into a 422.
    """
    definition = CAPABILITY_DEFINITIONS.get(capability)
    if definition is None:
        known = ", ".join(sorted(CAPABILITY_DEFINITIONS))
        raise ValueError(f"unknown capability '{capability}' (known: {known})")
    enabled, supplied = _grant_parts(value)
    merged = dict(definition.default_config) | dict(current_config or {}) | supplied
    return enabled, definition.normalize(merged)


def default_config_for(capability: str) -> dict[str, Any]:
    """Registry default config for `capability`, or `{}` if it isn't a known
    capability.

    Deliberately `.get`, never `[capability]`: read paths such as
    `structured_grants_dict` run over whatever grant rows exist, which may name
    a capability this build's registry no longer declares (a removed slice, a
    downgrade). Those rows must still render, not raise.
    """
    definition = CAPABILITY_DEFINITIONS.get(capability)
    return dict(definition.default_config) if definition is not None else {}
