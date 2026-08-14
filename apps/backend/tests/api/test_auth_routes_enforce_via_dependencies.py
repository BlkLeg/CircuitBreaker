"""Account and MFA mutations enforce auth through dependencies, not in-handler.

These routes used to read `get_optional_user` and raise 401 themselves. That
works at runtime but is invisible to the SEC-06/07 endpoint gate, which walks
the dependency tree: the gate saw an *optional* auth dependency and had to be
told, by a hand-written `auth-internal` exemption in endpoint_policy.json, that
the route was really protected. Eight mutating routes — including account
deletion and MFA disable — sat behind that promise with nothing checking it.

They now depend on `require_auth_always`, so the gate derives the protection
instead of trusting a comment, and the `auth-internal` exemption category is
empty. `/auth/logout` is deliberately excluded: it is idempotent teardown that
must stay reachable once a token has expired, and is declared `auth-flow`.
"""

import json
from pathlib import Path

import pytest

# No module-level asyncio mark: pytest is configured with asyncio_mode="auto",
# and marking the whole module would drag the sync policy-file check into it.
_POLICY = Path(__file__).resolve().parents[2] / "src/app/security/endpoint_policy.json"

_DEPENDENCY_ENFORCED = [
    ("GET", "/api/v1/auth/me", None),
    ("DELETE", "/api/v1/auth/me", None),
    ("PUT", "/api/v1/auth/me/avatar", None),
    ("POST", "/api/v1/auth/mfa/setup", None),
    ("POST", "/api/v1/auth/mfa/activate", {"code": "000000"}),
    ("POST", "/api/v1/auth/mfa/disable", {"code": "000000"}),
    ("POST", "/api/v1/auth/mfa/backup-codes/regenerate", {"code": "000000"}),
]


@pytest.mark.parametrize(("method", "path", "body"), _DEPENDENCY_ENFORCED)
async def test_route_rejects_anonymous_caller(client, method, path, body):
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 401, f"{method} {path} → {resp.status_code}: {resp.text}"


def test_no_route_claims_the_gate_blind_auth_internal_exemption():
    """`auth-internal` meant "trust me, the handler checks" — nothing verified it.

    If a route genuinely needs to do its own auth, give it a policy the gate can
    reason about (`auth-flow`, `bootstrap`) with a reason stating why, rather
    than reviving a category that exempts it from the dependency-tree check.
    """
    policy = json.loads(_POLICY.read_text(encoding="utf-8"))
    offenders = [
        f"{r.get('methods')} {r.get('path')}"
        for r in policy["routes"]
        if r.get("policy") == "auth-internal"
    ]
    assert offenders == [], f"auth-internal reintroduced for: {offenders}"


async def test_logout_stays_reachable_without_a_valid_session(client):
    """Excluded on purpose — a client whose token expired must still log out."""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code in (204, 200), resp.text
