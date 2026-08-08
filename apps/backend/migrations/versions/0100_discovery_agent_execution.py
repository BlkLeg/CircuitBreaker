"""Add the discovery execution-location columns, dispatch lease, and finding key.

Revision ID: 0100_discovery_agent_execution
Revises: 0099_monitor_probe_runs
Create Date: 2026-08-08

Slice 4 Task 4 / plan §2. Discovery gains an *execution location*: a profile
and a job may name one agent (``scan_agent_id IS NULL`` is every profile and
job that exists today, and stays the server scanner). A job dispatched to an
agent carries a lease — ``dispatch_id``, ``dispatch_status``,
``dispatch_deadline_at`` — so a silent agent is a recoverable state rather than
a job that hangs forever, and each accepted finding carries a ``finding_id``
so spool replay after an outage cannot double-insert a result.

All three discovery tables are in ``0001_init``'s ``_EXCLUDED_COLUMNS``, so this
revision is what creates these columns on a fresh install as well as on an
upgrade — the same shape ``0099_monitor_probe_runs.py`` uses, and for both of
the same reasons:

* Every new FK points at ``agents``, an excluded *table*, so the bootstrap's
  ``_should_copy_fk`` would drop the constraint and emit a bare integer. That
  would silently void the RESTRICT lifecycle below on every new deployment —
  and with it the 409 that stops an operator deleting an agent a discovery
  profile still points at.
* Three of the new indexes are **partial**, and the bootstrap's index-copy loop
  rebuilds indexes as ``sa.Index(name, *cols, unique=...)`` and discards
  ``postgresql_where``. A full unique index on ``(scan_job_id, finding_id)``
  would break every result row after the first with a NULL ``finding_id`` —
  which is every row the server scanner has ever written.

There is deliberately **no** partial unique index over the dispatch lease,
unlike ``uq_monitor_probe_runs_active``. That one works because a probe lease is
its own row and two racing workers would insert two of them; a discovery lease
lives *on the job row*, so there is only ever one row and a unique index over it
enforces nothing. The race is two workers both reading ``dispatch_status IS
NULL`` and both writing ``dispatched``, which only a conditional UPDATE can
stop. ``uq_scan_jobs_dispatch_id`` does carry real weight, though: it makes a
replayed or duplicated dispatch token an integrity error rather than two jobs
quietly sharing one.

The FK lifecycle splits deliberately, mirroring what Slice 3 settled for
monitors: RESTRICT on the *live assignment* (``discovery_profiles``, like
``monitor_items.probe_agent_id``) and CASCADE on *finished history*
(``scan_jobs`` / ``scan_results``, like ``monitor_probe_runs.agent_id``).
RESTRICT everywhere would make an agent permanently undeletable, because the
retention purge is disabled outright when ``discovery_retention_days <= 0``.
Plan §2's actual invariant — "revocation does not erase provenance" — is
untouched by that: revocation sets ``agents.status='revoked'`` and deletes no
row.

Every step inspects first, so replaying is safe. Nothing is backfilled:
``scan_agent_id`` stays NULL for every existing profile and job, which is how
"this is server-executed" is told apart from "its agent is unknown".
"""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0100_discovery_agent_execution"
down_revision = "0099_monitor_probe_runs"
branch_labels = None
depends_on = None

_PROFILES = "discovery_profiles"
_JOBS = "scan_jobs"
_RESULTS = "scan_results"
_RESULT_POLICY = "tenant_isolation_scan_results"

# Ordered so the downgrade can drop them back to front. Each entry builds a
# fresh `sa.Column` because a `ForeignKey` object binds to exactly one column
# and this migration is replayed (idempotently) rather than run once.
_PROFILE_COLUMNS: tuple[tuple[str, Callable[[], sa.Column]], ...] = (
    (
        "scan_agent_id",
        lambda: sa.Column(
            "scan_agent_id",
            sa.Integer(),
            sa.ForeignKey(
                "agents.id",
                ondelete="RESTRICT",
                name="fk_discovery_profiles_scan_agent_id_agents",
            ),
            nullable=True,
        ),
    ),
    # The canonical `ipaddress.ip_network(...)` form of `cidr`. The uniqueness
    # rule for system-managed profiles needs a stable key, and `cidr` as an
    # administrator typed it is not one: "10.0.0.5/24" and "10.0.0.0/24" name
    # the same segment.
    ("normalized_cidr", lambda: sa.Column("normalized_cidr", sa.String(), nullable=True)),
    # NULL for a user-created profile, 'system' for one the bootstrap owns.
    # Without it the uniqueness rule below would collide with a user profile
    # targeting the same CIDR, which plan §3 forbids.
    ("managed_by", lambda: sa.Column("managed_by", sa.String(16), nullable=True)),
    ("paused_at", lambda: sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True)),
)

_JOB_COLUMNS: tuple[tuple[str, Callable[[], sa.Column]], ...] = (
    (
        "scan_agent_id",
        lambda: sa.Column(
            "scan_agent_id",
            sa.Integer(),
            sa.ForeignKey(
                "agents.id",
                ondelete="CASCADE",
                name="fk_scan_jobs_scan_agent_id_agents",
            ),
            nullable=True,
        ),
    ),
    ("dispatch_id", lambda: sa.Column("dispatch_id", sa.String(32), nullable=True)),
    ("dispatch_status", lambda: sa.Column("dispatch_status", sa.String(24), nullable=True)),
    (
        "dispatch_deadline_at",
        lambda: sa.Column("dispatch_deadline_at", sa.DateTime(timezone=True), nullable=True),
    ),
    (
        "last_finding_at",
        lambda: sa.Column("last_finding_at", sa.DateTime(timezone=True), nullable=True),
    ),
    (
        "finding_count",
        lambda: sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
    ),
    # The `EffectiveScope.version` in force when the request was dispatched.
    # Plan §2 requires an active request to be cancelled when scope changes
    # incompatibly, and comparing a digest is what makes that possible without
    # diffing CIDR lists on every readiness frame.
    ("scope_version", lambda: sa.Column("scope_version", sa.String(64), nullable=True)),
)

_RESULT_COLUMNS: tuple[tuple[str, Callable[[], sa.Column]], ...] = (
    (
        "discovery_agent_id",
        lambda: sa.Column(
            "discovery_agent_id",
            sa.Integer(),
            sa.ForeignKey(
                "agents.id",
                ondelete="CASCADE",
                name="fk_scan_results_discovery_agent_id_agents",
            ),
            nullable=True,
        ),
    ),
    ("finding_id", lambda: sa.Column("finding_id", sa.String(64), nullable=True)),
    # `scan_jobs` already carries a tenant and `scan_results` did not, so plan
    # §8's "tenant context is derived from the job/agent, never accepted from a
    # finding" had nothing at result level to assert against.
    (
        "tenant_id",
        lambda: sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey(
                "tenants.id",
                ondelete="SET NULL",
                name="fk_scan_results_tenant_id_tenants",
            ),
            nullable=True,
        ),
    ),
)

_PROFILE_INDEXES = (
    "ix_discovery_profiles_scan_agent_id",
    "uq_discovery_profiles_system_agent_cidr",
)
_JOB_INDEXES = (
    "ix_scan_jobs_profile_id",
    "ix_scan_jobs_agent_status_created",
    "uq_scan_jobs_dispatch_id",
)
_RESULT_INDEXES = (
    "ix_scan_results_discovery_agent_id",
    "ix_scan_results_tenant_id",
    "uq_scan_results_job_finding",
)


def _add_missing(table: str, columns: tuple[tuple[str, Callable[[], sa.Column]], ...]) -> None:
    inspector = sa_inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table)}
    for name, build_column in columns:
        if name not in existing:
            op.add_column(table, build_column())


def _drop_present(table: str, columns: tuple[tuple[str, Callable[[], sa.Column]], ...]) -> None:
    inspector = sa_inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table)}
    for name, _build in reversed(columns):
        if name in existing:
            op.drop_column(table, name)


def upgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if _PROFILES in tables:
        _add_missing(_PROFILES, _PROFILE_COLUMNS)
        present = {index["name"] for index in sa_inspect(op.get_bind()).get_indexes(_PROFILES)}
        if "ix_discovery_profiles_scan_agent_id" not in present:
            op.create_index("ix_discovery_profiles_scan_agent_id", _PROFILES, ["scan_agent_id"])
        if "uq_discovery_profiles_system_agent_cidr" not in present:
            # Partial, so a user-created profile may target the same CIDR as a
            # system-managed one without colliding — plan §3's "user-created
            # profiles remain separate and are never overwritten" is enforced
            # here rather than trusted to the bootstrap.
            op.create_index(
                "uq_discovery_profiles_system_agent_cidr",
                _PROFILES,
                ["scan_agent_id", "normalized_cidr"],
                unique=True,
                postgresql_where=sa.text("managed_by = 'system'"),
            )

    if _JOBS in tables:
        _add_missing(_JOBS, _JOB_COLUMNS)
        present = {index["name"] for index in sa_inspect(op.get_bind()).get_indexes(_JOBS)}
        # Not new to this slice's feature set, but `scan_jobs.profile_id` has
        # been an unindexed FK since it was introduced, and the dispatcher's
        # per-profile lookups make that measurable rather than theoretical.
        if "ix_scan_jobs_profile_id" not in present:
            op.create_index("ix_scan_jobs_profile_id", _JOBS, ["profile_id"])
        if "ix_scan_jobs_agent_status_created" not in present:
            op.create_index(
                "ix_scan_jobs_agent_status_created",
                _JOBS,
                ["scan_agent_id", "status", "created_at"],
            )
        if "uq_scan_jobs_dispatch_id" not in present:
            # Partial rather than a plain unique constraint: every job the
            # server scanner has ever written has a NULL dispatch_id, and in
            # PostgreSQL NULLs do not collide — but stating the predicate keeps
            # the index small and says what it is for.
            op.create_index(
                "uq_scan_jobs_dispatch_id",
                _JOBS,
                ["dispatch_id"],
                unique=True,
                postgresql_where=sa.text("dispatch_id IS NOT NULL"),
            )

    if _RESULTS in tables:
        _add_missing(_RESULTS, _RESULT_COLUMNS)
        present = {index["name"] for index in sa_inspect(op.get_bind()).get_indexes(_RESULTS)}
        if "ix_scan_results_discovery_agent_id" not in present:
            op.create_index("ix_scan_results_discovery_agent_id", _RESULTS, ["discovery_agent_id"])
        if "ix_scan_results_tenant_id" not in present:
            op.create_index("ix_scan_results_tenant_id", _RESULTS, ["tenant_id"])
        if "uq_scan_results_job_finding" not in present:
            # The idempotent-replay key. Partial because every existing row —
            # and every future server-scanner row — has a NULL finding_id, and
            # a full unique index would let exactly one of them exist per job.
            op.create_index(
                "uq_scan_results_job_finding",
                _RESULTS,
                ["scan_job_id", "finding_id"],
                unique=True,
                postgresql_where=sa.text("finding_id IS NOT NULL"),
            )
        _apply_result_tenant_policy()


def _apply_result_tenant_policy() -> None:
    """Give `scan_results` the same tenant isolation `scan_jobs` already has.

    This lives here rather than in `0040_rls_policies._RLS_TABLES`, where it
    would be a no-op in both directions: `0040` skips any table with no
    `tenant_id` column, and on a fresh install the column does not exist when
    `0040` runs (it is in `0001_init._EXCLUDED_COLUMNS`), while on an upgrade
    `0040` has long since been applied. Mirrors `0040`'s policy shape exactly so
    the two tables cannot drift.
    """
    op.execute(sa.text(f"ALTER TABLE {_RESULTS} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {_RESULT_POLICY} ON {_RESULTS}"))
    op.execute(
        sa.text(
            f"CREATE POLICY {_RESULT_POLICY} ON {_RESULTS} "
            "USING (tenant_id = current_setting('app.current_tenant', true)::int)"
        )
    )


def downgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    for table, indexes, columns in (
        (_RESULTS, _RESULT_INDEXES, _RESULT_COLUMNS),
        (_JOBS, _JOB_INDEXES, _JOB_COLUMNS),
        (_PROFILES, _PROFILE_INDEXES, _PROFILE_COLUMNS),
    ):
        if table not in tables:
            continue
        if table == _RESULTS:
            op.execute(sa.text(f"DROP POLICY IF EXISTS {_RESULT_POLICY} ON {_RESULTS}"))
            op.execute(sa.text(f"ALTER TABLE {_RESULTS} DISABLE ROW LEVEL SECURITY"))
        present = {index["name"] for index in sa_inspect(op.get_bind()).get_indexes(table)}
        for name in indexes:
            if name in present:
                op.drop_index(name, table_name=table)
        _drop_present(table, columns)
