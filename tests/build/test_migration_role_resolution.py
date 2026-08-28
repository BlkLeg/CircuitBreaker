"""Migrations must not hardcode the database role, and must not poison the
transaction when a role-level statement fails.

Tier 3 (ADR 0005 Phase 2) reached this after CB_DATA_DIR and UPLOADS_DIR were
fixed. `0040_rls_policies` runs `ALTER ROLE breaker SET row_security = off`; the
packaged install connects as `circuitbreaker`, because
`packaging/postinstall.sh` generates that credential while `deploy/setup.sh`
generates `breaker`. So on a packaged host the role does not exist.

Two defects, and the second is the one that turned a cosmetic mismatch into a
dead install:

* The role is hardcoded. `0080_app_role_schema_grants` already solved this for
  0042's equivalent grants -- read the role from the connection URL, check
  pg_roles, quote the identifier -- so the pattern was in the tree, just not
  applied here.
* The `try/except` around it is not recovery. PostgreSQL aborts the enclosing
  transaction when a statement fails, so catching the Python exception rolls
  nothing back and every later statement dies with InFailedSqlTransaction. The
  warning text promises degradation ("RLS may block queries"); what actually
  happened is the migration run stopped at 0040 of roughly 100 and the service
  never started. Checking the role exists first avoids the exception rather than
  pretending to survive it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "apps/backend/migrations/versions"


def _migration_sources() -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(VERSIONS.glob("*.py"))]


def test_no_migration_alters_a_hardcoded_role():
    """ALTER ROLE against a literal name fails wherever that name is not the one
    the installer chose -- and a failed ALTER ROLE aborts the transaction."""
    offenders = []
    for name, text in _migration_sources():
        for lineno, line in enumerate(text.splitlines(), start=1):
            if re.search(r'ALTER ROLE\s+(?!\{)[A-Za-z_][A-Za-z0-9_]*', line):
                offenders.append(f"{name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "resolve the role from the connection URL and check pg_roles first, as "
        "0080_app_role_schema_grants does:\n  " + "\n  ".join(offenders)
    )


def test_role_level_statements_check_the_role_exists_first():
    """Cheaper and more honest than catching: no exception, no aborted
    transaction, and the skip is a real skip rather than a fatal one wearing a
    warning's clothes."""
    for name, text in _migration_sources():
        if "ALTER ROLE" not in text:
            continue
        assert "_role_exists" in text or "FROM pg_roles" in text, (
            f"{name} issues ALTER ROLE without confirming the role exists; a "
            f"failure there aborts the whole migration transaction"
        )
