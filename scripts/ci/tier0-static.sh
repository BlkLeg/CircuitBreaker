#!/usr/bin/env bash
# Tier 0 — static gates. Pure analysis of the checked-out tree: no database, no
# services, no network. Everything here was previously inline in dev-ci.yml's
# `lint` job, which meant it could only ever run in CI (ADR 0005, P1).
set -euo pipefail

# REL-20: both workflows pin this at workflow level (ci.yml, dev-ci.yml) and
# tests/build/test_ci_evidence_retention.py enforces it there. Exporting it
# here too means the local gate removes the same source of run-to-run
# nondeterminism (per-process str/bytes hash salting) that CI does, instead of
# only being deterministic when GitHub runs it.
export PYTHONHASHSEED=0

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

EVIDENCE="$(cb::evidence_dir)"

cb::require_tool python3
cb::require_file .venv/bin/ruff "run 'make install' to build the dev virtualenv"
cb::require_file .venv/bin/mypy "run 'make install' to build the dev virtualenv"
cb::require_file .venv/bin/pytest "run 'make install' to build the dev virtualenv"

cb::section "Alembic revision graph (single head)"
# CB_DB_URL is read at import time by app.db.session (0001_init.py imports
# app.db.models, which imports it), but only to validate the URL scheme —
# get_heads() never opens a connection. A placeholder keeps this gate offline
# rather than requiring a real database; a caller-supplied CB_DB_URL (e.g.
# dev-ci.yml's) still passes through unchanged.
( cd apps/backend && PYTHONPATH=src CB_DB_URL="${CB_DB_URL:-postgresql://cb:cb@127.0.0.1:5432/cb}" "$CB_REPO_ROOT/.venv/bin/python" -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
heads = ScriptDirectory.from_config(cfg).get_heads()
assert len(heads) == 1, f'expected 1 Alembic head, got: {heads!r}'
print('Alembic head:', heads[0])
" )

# The repo-policy suite: tracked-file policy (GOV-12), governance files
# (GOV-10/11/14/16), cb CLI parity (SRV-06/GOV-05), restart probes
# (SRV-03), version parity and release channel. Until 2026-08-19 no
# workflow ran it, so "a policy test prevents recurrence" was a claim with
# nothing behind it — the suite passed locally and could rot unnoticed.
#
# It belongs in Lint: it is pure static analysis of the checked-out tree
# (git ls-files, file reads, no network) and finishes in under a second,
# so it fails fast and needs no database or services.
#
# Scoped to tests/build on purpose — the sibling repo-root suite
# tests/integration/ needs a live PostgreSQL that no job in this workflow
# provides, so it stays out rather than being added as a guaranteed
# failure. /pytest.ini overrides pytest's norecursedirs default (which
# contains "build") so the same collection happens for a plain
# `pytest tests/` locally, and so files added under tests/build/ later
# cannot be silently dropped.
cb::section "Repo policy tests (tests/build)"
.venv/bin/pytest tests/build \
    --junitxml="$EVIDENCE/junit/repo-policy.xml" \
    2>&1 | tee "$EVIDENCE/logs/repo-policy.log"

cb::section "Ruff"
( cd apps/backend && "$CB_REPO_ROOT/.venv/bin/ruff" check src/app )

cb::section "Mypy"
( cd apps/backend && PYTHONPATH=src "$CB_REPO_ROOT/.venv/bin/mypy" src/app )

# EXEC: the requirement ledger is the release's source of truth, and dev
# is the branch it is edited on. ci.yml runs this same check on pushes and
# PRs to main; dev-ci is what catches a drifted ledger on the branch where
# the edit actually lands, rather than one merge later.
cb::section "1.0.0 release-control ledger"
python3 scripts/validate_v1_release_control.py

cb::section "ESLint"
# Fail closed rather than informational: unlike the security gate's copy of this
# step (issue #106), ESLint IS a tier-0 gate here, so a missing node_modules is
# a setup error the developer must fix, not a result.
cb::require_file apps/frontend/node_modules \
    "run 'cd apps/frontend && npm ci' first"
( cd apps/frontend && npm run lint )

cb::section "Tier 0 complete"
