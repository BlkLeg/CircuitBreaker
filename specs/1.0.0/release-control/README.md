# 1.0.0 Release Control

**Status:** Draft control plane for RC-07 and RC-08
**Owner:** release-owner
**Scope:** requirement ownership, retained evidence, risk tracking, exceptions, and invalidation

This directory is the auditable release-control workspace for the 1.0.0 production-readiness program.
It is deliberately separate from the implementation plans: a checked box in a plan is not release
evidence unless the corresponding ledger row identifies the artifact, environment, retained result,
reviewer, and current invalidation state.

## Files

| File | Purpose |
|---|---|
| `requirement-ledger.csv` | Machine-readable row for every RC/SEC/AGT/SRV/ACC/REL/GOV/NPM/EXEC requirement. |
| `owner-map.md` | Role-level accountable owner and reviewer map. |
| `risk-register.csv` | Consolidated open release risks, audit blockers, and evidence gaps. |
| `exception-register.csv` | Approved RC-08 exceptions. Empty means no exception is currently approved. |
| `evidence-and-invalidation.md` | Evidence bundle schema, status meanings, exception workflow, and invalidation rules. |

## Ledger status values

| Status | Meaning |
|---|---|
| `not_started` | No accepted release evidence exists. |
| `in_progress` | Work or evidence collection is active. |
| `blocked` | Owner cannot proceed without an external decision, dependency, or exception. |
| `passed` | Acceptance evidence passed and is current. |
| `failed` | Acceptance evidence ran and failed. |
| `excepted` | An active RC-08 exception authorizes release despite unmet acceptance. |
| `invalidated` | Prior evidence existed but a later change made it stale. |

## Validation

Run:

```bash
python3 scripts/validate_v1_release_control.py
```

The validator derives canonical IDs from `specs/1.0.0/[0-9][0-9]-*.md`, then fails if the ledger has
missing, duplicate, or unknown IDs. Rows marked `passed` must have retained artifact/evidence fields
and `invalidation_state=current`.

## Current control-plane state

- The ledger is seeded with 145 requirement rows.
- All rows start as `not_started` and `not_evidenced`.
- No release exception is approved at seed time.
- Risks are tracked separately from exceptions. A risk is not permission to ship.
