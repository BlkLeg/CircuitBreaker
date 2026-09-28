# Split CI/CD: verification on Forgejo, publication on GitHub

**Date:** 2026-09-28
**Status:** Superseded 2026-09-28 by [the GitLab cutover](./2026-09-28-gitlab-cutover.md).
**Forgejo:** `https://forgejo.blkleg.app/Shawnji/CircuitBreaker.git` (runner and Docker already installed)
**GitHub:** `https://github.com/BlkLeg/circuitbreaker`

## Goal

Every run that checks code (lint, types, unit and integration suites, security
scans, browser E2E, composed agent E2E, installer journey, package builds for
testing) runs on the self-hosted Forgejo instance. GitHub keeps only what has
to be public or has to use GitHub's identity: the GitHub Release, the GHCR images,
cosign keyless signing (GitHub OIDC), GitHub Pages, and CodeQL code scanning.

## The rule the design rests on

> **Forgejo owns the code. GitHub is where we publish.**
> Code reaches GitHub `dev`/`main` only through a Forgejo job that runs **after**
> the full gate is green on that exact SHA. That job then puts a
> `forgejo/verify` commit status on the SHA on GitHub. `release.yml` refuses to
> build a SHA that does not have that status.

Everything else in this plan follows from that rule. The two other designs
fail for concrete reasons:

- *GitHub stays the source, Forgejo pull-mirrors it and posts statuses back.*
  Pull mirrors poll, so the checks trail each push by up to the mirror interval.
  Fork PRs would also run on a homelab runner with no review first. The last
  problem is that required checks would come from a system GitHub cannot see
  failing.
- *Forgejo's built-in push mirror (sync on commit).* This mirrors every push,
  red or green. GitHub would stop being the "tested code only" copy, and the
  release gate would have nothing to rely on.

## Topology

```
 laptop ──push──▶ Forgejo (origin)
                    │  PR → dev / main           .forgejo/workflows/verify.yml   (every PR + push)
                    │  merge                     .forgejo/workflows/nightly.yml  (composed E2E, baseline, ledger)
                    │                            .forgejo/workflows/fleet.yml    (QEMU Tier 3, on demand)
                    ▼
            verify green on SHA X
                    │
                    ├─ promote job: git push --ff-only github X:refs/heads/dev (or main)
                    └─ POST /repos/BlkLeg/CircuitBreaker/statuses/X  context=forgejo/verify
                    ▼
 GitHub (publish mirror)
    release.yml (dispatch)  ── requires forgejo/verify on SHA ──▶ build → smoke → image → cosign → Release + GHCR
    publish-dev.yml (push: dev) ── requires forgejo/verify ──▶ ghcr.io/blkleg/circuitbreaker:dev, :nightly
    pages.yml, codeql.yml
                    │
                    ▼
    tag vX.Y.Z + follow-up branch ──▶ pulled back into Forgejo by sync-from-github.yml
```

The last arrow matters. `release.yml` creates the tag on GitHub, and
`release-followup.yml` bumps `VERSION`. Both write to GitHub. If they keep doing
that, GitHub and Forgejo diverge, and the next fast-forward promote fails. So the
follow-up moves to Forgejo, and Forgejo pulls tags back from GitHub.

## Inventory: where each of today's 22 workflows goes

| Workflow | Today | Goes to | Notes |
|---|---|---|---|
| `ci.yml` | PR/push `main` | **Forgejo** (`verify.yml`) | Its `candidate-*` jobs stay on GitHub as `release-rehearsal.yml` (see Task 6). |
| `dev-ci.yml` | PR/push `dev` | **Forgejo** (`verify.yml`) | `build-docker`'s GHCR push is publication, so it goes to GitHub `publish-dev.yml`. |
| `security.yml` | PR/push, weekly | **Forgejo** | All ten scanners run in containers, and none needs GitHub. SARIF upload goes away; reports become artifacts. |
| `codeql.yml` | PR/push, weekly | **GitHub** | CodeQL needs GitHub code scanning, and it is free on a public repo. Push + weekly only. |
| `docs.yml` | PR/push, paths | **Forgejo** | mkdocs strict build + lychee. |
| `pages.yml` | push `main`, after Release | **GitHub** | Publication. |
| `e2e.yml` + `composed-e2e.yml` | tag, PR paths, nightly | **Forgejo** | 40–75 min on a free box, not a shared queue. QUAR-001 row stays. |
| `installer-journey.yml` | PR paths, called by release | **both** | Forgejo runs it on PR; the GitHub copy stays as a callee of `release.yml`. |
| `browser-e2e.yml` | called by ci/dev-ci/release | **both** | Same split as above. |
| `artifact-smoke.yml` | called by dev-ci/release | **both** | Forgejo: amd64 per-commit. GitHub: amd64 + arm64 at release. |
| `build.yml` | called by ci/release | **GitHub** | Signing key `AGENT_SIGNING_PRIVATE_KEY` never leaves GitHub. Forgejo builds unsigned (warn-mode) test packages. |
| `release.yml` | dispatch | **GitHub** | Adds the `forgejo/verify` precondition (Task 5). |
| `release-dry-run.yml` | dispatch | **GitHub** | Unchanged. |
| `release-followup.yml` | dispatch | **Forgejo** | It writes to the source of truth, so it must run there. |
| `fleet.yml` | dispatch, `[self-hosted, qemu]` | **Forgejo** | Already self-hosted, and it belongs on the homelab. |
| `baseline.yml` | nightly | **Forgejo** | |
| `ledger-watch.yml` | nightly | **Forgejo** | Discord secrets move with it. |
| `notify.yml` | `workflow_run` | **both, reshaped** | Forgejo has no `workflow_run`. Each Forgejo workflow gets a final `if: always()` notify job instead. GitHub's copy only lists `Release`, `Deploy Pages`, `CodeQL`, `Publish dev image`. |
| `branch-cleanup.yml` | weekly | **Forgejo** | Branches live on Forgejo now. Needs its API calls ported (Task 7). |
| `dependabot-automerge.yml` | PR | **delete** | Replaced by Renovate on Forgejo (Task 8). |
| `dependabot-lockfile-sync.yml` | PR target | **delete** | Renovate's `postUpgradeTasks` regenerates the lockfile before it opens the PR. |
| (new) `publish-dev.yml` | — | **GitHub** | `:dev`, `:dev-<sha>`, `:nightly` GHCR tags, moved from `dev-ci.yml`. |
| (new) `release-rehearsal.yml` | — | **GitHub** | Push to `main`. Keeps the release-only callees exercised before a tag (Task 6). |

## Forgejo Actions: what behaves differently here

Check each of these in Task 1's spike before writing the full workflows. Several
depend on the Forgejo and runner versions installed, and I have not seen those.

1. **Directory precedence.** If `.forgejo/workflows/` exists, Forgejo runs only
   that directory and ignores `.github/workflows/`. GitHub never reads
   `.forgejo/`. The two sets never cross-trigger, and that separation is the
   reason for the directory choice.
2. **Runner labels.** The workflows say `ubuntu-22.04` / `ubuntu-24.04`. Register
   the runner with those labels mapped to images, e.g.
   `ubuntu-22.04:docker://ghcr.io/catthehacker/ubuntu:act-22.04` and
   `ubuntu-24.04:docker://ghcr.io/catthehacker/ubuntu:act-24.04`. Keep the
   names identical. `tests/build/test_ci_scripts_match_runner_python.py` depends
   on `ubuntu-22.04` having system `python3` 3.10, and `act-22.04` does.
3. **Where actions resolve from.** Forgejo's `DEFAULT_ACTIONS_URL` is
   `https://data.forgejo.org`, not GitHub. Either set it to `https://github.com`
   in `app.ini` or write `uses:` with full URLs. Otherwise `actions/checkout@v5`
   resolves against a mirror that may lag.
4. **Docker inside jobs.** The backend suite starts a TimescaleDB
   testcontainer (`tests/conftest.py`). The job container needs the host socket
   (`container.docker_host: automount` in the runner `config.yml`, and
   `/var/run/docker.sock` in `valid_volumes`). Testcontainers also needs
   `TESTCONTAINERS_HOST_OVERRIDE` set to an address the job container can reach.
   Composed E2E and the installer journey need the same.
5. **Artifacts.** `actions/upload-artifact@v7` / `download-artifact` depend on
   the artifact protocol the server implements. Check the installed Forgejo
   version. If v4+ is not supported, use the `forgejo/upload-artifact` fork or
   pass files through the workspace inside one job.
6. **Reusable workflows** (`uses: ./.github/workflows/x.yml`) are more limited
   on Forgejo, especially for secrets and outputs. The Forgejo side does not use
   them. Each job calls the existing scripts and `make` targets instead:
   `scripts/ci/tier0-static.sh`, `scripts/ci/tier1-unit.sh`,
   `scripts/ci/tier3-artifact.sh`, and `scripts/ci/installer-journey.sh`. This
   also keeps "what CI runs" and "what `make verify-full` runs" the same thing,
   which is the point of running it locally.
7. **Expressions that act does not evaluate like GitHub.** `strategy.job-total`
   (used in the shard names) should become a literal `4`. `concurrency:`,
   `permissions:`, `environment:` and `workflow_run` are either ignored or
   unsupported. Nothing on Forgejo may rely on them for safety.
8. **arm64.** The homelab runner is presumably amd64. Per-commit checks are
   amd64 only, and arm64 smoke stays in `release.yml` on GitHub's
   `ubuntu-22.04-arm`. If you later add an arm64 box (a Pi 5 would do), register
   it with the `ubuntu-22.04-arm` label and the matrix legs work unchanged.
9. **Playwright.** Run the browser job in the pinned Playwright container. It is
   the same tag `tests/build/test_playwright_image_matches_package.py` already
   locks to `@playwright/test`, so the pairing guard covers Forgejo for free.
10. **Air-gap.** A second runner label with no outbound network (a Docker network
    with `internal: true`) lets a `CB_AIRGAP=true` job prove that no outbound
    call happens. That is something hosted runners could never show.

## Secrets: where each one lives

| Secret | Lives on | Why |
|---|---|---|
| `AGENT_SIGNING_PRIVATE_KEY` | GitHub only | Signs shipped agents. Forgejo builds are warn-mode by design (`build.yml` already handles an empty key). |
| cosign | GitHub OIDC (no secret) | Keyless, bound to GitHub's identity. |
| `GITHUB_TOKEN` (GHCR, Releases) | GitHub only | |
| `GH_PROMOTE_DEPLOY_KEY` | Forgejo | SSH deploy key, write access, on GitHub. Used only by the promote job. |
| `GH_STATUS_TOKEN` | Forgejo | Fine-grained PAT, **Commit statuses: write** on this one repo, nothing else. |
| `DISCORD_WEBHOOK_URL`, `DISCORD_MENTION_USER_ID` | both | Each side notifies for its own runs. |
| `RENOVATE_TOKEN` | Forgejo | A Forgejo token for the Renovate bot user. |

CLAUDE.md's secrets rule still applies. Test fixtures keep generating ephemeral
values at runtime, and no secret is written into a Forgejo workflow file.

## Tasks

Each phase leaves both systems working. Nothing on GitHub is deleted until
Forgejo has shadowed it green for a week (Task 9).

### Task 1 — Runner spike (no repo changes)

Register or relabel the runner (§ "Forgejo Actions" items 2–5). Then push a
throwaway branch carrying a single `.forgejo/workflows/spike.yml` with four
steps: checkout, `setup-python` 3.12 with pip cache, a testcontainer-backed
backend test file, and an upload/download artifact round trip.
Exit criterion: all four pass. Record the Forgejo and runner versions and the
artifact action that worked. Everything later depends on this.

### Task 2 — `verify.yml`: the per-commit gate on Forgejo

Files:
- Create: `.forgejo/workflows/verify.yml`
- Read first: `.github/workflows/dev-ci.yml`
- Read first: `.github/workflows/ci.yml`
- Read first: `.github/workflows/security.yml`
- Read first: `scripts/ci/tier0-static.sh`
- Read first: `scripts/ci/tier1-unit.sh`

Triggers: `pull_request` and `push` on `dev` and `main`, plus `workflow_dispatch`.
Jobs keep the **exact check names** in `tests/build/required_checks.py` (`Lint`,
`Security Gate`, `Backend tests (shard 1/4)`…, `Backend coverage gate`,
`Fresh-install migrations`, `Test`, and the ten security scanner names). That
list is how the gate on Forgejo is enforced (Task 4). On top of those, the
following run on every PR, not only when a path filter matches:
`Browser E2E (shard 1/2)`/`(2/2)`, `Docs build`, `Artifact smoke (amd64)` (build
unsigned packages, then `circuit-breaker --selftest`, deb install, and
`/readyz` boot), and `Runtime parity`.
Keep the pinned `PYTHONHASHSEED` env from `dev-ci.yml`.

A final job, `verify`, `needs:` every job above, so the rest of the plan checks
one name.

### Task 3 — `promote.yml`: the only path onto GitHub

Files:
- Create: `.forgejo/workflows/promote.yml`
- Create: `scripts/ci/promote_to_github.sh`

It runs on `push` to `dev` or `main` on Forgejo. It re-runs nothing. It waits for
`verify` on the same SHA by polling Forgejo's commit-status API, and times out
after 90 min. It then:

1. `git push --ff-only`-equivalent: `git push github "$SHA:refs/heads/$BRANCH"` with
   no `--force`. A non-fast-forward is a hard failure plus a Discord alert. It
   means someone wrote to GitHub directly, and the fix is to find out who, not
   to overwrite.
2. `POST https://api.github.com/repos/BlkLeg/CircuitBreaker/statuses/$SHA` with
   `state=success`, `context=forgejo/verify`, and `target_url` set to the Forgejo
   run.
3. It pushes nothing else. Tags go the other direction (Task 7).

If `CB_AIRGAP`-style isolation is ever applied to the runner itself, this job
needs a runner label that is allowed outbound access to `github.com`. Say so in
the job's comment.

### Task 4 — Branch protection, on both sides

Forgejo (Settings → Branches) for `dev` and `main`: require a PR, and require the
`verify` status check. Block force-push.

GitHub rulesets `Main-Branch` / `Dev-Branch`:
- **Restrict updates** to the promote deploy key only. Nobody else pushes to
  these branches, and that includes you from a laptop.
- Replace the 21 required checks with **none**. A required status check cannot
  be satisfied here, because GitHub evaluates it before the ref moves, and the
  status is posted after the push. The gate is enforced (a) by Forgejo protection
  before the push and (b) by `release.yml`, which checks `forgejo/verify` before
  it builds anything.

**Governance impact, and this is your decision to make:** the branch-protection
document and GOV-15 evidence describe a single maintainer who cannot bypass 21
GitHub-enforced checks (EXC-002's compensating control). After this change the
same checks exist, but Forgejo enforces them. Update the document, the evidence
file and the exception register row in the same commit that changes the
rulesets, and don't let the document describe a control GitHub no longer enforces.

Files:
- Modify: `.github/branch-protection.md`
- Modify: `tests/build/required_checks.py`
- Modify: `specs/1.0.0/evidence/gov-15-branch-protection-enabled.md`
- Modify: `specs/1.0.0/release-control/exception-register.csv`

### Task 5 — `release.yml` refuses an unverified SHA

Files:
- Modify: `.github/workflows/release.yml`

Add a step at the top of the existing `gate` job, before the Tier 0 run:

```bash
state="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${GITHUB_SHA}/status" \
  --jq '.statuses[] | select(.context=="forgejo/verify") | .state' | head -1)"
[ "$state" = "success" ] || { echo "::error::${GITHUB_SHA} has no successful forgejo/verify status"; exit 1; }
```

Keep the in-release Tier 0, `artifact-smoke`, `installer-journey`,
`browser-e2e` and `runtime-parity`. They test the **artifact being shipped**
(both arches, signed), not only the commit. Rule 6 in CLAUDE.md is about exactly
that distinction, and Forgejo's amd64 unsigned build does not replace it.

### Task 6 — GitHub slims down

Files:
- Create: `.github/workflows/publish-dev.yml`
- Create: `.github/workflows/release-rehearsal.yml`
- Modify: `.github/workflows/notify.yml`
- Modify: `.github/workflows/codeql.yml`

- `publish-dev.yml`: `push` to `dev` → assert `forgejo/verify` (same snippet as
  Task 5) → build the mono image → push `:dev`, `:dev-<sha>`, `:nightly` to GHCR.
  This is `dev-ci.yml`'s `build-docker` push steps, lifted out unchanged.
- `release-rehearsal.yml`: `push` to `main` → the `candidate-build`,
  `candidate-artifact-smoke` and `candidate-installer-journey` jobs from `ci.yml`,
  plus `browser-e2e.yml`. **Why this has to exist:**
  `tests/build/test_release_paths_run_before_the_tag.py` requires every reusable
  workflow `release.yml` calls to also be reachable from a `push`/`pull_request`
  workflow. Without it, deleting `ci.yml` makes `artifact-smoke.yml` tag-only
  again, which is how v0.4.3 shipped. `main` moves rarely, so this costs little.
- `codeql.yml`: drop the `pull_request` trigger. PRs don't happen on GitHub any
  more.
- `notify.yml`: shrink the `workflows:` list to what still runs on GitHub.

### Task 7 — What flows back from GitHub

Files:
- Create: `.forgejo/workflows/sync-from-github.yml`
- Create: `.forgejo/workflows/release-followup.yml`
- Create: `.forgejo/workflows/nightly.yml`
- Create: `.forgejo/workflows/fleet.yml`
- Create: `.forgejo/workflows/branch-cleanup.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `scripts/ci/branch_cleanup.py`

- `sync-from-github.yml`: every 15 min plus dispatch. `git fetch github 'refs/tags/v*:refs/tags/v*'`,
  then push the tags to Forgejo. It fetches tags only and never touches branches.
- `release.yml`'s `post-publish` job (`gh workflow run release-followup.yml`,
  and the same for `e2e.yml` on the new tag) dispatches two GitHub workflows
  that no longer exist after the cut-over. Both dispatches move to Forgejo: the
  composed E2E against the tag runs from `nightly.yml`'s dispatch entry. Replace the follow-up dispatch with a call to the Forgejo API that
  dispatches `.forgejo/workflows/release-followup.yml` for the version (token:
  a Forgejo token with `write:repository`, stored as a GitHub `release`-environment
  secret). The follow-up then opens its `chore/post-release-v<ver>` PR **on
  Forgejo**, where `verify` runs on it with nothing extra: the
  `scripts/ci/dispatch_required_checks.sh` workaround existed only because
  GitHub's `GITHUB_TOKEN` pushes start no CI, and Forgejo has no such rule.
- `nightly.yml`: composed agent E2E (keeps honouring QUAR-001 through
  `quarantined:`), `baseline`, and `ledger-watch`. Each has a scheduled checkout
  pinned to `dev`, and `tests/build/test_scheduled_workflows_pin_their_ref.py`
  must be widened to scan `.forgejo/workflows/` too (Task 10).
- `fleet.yml`: move as is. Its `[self-hosted, qemu]` label becomes a Forgejo
  runner label on a KVM-capable host.
- `branch-cleanup.yml`: `scripts/ci/branch_cleanup.py` calls the GitHub API.
  Give it a `--forge forgejo` mode that uses Forgejo's `/api/v1` (whose branch
  and PR endpoints are close to GitHub's shape).

### Task 8 — Dependencies and outside contributors

Files:
- Create: `renovate.json`
- Modify: `.github/dependabot.yml`

- Run Renovate against Forgejo (one scheduled job in `nightly.yml` using the
  `renovate/renovate` image, `platform: forgejo`). Set `postUpgradeTasks` to
  regenerate `apps/backend/requirements.txt` from `poetry.lock`, which is what
  `dependabot-lockfile-sync.yml` does today.
- `.github/dependabot.yml`: remove the version-update entries. **Keep GitHub
  Dependabot security alerts turned on** (a repository setting, not a file).
  They cost nothing and are one more signal.
- Contributor PRs on GitHub: they are still welcome, but none of them runs on
  the homelab runner automatically. A fork PR is untrusted code, and a
  self-hosted runner with the Docker socket is root on that box. The maintainer
  reviews it, then `git fetch github pull/N/head:contrib/N`, pushes that to
  Forgejo, and opens the Forgejo PR. Update `CONTRIBUTING.md` to say so, and pin
  a short note on the GitHub PR template.

### Task 9 — Shadow week, then cut over

1. Merge Tasks 1–3 with `promote.yml`'s push step behind
   `if: vars.PROMOTE_ENABLED == 'true'` (unset). Keep `ci.yml`/`dev-ci.yml`/
   `security.yml`/`docs.yml`/`e2e.yml` running on GitHub.
2. For 7 days, compare every `dev` commit: Forgejo `verify` vs GitHub `Dev CI`
   plus `Security Scan`. Any disagreement blocks cut-over. Diagnose it (it will
   usually be a runner image difference) rather than dismiss it (CLAUDE.md rule 2).
3. Cut over in **one** commit on `dev`: delete `ci.yml`, `dev-ci.yml`,
   `security.yml`, `docs.yml`, `e2e.yml`, `baseline.yml`, `ledger-watch.yml`,
   `fleet.yml`, `branch-cleanup.yml`, `dependabot-automerge.yml`,
   `dependabot-lockfile-sync.yml`, `release-followup.yml` from
   `.github/workflows/`. Add Task 6's GitHub workflows, set `PROMOTE_ENABLED`,
   and apply Task 4's rulesets.
4. Swap remotes on your laptop: `origin` → Forgejo, `github` → GitHub (fetch only).

Rollback is `git revert` of that commit plus restoring the rulesets. GitHub's
workflows come back intact, because nothing was rewritten in place.

### Task 10 — Repo-policy suites and docs follow the move

These tests read `.github/workflows/` and fail or go quiet after the cut-over.
Each has to either widen to `.forgejo/workflows/` or have its assertion restated:

Files:
- Modify: `tests/build/test_release_paths_run_before_the_tag.py`
- Modify: `tests/build/test_scheduled_workflows_pin_their_ref.py`
- Modify: `tests/build/test_workflow_wiring_resolves.py`
- Modify: `tests/build/test_ci_evidence_retention.py`
- Modify: `tests/build/test_ci_scripts_match_runner_python.py`
- Modify: `tests/build/test_discord_notify.py`
- Modify: `tests/build/test_dispatch_required_checks.py`
- Modify: `tests/build/test_dependabot_automerge.py`
- Modify: `tests/build/test_dependabot_lockfile_sync.py`
- Modify: `tests/build/test_fleet_dispatch_contract.py`
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/cb-automation/SKILL.md`
- Modify: `.claude/skills/cb-build-test/SKILL.md`
- Modify: `.claude/skills/cb-release/SKILL.md`
- Modify: `plans/README.md`
- Create: `tests/build/test_forgejo_github_split.py`

Add one new guard, `test_forgejo_github_split.py`, asserting:
- no workflow under `.forgejo/workflows/` references `AGENT_SIGNING_PRIVATE_KEY`,
  `ghcr.io/.../push`, or `id-token: write`, so publication cannot drift onto the
  homelab;
- every name in `required_checks.py` is the `name:` of a job in
  `.forgejo/workflows/verify.yml`;
- `release.yml` and `publish-dev.yml` both contain the `forgejo/verify` check;
- no `.github/workflows/` file triggers on `pull_request` except
  `release-rehearsal.yml`'s callees.

CLAUDE.md changes: rule 4 ("confirm the push landed") now names Forgejo, and the
"What the gates do NOT cover" table gains a column for where each suite runs.

**Verification for this plan's own work:**
`python3 scripts/ci/verify_plan_references.py plans/2026-09-28-split-ci-forgejo-github.md`
before any task starts. `make verify` after Task 10, which runs the
`tests/build` suite. The Forgejo workflows themselves are verified only by
running them in Task 1's spike and Task 9's shadow week. No local gate executes
them.

## Risks

| Risk | Mitigation |
|---|---|
| Homelab box down → nothing can merge or release | Accepted for a solo maintainer. For an emergency, document `workflow_dispatch` of `release-dry-run.yml`, and a manual status post by the maintainer after running `make verify-full` + `npx playwright test` locally. |
| Self-hosted runner compromise via untrusted code | Only Forgejo users you create can open PRs. There are no fork PRs from GitHub (Task 8). The runner runs as a non-root user in its own VM or LXC, not on the box that holds your Circuit Breaker data. |
| Runner image drift vs `ubuntu-22.04` hosted | Pin `catthehacker` image digests, not tags. The shadow week catches the first drift. |
| Divergence: someone pushes to GitHub directly | The ruleset allows only the deploy key. The promote job fails loudly on non-fast-forward. |
| Checks exist on Forgejo but GitHub shows nothing to visitors | `forgejo/verify` status with a `target_url` appears on every GitHub commit. Pages or the README can link the Forgejo repo if it is public. |

## Open questions for you

1. Is `forgejo.blkleg.app` reachable from GitHub-hosted runners? Task 7's release
   → Forgejo follow-up dispatch needs that. If it is not, the follow-up runs from
   `sync-from-github.yml` when it sees a new `v*` tag instead.
2. Runner architecture(s) and whether the box has KVM (for `fleet.yml`).
3. Accept the EXC-002 / GOV-15 restatement in Task 4, or keep GitHub PRs into
   `dev`/`main` (opened by the promote job, auto-merged) so the GitHub-side
   control still exists? The second option costs more moving parts and changes
   nothing about what is actually tested.
4. Is the Forgejo repo public or private? That decides whether the
   `target_url` links work for outside readers.
