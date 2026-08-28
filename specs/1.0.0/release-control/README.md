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

## Ledger verification modes

RC-07 requires the ledger to record *how* each requirement is verified, not only who owns it.
Every row carries a `mode`, and `validate_v1_release_control.py` rejects a blank or unrecognised
value so the column cannot be added and then quietly left empty.

| Mode | Meaning |
|---|---|
| `automated` | Tests, gates, scanners, or CI jobs decide acceptance with no human step. |
| `manual` | A human decision, review, approval, signature, or physical act decides acceptance. |
| `hybrid` | An automated result that a human must also review, approve, or author. |

The mode is derived from the requirement's acceptance criterion in its owning spec, not from how
the work happens to be done today. `SEC-11` is `automated` because its acceptance is "scanners are
green"; `AGT-06` is `manual` because its acceptance is a signed checklist from two physical sites.
A requirement whose criterion names both an automated result and a human judgement over it — the
shape of most `EXEC` and several `GOV` rows — is `hybrid`. Changing a mode means the acceptance
criterion changed, which is a spec edit, not a ledger edit.

## Validation

Run:

```bash
python3 scripts/validate_v1_release_control.py
```

The validator derives canonical IDs from `specs/1.0.0/[0-9][0-9]-*.md`, then fails if the ledger has
missing, duplicate, or unknown IDs. Rows marked `passed` must have retained artifact/evidence fields
and `invalidation_state=current`.

## Current control-plane state

This section deliberately carries no tally. A count written here is a second source of truth that
goes stale the moment a row moves, and the seed-time counts it used to carry had already outlived
the state they described. To read the current state, query the ledger:

```bash
python3 - <<'EOF'
import csv, collections
rows = list(csv.DictReader(open("specs/1.0.0/release-control/requirement-ledger.csv")))
print(collections.Counter(r["status"] for r in rows))
EOF
```

The standing rules, which do not change with the counts:

- `requirement-ledger.csv` is the only source of truth for what is closed. A checked box in a
  plan, a slice document, or an audit summary is not release evidence.
- Risks are tracked separately from exceptions. A risk is not permission to ship.
- An exception authorizes release despite unmet acceptance; it does not mark the requirement met.
  Every active exception carries an expiry, and the validator fails once one expires.
