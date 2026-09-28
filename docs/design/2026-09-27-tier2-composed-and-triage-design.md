# Tier 2 (Composed) and Its Automated Triage — Design

**Date:** 2026-09-27
**Status:** Approved in design; slices A1–A3 implemented
**Version at writing:** 0.4.5
**ADR:** [0005 — Verification Tiers and Platform Support](../adr/0005-verification-tiers-and-platform-support.md)
**Programme:** [2026-08-27-verification-strategy-design.md](./2026-08-27-verification-strategy-design.md) — this is that
document's **Phase 4**, "T2 extraction and harness hardening", plus the maintenance automation that makes the
tier answerable without a human reading logs.
**Scope:** `.github/workflows/{tier2,composed-e2e,mono-smoke,maintainer-digest,review-alert}.yml`,
`.github/workflows/{e2e,dev-ci,release,release-dry-run,notify}.yml` (callers), `scripts/ci/{tier2_triage,maintainer_digest,review_alert}.py`,
`tests/build/`, `Makefile`.

---

## 0. Which "Tier 2" this is

Two unrelated tier ladders exist in this repository and both have a Tier 2. Confusing them is the first
mistake available to a reader of this document, so:

- **This document means the verification tier** — §4 of the verification strategy design, which defines
  **T2 composed** as "agent E2E, browser E2E, mono image smoke", 30 minutes, cadence "pre-merge to `main`".
- **It does not mean ADR 0005's platform support Tier 2** ("guaranteed to install and boot": deb/rpm on
  arm64). That ladder is about what the project promises users about packages, it is enforced by
  `tests/build/test_docs_match_tier_table.py`, and nothing here touches it.

Where this document says T0/T1/T2/T3 it always means the verification ladder.

---

## 1. Problem statement

### 1.1 Tier 2 does not exist as a thing that can be run or named

T0 and T1 are extracted scripts (`scripts/ci/tier0-static.sh`, `tier1-unit.sh`) called identically by the
laptop and by CI. T3 is a script that executes inside a fleet VM (`tier3-artifact.sh`) with
`make verify-fleet` in front of it. T2 has no script, no `make` target and no aggregate — its three suites
are scattered:

| T2 suite | Where it lives today | Load-bearing for |
|---|---|---|
| Browser E2E | `browser-e2e.yml` (reusable, 2 shards), called by `ci.yml`, `dev-ci.yml`, `release.yml`, `release-dry-run.yml` | the release candidate only — **not** a required check |
| Composed agent E2E | `e2e.yml`, job `composed-journey` — **disabled** with `if: false` under QUAR-001 | nothing |
| Mono image smoke | inline in `dev-ci.yml`, job `Build Docker (smoke test)` | nothing; `dev` only |

So the tier that CLAUDE.md's "What the gates do NOT cover" table exists to warn about is, itself,
uninspectable: there is no single thing to run, no single result to read, and no name to require.

### 1.2 The disabled suite is invisible rather than skipped

`e2e.yml`'s `if: false` removes the check run entirely. That is the defect class §4.4 of the programme
design and `cb::skipped` were written to prevent — "did not run" must never be spelled the same way as
"found nothing". QUAR-001's register row is honest and complete; the workflow it describes is silent.

### 1.3 A red composed suite currently costs a human a log-reading session

When a T2 suite fails, `notify.yml` posts that a workflow failed. Everything after that is manual: download
artifacts, read JUnit, decide whether the failure is new, consistent or flaky, and then either fix it or
write a register row by hand with an owner, a tracking issue and an expiry. Rule 2 of CLAUDE.md permits
exactly two outcomes for a red required check and neither is cheap. That triage is mechanical up to one
step — naming a suspected cause — and that one step is the only part worth a model.

### 1.4 There is no standing answer to "what is outstanding?"

`ledger_watch.py` nightly maintains one issue for expiring ledger rows. Nothing reports open PRs awaiting
review, open issues and their age, or whether last night's verification passed. For a solo maintainer the
absence of that single daily view is how a `major-update` Dependabot PR sits for a week and an issue goes
31 days without activity.

---

## 2. Decisions taken, and why

### D1 — Tier 2 is reusable workflows plus `make` targets, not a `tier2-composed.sh`

§5 of the programme design specifies `scripts/ci/tier2-composed.sh`. That is not what this design does,
and the departure is deliberate.

- **Security.** T2's three suites need three different privileged runtimes: a Playwright container image, a
  docker-socket runner as uid 1001, and the mono image. One script running all three must hold all three
  privileges in a single job. Split across reusable workflows, each keeps `permissions: contents: read` and
  its own `workflow_call` boundary — the unit GitHub's own trust model understands.
- **Precedent that works in production.** `build.yml`, `artifact-smoke.yml`, `installer-journey.yml` and
  `browser-e2e.yml` are four working instances of the reusable-workflow pattern in this repo. The one gate
  that *is* a script, `tier3-artifact.sh`, is a script because it runs inside a VM that no workflow can
  reach — which is the actual constraint §5 was reasoning from, and it does not apply to T2.
- **It is what makes automated triage tractable.** Per-suite check runs give a stable, machine-readable
  target (`Browser E2E (shard 2/2)`) and per-job retained artifacts. One script yields one opaque red
  result and a single six-thousand-line log.

**The concession to P1 (one definition per gate) is explicit and enforced.** Each suite has exactly one
definition; the `make` target and the workflow step invoke the *same* command; and a `tests/build/` guard
fails when they drift — the same enforcement `test_playwright_image_matches_package.py` already provides
for the two places the Playwright container tag is pinned.

### D2 — A red T2 blocks a release and reports nightly; it does not block merges

T2 gates the release candidate (browser E2E already does, since PR #182) and runs nightly against the default
branch so a defect is found within 24 hours rather than at tag time. It is **not** added to the 21 required
checks, so `tests/build/required_checks.py` is untouched by this design.

Rationale: a 30-minute composed suite on the critical path of every merge, in a single-maintainer repo,
converts one flake into a total merge lockout — and the automation would then be racing the maintainer to
quarantine it. The nightly has nobody waiting on it, so a diagnosis arriving ten minutes later costs nothing.

**The nightly tests `dev`, not `main`, and that is deliberate.** An earlier draft of this section accepted "a
regression introduced on `dev` is not seen by a nightly on `main`" as a consequence. It is not a consequence,
because `e2e.yml:57-59` already solved this: `schedule` fires only from the default branch's copy of a
workflow file, `main` trails the integration branch, so the existing nightly checks out `dev` and tests the
code that is actually moving. `tier2.yml` follows that precedent — the workflow file comes from `main`, the
tree under test comes from `dev` — which is why `composed-e2e.yml` takes a `ref` input rather than hard-coding
the redirect it inherited. Tag pushes, `workflow_dispatch` and `workflow_call` keep testing the ref that
triggered them. The release gate remains the backstop for anything that reaches a tag without a nightly having
seen it.

### D3 — The decision is deterministic; the model only writes prose

Every automation in this repo that is trusted — `ledger_watch.py`, `workflow_alert.py`,
`branch_cleanup.py` — is a typed stdlib script with fixture tests. `scripts/ci/tier2_triage.py` follows
them: it decides flaky vs consistently-red vs new, and whether a quarantine row is warranted, with no model
in the decision path.

The model writes one field. QUAR-001's `reason` — "Leading suspect: `schedule_bootstrap`'s
`_publish_soon` does `loop.create_task(...)` without keeping a reference to the returned Task, which asyncio
permits to be garbage-collected before it ever runs" — is judgement a script cannot produce and a model
can. That is the whole of the model's job, and if the model is unavailable the row still lands with a
mechanical reason and a `notes` marker saying the narrative is pending.

### D4 — The automation diagnoses and drafts; it never touches application code

On a red T2 the automation may: post to Discord, open one `release-control` issue, and open one PR that adds
a quarantine-register row — or, for a `RECOVERED` test, one PR that removes a row that is no longer true. It may not modify application code, may not merge anything, and may not renew an
existing row (the register's own docstring makes renewal a deliberate act; a bot drafting one would hollow
out the only date in the system that means anything). Nothing reaches `main` without the 21 required checks
and a human merge.

---

## 3. Architecture

### 3.1 Phase A — Tier 2 becomes a thing that exists and runs

| File | Change |
|---|---|
| `.github/workflows/composed-e2e.yml` | **New.** The composed agent journey as `workflow_call`, lifted out of `e2e.yml`. |
| `.github/workflows/mono-smoke.yml` | **New, but deferred to slice A3** (§9). The plan for A1 found that the smoke cannot be separated from its image: `dev-ci.yml:971-980` pushes to GHCR by `docker tag`-ing the image the *same job* built, in that runner's Docker daemon, and the job's own comment requires the push to happen only after the smoke has started that exact image. A reusable workflow puts the smoke on a different runner with nothing to tag, so extracting it needs either an image transported as an artifact or the publish moved inside the called workflow — a decision with its own cost, taken on its own evidence rather than folded into the first slice. Until A3 lands, the mono smoke stays inline in `dev-ci.yml` exactly as it is today. |
| `.github/workflows/tier2.yml` | **New.** `name: Tier 2 (composed)`, matching `Fleet (Tier 3)`. Nightly cron, `workflow_dispatch`, `workflow_call`. Carries a `concurrency` group so a manual dispatch and the nightly cannot interleave two runs whose artifacts the triage would then read as one. |
| `.github/workflows/e2e.yml` | Thin caller of `composed-e2e.yml`. Keeps its tag and path-filtered PR triggers; **drops its nightly schedule**, which `tier2.yml` takes over. |
| `.github/workflows/dev-ci.yml` | `build-docker` becomes a caller of `mono-smoke.yml`. |
| `.github/workflows/release.yml`, `release-dry-run.yml` | Call `tier2.yml` instead of `browser-e2e.yml` directly — with `["browser","composed"]` from A2, and the default all-three set once A3 adds the mono suite. **Superseded 2026-09-27 by the maintainer:** the release calls `tier2.yml` with `["browser"]` only. The composed journey is not a release gate (AGT-01 stands), because making it reliably green is a steep hill that should not block releases. Whether A3 adds `"mono"` to the release is decided in A3. |
| `Makefile` | `make verify-composed` — the laptop entry point §4 of the programme design anticipated but never named. Its browser half runs `scripts/ci/tier2-browser.sh`, which exports `CI=1`, because `playwright.config.ts` selects its JUnit reporter on `process.env.CI`; without that a local run writes no `junit.xml` and cannot be triaged, which would make the local and CI forms of the tier differ in exactly the way P1 forbids. |

`tier2.yml` selects suites with a `suites` JSON-array input and `if: contains(fromJSON(inputs.suites), 'browser')`
on each call job — the established pattern from `artifact-smoke.yml`'s `arches`.

**QUAR-001 changes shape rather than getting fixed.** The `if: false` is replaced by a `quarantined` input
whose true branch runs one step printing `SKIPPED (QUAR-001, issue #162, expires 2026-12-21)` and exits 0.
The check name stays present and honest, and it now correlates with the register row that
`test_quarantine_register.py` will fail every build over from 2026-12-21. Actually fixing #162 is out of
scope (§8).

### 3.2 Phase B — the automation

| File | Change |
|---|---|
| `scripts/ci/tier2_triage.py` | **New.** Deterministic verdicts from JUnit. Pure: reads files, no network. |
| `scripts/ci/maintainer_digest.py` | **New.** The nightly roll-up. Takes `gh api` JSON on stdin, emits a Discord body. Pure. |
| `scripts/ci/review_alert.py` | **New.** Builds the "a PR needs your review" message. One definition of how a PR is described; imported by the digest for its PR section. |
| `.github/workflows/maintainer-digest.yml` | **New.** Nightly 13:15 UTC, plus `workflow_dispatch`. Read-only. |
| `.github/workflows/review-alert.yml` | **New.** Hourly sweep plus `workflow_dispatch`, firing M5 for human and Dependabot PRs. `pull-requests: write` for the `review-alerted` label only — the narrowest write in the design (§6.1 for why this is not a pull-request-event workflow). |
| `.github/workflows/tier2.yml` | Two triage jobs, `if: always()`, `needs:` every suite job (§3.3). |
| `.github/workflows/notify.yml` | `Tier 2 (composed)` added to the watched list. Landed early, in A2, because A2 moves the watched nightly. |
| `make lint` | The three new scripts added to its ruff and mypy lines. |

No new nag path is needed for quarantine expiry: `ledger_watch.py` already reads
`quarantine-register.csv` for rows nearing expiry.

**Cron placement.** Existing: `e2e.yml` 03:00, `branch-cleanup.yml` Sundays 05:00, `baseline.yml` 05:17,
`ledger-watch.yml` 06:23 (all UTC). `tier2.yml` takes 03:00 as `e2e.yml` vacates it. `maintainer-digest.yml`
runs 13:15 UTC — after every other scheduled workflow, so it can report their results, and roughly 07:15 in
the maintainer's timezone.

### 3.3 The two triage jobs, and why they are two

The widest job this design could contain is one that parses artifacts *and* opens pull requests. It is
split so that the side holding the model holds no write access:

| Job | Permissions | Holds |
|---|---|---|
| suite jobs | `contents: read` | — |
| `triage-decide` | `actions: read`, `contents: read` | `tier2_triage.py` **and** the model step |
| `triage-emit` | `contents: write`, `issues: write`, `pull-requests: write` | verdict consumption only — no model, no artifact parsing |

**The model has no tools.** Text on stdin, text on stdout, in a job that cannot write to the repository.
This is the strongest available form of the `cb-automation` rule that a reader of untrusted input must not
also hold write access: here the reader has no write path to hold.

**Both triage jobs are gated on a `triage` boolean input defaulting to `false`.** `tier2.yml` is both a
scheduled workflow and a called one, and inside a called workflow the `github` context is the **caller's** —
`github.event_name` during a release reads `workflow_dispatch` or `push`, never `workflow_call`. No event test
can therefore distinguish "the nightly" from "the release". Only the schedule and manual-dispatch paths set
`triage: true`; `release.yml` and `release-dry-run.yml` leave it alone. Without that gate a release candidate
could open a quarantine pull request in the middle of a release, which is the single worst thing this design
could do. The Discord secrets are declared optional on the `workflow_call` interface for the same reason: the
release path never passes them, and a missing webhook is already a logged no-op.

### 3.4 The composed journey's rerun guard

The composed journey never runs twice on the same inputs while a previous failure is unaddressed:
"addressed" means either **fixed** (something under `SUITE_INPUTS` changed since the failed run, so the
inputs fingerprint is new) or **quarantined** (every failed test has a live register row for
`Composed Agent E2E / composed-journey`, and the journey deselects exactly those tests). There is
deliberately no force switch. See `scripts/ci/composed_rerun_guard.py`'s docstring for the full contract —
the `fingerprint`/`check`/`record`/`deselect` subcommands, the artifact lookup that reads every page and
fails closed if the listing is incomplete, trusting only artifacts from runs of this repository, and the
exact input set the fingerprint covers (the agent, the backend, `docker/`, `Dockerfile.mono` and its
build-context `COPY` sources, root `docker-compose.yml`, `pytest.ini`, the journey script and
`scripts/ci/lib/common.sh`, and `composed-e2e.yml` itself — deliberately excluding `apps/frontend`, so a
daily UI commit is never mistaken for a fix to an agent failure; a frontend-caused crash is therefore
fix-only). Register rows for `Composed Agent E2E / composed-journey` now quarantine individual tests by
deselection whenever the suite runs, rather than only the whole suite.

Two limits: "never runs twice" is best-effort across concurrent runs on the same fingerprint, since two runs
can both pass the guard before either records a verdict; and verdict artifacts are retained for 90 days,
after which an unaddressed failure may run once more.

---

## 4. Triage decision rules

The unit of judgement is a **test id** (`classname.name` from JUnit), not a job. "Browser E2E shard 2
failed" is not a fact that can be quarantined — the register's `scope` column holds test names, as
QUAR-001's three do.

History window: the last **7** runs of `Tier 2 (composed)` on the default branch **that produced JUnit**.
A cancelled run, or one that failed before collecting, is not history — it is neither evidence of passing nor
of failing, and counting it either way would corrupt the consistency test below. Artifact retention is 14
days, so 7 nightlies sits inside the window with margin.

| Verdict | Condition | Action |
|---|---|---|
| **NEW** | Fails now; passed in the previous run | Discord (ping) + issue. **No row** — a new failure is a bug to fix, not to park. |
| **PERSISTING** | Fails now and in the previous run, but on fewer than 3 consecutive runs | Comments the new occurrence on the issue `NEW` already opened. **No ping, no second issue, no row** — it is the same failure one night older. |
| **CONSISTENT** | Fails now and in every one of the last ≥ 3 runs that collected it | Issue + **quarantine row PR**. The only verdict that drafts a row. |
| **FLAKY** | Fails now; mixed pass/fail across the window | Discord (ping) + issue, **no row**. Rule 2 of CLAUDE.md says "probably flaky" is not an outcome; a flake needs an owner and an investigation, not an expiry date. |
| **RECOVERED** | Passes now; failed in the previous run | Recovery message, no ping. If a register row names it, **propose deleting the row** — quarantines need a retirement path, not only renewal. |
| **NOT_COLLECTED** | The test is absent from this run's JUnit, or a suite's collected count fell below the previous run's | Treated as a **failure regardless of exit code**. §1.2 of the programme design: an unregistered `e2e` marker collected zero tests and the job was green. |
| **NO VERDICT** | Cancellation, `startup_failure`, image-pull failure, or a timeout with no JUnit | Reported as infrastructure. Never quarantined, never counted as history. |

**Granularity differs by suite, and the verdict records which was used.** Playwright writes
`playwright-report/junit.xml` (`playwright.config.ts`) and the composed journey writes `junit-agent-e2e.xml`
(`e2e.yml`), so both support test-id verdicts. The mono image smoke emits **no JUnit at all** — it is a docker
build plus a provenance export — so it is judged at **job granularity**: the same verdicts computed over the
job conclusion rather than a test list, `NOT_COLLECTED` inapplicable, and a row drafted for it naming the job
in `scope` instead of test ids. A future T2 suite that emits JUnit gets test granularity for free; one that
does not is judged as a job, and `verdict.json` states which, so a reader never mistakes a job-level verdict
for a test-level one.

Two idempotence rules, per the `cb-automation` checklist:

1. A test that already has a register row produces no second row.
2. If such a row is still red and its expiry falls within 14 days, the script proposes nothing and escalates
   in the notification instead. Renewal is a human act.

The row branch name is derived from the failing test set, so a re-run force-updates one PR rather than
opening a second.

---

## 5. Data flow

```
suite jobs ──> artifacts/junit/*.xml + artifacts/logs/*.log
               uploaded as tier2-<suite>[-shard-N], retention 14 days
                      │
triage-decide (actions: read, contents: read)
   gh run download ───┤  this run's artifacts      ──> run/
   gh api + download ─┘  last 7 runs' JUnit        ──> history/
                      │
   tier2_triage.py --run-dir run/ --history-dir history/ --today YYYY-MM-DD
                      │   (pure: reads files; no network, no gh)
                      ├──> artifacts/tier2-verdict.json
                      └──> human-readable summary on stdout and $GITHUB_STEP_SUMMARY
                      │
   model step (read-only, non-blocking) ──> reason prose only
                      │
   uploads verdict.json + prose as an artifact
                      │
triage-emit (contents: write, issues: write, pull-requests: write)
   notify_discord.py · gh issue create --body-file · row PR · dispatch_required_checks.sh
```

`tier2_triage.py` never touches the network: the workflow downloads and passes paths. That is what makes
`tests/build/test_tier2_triage.py` a fixture test with no HTTP mocking — the same discipline that keeps
`workflow_alert.py` pure by taking the previous run's conclusion as an argument.

**Row filling** is mechanical except one field. `quarantine_id` is the next free `QUAR-NNN`; `check` is
`<workflow> / <job>`; `scope` is the failing test ids; `owner` comes from
`specs/1.0.0/release-control/owner-map.md` (validated locally, or the PR would fail
`test_every_owner_is_named_in_the_owner_map`); `tracking` is the issue just opened; `opened` is today;
`expiry` is today + 90 days; `notes` carries the run URL, the verdict and how the row was produced.
`reason` is the model's only output.

**The PR targets `dev`**, like every other change here; the row reaches `main` through the normal promotion.
That is correct even when the failing nightly ran on `main`, because `test_quarantine_register.py` runs in
Tier 0 on both branches and an unexpired row blocks neither.

---

## 6. Notification catalogue

`notify_discord.py` already carries everything needed: a 4096-character description, up to 25 fields of
1024 characters, `_clip` truncation, and `allowed_mentions` hard-fixed to `{"parse": []}` so no quantity of
detail can ping anyone. **No change to that module.**

Every message carries the same three closing fields — **run URL**, **commit sha + subject**, **what you
should do** — so no message leaves the reader asking what happens next. Field count stays at or below 8 for
phone readability. When a list overflows, the message says `+N more — full list in the run summary` and the
job writes the complete list to `$GITHUB_STEP_SUMMARY`; truncation is never silent.

**M1 — Tier 2 failed.** `failure`, pings.

> **Tier 2 (composed) failed on main — verdict: CONSISTENT**
> **Suites** `browser ❌ 2 tests · composed ⏭ SKIPPED (QUAR-001) · mono ✅`
> **Verdict** CONSISTENT — failed 4 of the last 4 nightlies, same 2 tests
> **Failing** `visual.spec.ts:topology renders`, `nav.spec.ts:deep link`
> **Collected** browser 248 (prev 248) · mono 12 (prev 12) — *no drop*
> **Suspected cause** ⟨model prose⟩
> **Next** a quarantine row PR will follow in this run
> **Reproduce** `cd apps/frontend && npx playwright test --project=chromium -g "deep link"`

The **Collected** field is the only place a zero-collected suite becomes visible, which is §1.2's
silent-green defect.

**M2 — Tier 2 recovered.** `success`, no ping. What recovered, how many nights it was red, and whether a
register row now has a retirement path.

**M3 — Tier 2 did not run.** `warning`. States explicitly that the gate did not run, rather than letting
absence read as green. It pings on the second consecutive occurrence, which needs no stored state: the
previous run is already in the history window, and a second `NO VERDICT` in a row means the tier has now been
blind for two nights — a different problem from one bad runner.

**M4 — New issue opened.** `warning`, pings. Number, title, labels, the tests it covers, the verdict, and
for `NEW`/`FLAKY` an explicit line on **why this was not quarantined**.

**M5 — A PR needs your review.** `warning`, pings. Derived mechanically wherever possible:

> **PR #184 needs review — adds QUAR-002 to the quarantine register**
> **Covers** `Browser E2E / browser-e2e`, 2 tests: `visual.spec.ts:topology renders`, `nav.spec.ts:deep link`
> **Implications** Browser E2E stops blocking the release candidate for these 2 tests until **2026-12-26**
> (90 days). From that date `test_quarantine_register.py` fails every build until the row is fixed or renewed.
> **You are accepting** that a release can ship with topology rendering unverified.
> **Tracking** issue #183 · **Owner** shawnji (qa)
> **Checks** 21 dispatched · ⚠️ 5 parked as `action_required` — approve them or the PR can never merge
> **Alternative** fix the suite instead: `make verify-composed`

The `action_required` field exists because of PR #176: a bot-opened PR's dispatched runs park as unapproved
holds, and the message says so rather than letting it be rediscovered at merge time.

**M6 — Nightly maintainer digest.** `info`, **always sent**, pings only on a threshold breach.

> **Circuit Breaker — nightly digest, 2026-09-28**
> **Tier 2** green, 6/7 nightlies (one infra failure 09-25)
> **PRs awaiting review — 2** · #184 quarantine row *(1d, 21/21 green)* · #177 Dependabot `vite` 5→6
> `major-update` *(6d ⚠️ over 3 days, 21/21 green)*
> **Open issues — 4** · #162 QUAR-001 tracking *(5d, expires in 85d)* · #106 scanner silence *(31d ⚠️ no
> activity 14d)* · #104, #103 packaging *(both > 30d)*
> **Quarantines** QUAR-001 expires in 85 days
> **Ledger** 2 rows expiring within 30 days — see issue #171
> **Thresholds tripped** PR #177 waiting 6 days · issue #106 stale 31 days → **pinged**

When nothing is outstanding it still sends: one line, `success` level, no ping. That is information too.

**Why M1–M3 are sent from inside `tier2.yml` rather than left to `notify.yml`.** A called workflow produces no
`workflow_run` event of its own — the caller's run is the run — so `notify.yml`'s watch covers the standalone
nightly and dispatch only, and would say nothing about a Tier 2 failure during a release. The tier therefore
sends its own verdict messages, and `notify.yml`'s entry is the backstop for the case where the tier fails
before the triage jobs are reached. Both are wanted; neither is redundant.

Thresholds are named constants in `maintainer_digest.py`: a PR awaiting review more than **3 days**, an
issue with no activity for more than **14 days**, a quarantine expiring within **14 days**. Only a tripped
threshold pings.

### 6.1 Two consequences worth stating plainly

**`review-alert.yml` is an hourly sweep, not a pull-request-event workflow.** Both obvious designs fail, and
the second fails silently:

- A plain `pull_request` trigger receives no secrets on a fork pull request, so `DISCORD_WEBHOOK_URL` would be
  absent and the alert would never fire.
- `pull_request_target` does hand out a writable token even for Dependabot — that is exactly why
  `dependabot-lockfile-sync.yml` uses it. But a run **triggered by a Dependabot event reads the Dependabot
  secret store, not the Actions one**, so the webhook would be missing for precisely the pull requests that
  most need the alert: the `major-update` ones nothing auto-merges. That is why every Discord message about a
  Dependabot pull request in this repo today travels through `notify.yml`'s `workflow_run` rather than being
  sent from the Dependabot-triggered run itself.

So M5 is delivered by an **hourly sweep over open pull requests**, with idempotency carried by a
`review-alerted` label the job applies once — the same labelling mechanism `dependabot-automerge.yml` already
uses for `major-update`. No `pull_request_target`, no writable token on an untrusted trigger, and no second
copy of the webhook in the Dependabot secret store. The cost is up to an hour of latency on "this PR needs
review", which is the right trade for a queue a human reads between other things.

The triage's own pull request cannot use that path either way — a `GITHUB_TOKEN`-created PR triggers no
pull-request event, and waiting an hour to be told about a PR the same run just opened would be absurd — so
`triage-emit` sends M5 immediately, through the same builder in `review_alert.py`. The sweep then sees the
label already applied and does not repeat it. One builder, one format, no double notification.

**The digest deliberately breaks the pager doctrine.** `cb-automation` says notify on state changes, not
every run; a nightly digest is per-run by construction. That exception is considered, and it is written both
here and into the skill so that a future reader does not correctly "fix" the digest into silence. What
preserves the pager's meaning is that the digest **pings only on a threshold breach** — an `@`-mention still
means "act now".

---

## 7. Security, failure modes, and verification

### 7.1 Injection surfaces

Test names and failure messages are attacker-influenceable on a public repository. Each surface is closed
explicitly:

1. **Test names → CSV.** Written with Python's `csv` module, never string concatenation. Commas, quotes and
   newlines are the writer's problem.
2. **Anything → Discord.** `notify_discord.py` fixes `allowed_mentions`, so no text can ping. Bodies go via
   `--body-file`, never interpolated into a `run:` block — `test_discord_notify.py` already enforces the
   `env:` rule for the secrets.
3. **Model prose → CSV and issue body.** Same `csv` writer; `gh issue create --body-file`; control
   characters stripped and length capped. The row arrives as a PR a human reads before it enters the register.
4. **Anything → the job log.** A fixed label plus the sanitised test id, never raw message text — the
   `py/log-injection` class that 0.4.5 already closed once in the OAuth rotation path.
5. **No execution of untrusted content.** Neither triage job checks out a suite run's head, and nothing in an
   artifact is executed. Artifacts are data, the same posture `notify.yml` takes toward its event payload.

Workflow hygiene per the `cb-automation` checklist: top-level `permissions: {}` with per-job grants;
every `${{ }}` through `env:` and quoted; actions pinned by tag; `persist-credentials: false` except in the
one job that pushes; `# checkov:skip=CKV_GHA_7` with a reason on every dispatch input, verified by running
`checkov -f <file> --framework github_actions` locally.

### 7.2 Failure modes designed for rather than discovered

- **The cron is inert until `tier2.yml` reaches the default branch.** `schedule` and `workflow_run` fire only
  from the default branch's copy. The file pins every checkout's ref instead of carrying the
  `default-branch-intentional` marker, so `test_scheduled_workflows_pin_their_ref.py` checks it rather than
  exempting it (A2 plan, deviation 3), and the sequencing in §9 puts the merge before anyone expects a
  nightly.
- **A `GITHUB_TOKEN` PR gets no checks.** Followed by `dispatch_required_checks.sh`. Per PR #176 those
  dispatches can still park as `action_required` holds on a bot-opened PR; M5 reports the count.
- **A row PR every night for the same failure.** Prevented by the two idempotence rules and the deterministic
  branch name.
- **Triage turning one red thing into two.** Emit steps are individually fault-tolerant: a missing webhook is
  a logged no-op, and a failed `gh issue create` still leaves `verdict.json` uploaded. The one condition that
  must fail loudly is malformed or absent JUnit, because that is a gate not running.
- **A model outage.** The prose step is non-blocking; the row lands with a mechanical reason and a `notes`
  marker. A diagnosis is never a reason for a job to fail.
- **Cost.** One model call per red nightly; none on green.

### 7.3 What actually verifies this, and what does not

`make verify` and `make verify-full` execute **none** of this. Their exit codes are not evidence for any
part of it, and must not be offered as such (CLAUDE.md, rule 1). The covering evidence is:

- `tests/build/test_tier2_triage.py` — one fixture per verdict row, including `NOT_COLLECTED` and both
  idempotence rules.
- `tests/build/test_maintainer_digest.py`, `tests/build/test_review_alert.py` — one fixture per message
  shape, including the overflow case and the nothing-outstanding case.
- `tests/build/test_tier2_wiring.py`: each suite has one script under `scripts/ci/`, called by both the
  workflow and the `make` target, and neither re-inlines it.
- `checkov -f` on each new workflow, locally, before pushing.
- A real `workflow_dispatch` of `tier2.yml` on the branch, with the triage pointed at fixture directories to
  force each verdict path. **This is the only thing that proves the automation works**, and it happens before
  the pull request, not after it.

### 7.4 Existing guards — which pass unchanged, and which must be edited

Expected to pass with no change: `test_workflow_job_graph.py`, `test_workflow_run_blocks.py`,
`test_workflow_wiring_resolves.py`, `test_discord_notify.py`, `test_ci_script_contract.py`,
`test_quarantine_register.py`, `test_repo_governance.py`, `test_plan_references.py`.

**`test_ci_evidence_retention.py` must be edited, and the edit is part of the slice that causes it.** It is a
registry, not an inference: `SEEDED_WORKFLOWS`, `EVIDENCE_OWING_JOBS` and `ARTIFACT_SOURCE_WORKFLOWS`
enumerate workflows and job ids by name, so moving the composed journey out of `e2e.yml` silently drops the
requirement that it upload diagnostics unless `composed-e2e.yml` is added to `ARTIFACT_SOURCE_WORKFLOWS` in
the same commit. `tier2.yml` joins the same maps in A2 — deferred to B1, since `tier2.yml` executes no
suite until its triage jobs exist (A2 plan, deviation 4) — and `mono-smoke.yml` in A3. Slice A1 is not
complete without its entry; a green run of that test proves nothing if the workflow it was watching has been
renamed out from under it.

**`test_scheduled_workflows_pin_their_ref.py`** covers the new crons. `tier2.yml` does not carry
`# scheduled-ref: default-branch-intentional`: it pins every checkout's ref, and the ref it passes to each
called suite, so the test checks it rather than exempting it (§7.2; A2 plan, deviation 3).

**Check-run names change on the release path, and nothing asserts them today.** `release.yml` currently calls
`browser-e2e.yml` directly, so its checks read `Browser E2E / browser-e2e (shard 1/2)`. Calling `tier2.yml`
instead nests one level deeper — `Tier 2 / Browser E2E / browser-e2e (shard 1/2)` — which is three levels of
reusable-workflow nesting, inside GitHub's limit of four. No test and no ruleset names those strings
(`required_checks.py` does not list Browser E2E at all), so nothing breaks; it is recorded here because a
future reader wondering why the release's check names grew a prefix deserves the answer.

---

## 8. Out of scope

Stated so that no slice quietly grows into one of these.

- **Fixing #162 / QUAR-001.** The register's leading suspect is a missing `Task` reference in
  `schedule_bootstrap`; that is a one-line change plus a regression test and deserves its own TDD cycle, not
  a ride inside a CI programme. This design only makes the quarantine *visible*.
- Making T2 a required check. `tests/build/required_checks.py` is untouched.
- arm64 rows and the remaining package formats (programme Phase 3, slices 3–4).
- Anything in the fleet / T3 path.
- Copilot CLI jobs on the headless box.
- Any automation that modifies application code, merges a PR, renews a quarantine row, or promotes a release.

---

## 9. Slices

Ordered so that the first slice holding write permissions ships fourth, after the decision logic has run
read-only against real nightlies.

| # | Slice | Delivers | Write access |
|---|---|---|---|
| A1 | Extract `composed-e2e.yml`; `e2e.yml` becomes a caller (keeping its nightly, which A2 moves to `tier2.yml` — one cron cannot live in two files); QUAR-001 becomes a visible `SKIPPED` backed by the register; the `test_ci_evidence_retention.py` registry follows the move (§7.4) | No behaviour change, fewer lines, an honest skip | none |
| A2 | `tier2.yml` aggregator, `make verify-composed`, the drift guard; `release.yml` and `release-dry-run.yml` call it with `["browser","composed"]` | Tier 2 exists, is runnable locally, and is nameable | none |
| A3 | `mono-smoke.yml`, after deciding how the built image reaches a second runner; the release's `suites` becomes the default all-three | The tier's third suite | `packages: write` stays wherever the push ends up |
| B1 | `tier2_triage.py` + tests + `triage-decide` | Verdicts, `verdict.json`, M1–M3 | none |
| B2 | `triage-emit`, and `review_alert.py` as the message builder it calls | M4, M5 for the bot's own PR, the issue and the row PR | first write access in the programme |
| B3 | `maintainer_digest.py`, `maintainer-digest.yml`, `review-alert.yml` (hourly sweep) | M5 for human and Dependabot PRs, M6 nightly | read-only (digest); `pull-requests: write` for the label only (review alert) |
| B4 | The model prose step in `triage-decide` | The narrative field | none |

**Prerequisite, already met.** A2 edits the `browser-e2e.yml` call sites PR #182 introduced; that PR merged
into `dev` as `227b9527` on 2026-09-27, so every slice here branches from `dev` with no ordering constraint.

Each slice is independently shippable, and the repository is never worse off between them. **This document is
a programme, not one implementation plan**, in the same sense as the verification strategy design: A1 is the
first slice that needs a written plan, and each later slice is planned against this document as the shared
reference rather than all six being planned at once.

### Implementation notes (slice A2)

Rulings made during A2's execution that this document did not anticipate:

- **`tier2.yml`'s pre-tag trigger.** It carries a path-filtered `pull_request` trigger on its own two files
  (`.github/workflows/tier2.yml`, `scripts/ci/tier2_gate.py`), so its job graph runs before a tag whenever
  either changes. `tests/build/test_release_paths_run_before_the_tag.py` now counts a workflow as its own
  pre-tag caller only when a qualifying trigger has no `paths:`/`paths-ignore:` filter, or its `paths:`
  filter includes the workflow's own file (`_self_qualifies`). T2 is still not a required check (D2).
- **The browser suite's JUnit report stopped disappearing.** `playwright.config.ts`'s HTML reporter now
  writes to `playwright-report/html` rather than `playwright-report/`, because sharing that directory with
  the JUnit file deleted `junit.xml` on every CI run. The JUnit path this document names above,
  `playwright-report/junit.xml`, is unchanged; a local `npx playwright show-report` now needs the path
  `playwright-report/html`.
- **The composed journey's rerun guard** is documented in §3.4.
- **`e2e.yml`'s stale comment.** The `composed:` job's inline comment said "For a tag push, a pull request or
  the nightly, `inputs` is null" — `e2e.yml` no longer has a `schedule` trigger, since the nightly moved to
  `tier2.yml` in this slice, so the comment was corrected to drop "or the nightly".

### Implementation notes (slice A3)

Rulings made during A3's execution that this document did not anticipate:

- **`mono-smoke.yml` inherits its caller's permissions.** It declares no `permissions:` block at any level, so
  every job runs with the calling job's `GITHUB_TOKEN` grant: `dev-ci.yml` grants `packages: write` so its
  `build-docker` job can publish `:nightly`/`:dev`, while `tier2.yml`, `release.yml` and `release-dry-run.yml`
  grant read only and their mono runs cannot push. A declared block would be wrong either way — `packages:
  write` is more than a read-only caller grants (GitHub refuses to load such a callee), and `contents: read`
  would strip `dev-ci.yml`'s write grant.
- **Decision 2 is confirmed: the release adds `"mono"`.** `release.yml` and `release-dry-run.yml` pass
  `suites: ["browser","mono"]` to `tier2.yml` — §10.2's "the release runs the whole tier" now holds for
  browser and mono, with only the composed journey excluded (AGT-01, decision 1 of A2).
- **The check name is now compound.** `Build Docker (smoke test)` becomes `Build Docker (smoke test) / Mono
  image smoke`, since `build-docker` now calls the reusable `mono-smoke.yml` rather than running the smoke
  inline. It is still not a required check (`.github/branch-protection.md`, `tests/build/required_checks.py`).
- **The inherited-permissions choice needed a scanner exception.** checkov reads `mono-smoke.yml`'s absent
  `permissions:` block as `write-all` and fails `CKV2_GHA_1`; it cannot apply an inline `checkov:skip` to a
  graph check, so the skip is scoped to this one file and this one check in the scanner invocation itself,
  governed by manifest row `CHECKOV-001`
  (`specs/1.0.0/release-control/security-suppressions.json`) and held to that scope by
  `tests/build/test_checkov_mono_smoke_exception.py`.
- **The push is tied to `inputs.ref == ''`.** A caller passing `publish: true` together with a non-empty
  `ref` would build and smoke a different commit than the one that triggered the run, then push that other
  commit's image tagged `:dev`/`:nightly` — so both push steps' `if:` require `inputs.ref == ''` alongside
  `inputs.publish` and a push to `dev`.
- **The smoke refuses to run over a developer's real stack, and redacts what it uploads.**
  `scripts/ci/tier2-mono-smoke.sh` exits before doing anything if a repo-root `.env` already exists or a
  container named `circuitbreaker` already exists (docker-compose.yml pins that name), since either is very
  likely the developer's own stack that `up -d`/`down -v` would recreate or destroy. Its diagnostics
  collection also strips `Config.Env` from the `docker inspect` output it uploads, because that field carries
  the four minted smoke secrets in clear and `::add-mask::` only redacts log output, not an artifact.

---

## 10. Decisions that were open during design

Both were settled on 2026-09-27 and are recorded here so a later reader does not reopen them by accident.

1. **Digest delivery time: 13:15 UTC**, chosen to follow every other scheduled workflow and land mid-morning
   in the maintainer's timezone. The only hard constraint is that it runs after `ledger-watch.yml` at 06:23
   UTC, so its ledger line can reference that night's issue.
2. **Superseded** (see §3.1): **The release calls all three suites.** Mono smoke is not skipped on the release path. It costs a second
   mono image build there, and the reason it is worth paying is in §3.1: `runtime_digest` parity proves the
   image and the package came from the same tree, not that the image boots.
