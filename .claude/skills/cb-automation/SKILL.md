---
name: cb-automation
description: The maintenance automation around Circuit Breaker — which bots and scheduled workflows exist (Discord notifications, ledger watch, branch cleanup, Dependabot lockfile sync, the required-checks dispatcher, the post-release follow-up), the GITHUB_TOKEN rules they are built around, how to add a new one safely, and the guardrails for AI agents (Copilot cloud agent, Agentic Workflows, Copilot CLI on the headless box). Use this whenever adding or changing a scheduled or bot workflow, anything under scripts/ci/, a Discord notification, a workflow that pushes commits or opens PRs, a self-hosted runner, or an AI/agent workflow, and when asked why a bot did or did not act.
---

# Circuit Breaker — Automation

One maintainer, no budget: automation exists to remove toil, and must never
become toil itself (a noisy alert, a red check nobody owns, a bot that needs
babysitting). Everything that needs a human reaches them through **Discord**.

## What runs on its own

| Workflow | When | Does | Talks to Discord |
|---|---|---|---|
| `notify.yml` | Every watched workflow completes | `scripts/ci/workflow_alert.py` decides; posts failures (with ping) and recoveries | Yes — it is the pager |
| `release.yml` | `make release-candidate` | See **cb-release** | "draft staged, waiting for you" (ping), "vX is published" |
| `release-followup.yml` | Dispatched by release post-publish | Next-patch PR into `dev`, stale draft cleanup | Via notify.yml on failure |
| `ledger-watch.yml` | Nightly 06:23 UTC | `scripts/ci/ledger_watch.py`: one `release-control` issue listing ledger rows expiring within 30 days and risks past `next_review`; closes it when clear | When a new issue opens (ping) |
| `branch-cleanup.yml` | Sundays 05:00 UTC; manual dispatch defaults to dry run | `scripts/ci/branch_cleanup.py`: deletes branches fully contained in main/dev, idle > 14 days, not the head or base of an open PR | Via notify.yml on failure |
| `dependabot-lockfile-sync.yml` | Dependabot pip PR into dev/main | Regenerates `requirements.txt` from `poetry.lock` with the **base** branch's generator, pushes, then dispatches required checks | Via notify.yml on failure |
| `security.yml`, `codeql.yml` | Weekly + push/PR + dispatch | Scanners | Via notify.yml on failure |
| `e2e.yml` | Disabled (`if: false`, QUAR-001, issue #162) | Composed agent journey | — |

Squash-merged branches are never cleaned up (their commits are not contained
in main), by design of the containment rule.

## GITHUB_TOKEN rules everything here is built around

1. **Events caused by GITHUB_TOKEN start no workflows** — no `push`,
   `pull_request`, `release`, or `push: tags` run follows a bot's commit, PR,
   release or tag. The one exception is `workflow_dispatch` (and
   `repository_dispatch`). So:
   - a bot that pushes a commit or opens a PR must then run
     `bash scripts/ci/dispatch_required_checks.sh <branch> [dev|main]`, which
     dispatches `dev-ci.yml`/`ci.yml`, `security.yml` and `codeql.yml` so all
     21 required checks land on the head SHA. Without it the PR can never
     merge. The list of 21 lives only in `tests/build/required_checks.py`.
   - follow-on work after a release is *dispatched*, never triggered.
2. **Draft releases are invisible without push access.** A job that reads a
   draft needs `contents: write` even if it only reads.
3. **`workflow_run` and `schedule` only fire from the default branch's copy**
   of the workflow file. A new watcher or cron does nothing until it reaches
   `main`. Scheduled workflows carry `# scheduled-ref: default-branch-intentional`
   or pin a ref (`test_scheduled_workflows_pin_their_ref`).
4. **`pull_request_target` hands out a writable token.** Never check out and
   execute the PR head in it: restore scripts from the base SHA (see
   `dependabot-lockfile-sync.yml`) and guard on the actor.
5. Creating PRs with GITHUB_TOKEN requires the repo setting "Allow GitHub
   Actions to create and approve pull requests".

## Discord

- Send only through `scripts/ci/notify_discord.py` (`--level
  info|success|warning|failure --title … [--body|--body-file] [--url]
  [--field k=v] [--mention]`). Never `curl` the webhook.
- Secrets: `DISCORD_WEBHOOK_URL` (required for anything to send) and
  `DISCORD_MENTION_USER_ID` (the numeric user id — Developer Mode, right-click
  your name, Copy User ID — never the username; used only with `--mention`,
  and a bad value costs only the ping, not the message). Both must be
  **repository** secrets: environment secrets are invisible to every job
  without that `environment:`. Pass them
  through step `env:`, never interpolated into `run:` — a test enforces it.
- Unset webhook or a Discord outage = logged no-op, exit 0. A notification is
  never a reason for a job to fail.
- `allowed_mentions` is always explicit: text can never ping `@everyone`,
  whatever a branch or commit is named. Only `--mention` pings, and only the
  configured user.
- **Notify on state changes, not on every run.** New failure on main/dev or a
  scheduled/dispatched run → ping. Green after red → recovery, no ping. PR
  runs, cancellations and green-after-green → silence. A nightly that rewrites
  an existing issue does not re-notify.
- Adding a workflow that should page: add its exact `name:` to
  `notify.yml`'s `workflows:` list. `test_every_watched_name_is_a_workflow_that_exists`
  fails if a listed name stops matching.

## Adding an automation — checklist

- [ ] Logic in a typed, docstringed stdlib script under `scripts/ci/` with
      unit tests in `tests/build/` (fixtures, no network); add it to the
      ruff/mypy lines of `make lint`.
- [ ] Top-level `permissions: {}` or read-only; grant per job, minimum needed.
- [ ] Every `${{ }}` through `env:` and quoted; actions pinned by tag like the
      rest of the repo (`actions/checkout@v5`), `persist-credentials: false`
      unless the job pushes.
- [ ] Dispatch inputs get `# checkov:skip=CKV_GHA_7` with a reason; run
      `checkov -f <file> --framework github_actions` locally.
- [ ] Anything it pushes or opens is followed by `dispatch_required_checks.sh`.
- [ ] Idempotent: a re-run for the same input updates or exits cleanly.
- [ ] Destructive actions (delete branch, delete draft, close issue) re-check
      their precondition immediately before acting, and log each decision.
- [ ] Failures reach Discord (add to `notify.yml`); successes usually don't.
- [ ] Never `continue-on-error` to make it green, never auto-merge to `main`.

## AI agents

Issue and PR text on this public repo is **untrusted input**. An agent that
reads it must not also hold write access.

- **Copilot cloud agent** (assign an issue, or `gh agent-task create`): for
  bounded code changes that come back as a PR for review. Good first tasks:
  QUAR-001 (#162), major Dependabot migrations, a shared sanitiser for the
  `py/log-injection` alerts. It reads `CLAUDE.md` and these skills
  (`.claude/skills/` is a supported skills path), so the verification rules
  apply to it too.
- **GitHub Agentic Workflows** (`gh aw`, Copilot engine): for judgement over
  untrusted text — issue triage, CI failure analysis, release-note drafts,
  security digests. Keep them read-only; writes go through safe outputs.
- **Copilot CLI unattended** (cron on the headless box): explicit
  `--allow-tool` lists, never `--allow-all`/`--yolo`; always
  `--deny-tool 'shell(git push)'`, `--secret-env-vars`, `--max-ai-credits`,
  `--no-ask-user`. Auth via a fine-grained PAT with **Copilot Requests** in
  `COPILOT_GITHUB_TOKEN` (classic PATs are not supported). Report through
  `notify_discord.py`.
- Nothing an agent produces reaches `main` without a PR, the 21 required
  checks and a human merge. No agent approves or promotes a release.

## The headless box (Fedora Server, AMD, always on)

Runs only what hosted runners cannot: the release soak (install the draft
tarball, boot, probe `/readyz`, uninstall), a nightly `make e2e-local`
against `main`, the Tier 3 QEMU fleet runner (`fleet.yml`,
`[self-hosted, qemu]`, needs KVM) and Copilot CLI report jobs.

**Self-hosted runners on a public repo will run fork code** unless
restricted: register the box in a runner group limited to named workflows
(`fleet.yml` and the soak/nightly ones), make jobs ephemeral (fresh container
or VM per job), and never attach it to a `pull_request` trigger. Installer
journeys there use rootless podman with `--security-opt label=disable`.
