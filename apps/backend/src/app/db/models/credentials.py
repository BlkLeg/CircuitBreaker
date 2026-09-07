"""Encrypted secrets: per-entity credentials, integration configuration and TLS material."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

# ── Credentials (encrypted per-entity secrets) ────────────────────────────────


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    credential_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # snmp|ssh|ipmi|smtp|api_key|proxmox_api
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Integration Configs ───────────────────────────────────────────────────────


class IntegrationConfig(Base):
    __tablename__ = "integration_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # "proxmox" (extensible)
    name: Mapped[str] = mapped_column(String, nullable=False)
    config_url: Mapped[str] = mapped_column(String, nullable=False)
    credential_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("credentials.id"), nullable=True
    )
    cluster_name: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_poll_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tls_cert_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("certificates.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    credential: Mapped["Credential | None"] = relationship(
        "Credential", foreign_keys=[credential_id]
    )
    tls_cert: Mapped["Certificate | None"] = relationship("Certificate", foreign_keys=[tls_cert_id])


# ── Certificates ──────────────────────────────────────────────────────────────


class Certificate(Base):
    __tablename__ = "certificates"

    __table_args__ = (
        # INC-22: the "at most one active certificate" rule, enforced by Postgres
        # rather than by application code. Declared here *and* in the migration so
        # `create_all` (the test schema) and the migrated schema agree.
        Index(
            "ix_certificates_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="selfsigned"
    )  # letsencrypt | selfsigned
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # INC-22: which certificate is written to $CB_DATA_DIR/tls and served by nginx.
    # At most one row may hold this; the partial unique index above is the constraint,
    # not application code — two active certificates is a state with no answer.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # INC-07: how this certificate was issued, so the unattended renewal can make the same
    # choice months later. Null for anything ACME did not issue — a stored "http-01" on a
    # self-signed row would read as if ACME applied to it.
    acme_challenge: Mapped[str | None] = mapped_column(String(16))
    acme_staging: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
