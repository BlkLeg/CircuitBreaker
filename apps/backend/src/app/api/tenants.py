"""Legacy tenants API disabled for the v1 single-tenant product contract.

Circuit Breaker 1.0 supports multiple users and RBAC inside one trusted
deployment. It does not support tenant isolation as a security boundary; see
ADR 0003. The legacy route is intentionally kept mounted so stale clients and
bookmarks receive a stable, explicit response instead of accidentally
reactivating dormant tenant behavior.
"""

from fastapi import APIRouter, HTTPException, status

router = APIRouter()

_TENANCY_DISABLED_DETAIL = (
    "True multi-tenancy is not supported in Circuit Breaker 1.0. "
    "Use separate deployments for separate trust boundaries."
)


def _raise_tenancy_disabled() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=_TENANCY_DISABLED_DETAIL,
        headers={"Cache-Control": "no-store"},
    )


@router.api_route("", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@router.api_route(
    "/{legacy_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)
def tenancy_disabled() -> None:
    _raise_tenancy_disabled()
