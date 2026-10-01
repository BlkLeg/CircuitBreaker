#!/usr/bin/env bash
# Tier 0 — static gates. Pure analysis of the checked-out tree: no database, no
# services, no network. Everything here was previously inline in dev-ci.yml's
# `lint` job, which meant it could only ever run in CI (ADR 0005, P1).
set -euo pipefail

# Both workflows pin this at workflow level (ci.yml, dev-ci.yml) and
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
# test_cli_package.py reads the CLI's installed dependency tree to prove no
# package in it runs install-time scripts (NPM-10). Like ESLint's node_modules
# below, a missing tree is a setup error, not something to install from here.
cb::require_file packages/cli/node_modules \
    "run 'npm ci --ignore-scripts --prefix packages/cli' first"
.venv/bin/pytest tests/build \
    --junitxml="$EVIDENCE/junit/repo-policy.xml" \
    2>&1 | tee "$EVIDENCE/logs/repo-policy.log"

cb::section "Ruff"
( cd apps/backend && "$CB_REPO_ROOT/.venv/bin/ruff" check src/app )

cb::section "Mypy"
( cd apps/backend && PYTHONPATH=src "$CB_REPO_ROOT/.venv/bin/mypy" src/app )

# Until 2026-09-27 these two sections were the whole of Tier 0's Python
# analysis, which meant NO script under scripts/ was linted or type-checked by
# any workflow: `make lint` named eight of them, but `make lint` is not on the
# CI path and this file is (ci.yml and dev-ci.yml's Lint job run this script,
# ADR 0005 P1). The scripts that build the release artifact, assert runtime
# parity and validate the release-control ledger were analysed on nobody's
# path, and 30 ruff findings and 5 real type errors had accumulated there
# unseen — including four unguarded regex `.group()` calls and a release
# builder that dropped a package format with a warning.
#
# Globbed rather than enumerated, for the same reason the Makefile is: a list
# that has to be edited when a script is added is a list that loses files.
# scripts/loadgen is a package, so it is matched on its own below.
cb::section "Ruff (scripts)"
# nullglob so a pattern matching nothing yields an empty array instead of the
# literal pattern: the count check below is then what fails, naming the gate,
# rather than ruff failing on a filename that never existed.
mapfile -t CB_SCRIPTS < <(shopt -s nullglob; printf '%s\n' scripts/*.py scripts/ci/*.py | sort)
cb::require_nonempty_glob "scripts/*.py scripts/ci/*.py" "${#CB_SCRIPTS[@]}"
"$CB_REPO_ROOT/.venv/bin/ruff" check "${CB_SCRIPTS[@]}" scripts/loadgen

# MYPYPATH plus --explicit-package-bases is what lets the few scripts importing
# `app.*` resolve it from source instead of reporting the installed package as
# missing py.typed, and what lets the two sibling imports that follow a runtime
# sys.path insert — build_native_release.py's `pbs_tree`, workflow_alert.py's
# `notify_discord` — resolve as modules.
#
# loadgen is a second invocation rather than more arguments to the first: with
# scripts/ on MYPYPATH it resolves as both `loadgen.x` and `scripts.loadgen.x`,
# and mypy refuses a source file reachable under two module names.
cb::section "Mypy (scripts)"
MYPYPATH="$CB_REPO_ROOT:$CB_REPO_ROOT/apps/backend/src:$CB_REPO_ROOT/scripts:$CB_REPO_ROOT/scripts/ci" \
    "$CB_REPO_ROOT/.venv/bin/mypy" --explicit-package-bases "${CB_SCRIPTS[@]}"

MYPYPATH="$CB_REPO_ROOT:$CB_REPO_ROOT/apps/backend/src" \
    "$CB_REPO_ROOT/.venv/bin/mypy" --explicit-package-bases scripts/loadgen

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
