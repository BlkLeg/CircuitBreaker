"""The addresses an operator declares for agents to dial.

Deliberately not `api_base_url`: that is the browser-facing URL, and the
address a browser uses can legitimately differ from the one an agent uses.
See docs/design/2026-09-05-agent-reachability-design.md §3.1.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, AppSettings

# A scheme-and-host check, deliberately NOT core.url_validation: its
# `_is_forbidden_address` rejects private addresses unless `allow_private` is
# set, so it would refuse https://192.168.0.51 — the LAN endpoint an operator
# most needs to declare. It also resolves DNS, which answers the wrong question:
# what matters is whether the address resolves from the *agent*.
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ID_BYTES = 6
_MAX_LABEL = 60


def _mint_id() -> str:
    """A short, opaque, never-reused endpoint id."""
    return secrets.token_hex(_ID_BYTES)


def normalize_endpoints(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate operator-supplied endpoints, minting ids for new ones.

    Raises ValueError with an operator-readable message on any bad entry.
    """
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        label = str(entry.get("label") or "").strip()
        if not label:
            raise ValueError("each endpoint needs a label")
        if len(label) > _MAX_LABEL:
            raise ValueError(f"label is longer than {_MAX_LABEL} characters: {label[:20]}...")

        url = str(entry.get("url") or "").strip().rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"endpoint '{label}' has an unsupported URL scheme: {parsed.scheme!r}")
        if not parsed.netloc:
            raise ValueError(f"endpoint '{label}' has no host")
        # Every fetch is built as `{url}/install-agent.sh` or
        # `{url}/api/v1/...`, so a base with a path produces
        # `https://example.com/cb/install-agent.sh` — a 404 the operator only
        # discovers on the target machine, long after saving. The trailing
        # slash was stripped above, so a bare `https://example.com/` still
        # passes.
        if parsed.path:
            raise ValueError(
                f"endpoint '{label}' must be a scheme and host only, with no path: {parsed.path}"
            )

        endpoint_id = str(entry.get("id") or "").strip() or _mint_id()
        if endpoint_id in seen:
            raise ValueError(f"duplicate endpoint id: {endpoint_id}")
        seen.add(endpoint_id)

        result.append({"id": endpoint_id, "label": label, "url": url})
    return result


def list_endpoints(db: Session) -> list[dict[str, str]]:
    """Every configured endpoint, or [] when none are."""
    row = db.get(AppSettings, 1)
    return list(row.agent_endpoints or []) if row is not None else []


def find_endpoint(db: Session, endpoint_id: str) -> dict[str, str] | None:
    """The endpoint with this id, or None when it does not exist.

    None is what makes the caller 404 rather than silently substituting a
    different address — see the design's §7 note on why falling back here would
    reintroduce the defect this work exists to fix.
    """
    for endpoint in list_endpoints(db):
        if endpoint.get("id") == endpoint_id:
            return endpoint
    return None


def usage_counts(db: Session) -> dict[str, int]:
    """How many agents enrolled through each endpoint, keyed by URL.

    Keyed by URL rather than endpoint id so a deleted endpoint still accounts
    for the agents that came through it — those agents keep dialing that
    address whether or not it is still in the list.

    Agents that enrolled before the server recorded the address are excluded
    rather than bucketed under a placeholder: they are not evidence that any
    particular endpoint works.
    """
    rows = db.execute(
        select(Agent.enrolled_via_endpoint, func.count())
        .where(Agent.enrolled_via_endpoint.is_not(None))
        .group_by(Agent.enrolled_via_endpoint)
    ).all()
    return {url: count for url, count in rows}
