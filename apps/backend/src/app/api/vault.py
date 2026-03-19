"""Vault API — key health, initialization, rotation, and decryption test endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db.session import get_db
from app.services import vault_service
from app.services.credential_vault import get_vault

router = APIRouter(tags=["vault"])


class VaultStatusResponse(BaseModel):
    status: str  # "healthy" | "ephemeral" | "degraded"
    key_source: str
    encrypted_secrets: int
    last_rotation: str | None


class VaultTestResponse(BaseModel):
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# GET /health/vault  — public-ish (admin-only read, but used by settings panel)
# ---------------------------------------------------------------------------


@router.get("/health/vault", response_model=VaultStatusResponse)
def get_vault_health(
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> dict[str, Any]:
    """Return vault status: active key source, encrypted secret count, last rotation."""
    return vault_service.get_vault_status(db)


# ---------------------------------------------------------------------------
# POST /admin/vault/initialize  — admin only
# ---------------------------------------------------------------------------


@router.post("/admin/vault/initialize", response_model=VaultStatusResponse)
def initialize_vault_key(
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> dict[str, Any]:
    """Create the first persistent vault key when the vault is uninitialized."""
    try:
        vault_service.initialize_vault_key(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return vault_service.get_vault_status(db)


# ---------------------------------------------------------------------------
# POST /admin/vault/rotate  — admin only
# ---------------------------------------------------------------------------


@router.post("/admin/vault/rotate", response_model=VaultStatusResponse)
def rotate_vault_key(
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> dict[str, Any]:
    """Re-generate the vault key and re-encrypt all secrets in-place.

    The new key is immediately written to /data/.env and the database.
    The in-memory vault singleton is hot-swapped; no restart is required.
    """
    vault_service.rotate_vault_key(db)
    return vault_service.get_vault_status(db)


# ---------------------------------------------------------------------------
# POST /admin/vault/test  — admin only
# ---------------------------------------------------------------------------


@router.post("/admin/vault/test", response_model=VaultTestResponse)
def test_vault_decryption(
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> VaultTestResponse:
    """Round-trip encrypt/decrypt a test value to verify vault health."""
    vault = get_vault()
    if not vault.is_initialized:
        return VaultTestResponse(
            ok=False,
            message="Vault is not initialized — no key loaded.",
        )
    try:
        sentinel = "circuit-breaker-vault-test-2026"
        encrypted = vault.encrypt(sentinel)
        decrypted = vault.decrypt(encrypted)
        if decrypted == sentinel:
            return VaultTestResponse(ok=True, message="Vault encryption/decryption verified.")
        return VaultTestResponse(ok=False, message="Decrypted value did not match.")
    except Exception as exc:  # noqa: BLE001
        return VaultTestResponse(ok=False, message=f"Vault test failed: {exc}")
