# RC decision-approval evidence capture — 2026-08-28

**Requirements evidenced:** RC-01, RC-03, RC-07, RC-08
**Requirements advanced but not evidenced:** RC-02, RC-04, RC-05, RC-06
**Owner:** shawnji (release) · **Reviewer:** shawnji (product) · **Mode:** manual / hybrid
**Commit:** `4537acf8bcf701d9cbef4c366237dbe16bfb512e`
**Tree:** `git-tree:9f8513259e426b006ff7fed726fef3b9e2c6428c`
**Version:** `0.4.0` (`VERSION`), release-control version string `1.0.0-rc-candidate`
**Environment:** Fedora Linux (kernel 7.1.10-200.fc44.x86_64), CPython 3.14, local working
checkout of `main`. No artifact, service, or browser is involved — every requirement in this
bundle is a decision or a register, and its acceptance is a document state.

## What this bundle is

Four of the eight RC requirements have acceptance criteria that are satisfied by a decision being
made and recorded, not by a test passing. This document is the record of those decisions being
taken on 2026-08-28, and the digests that pin what was approved.

It deliberately also records what these approvals do **not** settle. RC-02, RC-04, RC-05 and
RC-06 each name an ACC or REL acceptance in their criteria; approving the documents they rest on
moves them forward but cannot close them. Recording an approval as though it were evidence is the
specific failure this control plane exists to prevent — the same error EXC-001 was raised to
correct when SEC-02/03/04 were marked `passed` on the grounds that they were vacuously satisfied.

## Procedure

1. Read each ADR and each release document against its requirement's acceptance criterion in
   `specs/1.0.0/01-release-contract.md`.
2. Record the approval in the ADR header (`**Status:**` and a new `**Approved:**` line naming the
   date, the hats worn, and the EXC-002 single-codeowner deviation).
3. Update the three release documents' `**Status:**` lines to separate approval of the document
   from evidence for the rows inside it.
4. Add the `mode` column RC-07's criterion names, populate all 145 rows from each requirement's
   acceptance criterion, and extend `validate_v1_release_control.py` to reject a blank or
   unrecognised value.
5. Run `python3 scripts/validate_v1_release_control.py`.

## Result

`release-control validation ok: 145 ledger rows, 145 canonical IDs`

The `mode` gate was verified to fail closed before being relied on — a blank value and an
out-of-enum value (`semi-automatic`) were each injected into a copy of the ledger and each was
rejected with exit status 1. A gate that has never been observed failing is not a gate.

## What was approved, and its digest at this commit

| Document | Status set | sha256 |
|---|---|---|
| `docs/adr/0001-1.0-support-boundary.md` | Accepted for 1.0.0 | `c57a8c50e28644db41c1f709e7fe6eb9327721beed30ff92f01a4eedda48af41` |
| `docs/adr/0002-1.0-compatibility-and-service-objectives.md` | Accepted for 1.0.0 | `6c9bce6d021718ba485cc2debe2206b3f16ddcd0401f975c83da84b2271f1f03` |
| `docs/adr/0005-verification-tiers-and-platform-support.md` | Accepted for 1.0.0 | `fa26ca6851e23ebad91138d0337b6e3fd979bf47411c4bb1af7f5b01fb0172de` |
| `docs/adr/0003-defer-true-multi-tenancy.md` | unchanged (Accepted 2026-08-11) | `6e572e93f320e000f1e22837d8acac03b5bcf1db50a95467ab02478122320f8a` |
| `docs/adr/0004-npm-out-of-scope-for-1.0.md` | unchanged (Accepted 2026-08-19) | `7e34e959c4b814aa8e918bcae56d3ca1b65626336fe57e9269d5d672d38c96e5` |
| `docs/release/1.0.0-support-contract.md` | Approved under ADR-0001 | `4411f5d0a82399f621662aa1f8c9129c5c142a621f5a92e2d1ac78f88b84e318` |
| `docs/release/1.0.0-compatibility-policy.md` | Approved under ADR-0002 | `387f3348fef6aaae616e90d0f77533886a0588dc236190cdeb883047e707a8f4` |
| `docs/release/1.0.0-service-objectives.md` | Approved under ADR-0002 | `0019fab9d0858b796a8458ee7916d953a64e0e1c8185aca997035983fe9c3368` |
| `specs/1.0.0/release-control/owner-map.md` | unchanged | `860e697783751f875d118a898c5bef84caf5a04e20f5b57bc481629773ead4c9` |
| `specs/1.0.0/release-control/exception-register.csv` | unchanged | `09328c1b67f05ad80e1b64935f30141d1520958874dd8484dc11fc3dc4a68c14` |
| `specs/1.0.0/release-control/risk-register.csv` | unchanged | `68a3edbc7f921f8f9d8f00a70f71c187982eed57448df50fa640e5ef143613dd` |

## Requirement-by-requirement determination

### RC-01 — passed

> *Acceptance: Versioned scope document approved before RC1; release changes require explicit
> scope review.*

`docs/release/1.0.0-support-contract.md` is the versioned scope document; it carries the feature
scope, the deferred surfaces and the known limitations. It is approved as of this commit under
ADR-0001, which is itself now Accepted. The second clause is met by the document's own standing
rule — a row is promoted only when its named acceptance passes — and by ADR-0001's consequence
that "future work may expand support through an ADR update plus ACC/AGT evidence." A scope change
therefore cannot be made by editing the contract alone.

### RC-02 — remains in_progress

> *Acceptance: Every acceptance job maps to a support-matrix row; no untested row is called
> supported.*

Not met, and not affected by approval. The support contract publishes its platform rows as
"supported candidate" and states that a row is promoted only on passing acceptance, so nothing
untested is *called* supported — but the first clause needs acceptance jobs that exist, and
`ACC-01` through `ACC-21` are all `not_started`. `scripts/ci/fleet/matrix.yaml` is the beginning
of the mapping this criterion wants and currently holds exactly one row
(`fedora-rpm-amd64`, install-and-boot). ADR-0005's in-force clause forbids promoting a platform
row on the strength of its tier table until the corresponding evidence exists.

### RC-03 — passed

> *Acceptance: One or more accepted ADRs state each decision and its consequences.*

Every decision the requirement enumerates is now stated in an Accepted ADR with a Consequences
section:

| Decision required by RC-03 | Where it is decided |
|---|---|
| Single-node versus HA | ADR-0001 — "1.0.0 is single-node only. High availability is unsupported." |
| Linux-only boundaries | ADR-0001 — Linux-only server support; macOS/Windows are client platforms only |
| IPv6 level | ADR-0001 — IPv4 private-network baseline; IPv6 beta, limited to tested ULA workflows |
| Internet-exposed versus LAN/VPN | ADR-0001 — trusted-LAN/VPN first; direct exposure and Tunnel remain beta |
| Multi-tenancy | ADR-0001 and ADR-0003 — not a 1.0.0 security boundary; separate deployments required |
| Offline / air-gap behavior | ADR-0001 — air-gapped enrollment and update unsupported for 1.0.0 |
| Public API / SDK stability | ADR-0001 and ADR-0002 — stability deferred; `/api/v1` is not a stable third-party API |

ADR-0004 additionally settles the npm channel question that RC-03 inherits through EXC-003.

### RC-04 — remains in_progress

> *Acceptance: Compatibility table includes allowed, blocked, and degraded combinations and is
> exercised by ACC-12.*

The first clause is met and now approved: `docs/release/1.0.0-compatibility-policy.md` carries the
allowed, blocked and degraded combinations, the upgrade order, the deprecation stages and the
`0.3.5` source floor, decided in ADR-0002. The second clause is unmet — ACC-12 is `not_started`,
so the policy's "Required examples for verification" section has never been exercised. The
blocker is evidence, not the decision.

### RC-05 — remains in_progress

> *Acceptance: Targets and measurement windows are published; SRV-03 and REL-21 tests produce the
> named metrics.*

First clause met and approved. Second clause unmet, and the gap is code rather than a test run:
no named metric is emitted anywhere. `/api/v1/metrics` exposes inventory and service gauges only;
there is no HTTP availability or latency instrumentation; no REL-21 test exists. The service
objectives publish the Degraded and "not ready rejects writes" rows as explicitly unimplemented,
which is honest but is not the same as satisfied.

### RC-06 — remains in_progress

> *Acceptance: Values are evidence-based and validated by ACC-09 through ACC-15 and REL-21 through
> REL-26.*

Every value is published and now approved as a *candidate*: RPO 24 hours, RTO 4 hours to a clean
supported host at the approved medium dataset, local and remote backup retention of 7 and 30
snapshots, and the audit, upload and metrics retention defaults. None is evidence-based yet —
ACC-09 through ACC-15 and REL-21 through REL-26 are all `not_started`, and telemetry and
check-history retention are explicitly deferred to REL-02 and REL-25.

### RC-07 — passed

> *Acceptance: Ledger contains owner, automated/manual mode, environment, evidence, and current
> disposition.*

`owner-map.md` names an accountable owner and reviewer for all nine requirement prefixes, and
every one of the 145 ledger rows carries both. The single-codeowner deviation, where owner and
reviewer resolve to the same person, is recorded as EXC-002 rather than concealed by a placeholder
second name.

The `automated/manual mode` clause was unmet until this commit: the ledger had no such field, so
the criterion was being read as satisfied by a column that did not exist. A `mode` column is now
present on all 145 rows, derived from each requirement's acceptance criterion in its owning spec
(86 `automated`, 43 `hybrid`, 16 `manual`), documented in the release-control README, and enforced
by the validator against a fixed enum so it cannot regress to blank.

`environment`, `evidence` and `invalidation_state` are columns in the schema and are populated on
every row that has evidence. They are empty on rows with no evidence, which is the correct state
for an unevidenced requirement rather than a gap in the ledger: RC-07 requires the ledger to be
able to record them, and the validator requires them to be present on any row claiming `passed`.

### RC-08 — passed

> *Acceptance: Maintain one risk and exception register. Every exception has owner, rationale,
> compensating control, expiry, and release approval.*

One risk register (`risk-register.csv`, 11 open risks) and one exception register
(`exception-register.csv`, EXC-001, EXC-002, EXC-003) exist and are the only ones. Each active
exception carries owner, reviewer, rationale, compensating control, evidence URL, expiry
(2026-11-13) and a named approval, and `validate_v1_release_control.py` enforces every one of
those fields plus expiry — an expired active exception fails the release-control gate.

The requirement's summary clause is what is being evidenced here. Its wider acceptance note in
`01-release-contract.md` — "no unexplained skip, xfail, warning, scan suppression, or unmet gate
remains **at sign-off**" — is a condition on EXEC-09, evaluated when sign-off happens, and is
tracked by RISK-010 through REL-08, REL-19 and SEC-18. It is not a precondition for maintaining
the registers, and this bundle does not claim it.

## What this bundle does not evidence

- No platform, distro, architecture, or browser row is promoted to supported by this approval.
- No tier guarantee in ADR-0005 enters force. Tier 1 and Tier 2 are recorded as **not in force**;
  only Tier 3 (build-only) is in force at this commit.
- No SLO, RPO, RTO, retention default, or scale ceiling becomes a measured promise. They remain
  approved candidate values.
- The overall release recommendation is unchanged. `docs/1.0.0-release-readiness-audit.md` records
  NO-GO for 1.0.0, and nothing in this bundle addresses any of the conditions it lists.
