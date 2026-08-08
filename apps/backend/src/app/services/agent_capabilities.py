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

This module imports nothing from `app` outside `core` per **D-14**, so both the
service layer (`services/agent_registry.py`) and the schema layer
(`schemas/agents.py`) can import it at module scope with no cycle and without
the schema layer pulling in a DB-touching service. `core.agent_scope` is the
one exception and stays inside that rule: it is stdlib-only itself, and the
alternative — a second CIDR rule set written here — is the duplication the
"one scope evaluator" constraint exists to forbid.

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

from app.core.agent_scope import (
    SCOPE_MODE_DIRECT_PRIVATE,
    SCOPE_MODES,
    normalize_scope_cidrs,
    normalize_scope_hostname,
)


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


_REMOTE_PROBE_DEFAULT_CONFIG: Mapping[str, Any] = MappingProxyType(
    {
        "max_concurrent": 20,
        "scope_mode": SCOPE_MODE_DIRECT_PRIVATE,
        "excluded_cidrs": (),
        "additional_cidrs": (),
        "additional_hostnames": (),
    }
)


def _materialized(defaults: Mapping[str, Any]) -> dict[str, Any]:
    """A mutable copy of `defaults` with its tuple values turned into lists.

    List-valued defaults are stored as tuples so the registry itself cannot be
    mutated through them, but a tuple must never leave this module: it would be
    handed to a normalizer that type-checks for `list`, and JSON round-trips it
    to a list anyway, so the two would disagree about a config that never
    changed. This is the single place that conversion happens.
    """
    return {key: list(v) if isinstance(v, tuple) else v for key, v in defaults.items()}


def _normalize_remote_probe_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate a `remote_probe` grant config (design §3).

    Every CIDR and hostname rule is delegated to `core.agent_scope`, which is
    also what the dispatcher and the Go agent evaluate against — an
    administrator must not be able to save a scope entry that the evaluator
    would later read differently, or "the backend approved it" stops implying
    "the agent will accept it". That includes the *type* checks: each field is
    passed through untouched so `agent_scope` raises its own `ValueError`,
    which `schemas/agents.py::_validate_capability_map` turns into a 422.
    Widening a value on the way in (`list(...)`) would defeat the check and
    surface administrator error as a 500 instead.
    """
    unknown = set(config) - set(_REMOTE_PROBE_DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown remote probe settings: {', '.join(sorted(unknown))}")
    normalized = _materialized(_REMOTE_PROBE_DEFAULT_CONFIG) | config
    limit = normalized["max_concurrent"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("remote probe max_concurrent must be between 1 and 100")
    # `in` on a frozenset is a hash lookup, so an unhashable value raises
    # `TypeError` rather than answering False — the type test has to come first.
    if not isinstance(normalized["scope_mode"], str) or normalized["scope_mode"] not in SCOPE_MODES:
        known = ", ".join(sorted(SCOPE_MODES))
        raise ValueError(f"remote probe scope_mode must be one of: {known}")
    normalized["excluded_cidrs"] = normalize_scope_cidrs(
        normalized["excluded_cidrs"], field="excluded_cidrs"
    )
    normalized["additional_cidrs"] = normalize_scope_cidrs(
        normalized["additional_cidrs"], field="additional_cidrs"
    )
    hostnames = normalized["additional_hostnames"]
    if not isinstance(hostnames, list):
        raise ValueError("additional_hostnames must be a list of hostnames")
    normalized["additional_hostnames"] = sorted(
        {normalize_scope_hostname(name) for name in hostnames}
    )
    return normalized


def _reject_unknown_keys(capability: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Normalizer for a capability that has no configurable settings *yet*.

    The allow-set is `default_config`'s own keys, which is empty today for
    `local_discovery` — so any config supplied for it is rejected rather than
    silently persisted and shipped to an agent that has no idea what to do with
    it. Slice 4 replaces that entry with real defaults plus a real normalizer;
    nothing else has to change.
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
        default_config=_REMOTE_PROBE_DEFAULT_CONFIG,
        normalize=_normalize_remote_probe_config,
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
    merged = _materialized(definition.default_config) | dict(current_config or {}) | supplied
    return enabled, definition.normalize(merged)


def default_config_for(capability: str) -> dict[str, Any]:
    """Registry default config for `capability`, or `{}` if it isn't a known
    capability.

    Deliberately `.get`, never `[capability]`: read paths such as
    `structured_grants_dict` run over whatever grant rows exist, which may name
    a capability this build's registry no longer declares (a removed slice, a
    downgrade). Those rows must still render, not raise.

    Fresh lists on every read (`_materialized`): callers merge this into the
    config they hand to an API response or a grant row, and a shared `[]` would
    let one of them widen every future agent's default scope.
    """
    definition = CAPABILITY_DEFINITIONS.get(capability)
    if definition is None:
        return {}
    return _materialized(definition.default_config)
