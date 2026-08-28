# Evidence, Exception, and Invalidation Rules

**Status:** Draft release-control policy
**Requirements:** RC-07, RC-08

## Evidence bundle schema

Every passed ledger row must identify:

- requirement ID;
- verification mode (`automated`, `manual`, or `hybrid`), per RC-07;
- exact Git commit;
- version string;
- artifact digest or container digest;
- environment image or host details;
- configuration and deployment mode;
- procedure or command;
- start/end time or completion time;
- result;
- retained logs, screenshots, reports, SBOMs, or attestations;
- evidence digest or immutable artifact identity;
- reviewer; and
- invalidation state.

Mutable CI URLs are acceptable only when the ledger also records an immutable artifact digest or a
retained evidence bundle digest.

## Invalidation labels

Any later change with one of these labels must invalidate affected passed evidence unless the owner
records a narrower impact analysis:

| Label | Invalidates |
|---|---|
| `impact:runtime-code` | API/UI/server/agent behavior evidence touching changed code paths |
| `impact:migration` | Fresh-install, upgrade, downgrade, backup, restore, and schema evidence |
| `impact:build-input` | Artifact packaging, SBOM, provenance, install, startup, and distribution evidence |
| `impact:config-default` | Install, upgrade, config validation, health, security, and docs examples |
| `impact:dependency` | Security scans, SBOMs, startup, runtime compatibility, and affected feature tests |
| `impact:docs-claim` | Support contract, release notes, user docs, and acceptance rows relying on the claim |
| `impact:test-harness` | Prior test result trust if the harness, fixture, or assertion changed materially |
| `impact:environment` | Support-matrix rows tied to changed OS, browser, database, architecture, or topology |
| `impact:artifact` | All release evidence tied to an artifact replaced or rebuilt after the evidence ran |

Evidence can move from `current` to `superseded` only when replacement evidence exists. Otherwise it
must move to `invalidated`.

## Exception workflow

1. Owner opens an exception row with affected requirement IDs, severity, rationale, compensating
   control, evidence, expiry, and reviewer.
2. Reviewer confirms the exception is narrower than the requirement and does not silently redefine
   the support contract.
3. P0/P1 security or public-exposure exceptions require security-owner and release-owner approval.
4. Active exceptions must expire before or at the next planned release checkpoint unless renewed.
5. Expired active exceptions force the release-control validator to fail.
6. Closed exceptions keep their row for auditability and must record closure evidence.

## Tabletop exercises required before RC sign-off

- Expiring exception: create a non-active sample outside the register or in a throwaway branch, verify
  the validator fails once it is active and expired, then close the exercise.
- Evidence invalidation: mark a passed sample row invalidated by a simulated `impact:migration`
  change, verify the release decision no longer counts it as current, then restore the sample state.
