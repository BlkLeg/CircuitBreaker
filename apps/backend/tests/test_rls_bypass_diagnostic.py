"""The RLS diagnostic must not call a working install broken.

Tier 3 surfaced this on a packaged Fedora boot:

    Row-level security is enabled on public.hardware but the database role
    'circuitbreaker' does not have BYPASSRLS. Tenant-scoped queries may return
    no rows unless session variables match policies.

The install was fine. PostgreSQL does not apply RLS to a table's owner unless
the table is set FORCE ROW LEVEL SECURITY, and 0040_rls_policies only ENABLEs
it. The packaged role owns the database it migrated, so it owns those tables and
reads them normally -- verified directly: an owner with rolbypassrls=false still
sees every row.

The check looked only at rolbypassrls, so it warned about a condition that did
not exist. That matters more than a noisy log, because the remedy it implies is
`ALTER ROLE ... BYPASSRLS`, and BYPASSRLS is cluster-wide, unconditional and
permanent for that role, where ownership bypass is scoped to owned tables and
can be tightened later with FORCE. A misleading warning that points at a
privilege escalation is worse than silence.
"""

from __future__ import annotations

import logging
import os

import pytest
import sqlalchemy as sa

TEST_DB_URL = os.environ.get(
    "CB_TEST_DB_URL", "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"
)


PROBE_ROLE = "rls_diag_owner"
PROBE_PASSWORD = "rls_diag_probe_pw"  # noqa: S105 - throwaway, local test role


@pytest.fixture()
def rls_table():
    """A table owned by a role WITHOUT bypassrls, with RLS enabled.

    A dedicated role is the point. The development and CI database role
    (`breaker`) is created with BYPASSRLS, which is exactly why this defect never
    appeared outside a packaged install: every suite ran as a role the diagnostic
    returns early for. The packaged role has no such attribute, so it takes the
    path nothing exercised.
    """
    admin = sa.create_engine(TEST_DB_URL)
    with admin.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS rls_diag_probe"))
        conn.execute(
            sa.text(
                f"DO $$ BEGIN IF NOT EXISTS "
                f"(SELECT 1 FROM pg_roles WHERE rolname = '{PROBE_ROLE}') THEN "
                f"CREATE ROLE {PROBE_ROLE} LOGIN PASSWORD '{PROBE_PASSWORD}'; "
                f"END IF; END $$"
            )
        )
        conn.execute(sa.text(f"GRANT CREATE, USAGE ON SCHEMA public TO {PROBE_ROLE}"))

    url = sa.engine.make_url(TEST_DB_URL).set(username=PROBE_ROLE, password=PROBE_PASSWORD)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE rls_diag_probe (id int, tenant_id int)"))
        conn.execute(sa.text("INSERT INTO rls_diag_probe VALUES (1, 42)"))
        conn.execute(sa.text("ALTER TABLE rls_diag_probe ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            sa.text(
                "CREATE POLICY p ON rls_diag_probe USING "
                "(tenant_id = current_setting('app.current_tenant', true)::int)"
            )
        )
    yield engine
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS rls_diag_probe"))
    admin.dispose()


def test_owner_without_bypassrls_still_reads_its_own_rows(rls_table):
    """The premise the diagnostic got wrong, pinned as a fact about PostgreSQL."""
    with rls_table.connect() as conn:
        bypass = conn.execute(
            sa.text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar()
        visible = conn.execute(sa.text("SELECT count(*) FROM rls_diag_probe")).scalar()
    assert bypass is False, "this test is meaningless if the role can bypass RLS"
    assert visible == 1, (
        "RLS does not apply to a table's owner unless FORCE ROW LEVEL SECURITY "
        "is set; if this fails, the diagnostic's original assumption was right"
    )


def test_diagnostic_is_quiet_when_the_role_owns_the_tables(rls_table, caplog):
    from app.main import _rls_bypass_warning

    with caplog.at_level(logging.WARNING):
        message = _rls_bypass_warning(rls_table, ("rls_diag_probe",))
    assert message is None, f"warned about a table the role owns: {message}"


def test_diagnostic_warns_when_force_rls_actually_binds_the_owner(rls_table):
    """FORCE is the case where ownership stops helping — then the warning is
    correct and must still fire."""
    from app.main import _rls_bypass_warning

    with rls_table.begin() as conn:
        conn.execute(sa.text("ALTER TABLE rls_diag_probe FORCE ROW LEVEL SECURITY"))
    message = _rls_bypass_warning(rls_table, ("rls_diag_probe",))
    assert message is not None and "rls_diag_probe" in message
