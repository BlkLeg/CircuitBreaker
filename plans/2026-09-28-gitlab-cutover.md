# Clean cutover: GitLab is the source and the test gate, GitHub only publishes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move day-to-day development and every verification run to the self-hosted
GitLab at `https://gitlab.blkleg.app/BlkLeg/circuitbreaker`, in one planned cutover,
and leave GitHub with exactly the jobs that must publish under GitHub's identity.

**Architecture:** GitLab holds the branches and merge requests. A pipeline on the
self-hosted runners is the gate. When the pipeline on `dev` or `main` goes green,
a `promote` job fast-forwards GitHub to that same SHA and posts a `gitlab/verify`
commit status. GitHub keeps `release.yml` (which refuses a SHA without that
status), GHCR `:dev` publishing, Pages and CodeQL, and nothing else runs there on
a push. Tags flow the other way: `release.yml` creates them on GitHub, and a
GitLab job pulls them back.

**Tech Stack:** GitLab CE 19.4.1, GitLab Runner 19.4.1 (Docker executor plus one
shell-executor VM), bash, Python 3.12, pytest, GitHub Actions (publishing only),
Renovate.

**Spec:** the "Decisions" section below. The maintainer made these decisions on
2026-09-28. The Forgejo plan this replaces is
[`2026-09-28-split-ci-forgejo-github.md`](./2026-09-28-split-ci-forgejo-github.md);
its topology (promote job, status gate on `release.yml`) carries over, its
Forgejo mechanics do not.

## Decisions (2026-09-28)

1. **GitLab is the source of truth.** Branches and merge requests live there. From
   the cutover on, nobody pushes to or merges on GitHub `dev`/`main`. The promote
   job's deploy key is the only writer.
2. **GitHub is only the final publishing place.** It publishes GitHub Releases,
   GHCR images and Pages, signs with cosign keyless through GitHub OIDC, and runs
   CodeQL, which is free for public repos and has no GitLab CE equivalent.
3. **Self-hosted GitLab runners only.** There are no shared runners.
4. **Clean cutover.** This is not a shadow week. GitLab reaches parity with GitHub's
   `Dev CI` on the same SHA, and that single comparison is the gate. Then a single
   cutover day freezes GitHub, moves the source, and flips both sides' branch
   protection. This plan includes the rollback.
5. **SAST and Secret Detection** GitLab templates are kept as extra signals. Auto
   DevOps is off and stays off.

## What the Forgejo spike already established

These findings come from the Forgejo spike, which ran the same kind of runner:
Docker executor, with jobs in containers on the host daemon. They are recorded in
the superseded plan's history and in the maintainer's notes. Each one is a
requirement here:

- **Job containers use per-job Docker bridges (`172.16.0.0/12`).** When the runner
  shares a host with the forge (it does here: the runner is on the `gitlab`
  host), the host firewall must admit that subnet to the forge's HTTP port.
  Otherwise the clone hangs for about two minutes and then fails.
- **`scripts/security_scan.sh` falls back to `docker run -v "$(pwd):/repo"`**
  for gitleaks, trivy and hadolint. From inside a job container that mount comes
  up empty, and the scanner passes without scanning.
  `scripts/ci/install_scanners.sh` (branch `feat/gitlab-ci`) installs pinned,
  SHA-256-verified binaries so the fallback is never taken.
- **Testcontainers must get no `TESTCONTAINERS_HOST_OVERRIDE` and no
  `DOCKER_HOST=unix://…`.** testcontainers-python ≥ 4 then attaches its containers
  to the job's own network and connects by bridge IP. A gateway override
  routes across two bridges, and Docker's isolation rules drop that traffic.
- **Job containers run as root.** `tests/build/test_restore_dump_errors.py` failed
  10 tests as root until `su` was stubbed (branch `fix/restore-tests-as-root`).
- **`artifact-smoke.yml`'s deb-boot and the installer journey need systemd.** A
  job container does not have it.

Measured since:

- **The amd64 package set is 865 MB** (the `dev-packages-amd64` artifact of GitHub
  Dev CI run 36386697012). That is over Cloudflare's 100 MB request-body cap and
  GitLab's default 100 MB maximum artifact size. So build, install smoke, image
  smoke and runtime parity run **in one job** that never uploads the packages.
- **Browser E2E is backend-free** (`apps/frontend/playwright.config.js`: the API is
  stubbed with `page.route`, and Playwright serves a production build itself). It runs
  unchanged in the pinned Playwright image on the Docker runner.

## Global Constraints

- CLAUDE.md "Secrets": no credential, token or key in any file, including
  `.gitlab-ci.yml`, tests and fixtures. Tokens are GitLab CI/CD variables (masked,
  protected) or GitHub secrets. GitHub's SSH host keys are public data and may be
  committed.
- CLAUDE.md "Never lower the coverage gate": the combined backend gate reads its
  threshold from `apps/backend/pyproject.toml` (`--cov-fail-under=56`), exactly as
  `dev-ci.yml` does.
- CLAUDE.md verification rule 1: every task names the suite that exercises it, and
  a task is not done until that suite ran. For anything under `ci/gitlab/`, that
  suite is a GitLab pipeline. `make verify` does not execute it.
- CLAUDE.md verification rule 4: never trigger or rely on a pipeline for a ref
  until `git ls-remote gitlab <ref>` shows it landed.
- CLAUDE.md verification rule 5: two pins that must move together get a guard test
  in the same task (CI image tag ↔ Dockerfile; Playwright image ↔ `@playwright/test`).
- CLAUDE.md "Air-gap": unaffected. This plan changes CI, not the product. No
  product code path may start depending on GitLab or GitHub.
- Node **20.20.2** (`df770b2a6f130ed8627c9782c988fda9669fa23898329a61a871e32f965e007d`),
  Go **1.26.8** (`d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b`,
  matches `apps/agent/go.mod`), Python **3.12**, PostgreSQL client **16**.
- Determinism pins from `dev-ci.yml`: `PYTHONHASHSEED=0`, `CB_TEST_SEED=20260826`.
- GitLab job names that stand in for GitHub required checks keep the exact strings
  in `tests/build/required_checks.py`, except the two CodeQL `Analyze (...)` names,
  which stay on GitHub.
- `apps/backend/tests/test_endpoint_policy_inventory.py:257-288` reads
  `.github/branch-protection.md`. Any rewrite must keep the strings
  "SEC-07 Public Route Review Gate" and exactly one of "Require review from Code
  Owners: ✓ Enabled" or "This gate is not currently enforced by review".

## Review Focus

The five failure modes most likely to bite once this is live, with the test that
pins each one and the task that owns it:

1. **A red pipeline still promotes.** An `allow_failure: true` job or a skipped job
   must never let `promote` run on a SHA that did not pass. The pin is
   `test_no_verify_job_may_fail_silently` (Task 2).
2. **GitHub and GitLab diverge and the promote job "fixes" it by force.** A
   non-fast-forward must fail loudly and never pass `--force`. A remote that is
   already *ahead* (a newer pipeline promoted first) is success, not an error. The
   pins are `test_non_fast_forward_is_refused` and `test_remote_already_ahead_is_a_noop`
   (Task 8).
3. **A re-cut tag on GitHub never reaches GitLab.** That happened on 2026-09-28 with
   `v0.4.2` and `v0.4.3`. Tag sync compares tag *targets*, updates a moved tag,
   and says so. The pin is `test_a_moved_tag_is_updated_and_reported` (Task 10).
4. **State leaks across jobs on the shell-executor VM.** A package left installed by
   a failed smoke would make the next smoke test a stale install. The pin is
   `test_leftover_package_fails_closed` (Task 6).
5. **A token is printed to a job log.** The pin is `test_ci_scripts_never_trace`
   (Task 8): no script under `scripts/ci/` that touches a token runs `set -x`,
   and none puts a token in a URL.

---

## File map

```
.gitlab-ci.yml                         entry point: workflow rules, stages, includes, SAST/Secret Detection templates
ci/images/ci.Dockerfile                the job image: Python 3.12 + Node 20 + Go 1.26 + pg client 16 + docker CLI
ci/github_known_hosts                  GitHub's published SSH host keys (public), for the promote push
ci/gitlab/image.yml                    builds cb-ci:<tag> on the runner host's daemon (stage .pre)
ci/gitlab/verify.yml                   Lint, backend shards, coverage gate, migrations, Test, Security Gate, Docs build
ci/gitlab/security.yml                 the nine scanner jobs from security.yml
ci/gitlab/browser.yml                  Browser E2E (2 shards) in the Playwright image
ci/gitlab/package.yml                  build + selftest + deb install/boot + mono smoke + runtime parity, one job, systemd runner
ci/gitlab/promote.yml                  promote: fast-forward GitHub, post gitlab/verify
ci/gitlab/scheduled.yml                nightly Tier 2, baseline, ledger watch, tag sync, Renovate
ci/gitlab/release-followup.yml         triggered by release.yml post-publish: VERSION bump MR on GitLab
scripts/ci/install_scanners.sh         (exists on feat/gitlab-ci) pinned scanner binaries
scripts/ci/assert_clean_runner.sh      fail closed if the systemd VM carries a previous run's install
scripts/ci/promote_to_github.sh        the only writer to GitHub dev/main
scripts/ci/post_github_status.sh       POST a commit status to GitHub
scripts/ci/sync_tags_from_github.sh    GitHub v* tags -> GitLab, by target
scripts/ci/gitlab_release_followup.sh  bump VERSION/CHANGELOG, push branch, open the MR
scripts/ci/gitlab_ledger_issue.sh      ledger-watch's issue, on GitLab
renovate.json                          dependency updates on GitLab (replaces Dependabot version updates)
tests/build/test_gitlab_pipeline.py    guards: names, no silent failures, image tag pin, split rules
tests/build/test_promote_to_github.py  promote behaviour against local bare repos
tests/build/test_sync_tags_from_github.py
tests/build/test_assert_clean_runner.py
.github/workflows/publish-dev.yml      push: dev -> require gitlab/verify -> mono-smoke (publish)
.github/workflows/release-rehearsal.yml push: main -> build + artifact smoke + installer journey (pre-tag coverage)
```

---

## Phase 0 — Land what the runner already proved (GitHub is still the source)

### Task 0: Merge the three waiting branches through GitHub

These exist only on this machine. Two fix real defects that a root job container
exposes, and the GitLab pipeline cannot go green without them.

**Files:**
- Read first: `tests/build/test_restore_dump_errors.py`
- Read first: `apps/frontend/src/__tests__/navigator-wiring.test.jsx`
- Read first: `scripts/ci/install_scanners.sh`

**Interfaces:**
- Produces: `scripts/ci/install_scanners.sh <dest-dir>`, which installs `gitleaks`
  8.30.1, `trivy` 0.70.0 and `hadolint` 2.15.1 into `<dest-dir>` and exits non-zero
  if any is missing afterwards.

- [ ] **Step 1: Confirm each branch is still one commit on current `dev`**

```bash
git fetch origin
for b in fix/restore-tests-as-root fix/navigator-recents-race feat/gitlab-ci; do
  echo "$b: $(git rev-list --count origin/dev..$b) ahead, $(git rev-list --count $b..origin/dev) behind"
done
```
Expected: each is `1 ahead`. If any is behind, `git rebase origin/dev` it.

- [ ] **Step 2: Run the covering suites**

```bash
.venv/bin/python -m pytest tests/build/test_restore_dump_errors.py -q -p no:cacheprovider
podman run --rm -v "$PWD:/r:Z" -w /r docker.io/library/python:3.12-slim \
  sh -c 'pip -q install pytest >/dev/null && python -m pytest tests/build/test_restore_dump_errors.py -q -p no:cacheprovider'
(cd apps/frontend && npx vitest run src/__tests__/navigator-wiring.test.jsx)
bash scripts/ci/install_scanners.sh "$(mktemp -d)"
```
Expected: 18 passed (non-root), 18 passed (root, in the container), 6 passed, and
the installer printing `8.30.1`, `Version: 0.70.0` and `Haskell Dockerfile Linter 2.15.1`.

- [ ] **Step 3: Push each branch to GitHub and open a PR into `dev`**

```bash
for b in fix/restore-tests-as-root fix/navigator-recents-race feat/gitlab-ci; do
  git push -u origin "$b"
  gh pr create --base dev --head "$b" --fill
done
```
Merge each once `Dev CI` and `Security Scan` are green. `feat/gitlab-ci` keeps
receiving Phase 1 work afterwards, so after it merges, recreate it from the new
`dev`: `git switch -C feat/gitlab-ci origin/dev`.

- [ ] **Step 4: Re-sync GitLab `dev` (fast-forward only)**

```bash
git fetch origin
git push gitlab 'refs/remotes/origin/dev:refs/heads/dev'
diff <(git ls-remote gitlab refs/heads/dev) <(git ls-remote origin refs/heads/dev) && echo in-sync
```
Expected: `in-sync`. A rejection means GitLab `dev` moved on its own. Stop and
find out why. Never force it.

**The sync rule for all of Phase 0–2:** after *every* merge on GitHub `dev` or
`main` until cutover day, repeat Step 4 for that branch. GitLab only mirrors in
this period; it is not yet a place where anyone merges.

---

## Phase 1 — The GitLab pipeline reaches parity

All Phase 1 work happens on `feat/gitlab-ci`. It is pushed to **GitLab** so
pipelines run, and it is merged into GitHub `dev` by PR, because GitHub is still
the source. Nothing in Phase 1 can write to GitHub: `promote` is gated on
`PROMOTE_ENABLED`, which stays unset until cutover day.

### Task 1: Runner prerequisites (maintainer, on the runner hosts; no repo change)

**Files:**
- Read first: `scripts/ci/tier3-artifact.sh:15-20` (runs as root on a clean host)
- Read first: `scripts/ci/tier2-mono-smoke.sh:29-40` (uses `sudo -n` and host Docker)

- [ ] **Step 1: Docker runner — allow the local CI image**

In `/etc/gitlab-runner/config.toml` on the `gitlab` host, under `[runners.docker]`:

```toml
    allowed_pull_policies = ["always", "if-not-present"]
```

Then `sudo gitlab-runner restart && sudo gitlab-runner verify`. Without this,
a job's `pull_policy: if-not-present` is rejected, and the job image built by
Task 2 (which only exists on the host daemon) cannot be used.

- [ ] **Step 2: Docker runner — firewall**

```bash
sudo ufw status | grep -E '^(80|443)/tcp' || true
sudo ufw allow from 172.16.0.0/12 to any port 443 proto tcp
sudo ufw allow from 172.16.0.0/12 to any port 80 proto tcp
```
Verification: `docker run --rm alpine wget -qO- -T 5 https://gitlab.blkleg.app/-/health`
prints `GitLab OK`. The runner is registered against the public URL, so this may
already pass through Cloudflare. Run it anyway, since the spike showed the
failure is a silent two-minute hang.

- [ ] **Step 3: The `systemd` runner — a clean-host VM with a shell executor**

A VM, not an LXC (the deb smoke starts systemd units): Ubuntu 22.04, the release the
GitHub-hosted `artifact-smoke.yml` runs on. 4 vCPU, 8 GB RAM, 60 GB disk. Take a
snapshot named `clean` right after the provisioning below.

```bash
# on the new VM
sudo apt-get update && sudo apt-get install -y curl git jq make python3 python3-venv docker.io docker-compose-v2
curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash
sudo apt-get install -y gitlab-runner
sudo usermod -aG docker gitlab-runner
echo 'gitlab-runner ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/gitlab-runner
sudo chmod 0440 /etc/sudoers.d/gitlab-runner
# Ubuntu 22.04 ships Python 3.10; the package, baseline and composed jobs need 3.12 and Node 20.
sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
curl -fsSLo /tmp/node.tar.xz https://nodejs.org/dist/v20.20.2/node-v20.20.2-linux-x64.tar.xz
echo "df770b2a6f130ed8627c9782c988fda9669fa23898329a61a871e32f965e007d  /tmp/node.tar.xz" | sha256sum --check --strict -
sudo tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
python3.12 --version && node --version && docker compose version
```
Register it in GitLab (Settings → CI/CD → Runners → New project runner) with tags
`systemd`, `amd64`, **Run untagged jobs: off**, **Protected: off**. Choose
executor `shell`. Set `concurrent = 1` in its `config.toml`: one clean host,
one job at a time.

- [ ] **Step 4: Record the facts**

Append to this plan under "Runner facts (recorded)" at the end: the VM's
hostname, IP, Ubuntu release, runner id, and the date of the `clean` snapshot.

### Task 2: The job image and the pipeline skeleton

**Files:**
- Create: `ci/images/ci.Dockerfile`
- Create: `ci/gitlab/image.yml`
- Create: `.gitlab-ci.yml`
- Create: `tests/build/test_gitlab_pipeline.py`

**Interfaces:**
- Produces: CI variable `CB_CI_IMAGE` = `cb-ci:<first 12 hex of sha256(ci/images/ci.Dockerfile)>`,
  used by every Docker-runner job as `image: {name: $CB_CI_IMAGE, pull_policy: if-not-present}`.
- Produces: the `.cb-docker` hidden job (tags `docker`, image as above), which every
  Docker-runner job `extends`.
- Produces: `tests/build/test_gitlab_pipeline.py::load_pipeline()` → `dict[str, dict]`
  mapping job name to job body, with every `include: local:` file merged. Later tasks
  add tests to this file.

- [ ] **Step 1: Write the failing guard tests**

```python
"""Guards for the GitLab pipeline (plans/2026-09-28-gitlab-cutover.md).

The pipeline YAML is only ever executed by GitLab, so these are the checks that
run on every `make verify`: names the governance docs rely on, the image pin,
and the rule that no verify job can fail without failing the pipeline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY = REPO_ROOT / ".gitlab-ci.yml"
DOCKERFILE = REPO_ROOT / "ci" / "images" / "ci.Dockerfile"

# Keys GitLab treats as configuration rather than jobs.
_RESERVED = {
    "stages", "include", "variables", "workflow", "default", "image",
    "services", "cache", "before_script", "after_script",
}


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(document, dict), f"{path} is not a mapping"
    return document


def load_entry() -> dict[str, Any]:
    return _load(ENTRY)


def load_pipeline() -> dict[str, dict[str, Any]]:
    """Every job, from .gitlab-ci.yml and each `include: local:` file."""
    entry = load_entry()
    documents = [entry]
    for item in entry.get("include", []):
        if isinstance(item, dict) and "local" in item:
            documents.append(_load(REPO_ROOT / item["local"].lstrip("/")))
    jobs: dict[str, dict[str, Any]] = {}
    for document in documents:
        for name, body in document.items():
            if name in _RESERVED or not isinstance(body, dict):
                continue
            assert name not in jobs, f"job {name!r} is defined twice"
            jobs[name] = body
    return jobs


def test_image_tag_is_the_dockerfile_digest():
    """Rule 5: the tag and the Dockerfile move together, or a stale image is reused."""
    digest = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:12]
    assert load_entry()["variables"]["CB_CI_IMAGE"] == f"cb-ci:{digest}"


def test_auto_devops_is_not_included():
    templates = [i.get("template", "") for i in load_entry().get("include", []) if isinstance(i, dict)]
    assert not any("Auto-DevOps" in t for t in templates), templates


def test_tag_pipelines_do_not_run():
    """Tags arrive from GitHub by sync; a tag pipeline would re-test released code for nothing."""
    rules = load_entry()["workflow"]["rules"]
    assert rules[0] == {"if": "$CI_COMMIT_TAG", "when": "never"}, rules[0]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py -q -p no:cacheprovider`
Expected: FAIL with `FileNotFoundError: ... .gitlab-ci.yml`.

- [ ] **Step 3: Write the image**

`ci/images/ci.Dockerfile`:

```dockerfile
# The one job image for Docker-runner jobs (plans/2026-09-28-gitlab-cutover.md).
# Built on the runner host's daemon by ci/gitlab/image.yml and never pushed:
# jobs use it with pull_policy if-not-present. Its tag is the first 12 hex of
# this file's sha256, and tests/build/test_gitlab_pipeline.py fails if the two
# disagree, so editing this file forces a rebuild.
FROM python:3.12-bookworm

ARG NODE_VERSION=20.20.2
ARG NODE_SHA256=df770b2a6f130ed8627c9782c988fda9669fa23898329a61a871e32f965e007d
ARG GO_VERSION=1.26.8
ARG GO_SHA256=d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg jq make gcc git xz-utils sudo lsb-release; \
    install -d -m 0755 /etc/apt/keyrings; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/keyrings/pgdg.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list; \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16 docker-ce-cli docker-compose-plugin; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum --check --strict -; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; \
    rm /tmp/node.tar.xz; \
    curl -fsSLo /tmp/go.tar.gz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"; \
    echo "${GO_SHA256}  /tmp/go.tar.gz" | sha256sum --check --strict -; \
    tar -xzf /tmp/go.tar.gz -C /usr/local; \
    rm /tmp/go.tar.gz

ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"
RUN node --version && go version && python3.12 --version && pg_dump --version && docker --version
```

- [ ] **Step 4: Write `ci/gitlab/image.yml`**

```yaml
# Builds the job image on the runner host's daemon, once per Dockerfile digest.
# The job itself runs in docker:cli with the host socket (config.toml mounts it),
# so the image lands where every later job's `pull_policy: if-not-present` finds it.
ci-image:
  stage: .pre
  tags: [docker]
  image: docker:28-cli
  script:
    - |
      if docker image inspect "$CB_CI_IMAGE" >/dev/null 2>&1; then
        echo "$CB_CI_IMAGE already present"
      else
        docker build -f ci/images/ci.Dockerfile -t "$CB_CI_IMAGE" ci/images
      fi
```

- [ ] **Step 5: Write `.gitlab-ci.yml`**

Compute the tag first: `echo "cb-ci:$(sha256sum ci/images/ci.Dockerfile | cut -c1-12)"`,
then put the output in place of the tag value below.

```yaml
# Circuit Breaker CI (plans/2026-09-28-gitlab-cutover.md). GitLab is the source
# and this pipeline is the gate; GitHub only publishes. promote.yml is the one
# job that writes to GitHub, and only after every earlier stage succeeded.
workflow:
  rules:
    - if: $CI_COMMIT_TAG
      when: never
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "trigger"
    - if: $CI_PIPELINE_SOURCE == "web"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH

stages: [lint, test, security, package, promote]

variables:
  CB_CI_IMAGE: "cb-ci:REPLACE_WITH_STEP_5_OUTPUT"
  PYTHONHASHSEED: "0"
  CB_TEST_SEED: "20260826"
  GIT_DEPTH: "50"

.cb-docker:
  tags: [docker]
  image:
    name: $CB_CI_IMAGE
    pull_policy: if-not-present

include:
  - local: ci/gitlab/image.yml
  - template: Jobs/SAST.gitlab-ci.yml
  - template: Jobs/Secret-Detection.gitlab-ci.yml
```

The literal `REPLACE_WITH_STEP_5_OUTPUT` must not survive this step. The guard in
Step 1 fails until the real digest is in place.

- [ ] **Step 6: Run the guards to verify they pass**

Run: `.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py -q -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 7: Commit, push to GitLab, and run the covering suite (a pipeline)**

```bash
git add ci/images/ci.Dockerfile ci/gitlab/image.yml .gitlab-ci.yml tests/build/test_gitlab_pipeline.py
git commit -m "feat(ci): GitLab job image and pipeline skeleton"
git push gitlab feat/gitlab-ci
git ls-remote gitlab refs/heads/feat/gitlab-ci
```
Expected on GitLab: `ci-image` passes on the first run (it builds), and on a
re-run it prints `already present`. The SAST and Secret Detection jobs run. Read
them in the job log and record any finding. They are signals, not gates, until a
maintainer decides otherwise.

### Task 3: The verify jobs

**Files:**
- Create: `ci/gitlab/verify.yml`
- Modify: `.gitlab-ci.yml`
- Modify: `tests/build/test_gitlab_pipeline.py`
- Read first: `.github/workflows/dev-ci.yml:40-570` (the jobs being ported)
- Read first: `.github/workflows/docs.yml`
- Read first: `scripts/ci/tier0-static.sh`

**Interfaces:**
- Consumes: `.cb-docker` (Task 2), `scripts/ci/install_scanners.sh` (Task 0).
- Produces: GitLab jobs named `Lint`, `Backend tests (shard 1/4)` … `(shard 4/4)`,
  `Backend coverage gate`, `Fresh-install migrations`, `Test`, `Security Gate`,
  `Docs build`.

- [ ] **Step 1: Add the failing name guard**

Append to `tests/build/test_gitlab_pipeline.py`:

```python
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from required_checks import REQUIRED_CHECKS  # noqa: E402

# CodeQL is the one required check that stays on GitHub (codeql.yml).
_GITHUB_ONLY = {"Analyze (Python)", "Analyze (JavaScript / TypeScript)"}


def test_every_required_check_is_a_gitlab_job():
    """EXC-002's compensating control is these gates; each must exist as a job."""
    jobs = set(load_pipeline())
    missing = [c for c in REQUIRED_CHECKS if c not in _GITHUB_ONLY and c not in jobs]
    assert not missing, missing


def _extends(body: dict[str, Any]) -> list[str]:
    value = body.get("extends", [])
    return [value] if isinstance(value, str) else list(value)


def test_no_verify_job_may_fail_silently():
    """Review Focus 1: a job that may fail without failing the pipeline cannot gate a promote.

    Scheduled jobs are exempt only because `.scheduled`'s rule admits schedule
    pipelines alone, so they never share a pipeline with `promote`.
    """
    offenders = [
        name for name, body in load_pipeline().items()
        if body.get("allow_failure") and not name.startswith(".")
        and ".scheduled" not in _extends(body)
    ]
    assert not offenders, offenders
```

Run: `.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py -q -p no:cacheprovider`
Expected: FAIL. `test_every_required_check_is_a_gitlab_job` lists the missing names.

- [ ] **Step 2: Write `ci/gitlab/verify.yml`**

Every job's script is `dev-ci.yml`'s steps with three mechanical changes. Artifact
uploads become `artifacts: {when: always, expire_in: 14 days, paths: [artifacts/]}`.
`${GITHUB_WORKSPACE}` becomes `${CI_PROJECT_DIR}`. `actions/setup-*` goes away
because the job image has the toolchains. Service containers are reached by their
alias, not `127.0.0.1`.

```yaml
# Ports .github/workflows/dev-ci.yml's gate jobs (and docs.yml's build) to the
# Docker runner. Names are tests/build/required_checks.py's; the scripts are the
# same scripts, so "what CI runs" and "what make verify runs" stay one thing.
.venv-install: &venv-install
  - python3.12 -m venv .venv
  - .venv/bin/pip install --upgrade pip
  - .venv/bin/pip install -e "apps/backend/[dev]"

Lint:
  extends: .cb-docker
  stage: lint
  timeout: 20m
  script:
    - *venv-install
    - (cd apps/frontend && npm ci)
    # Only a string here: the Alembic head check builds a Config and never connects.
    - CB_DB_URL=postgresql://cb_ci:cb_ci@127.0.0.1:5432/cb_ci scripts/ci/tier0-static.sh
  artifacts:
    when: always
    expire_in: 14 days
    paths: [artifacts/]

# Same sharding as dev-ci.yml (tests/build/backend_shard.py). The TimescaleDB
# testcontainer needs no configuration: no DOCKER_HOST, no host override, so
# testcontainers joins this job's network (spike finding).
.backend-shard:
  extends: .cb-docker
  stage: test
  timeout: 30m
  variables:
    SHARD_TOTAL: "4"
  script:
    - *venv-install
    - (cd apps/frontend && npm ci && npm run build)
    - mkdir -p artifacts/junit artifacts/coverage artifacts/logs
    - export COVERAGE_FILE="${CI_PROJECT_DIR}/artifacts/coverage/.coverage.backend-${SHARD}"
    - python3 tests/build/backend_shard.py --index "${SHARD}" --total "${SHARD_TOTAL}" > artifacts/shard-files.txt
    - cat artifacts/shard-files.txt
    - |
      cd apps/backend
      PYTHONPATH=src ../../.venv/bin/pytest $(cat "${CI_PROJECT_DIR}/artifacts/shard-files.txt") \
        --junitxml="${CI_PROJECT_DIR}/artifacts/junit/backend-shard-${SHARD}.xml" \
        --cov-fail-under=0 -p no:cacheprovider \
        2>&1 | tee "${CI_PROJECT_DIR}/artifacts/logs/backend-shard-${SHARD}.log"
      exit "${PIPESTATUS[0]}"
  artifacts:
    when: always
    expire_in: 14 days
    paths: [artifacts/]
    reports:
      junit: artifacts/junit/*.xml

"Backend tests (shard 1/4)":
  extends: .backend-shard
  variables: {SHARD: "1"}
"Backend tests (shard 2/4)":
  extends: .backend-shard
  variables: {SHARD: "2"}
"Backend tests (shard 3/4)":
  extends: .backend-shard
  variables: {SHARD: "3"}
"Backend tests (shard 4/4)":
  extends: .backend-shard
  variables: {SHARD: "4"}

"Backend coverage gate":
  extends: .cb-docker
  stage: security
  timeout: 20m
  needs:
    - "Backend tests (shard 1/4)"
    - "Backend tests (shard 2/4)"
    - "Backend tests (shard 3/4)"
    - "Backend tests (shard 4/4)"
  script:
    - *venv-install
    - find artifacts/coverage -name '.coverage.backend-*' -exec cp {} apps/backend/ \;
    - ls -la apps/backend/.coverage.backend-*
    - |
      cd apps/backend
      THRESHOLD=$(python3 -c 'import tomllib; o=tomllib.load(open("pyproject.toml","rb"))["tool"]["pytest"]["ini_options"]["addopts"]; print(next(x.split("=",1)[1] for x in o if x.startswith("--cov-fail-under=")))')
      echo "combined backend coverage must reach ${THRESHOLD}%"
      ../../.venv/bin/python -m coverage combine
      ../../.venv/bin/python -m coverage report --fail-under="${THRESHOLD}"

"Fresh-install migrations":
  extends: .cb-docker
  stage: test
  timeout: 25m
  services:
    - name: postgres:16
      alias: postgres
  variables:
    POSTGRES_USER: cb_ci
    POSTGRES_PASSWORD: cb_ci
    POSTGRES_DB: cb_ci
    CB_TEST_DB_URL: postgresql://cb_ci:cb_ci@postgres:5432/cb_ci
    CB_ALLOW_DEGRADED_DEPENDENCIES: "true"
    CB_ALLOW_DIRECT_EGRESS: "true"
  script:
    - *venv-install
    - until pg_isready -h postgres -U cb_ci; do sleep 2; done
    - cd apps/backend
    - PYTHONPATH=src ../../.venv/bin/pytest ../../tests/integration/test_fresh_install_migration_chain.py -p no:cacheprovider

Test:
  extends: .cb-docker
  stage: test
  timeout: 25m
  script:
    - (cd apps/frontend && npm ci)
    - mkdir -p artifacts/junit artifacts/coverage artifacts/logs
    - (cd apps/frontend && npx vitest run --coverage --sequence.shuffle=false --sequence.seed="${CB_TEST_SEED}")
    - (cd apps/agent && GOFLAGS="-shuffle=off" make test)
    - (cd apps/agent && go vet ./...)
  artifacts:
    when: always
    expire_in: 14 days
    paths: [apps/frontend/coverage/]

"Security Gate":
  extends: .cb-docker
  stage: security
  timeout: 25m
  needs: []
  variables:
    SECURITY_SCAN_VENV: /tmp/cb-scanner-venv
  script:
    - scripts/ci/install_scanners.sh /usr/local/bin
    - python3.12 -m venv "$SECURITY_SCAN_VENV"
    - '"$SECURITY_SCAN_VENV/bin/pip" install --upgrade pip bandit semgrep'
    - (cd apps/frontend && npm ci)
    - ./scripts/security_scan.sh --gate
  artifacts:
    when: always
    expire_in: 30 days
    paths: [security_scan_report.md]

"Docs build":
  extends: .cb-docker
  stage: lint
  timeout: 15m
  script:
    - pip install 'mkdocs~=1.6'
    - mkdocs build --strict
```

Add `- local: ci/gitlab/verify.yml` to the `include:` list in `.gitlab-ci.yml`.

`docs.yml`'s lychee link check is not ported. It runs on a `paths:` filter, calls
the internet for every external link, and is not a required check. That is a
deliberate reduction, and Task 13 records it in `CONTRIBUTING.md`.

- [ ] **Step 3: Run the guards**

Run: `.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py -q -p no:cacheprovider`
Expected: `test_every_required_check_is_a_gitlab_job` still FAILS, now listing only
the nine scanner names, which Task 4 adds. The other tests pass.

- [ ] **Step 4: Commit, push, run the pipeline**

```bash
git add ci/gitlab/verify.yml .gitlab-ci.yml tests/build/test_gitlab_pipeline.py
git commit -m "feat(ci): GitLab verify jobs (lint, backend shards, coverage, migrations, test, security gate, docs)"
git push gitlab feat/gitlab-ci && git ls-remote gitlab refs/heads/feat/gitlab-ci
```
Expected: every job in `ci/gitlab/verify.yml` green. For any red job, apply
CLAUDE.md rule 2: reproduce it, or compare it against the same job on GitHub
`Dev CI` for the same SHA. Never retry until it passes.

### Task 4: The scanner jobs

**Files:**
- Create: `ci/gitlab/security.yml`
- Modify: `.gitlab-ci.yml`
- Read first: `.github/workflows/security.yml`

**Interfaces:**
- Consumes: `.cb-docker`, `scripts/ci/install_scanners.sh`.
- Produces: jobs `Security Suppression Metadata`, `Trivy Filesystem Scan`,
  `Trivy Config / IaC Scan`, `Semgrep (SAST)`, `Bandit (Python SAST)`,
  `Gitleaks (Secret Scanning)`, `Checkov (GitHub Actions / IaC)`,
  `Python Dependency Audit`, `Frontend Dependency Audit`, `Go Vulnerability Scan`.

- [ ] **Step 1: Write `ci/gitlab/security.yml`**

```yaml
# Ports .github/workflows/security.yml. SARIF upload goes away (no GitHub code
# scanning here); reports are artifacts. trivy is v0.70.0, the default of the
# trivy-action@v0.36.0 GitHub used, so the two systems scan with one binary.
.scanner:
  extends: .cb-docker
  stage: security
  needs: []
  timeout: 20m

"Security Suppression Metadata":
  extends: .scanner
  script:
    - python3.12 scripts/validate_security_suppressions.py

"Trivy Filesystem Scan":
  extends: .scanner
  script:
    - scripts/ci/install_scanners.sh /usr/local/bin
    - trivy fs . --severity CRITICAL,HIGH,MEDIUM --exit-code 1 --skip-dirs .venv,node_modules,dist

"Trivy Config / IaC Scan":
  extends: .scanner
  script:
    - scripts/ci/install_scanners.sh /usr/local/bin
    - trivy config . --severity CRITICAL,HIGH --exit-code 1 --skip-dirs .venv,node_modules,dist --ignorefile .trivyignore

"Semgrep (SAST)":
  extends: .scanner
  script:
    - pip install semgrep
    - semgrep scan --config p/default --error --severity ERROR apps/backend/src/ apps/frontend/src/

"Bandit (Python SAST)":
  extends: .scanner
  script:
    - pip install bandit
    - bandit -r apps/backend/src/ -lll --skip B101

# gitleaks-action reads the GitHub API, so the binary scans the full history,
# which is what security.yml's weekly run does, with the same config.
"Gitleaks (Secret Scanning)":
  extends: .scanner
  variables:
    GIT_DEPTH: "0"
  script:
    - scripts/ci/install_scanners.sh /usr/local/bin
    - gitleaks git . --config .gitleaks.toml --redact -v

"Checkov (GitHub Actions / IaC)":
  extends: .scanner
  script:
    - pip install checkov
    - checkov -d .github/workflows/ --skip-path '(^|/)\.github/workflows/mono-smoke\.yml$' --quiet
    - checkov -f .github/workflows/mono-smoke.yml --skip-check CKV2_GHA_1 --quiet

"Python Dependency Audit":
  extends: .scanner
  script:
    - python3.12 -m venv /tmp/audit && /tmp/audit/bin/pip install --upgrade pip pip-audit
    - /tmp/audit/bin/pip-audit -r apps/backend/requirements.txt -r apps/backend/requirements-pg.txt

"Frontend Dependency Audit":
  extends: .scanner
  script:
    - cd apps/frontend && npm ci && npm audit --audit-level=high

"Go Vulnerability Scan":
  extends: .scanner
  script:
    - go install golang.org/x/vuln/cmd/govulncheck@v1.7.0
    - cd apps/agent && govulncheck ./...
```

Add `- local: ci/gitlab/security.yml` to `.gitlab-ci.yml`'s `include:`.

- [ ] **Step 2: Run the guards**

Run: `.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 3: Commit, push, run the pipeline**

```bash
git add ci/gitlab/security.yml .gitlab-ci.yml
git commit -m "feat(ci): GitLab scanner jobs"
git push gitlab feat/gitlab-ci && git ls-remote gitlab refs/heads/feat/gitlab-ci
```
Expected: all ten jobs green. Gitleaks scans the full history on every run.
GitHub did that only weekly, so any hit it finds is a real finding (rule 2).

### Task 5: Browser E2E

**Files:**
- Create: `ci/gitlab/browser.yml`
- Modify: `.gitlab-ci.yml`
- Modify: `tests/build/test_playwright_image_matches_package.py`
- Read first: `.github/workflows/browser-e2e.yml`
- Read first: `scripts/ci/tier2-browser.sh`

**Interfaces:**
- Produces: jobs `Browser E2E (shard 1/2)`, `Browser E2E (shard 2/2)`.

- [ ] **Step 1: Widen the pairing guard first (rule 5)**

In `tests/build/test_playwright_image_matches_package.py`, the workflow glob (lines
28 and 44) collects pinned images from `.github/workflows/*.yml`. Add the GitLab
files to the same collection:

```python
PINNED_SOURCES = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")) + sorted(
    (REPO_ROOT / "ci" / "gitlab").glob("*.yml")
)
```

Use `PINNED_SOURCES` wherever the file iterated the glob. Run it:
`.venv/bin/python -m pytest tests/build/test_playwright_image_matches_package.py -q -p no:cacheprovider`
Expected: PASS (no GitLab pin exists yet, and the GitHub one still matches).

- [ ] **Step 2: Write `ci/gitlab/browser.yml`**

```yaml
# Backend-free (the API is stubbed with page.route), so it runs in the pinned
# Playwright image on the Docker runner. The tag must equal @playwright/test;
# tests/build/test_playwright_image_matches_package.py enforces it here too.
.browser-e2e:
  stage: test
  tags: [docker]
  image: mcr.microsoft.com/playwright:v1.63.0-noble
  timeout: 40m
  script:
    - (cd apps/frontend && npm ci)
    - scripts/ci/tier2-browser.sh "${SHARD}"
  artifacts:
    when: always
    expire_in: 14 days
    paths: [apps/frontend/playwright-report/, artifacts/playwright.log]

"Browser E2E (shard 1/2)":
  extends: .browser-e2e
  variables: {SHARD: "1/2"}
"Browser E2E (shard 2/2)":
  extends: .browser-e2e
  variables: {SHARD: "2/2"}
```

Add `- local: ci/gitlab/browser.yml` to `.gitlab-ci.yml`'s `include:`.

- [ ] **Step 3: Run the pairing guard again, then the pipeline**

Run: `.venv/bin/python -m pytest tests/build/test_playwright_image_matches_package.py tests/build/test_gitlab_pipeline.py -q -p no:cacheprovider`
Expected: PASS. Now commit (`feat(ci): GitLab browser E2E`), push to GitLab,
confirm with `ls-remote`, and check that both shards are green.

### Task 6: Package, install, boot, image smoke and parity: one job on the `systemd` runner

**Files:**
- Create: `scripts/ci/assert_clean_runner.sh`
- Create: `tests/build/test_assert_clean_runner.py`
- Create: `ci/gitlab/package.yml`
- Modify: `.gitlab-ci.yml`
- Read first: `.github/workflows/dev-ci.yml:571-705` (build-native, artifact-smoke, build-docker, runtime-parity)
- Read first: `scripts/ci/tier3-artifact.sh`
- Read first: `scripts/ci/tier2-mono-smoke.sh`
- Read first: `scripts/ci/assert_runtime_parity.py`

**Interfaces:**
- Consumes: the `systemd` runner (Task 1 Step 3).
- Produces: job `Artifact smoke and parity (amd64)`.
- Produces: `scripts/ci/assert_clean_runner.sh`, which exits 0 on a clean host and
  1 with a `clean runner check failed:` line per leftover otherwise. It reads
  `CB_DPKG` (default `dpkg-query`) and `CB_DOCKER` (default `docker`) so tests can
  stub them.

- [ ] **Step 1: Write the failing test**

`tests/build/test_assert_clean_runner.py`:

```python
"""Review Focus 4: the shell-executor VM must refuse to test on a dirty host."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "assert_clean_runner.sh"


def _stub(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return str(path)


def _run(tmp_path: Path, dpkg_body: str, docker_body: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CB_DPKG": _stub(tmp_path, "dpkg-query", dpkg_body),
        "CB_DOCKER": _stub(tmp_path, "docker", docker_body),
        "CB_ETC_DIR": str(tmp_path / "etc-circuit-breaker"),
    }
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False)


def test_clean_host_passes(tmp_path):
    result = _run(tmp_path, "exit 1", "exit 0")
    assert result.returncode == 0, result.stderr


def test_leftover_package_fails_closed(tmp_path):
    result = _run(tmp_path, 'echo "install ok installed"; exit 0', "exit 0")
    assert result.returncode == 1
    assert "clean runner check failed: package circuit-breaker is installed" in result.stderr


def test_leftover_container_fails_closed(tmp_path):
    result = _run(tmp_path, "exit 1", 'echo circuitbreaker')
    assert result.returncode == 1
    assert "container circuitbreaker exists" in result.stderr


def test_leftover_config_dir_fails_closed(tmp_path):
    (tmp_path / "etc-circuit-breaker").mkdir()
    result = _run(tmp_path, "exit 1", "exit 0")
    assert result.returncode == 1
    assert "etc-circuit-breaker exists" in result.stderr
```

Run: `.venv/bin/python -m pytest tests/build/test_assert_clean_runner.py -q -p no:cacheprovider`
Expected: FAIL (`No such file or directory`).

- [ ] **Step 2: Write `scripts/ci/assert_clean_runner.sh`**

```bash
#!/usr/bin/env bash
#
# Refuse to run the install smoke on a host that still carries a previous run.
#
# The `systemd` runner is a VM with a shell executor, not a fresh machine per job.
# tier3-artifact.sh's contract is "a clean host", and a failed run can leave the
# package installed, its config behind, or the mono smoke's container running. A
# smoke on top of that tests the leftover, not the candidate. This fails closed;
# the fix is reverting the VM to its `clean` snapshot, never deleting by hand.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

DPKG="${CB_DPKG:-dpkg-query}"
DOCKER="${CB_DOCKER:-docker}"
ETC_DIR="${CB_ETC_DIR:-/etc/circuit-breaker}"
dirty=0

report() { printf 'clean runner check failed: %s\n' "$1" >&2; dirty=1; }

for pkg in circuit-breaker circuit-breaker-nats; do
    if "$DPKG" -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
        report "package $pkg is installed"
    fi
done
if [ -e "$ETC_DIR" ]; then
    report "$ETC_DIR exists"
fi
if "$DOCKER" ps -a --format '{{.Names}}' | grep -qx circuitbreaker; then
    report "container circuitbreaker exists"
fi

if [ "$dirty" -ne 0 ]; then
    echo "Revert the systemd runner VM to its 'clean' snapshot, then re-run." >&2
    exit 1
fi
echo "runner is clean"
```

`chmod +x scripts/ci/assert_clean_runner.sh`, then run the test again.
Expected: 4 passed.

- [ ] **Step 3: Write `ci/gitlab/package.yml`**

```yaml
# One job, because the amd64 package set is ~865 MB: over Cloudflare's 100 MB
# body cap and GitLab's default artifact limit. Build, install smoke, image
# smoke and parity all read the same dist/ on the same host; only evidence is
# uploaded. On the `systemd` VM (shell executor), because the deb smoke starts
# systemd units and the mono smoke uses `sudo -n` and the host's Docker.
"Artifact smoke and parity (amd64)":
  stage: package
  tags: [systemd]
  timeout: 90m
  needs: []
  before_script:
    - scripts/ci/assert_clean_runner.sh
  script:
    - VERSION="$(cat VERSION)"
    - bash scripts/install-build-deps.sh
    - python3.12 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e "apps/backend/[dev]"
    - (cd apps/frontend && npm ci && npm run build)
    - .venv/bin/python scripts/build_native_release.py --version "$VERSION" --clean
    - dist/native/bundle/bin/circuit-breaker --selftest
    - sudo bash scripts/ci/tier3-artifact.sh "$(ls dist/native/*_amd64.deb | head -1)"
    - docker build -f Dockerfile.mono -t "circuitbreaker:${VERSION}" .
    - scripts/ci/tier2-mono-smoke.sh "circuitbreaker:${VERSION}"
    - mkdir -p unpacked image-info
    - tar -xzf "dist/native/circuit-breaker_${VERSION}_linux_amd64.tar.gz" -C unpacked share/build-info.json
    - docker run --rm --entrypoint cat "circuitbreaker:${VERSION}" /opt/circuitbreaker/share/build-info.json > image-info/build-info.json
    - python3 scripts/ci/assert_runtime_parity.py unpacked/share/build-info.json image-info/build-info.json
  after_script:
    # GitLab uploads artifacts only from inside the project directory.
    - mkdir -p artifacts/tier3 && sudo cp -a /tmp/cb-tier3-evidence/. artifacts/tier3/ 2>/dev/null || true
    - sudo chown -R "$(id -u):$(id -g)" artifacts || true
    - sudo apt-get remove -y circuit-breaker circuit-breaker-nats || true
    - docker compose -f docker-compose.yml down -v --remove-orphans || true
  artifacts:
    when: always
    expire_in: 14 days
    paths: [artifacts/]
```

The `tier3-artifact.sh` line passes one `.deb`. `artifact-smoke.yml` installs the
whole candidate set, including `circuit-breaker-nats`
(`tests/build/test_nats_provisioning_contract.py`). Read how `tier3-artifact.sh`
installs the NATS package when handed the main `.deb`. If it does not fetch the
sibling itself, pass the directory's candidate set the way `artifact-smoke.yml`
does (`find "$PWD/dist" -name '*.deb' -print0 | xargs -0 sudo apt-get install -y`
before calling it). Do that check before the first pipeline run.

Before committing, check two lines against the source. First, the path of
`build-info.json` inside the image: read `dev-ci.yml`'s `build-docker` job via
`mono-smoke.yml:100-130` (the `app-build-info` target) and use exactly what it
extracts, replacing the `docker run ... cat` line if it differs. Second, the
selftest binary path: `ls dist/native/bundle/bin/`. `verify_plan_references.py`
cannot catch either of these, so it has to be done by reading (its own docstring
says so).

The `after_script` `|| true` is teardown, which runs after the verdict is already
decided. It is not a gate. `assert_clean_runner.sh` at the start of the next job
is what catches a teardown that failed.

Add `- local: ci/gitlab/package.yml` to `.gitlab-ci.yml`'s `include:`.

- [ ] **Step 4: Commit, push, run the pipeline**

```bash
git add scripts/ci/assert_clean_runner.sh tests/build/test_assert_clean_runner.py ci/gitlab/package.yml .gitlab-ci.yml
git commit -m "feat(ci): package, install, boot, image smoke and parity in one systemd-runner job"
git push gitlab feat/gitlab-ci && git ls-remote gitlab refs/heads/feat/gitlab-ci
```
Expected: the job is green. Its log shows `runner is clean`, then `--selftest`
passing, then the tier3 contract passing, the mono smoke passing, and parity passing.
Re-run the job once to prove that teardown leaves the VM clean: the second run's
`before_script` must print `runner is clean`.

### Task 7: The parity gate for the cutover

**Files:**
- Modify: `plans/2026-09-28-gitlab-cutover.md`

- [ ] **Step 1: Merge `feat/gitlab-ci` into GitHub `dev` by PR, then re-sync GitLab `dev`**

`Dev CI` must be green on the PR. The additions are new files under `ci/`, a new
entry file and new tests, so nothing on GitHub changes behaviour. After the merge,
run Task 0 Step 4.

- [ ] **Step 2: Compare one SHA on both systems**

For the `dev` SHA now on both remotes, list every job and its result:

```bash
SHA="$(git rev-parse origin/dev)"
gh run list -R BlkLeg/CircuitBreaker --commit "$SHA" --json name,conclusion
curl -s -H "PRIVATE-TOKEN: $(cat ~/.config/cb/gitlab-token)" \
  "https://gitlab.blkleg.app/api/v4/projects/1/pipelines?sha=${SHA}" | jq '.[0].id' \
  | xargs -I{} curl -s -H "PRIVATE-TOKEN: $(cat ~/.config/cb/gitlab-token)" \
  "https://gitlab.blkleg.app/api/v4/projects/1/pipelines/{}/jobs?per_page=100" | jq -r '.[] | "\(.name)\t\(.status)"'
```

The cutover gate: every GitHub `Dev CI` and `Security Scan` job that passed has a
GitLab job, by the Global Constraints' name mapping, that also passed on this SHA.
The same holds for `Build Native (amd64)`, `Artifact Smoke`,
`Build Docker (smoke test)` and `Runtime parity (image == package)`, whose GitLab
equivalent is `Artifact smoke and parity (amd64)`. Any disagreement blocks the
cutover and is diagnosed under rule 2.

- [ ] **Step 3: Record the result**

Append a "Parity result" section at the end of this plan with the SHA, both run
URLs, and the job-by-job table. Commit it (`docs(plan): record the GitLab parity result`)
and merge it the same way as Step 1.

---

## Phase 2 — The cutover payload (built on a branch, merged on cutover day)

All of Phase 2 lands on one branch, `chore/gitlab-cutover`, cut from `dev` after
Task 7. It is **not merged** until cutover day (Task 14). Every commit on it must
keep `make verify` green, since that runs the `tests/build` suite that Task 12
rewrites.

### Task 8: The promote job

**Files:**
- Create: `scripts/ci/promote_to_github.sh`
- Create: `scripts/ci/post_github_status.sh`
- Create: `ci/github_known_hosts`
- Create: `ci/gitlab/promote.yml`
- Create: `tests/build/test_promote_to_github.py`
- Modify: `.gitlab-ci.yml`
- Modify: `tests/build/test_gitlab_pipeline.py`

**Interfaces:**
- Produces: `scripts/ci/promote_to_github.sh <branch>`. It reads `CI_COMMIT_SHA`,
  `CB_GITHUB_REMOTE` (default `git@github.com:BlkLeg/CircuitBreaker.git`),
  `CB_STATUS_POSTER` (default `scripts/ci/post_github_status.sh`) and
  `CI_PIPELINE_URL`. It exits 0 when GitHub is at or ahead of the SHA, and 1 on a
  non-fast-forward or a branch other than `dev`/`main`.
- Produces: `scripts/ci/post_github_status.sh <sha> <state> <target_url>`. It reads
  `GH_STATUS_TOKEN` and posts context `gitlab/verify` to
  `repos/BlkLeg/CircuitBreaker/statuses/<sha>`.

- [ ] **Step 1: Write the failing tests**

`tests/build/test_promote_to_github.py`:

```python
"""Review Focus 2 and 5: promote only fast-forwards, and never leaks a token."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "promote_to_github.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "--allow-empty", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A GitLab-side work tree and a bare 'GitHub', sharing a first commit on dev."""
    github = tmp_path / "github.git"
    _git(tmp_path, "init", "-q", "--bare", str(github))
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "dev", str(work))
    _git(work, "config", "user.email", "ci@example.invalid")
    _git(work, "config", "user.name", "ci")
    _commit(work, "base")
    _git(work, "push", "-q", str(github), "dev")
    log = tmp_path / "status.log"
    poster = tmp_path / "poster.sh"
    poster.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    poster.chmod(0o755)
    return work, github, log


def _promote(work: Path, github: Path, sha: str, branch: str = "dev") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CI_COMMIT_SHA": sha,
        "CI_PIPELINE_URL": "https://gitlab.example.invalid/p/1",
        "CB_GITHUB_REMOTE": str(github),
        "CB_STATUS_POSTER": str(work.parent / "poster.sh"),
    }
    return subprocess.run(["bash", str(SCRIPT), branch], cwd=work, env=env,
                          capture_output=True, text=True, check=False)


def test_fast_forward_is_pushed_and_status_posted(tmp_path):
    work, github, log = _setup(tmp_path)
    sha = _commit(work, "next")
    result = _promote(work, github, sha)
    assert result.returncode == 0, result.stderr
    assert _git(github, "rev-parse", "refs/heads/dev") == sha
    assert log.read_text().split() == [sha, "success", "https://gitlab.example.invalid/p/1"]


def test_remote_already_ahead_is_a_noop(tmp_path):
    work, github, log = _setup(tmp_path)
    older = _commit(work, "older")
    newer = _commit(work, "newer")
    _git(work, "push", "-q", str(github), "dev")
    result = _promote(work, github, older)
    assert result.returncode == 0, result.stderr
    assert _git(github, "rev-parse", "refs/heads/dev") == newer
    assert log.read_text().split()[0] == older


def test_non_fast_forward_is_refused(tmp_path):
    work, github, log = _setup(tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", "-b", "dev", str(github), str(other))
    _git(other, "config", "user.email", "x@example.invalid")
    _git(other, "config", "user.name", "x")
    diverged = _commit(other, "written on github directly")
    _git(other, "push", "-q", "origin", "dev")
    sha = _commit(work, "gitlab work")
    result = _promote(work, github, sha)
    assert result.returncode == 1
    assert "non-fast-forward" in result.stderr
    assert _git(github, "rev-parse", "refs/heads/dev") == diverged
    assert not log.exists()


def test_only_dev_and_main_are_promoted(tmp_path):
    work, github, _ = _setup(tmp_path)
    result = _promote(work, github, _git(work, "rev-parse", "HEAD"), branch="feature")
    assert result.returncode == 1
    assert "refusing to promote branch 'feature'" in result.stderr


def test_ci_scripts_never_trace():
    """Review Focus 5: no token-handling script may `set -x` or put a token in a URL."""
    for name in ("promote_to_github.sh", "post_github_status.sh",
                 "sync_tags_from_github.sh", "gitlab_release_followup.sh", "gitlab_ledger_issue.sh"):
        path = REPO_ROOT / "scripts" / "ci" / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*set\s+-[a-z]*x", text, re.MULTILINE), f"{name} traces"
        assert not re.search(r"https://[^\s\"']*:\$\{?[A-Z_]*TOKEN", text), f"{name} puts a token in a URL"
```

Run: `.venv/bin/python -m pytest tests/build/test_promote_to_github.py -q -p no:cacheprovider`
Expected: FAIL on the missing script (4 failures). `test_ci_scripts_never_trace` passes vacuously.

- [ ] **Step 2: Write `scripts/ci/promote_to_github.sh`**

```bash
#!/usr/bin/env bash
#
# The only writer to GitHub dev/main (plans/2026-09-28-gitlab-cutover.md).
#
# Runs from GitLab's promote stage, which exists only when every earlier stage of
# this pipeline succeeded. Fast-forward or nothing: a GitHub branch that has
# commits this SHA does not contain means someone wrote to GitHub directly, and
# the answer is to find out who, never --force. A GitHub branch that already
# contains this SHA (a newer pipeline promoted first) is success.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

BRANCH="${1:?usage: promote_to_github.sh <dev|main>}"
case "$BRANCH" in
    dev|main) ;;
    *) printf "::error::refusing to promote branch '%s'\n" "$BRANCH" >&2; exit 1 ;;
esac
SHA="${CI_COMMIT_SHA:?CI_COMMIT_SHA is required}"
REMOTE="${CB_GITHUB_REMOTE:-git@github.com:BlkLeg/CircuitBreaker.git}"
POSTER="${CB_STATUS_POSTER:-$CB_REPO_ROOT/scripts/ci/post_github_status.sh}"
TARGET_URL="${CI_PIPELINE_URL:?CI_PIPELINE_URL is required}"

git fetch --quiet "$REMOTE" "refs/heads/${BRANCH}:refs/cb-promote/github-${BRANCH}"
REMOTE_TIP="$(git rev-parse "refs/cb-promote/github-${BRANCH}")"

if git merge-base --is-ancestor "$SHA" "$REMOTE_TIP"; then
    echo "GitHub ${BRANCH} (${REMOTE_TIP}) already contains ${SHA}; nothing to push"
elif git merge-base --is-ancestor "$REMOTE_TIP" "$SHA"; then
    git push --quiet "$REMOTE" "${SHA}:refs/heads/${BRANCH}"
    echo "GitHub ${BRANCH}: ${REMOTE_TIP} -> ${SHA}"
else
    printf '::error::non-fast-forward: GitHub %s is at %s, which %s does not contain. Someone wrote to GitHub directly.\n' \
        "$BRANCH" "$REMOTE_TIP" "$SHA" >&2
    exit 1
fi

"$POSTER" "$SHA" success "$TARGET_URL"
```

- [ ] **Step 3: Write `scripts/ci/post_github_status.sh`**

```bash
#!/usr/bin/env bash
#
# Post the `gitlab/verify` commit status that release.yml and publish-dev.yml
# require. GH_STATUS_TOKEN is a fine-grained PAT with "Commit statuses: write"
# on BlkLeg/CircuitBreaker only, stored as a masked, protected GitLab variable.
# The token travels in a header read from the environment; it is never echoed
# and never part of a URL.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

SHA="${1:?usage: post_github_status.sh <sha> <state> <target_url>}"
STATE="${2:?}"
TARGET_URL="${3:?}"
: "${GH_STATUS_TOKEN:?GH_STATUS_TOKEN is required}"

jq -n --arg state "$STATE" --arg url "$TARGET_URL" \
    '{state: $state, context: "gitlab/verify", target_url: $url, description: "GitLab pipeline passed"}' \
  | curl --fail-with-body -sS -X POST \
      -H "Authorization: Bearer ${GH_STATUS_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      --data @- \
      "https://api.github.com/repos/BlkLeg/CircuitBreaker/statuses/${SHA}" > /dev/null
echo "posted gitlab/verify=${STATE} on ${SHA}"
```

`chmod +x` both scripts, then run the tests.
Expected: 5 passed.

- [ ] **Step 4: Commit GitHub's SSH host keys (public data)**

```bash
curl -s https://api.github.com/meta | jq -r '.ssh_keys[] | "github.com \(.)"' > ci/github_known_hosts
cat ci/github_known_hosts
```
Expected: three lines (`ssh-ed25519`, `ecdsa-sha2-nistp256`, `ssh-rsa`). Compare
them with https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints.

- [ ] **Step 5: Write `ci/gitlab/promote.yml`**

```yaml
# Runs only after every earlier stage succeeded (default when: on_success), only
# for pushes to dev/main, and only once PROMOTE_ENABLED is set on cutover day.
# GH_PROMOTE_DEPLOY_KEY is a File-type variable: GitLab writes the key to a
# temp file and puts its path in the variable.
promote:
  extends: .cb-docker
  stage: promote
  resource_group: promote-github
  rules:
    - if: $PROMOTE_ENABLED != "true"
      when: never
    - if: $CI_PIPELINE_SOURCE == "push" && ($CI_COMMIT_BRANCH == "dev" || $CI_COMMIT_BRANCH == "main")
  variables:
    GIT_DEPTH: "0"
  script:
    - export GIT_SSH_COMMAND="ssh -i ${GH_PROMOTE_DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${CI_PROJECT_DIR}/ci/github_known_hosts"
    - scripts/ci/promote_to_github.sh "$CI_COMMIT_BRANCH"
```

`resource_group` serialises promotes, so two quick merges cannot race each
other's pushes. Add `- local: ci/gitlab/promote.yml` to `.gitlab-ci.yml`.

- [ ] **Step 6: Guard the promote job's shape**

Append to `tests/build/test_gitlab_pipeline.py`:

```python
def test_promote_is_last_gated_and_serialised():
    entry, promote = load_entry(), load_pipeline()["promote"]
    assert entry["stages"][-1] == "promote"
    assert promote["stage"] == "promote"
    assert promote["rules"][0] == {"if": '$PROMOTE_ENABLED != "true"', "when": "never"}
    assert "when" not in promote and "needs" not in promote, "promote must wait for every stage"
    assert promote["resource_group"] == "promote-github"
```

Run: `.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py tests/build/test_promote_to_github.py -q -p no:cacheprovider`
Expected: all pass. Commit: `feat(ci): promote green GitLab SHAs to GitHub with a gitlab/verify status`.

### Task 9: GitHub keeps only what publishes

**Files:**
- Create: `.github/workflows/publish-dev.yml`
- Create: `.github/workflows/release-rehearsal.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `.github/workflows/codeql.yml`
- Modify: `.github/workflows/notify.yml`
- Modify: `.github/workflows/tier2.yml`
- Modify: `.github/dependabot.yml`
- Read first: `.github/workflows/ci.yml:629-660` (the candidate jobs lifted into release-rehearsal.yml)
- Read first: `.github/workflows/release-followup.yml:89-112` (draft cleanup, which stays on GitHub)

**Interfaces:**
- Produces: GitHub secret `GITLAB_TRIGGER_TOKEN` (a GitLab pipeline trigger token,
  in the `release` environment), consumed by `release.yml` post-publish.
- Produces: the pipeline variables `CB_PIPELINE=release-followup`,
  `CB_FOLLOWUP_VERSION` and `CB_FOLLOWUP_PUBLISHED_AT`, consumed by Task 10.

- [ ] **Step 1: `release.yml` refuses an unverified SHA**

In `.github/workflows/release.yml`, insert this as the first step of the `gate` job,
directly after `- uses: actions/checkout@v5`:

```yaml
      # plans/2026-09-28-gitlab-cutover.md: GitLab is the test gate. A SHA
      # reaches GitHub only through GitLab's promote job, which posts this
      # status after the whole pipeline passed. Nothing is built without it.
      - name: Require gitlab/verify on this SHA
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          state="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${GITHUB_SHA}/status" \
            --jq '[.statuses[] | select(.context=="gitlab/verify")][0].state // "missing"')"
          echo "gitlab/verify on ${GITHUB_SHA}: ${state}"
          [ "$state" = "success" ] || { echo "::error::${GITHUB_SHA} has no successful gitlab/verify status"; exit 1; }
```

The `gate` job inherits `release.yml`'s top-level `permissions:`, which grants no
`statuses` scope, so the status read would 403. Give the `gate` job its own block
directly under `runs-on:`:

```yaml
    permissions:
      contents: read
      statuses: read
```

Keep the in-release Tier 0, security gate, `artifact-smoke`, `installer-journey`,
`tier2` and `runtime-parity`. They test the **artifacts being shipped** (both
architectures, signed), and CLAUDE.md rule 6 is about exactly that distinction.

- [ ] **Step 2: `release.yml` post-publish hands the follow-up to GitLab**

Replace the two steps `Dispatch the composed agent E2E on the published tag` and
`Dispatch the post-release follow-up on dev` (release.yml:1020-1038) with the
steps below. `e2e.yml` is deleted in Step 7. The composed journey still gates the
release through the `tier2` job, which calls `composed-e2e.yml`, before anything
is published.

```yaml
      # Stale draft cleanup stays here: it is a GitHub Releases operation.
      # Moved verbatim from release-followup.yml, which Step 7 deletes.
      - name: Delete stale draft releases
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          STALE="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/releases?per_page=100" \
            --jq ".[] | select(.draft) | select(.tag_name == \"v${VERSION}\" or (.tag_name | startswith(\"v${VERSION}-\"))) | .id")"
          for ID in ${STALE}; do
            gh api -X DELETE "repos/${GITHUB_REPOSITORY}/releases/${ID}"
          done

      # The follow-up (VERSION bump, CHANGELOG rotation) writes to the source of
      # truth, so it runs on GitLab: ci/gitlab/release-followup.yml.
      - name: Trigger the post-release follow-up on GitLab
        env:
          GITLAB_TRIGGER_TOKEN: ${{ secrets.GITLAB_TRIGGER_TOKEN }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          PUBLISHED_AT="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/v${VERSION}" --jq '.published_at')"
          curl --fail-with-body -sS -X POST \
            -F "token=${GITLAB_TRIGGER_TOKEN}" -F "ref=dev" \
            -F "variables[CB_PIPELINE]=release-followup" \
            -F "variables[CB_FOLLOWUP_VERSION]=${VERSION}" \
            -F "variables[CB_FOLLOWUP_PUBLISHED_AT]=${PUBLISHED_AT}" \
            "https://gitlab.blkleg.app/api/v4/projects/1/trigger/pipeline" > /dev/null
          echo "follow-up for v${VERSION} triggered on GitLab"
```

Read `release-followup.yml:89-112` before pasting the draft-cleanup step and copy
its selection expression exactly. The `--jq` above is the shape to expect, not a
substitute for reading it.

- [ ] **Step 3: Create `.github/workflows/publish-dev.yml`**

```yaml
# plans/2026-09-28-gitlab-cutover.md: publishes :dev / :dev-<sha> / :nightly to
# GHCR for a dev SHA GitLab verified. The push that triggers this can only come
# from GitLab's promote job (the ruleset admits only its deploy key), and the
# gate re-checks the status anyway, so a mis-set ruleset cannot publish an
# untested SHA.
name: Publish dev image

on:
  push:
    branches: [dev]

permissions:
  contents: read

jobs:
  gate:
    name: Require gitlab/verify
    runs-on: ubuntu-22.04
    timeout-minutes: 5
    permissions:
      contents: read
      statuses: read
    steps:
      - name: Require gitlab/verify on this SHA
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          state="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${GITHUB_SHA}/status" \
            --jq '[.statuses[] | select(.context=="gitlab/verify")][0].state // "missing"')"
          echo "gitlab/verify on ${GITHUB_SHA}: ${state}"
          [ "$state" = "success" ] || { echo "::error::${GITHUB_SHA} has no successful gitlab/verify status"; exit 1; }

  publish:
    name: Build, smoke and publish the dev image
    needs: gate
    permissions:
      contents: read
      packages: write
    uses: ./.github/workflows/mono-smoke.yml
    with:
      publish: true
```

- [ ] **Step 4: Create `.github/workflows/release-rehearsal.yml`**

`tests/build/test_release_paths_run_before_the_tag.py` requires every workflow
`release.yml` calls to also run from a `push` or `pull_request` workflow. After
the cutover, `build.yml` and `artifact-smoke.yml` would otherwise run only from a
tag, which is how v0.4.3 shipped. `main` moves only at a release, so this costs
little.

```yaml
# plans/2026-09-28-gitlab-cutover.md: the release's own build and installed-
# artifact gates, run on every promote to main, so a tag is never their first
# execution (GOV-20). Lifted from ci.yml's candidate-* jobs, unchanged.
name: Release rehearsal

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  candidate-build:
    name: Build Packages
    uses: ./.github/workflows/build.yml
    with:
      version: ""
      signing_pubkey: ${{ vars.AGENT_SIGNING_PUBLIC_KEY }}
    secrets:
      AGENT_SIGNING_PRIVATE_KEY: ${{ secrets.AGENT_SIGNING_PRIVATE_KEY }}

  candidate-artifact-smoke:
    name: Artifact Smoke
    needs: candidate-build
    uses: ./.github/workflows/artifact-smoke.yml
    with:
      version: ${{ needs.candidate-build.outputs.version }}

  candidate-installer-journey:
    name: Installer Journey
    needs: candidate-build
    uses: ./.github/workflows/installer-journey.yml
```

Copy `candidate-installer-journey`'s `with:` block from `ci.yml:654` onward. The
excerpt above ends where the Read-first range ends, and the job's inputs must match.

- [ ] **Step 5: Trim the remaining GitHub workflows**

- `.github/workflows/codeql.yml`: delete the `pull_request:` trigger. PRs no longer happen on GitHub.
- `.github/workflows/notify.yml`: set its `workflow_run: workflows:` list to exactly
  `["Release", "Deploy Pages", "CodeQL", "Publish dev image", "Release rehearsal"]`.
  Every other name it lists today belongs to a workflow deleted in Step 7.
- `.github/workflows/tier2.yml`: delete the `schedule:` trigger. The nightly moves
  to GitLab (Task 11). Tier 2 stays a `release.yml` callee and keeps its own
  `pull_request` path filter.
- `.github/dependabot.yml`: delete every `updates:` entry, and replace the file's
  header comment with one line: version updates run as Renovate on GitLab
  (`renovate.json`). Dependabot **security alerts** stay on. That is a repository
  setting, which the maintainer confirms in Task 14.

- [ ] **Step 6: Run the workflow policy suites**

Run: `.venv/bin/python -m pytest tests/build -q -p no:cacheprovider -k "workflow or release or reusable or checkov or tier2"`
Expected: the failures are exactly the ones Task 12 rewrites, and nothing else.
Record the list in the commit message.

- [ ] **Step 7: Delete the workflows GitLab replaced**

```bash
git rm .github/workflows/ci.yml .github/workflows/dev-ci.yml .github/workflows/security.yml \
  .github/workflows/docs.yml .github/workflows/e2e.yml .github/workflows/baseline.yml \
  .github/workflows/ledger-watch.yml .github/workflows/fleet.yml .github/workflows/branch-cleanup.yml \
  .github/workflows/dependabot-automerge.yml .github/workflows/dependabot-lockfile-sync.yml \
  .github/workflows/release-followup.yml
```

`composed-e2e.yml` is **kept**. `tier2.yml` calls it, and deleting it breaks the
release's Tier 2 gate plus five repo-policy suites. Commit Steps 1–7 together as
`feat(ci): GitHub keeps only publication; GitLab owns verification`. Do not run
`make verify` for this commit; its red suites are Task 12's input. Task 12 runs it.

### Task 10: Tags come back, and the follow-up runs on GitLab

**Files:**
- Create: `scripts/ci/sync_tags_from_github.sh`
- Create: `scripts/ci/gitlab_release_followup.sh`
- Create: `tests/build/test_sync_tags_from_github.py`
- Create: `ci/gitlab/release-followup.yml`
- Modify: `.gitlab-ci.yml`
- Read first: `scripts/post_release_bump.py`
- Read first: `scripts/check_version_parity.py`

**Interfaces:**
- Consumes: `CB_FOLLOWUP_VERSION` and `CB_FOLLOWUP_PUBLISHED_AT` (Task 9 Step 2).
- Produces: `scripts/ci/sync_tags_from_github.sh`, which reads `CB_GITHUB_URL`
  (default `https://github.com/BlkLeg/CircuitBreaker.git`) and `CB_GITLAB_PUSH_URL`
  (a remote the job can push tags to). It prints `new tag <t>` or
  `moved tag <t>: <old> -> <new>` per change. It never deletes a tag.
- Produces: `scripts/ci/gitlab_release_followup.sh <released-version> <published-at>`.

- [ ] **Step 1: Write the failing test**

`tests/build/test_sync_tags_from_github.py`:

```python
"""Review Focus 3: GitHub's tags reach GitLab by target, including a re-cut."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "sync_tags_from_github.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    src = tmp_path / "src"
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    _git(src, "config", "user.email", "ci@example.invalid")
    _git(src, "config", "user.name", "ci")
    _git(src, "commit", "--allow-empty", "-q", "-m", "one")
    github = tmp_path / "github.git"
    gitlab = tmp_path / "gitlab.git"
    for bare in (github, gitlab):
        _git(tmp_path, "init", "-q", "--bare", str(bare))
    return src, github, gitlab


def _sync(tmp_path: Path, github: Path, gitlab: Path) -> subprocess.CompletedProcess[str]:
    work = tmp_path / "job"
    if not work.exists():
        _git(tmp_path, "init", "-q", str(work))
    env = {**os.environ, "CB_GITHUB_URL": str(github), "CB_GITLAB_PUSH_URL": str(gitlab)}
    return subprocess.run(["bash", str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True, check=False)


def test_a_new_tag_is_pushed(tmp_path):
    src, github, gitlab = _repo(tmp_path)
    _git(src, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    _git(src, "push", "-q", str(github), "main", "v1.0.0")
    result = _sync(tmp_path, github, gitlab)
    assert result.returncode == 0, result.stderr
    assert "new tag v1.0.0" in result.stdout
    assert _git(gitlab, "rev-parse", "v1.0.0") == _git(github, "rev-parse", "v1.0.0")


def test_a_moved_tag_is_updated_and_reported(tmp_path):
    src, github, gitlab = _repo(tmp_path)
    _git(src, "tag", "-a", "v0.4.2", "-m", "first cut")
    _git(src, "push", "-q", str(github), "main", "v0.4.2")
    _git(src, "push", "-q", str(gitlab), "main", "v0.4.2")
    _git(src, "commit", "--allow-empty", "-q", "-m", "fix")
    _git(src, "tag", "-f", "-a", "v0.4.2", "-m", "re-cut")
    _git(src, "push", "-q", "-f", str(github), "main", "v0.4.2")
    result = _sync(tmp_path, github, gitlab)
    assert result.returncode == 0, result.stderr
    assert "moved tag v0.4.2" in result.stdout
    assert _git(gitlab, "rev-parse", "v0.4.2") == _git(github, "rev-parse", "v0.4.2")


def test_a_tag_only_on_gitlab_is_left_alone(tmp_path):
    src, github, gitlab = _repo(tmp_path)
    _git(src, "tag", "v9.9.9-local")
    _git(src, "push", "-q", str(gitlab), "main", "v9.9.9-local")
    _git(src, "push", "-q", str(github), "main")
    result = _sync(tmp_path, github, gitlab)
    assert result.returncode == 0, result.stderr
    assert _git(gitlab, "rev-parse", "v9.9.9-local")
```

Run: `.venv/bin/python -m pytest tests/build/test_sync_tags_from_github.py -q -p no:cacheprovider`
Expected: FAIL on the missing script.

- [ ] **Step 2: Write `scripts/ci/sync_tags_from_github.sh`**

```bash
#!/usr/bin/env bash
#
# Bring GitHub's v* tags to GitLab, compared by target.
#
# release.yml creates tags on GitHub. GitHub is authoritative for them, and it
# has re-cut tags after a release recovery (v0.4.2 and v0.4.3, 2026-09): a
# name-only comparison would miss that, and did once. So a tag whose target
# differs is updated and reported. A tag that exists only on GitLab is left
# alone: this never deletes.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

GITHUB_URL="${CB_GITHUB_URL:-https://github.com/BlkLeg/CircuitBreaker.git}"
PUSH_URL="${CB_GITLAB_PUSH_URL:?CB_GITLAB_PUSH_URL is required}"

declare -A github_tags gitlab_tags
while read -r sha ref; do
    case "$ref" in *'^{}') continue ;; esac
    github_tags["${ref#refs/tags/}"]="$sha"
done < <(git ls-remote --tags "$GITHUB_URL" 'refs/tags/v*')
while read -r sha ref; do
    case "$ref" in *'^{}') continue ;; esac
    gitlab_tags["${ref#refs/tags/}"]="$sha"
done < <(git ls-remote --tags "$PUSH_URL" 'refs/tags/v*')

changed=()
for tag in "${!github_tags[@]}"; do
    want="${github_tags[$tag]}"
    have="${gitlab_tags[$tag]:-}"
    if [ -z "$have" ]; then
        echo "new tag ${tag}"
        changed+=("$tag")
    elif [ "$have" != "$want" ]; then
        echo "moved tag ${tag}: ${have} -> ${want}"
        changed+=("$tag")
    fi
done

if [ "${#changed[@]}" -eq 0 ]; then
    echo "GitLab tags match GitHub"
    exit 0
fi
refspecs=()
for tag in "${changed[@]}"; do
    git fetch --quiet --force "$GITHUB_URL" "refs/tags/${tag}:refs/tags/${tag}"
    refspecs+=("+refs/tags/${tag}:refs/tags/${tag}")
done
git push --quiet "$PUSH_URL" "${refspecs[@]}"
```

`chmod +x`, then run the test. Expected: 3 passed.

- [ ] **Step 3: Write `scripts/ci/gitlab_release_followup.sh`**

This is `release-followup.yml`'s open-next logic (lines 114-176) with the GitHub
calls replaced. The bump itself is still `scripts/post_release_bump.py` and
`scripts/check_version_parity.py`.

```bash
#!/usr/bin/env bash
#
# Open the next patch on dev after a release (was release-followup.yml).
# Triggered by release.yml post-publish through GitLab's pipeline trigger API.
# GITLAB_PUSH_TOKEN: project access token (Maintainer; api, write_repository),
# masked and protected. It is passed to git through an http header, never a URL.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

RELEASED="${1:?usage: gitlab_release_followup.sh <released-version> <published-at>}"
PUBLISHED_AT="${2:?}"
: "${GITLAB_PUSH_TOKEN:?GITLAB_PUSH_TOKEN is required}"
[[ "$RELEASED" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "::error::bad version: $RELEASED" >&2; exit 1; }
API="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}"
BRANCH="chore/post-release-v${RELEASED}"
AUTH=(-c "http.extraHeader=PRIVATE-TOKEN: ${GITLAB_PUSH_TOKEN}")

git "${AUTH[@]}" fetch --quiet origin dev
git checkout -B "$BRANCH" origin/dev
NEXT="$(python3 scripts/post_release_bump.py open-next --released "$RELEASED" --published-at "$PUBLISHED_AT")"
python3 scripts/check_version_parity.py --write
if git diff --quiet; then
    echo "dev already opens the version after v${RELEASED}; nothing to propose"
    exit 0
fi
git -c user.name="cb-release-bot" -c user.email="release-bot@gitlab.blkleg.app" \
    commit --all --quiet -m "chore(release): open v${NEXT} after v${RELEASED}" \
    -m "Dates the v${RELEASED} CHANGELOG entry and opens [${NEXT}] above it."
git "${AUTH[@]}" push --quiet --force-with-lease origin "HEAD:refs/heads/${BRANCH}"

existing="$(curl -sS --fail-with-body -H "PRIVATE-TOKEN: ${GITLAB_PUSH_TOKEN}" \
    "${API}/merge_requests?state=opened&source_branch=${BRANCH}&target_branch=dev" | jq 'length')"
if [ "$existing" -eq 0 ]; then
    jq -n --arg s "$BRANCH" --arg t "chore(release): open v${NEXT} after v${RELEASED}" \
        '{source_branch: $s, target_branch: "dev", title: $t, remove_source_branch: true}' \
      | curl -sS --fail-with-body -X POST -H "PRIVATE-TOKEN: ${GITLAB_PUSH_TOKEN}" \
          -H "Content-Type: application/json" --data @- "${API}/merge_requests" > /dev/null
    echo "opened the follow-up MR for v${NEXT}"
else
    echo "the follow-up MR for ${BRANCH} already exists"
fi
```

Before committing, read `post_release_bump.py`'s `open-next` subcommand to confirm
it prints only the next version on stdout. `release-followup.yml:139` relies on
the same thing.

- [ ] **Step 4: Write `ci/gitlab/release-followup.yml`**

```yaml
# Triggered by release.yml post-publish (CB_PIPELINE=release-followup). Tags
# first, so the MR's pipeline and any later compare can see v<released>.
release-followup:
  extends: .cb-docker
  stage: lint
  rules:
    - if: $CI_PIPELINE_SOURCE == "trigger" && $CB_PIPELINE == "release-followup"
  variables:
    GIT_DEPTH: "0"
  script:
    - export CB_GITLAB_PUSH_URL="https://gitlab-ci-token:${GITLAB_PUSH_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"
    - scripts/ci/sync_tags_from_github.sh
    - scripts/ci/gitlab_release_followup.sh "$CB_FOLLOWUP_VERSION" "$CB_FOLLOWUP_PUBLISHED_AT"
```

Every other job must not run in this pipeline. Add this rule as the **first** rule
of `.cb-docker`, `.browser-e2e` and the package job, and give each a `rules:`
block if it lacks one:

```yaml
  rules:
    - if: $CB_PIPELINE
      when: never
    - when: on_success
```

`CB_GITLAB_PUSH_URL` carries the token in a URL, which Review Focus 5 forbids in
scripts. It is built in the job's `script:`, not in a script file, and GitLab
masks the variable in the log. `test_ci_scripts_never_trace` scans
`scripts/ci/` only, so this is the one sanctioned place. Say so in a comment on
that line.

Add `- local: ci/gitlab/release-followup.yml` to `.gitlab-ci.yml`. Run
`.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py tests/build/test_sync_tags_from_github.py tests/build/test_promote_to_github.py -q -p no:cacheprovider`.
Expected: all pass. Commit: `feat(ci): release follow-up and tag sync on GitLab`.

### Task 11: Scheduled work on GitLab

**Files:**
- Create: `ci/gitlab/scheduled.yml`
- Create: `scripts/ci/gitlab_ledger_issue.sh`
- Create: `renovate.json`
- Modify: `.gitlab-ci.yml`
- Read first: `.github/workflows/tier2.yml`
- Read first: `.github/workflows/baseline.yml`
- Read first: `.github/workflows/ledger-watch.yml`
- Read first: `.github/workflows/dependabot-lockfile-sync.yml:76-84`
- Read first: `specs/1.0.0/release-control/quarantine-register.csv`

**Interfaces:**
- Consumes: schedule variable `CB_PIPELINE` ∈ {`nightly`, `tag-sync`, `renovate`},
  set per schedule in GitLab.

- [ ] **Step 1: Write `ci/gitlab/scheduled.yml`**

```yaml
# Scheduled pipelines. Each GitLab schedule sets CB_PIPELINE; nothing here runs
# on a push. `.scheduled` is always LAST in `extends:` so its rules win over
# `.cb-docker`'s (GitLab merges extends left to right, later keys override).
# The composed journey is allow_failure while QUAR-001 is active
# (specs/1.0.0/release-control/quarantine-register.csv); test_quarantine_notice
# keeps that coupled to the register row.
.scheduled:
  stage: scheduled
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule" && $CB_PIPELINE == $CB_SCHEDULE

"Nightly: composed agent journey":
  extends: .scheduled
  tags: [systemd]
  variables: {CB_SCHEDULE: nightly}
  allow_failure: true
  timeout: 90m
  before_script:
    - scripts/ci/assert_clean_runner.sh
  script:
    - python3.12 -m venv .venv && .venv/bin/pip install -e "apps/backend/[dev]"
    - scripts/ci/tier2-agent-journey.sh

# baseline.yml, ported. On the systemd VM, not the Docker runner: it starts its
# dependencies with `docker run --network host` and talks to them on 127.0.0.1,
# which only works where the job runs directly on the Docker host. Secrets are
# minted per run exactly as before (never committed); GitLab has no add-mask,
# so they are never echoed.
"Nightly: baseline":
  extends: .scheduled
  tags: [systemd]
  variables:
    CB_SCHEDULE: nightly
    CB_REDIS_URL: redis://127.0.0.1:6379/0
    CB_NATS_URL: nats://127.0.0.1:4222
    CB_ALLOW_DIRECT_EGRESS: "true"
    CB_ALLOW_DEGRADED_DEPENDENCIES: "true"
    CB_AUTO_MIGRATE: "true"
    CB_DATA_DIR: /tmp/cb-baseline
    PYTHONPATH: apps/backend/src
  allow_failure: true
  timeout: 45m
  before_script:
    - scripts/ci/assert_clean_runner.sh
  script:
    - python3.12 -m venv .venv && . .venv/bin/activate && pip install -e "apps/backend/[dev]"
    - |
      db_password=$(openssl rand -hex 24)
      export CB_DB_URL="postgresql://breaker:${db_password}@127.0.0.1:5432/circuitbreaker_loadgen"
      export CB_JWT_SECRET=$(openssl rand -hex 32)
      export CB_VAULT_KEY=$(openssl rand -base64 32 | tr -d '\n')
      export CB_BASELINE_PASSWORD="Aa1!$(openssl rand -hex 16)"
      docker run -d --name baseline-postgres --network host \
        -e POSTGRES_USER=breaker -e POSTGRES_PASSWORD="$db_password" \
        -e POSTGRES_DB=circuitbreaker_loadgen postgres:16-alpine
      docker run -d --name baseline-redis --network host redis:7-alpine
      docker run -d --name baseline-nats --network host nats:2.10-alpine -js
      for i in $(seq 1 30); do docker exec baseline-postgres pg_isready -U breaker -d circuitbreaker_loadgen && break; sleep 1; done
      (cd apps/backend && alembic upgrade head)
      mkdir -p artifacts/baselines
      (cd apps/backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers > ../../artifacts/baseline-server.log 2>&1 &)
      (cd apps/backend && CB_TOPOLOGY_MODE=worker python -m app.workers.main --type=monitor_scheduler > ../../artifacts/monitor-scheduler.log 2>&1 &)
      (cd apps/backend && CB_TOPOLOGY_MODE=worker python -m app.workers.main --type=monitor_poll > ../../artifacts/monitor-poll.log 2>&1 &)
      for i in $(seq 1 60); do curl -fsS http://127.0.0.1:8000/api/v1/livez && break; sleep 1; done
      curl -fsS http://127.0.0.1:8000/api/v1/bootstrap/status > /dev/null
      setup_token=$(tr -d '\r\n' < /tmp/cb-baseline/bootstrap-setup-token)
      CB_LOADGEN_TOKEN=$(curl -fsS -H 'Content-Type: application/json' \
        -d "{\"setup_token\":\"$setup_token\",\"email\":\"baseline@example.test\",\"password\":\"$CB_BASELINE_PASSWORD\",\"theme_preset\":\"gruvbox-dark\"}" \
        http://127.0.0.1:8000/api/v1/bootstrap/initialize | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')
      for tier in A B C; do
        python scripts/loadgen/seed.py seed --tier "$tier" --db-url "$CB_DB_URL"
        python scripts/loadgen/run.py --tier "$tier" --duration 120 --token "$CB_LOADGEN_TOKEN" --output "artifacts/baselines/${tier}.json"
        python scripts/loadgen/seed.py cleanup --tier "$tier" --db-url "$CB_DB_URL"
      done
      python scripts/loadgen/summarize.py artifacts/baselines
  after_script:
    - pkill -f 'uvicorn app.main:app' || true
    - pkill -f 'app.workers.main' || true
    - docker rm -f baseline-postgres baseline-redis baseline-nats || true
    - sudo rm -rf /tmp/cb-baseline
  artifacts:
    when: always
    expire_in: 30 days
    paths: [artifacts/]

"Nightly: ledger watch":
  extends: [.cb-docker, .scheduled]
  variables: {CB_SCHEDULE: nightly, HORIZON_DAYS: "14"}
  script:
    - python3 scripts/ci/ledger_watch.py --days "$HORIZON_DAYS" > ledger-report.md
    - python3 scripts/ci/ledger_watch.py --days "$HORIZON_DAYS" --json > ledger-report.json
    - scripts/ci/gitlab_ledger_issue.sh ledger-report.md ledger-report.json

tag-sync:
  extends: [.cb-docker, .scheduled]
  variables: {CB_SCHEDULE: tag-sync, GIT_DEPTH: "0"}
  script:
    - export CB_GITLAB_PUSH_URL="https://gitlab-ci-token:${GITLAB_PUSH_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"  # masked; see release-followup.yml
    - scripts/ci/sync_tags_from_github.sh

# -full: postUpgradeTasks runs scripts/gen_requirements.py (stdlib only), which
# needs a python3 the slim image does not ship.
renovate:
  extends: .scheduled
  tags: [docker]
  image: renovate/renovate:41-full
  variables:
    CB_SCHEDULE: renovate
    RENOVATE_PLATFORM: gitlab
    RENOVATE_ENDPOINT: $CI_API_V4_URL
    RENOVATE_REPOSITORIES: $CI_PROJECT_PATH
    RENOVATE_ALLOWED_COMMANDS: '["^python3 scripts/gen_requirements\\.py$"]'
  script:
    - RENOVATE_TOKEN="$GITLAB_PUSH_TOKEN" renovate
```

Add `scheduled` to `.gitlab-ci.yml`'s `stages:` list, after `package` and before
`promote`. `test_no_verify_job_may_fail_silently` exempts `stage: scheduled`,
because those jobs never share a pipeline with `promote`: `.scheduled`'s rule
admits only `schedule` sources. Add `- local: ci/gitlab/scheduled.yml` to `include:`.

- [ ] **Step 2: Write `scripts/ci/gitlab_ledger_issue.sh`**

```bash
#!/usr/bin/env bash
#
# ledger-watch's issue, on GitLab (was `gh issue create/edit` in ledger-watch.yml).
# One open issue labelled `ledger-expiry` is created or updated with the report;
# when the report has no rows, an open one is closed.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

REPORT_MD="${1:?usage: gitlab_ledger_issue.sh <report.md> <report.json>}"
REPORT_JSON="${2:?}"
: "${GITLAB_PUSH_TOKEN:?GITLAB_PUSH_TOKEN is required}"
API="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}"
H=(-H "PRIVATE-TOKEN: ${GITLAB_PUSH_TOKEN}")

rows="$(jq 'if type == "array" then length else (.rows // []) | length end' "$REPORT_JSON")"
iid="$(curl -sS --fail-with-body "${H[@]}" "${API}/issues?state=opened&labels=ledger-expiry" | jq -r '.[0].iid // empty')"
body="$(cat "$REPORT_MD"; printf '\n\nMaintained by `ci/gitlab/scheduled.yml` from `scripts/ci/ledger_watch.py`. Last run: %s\n' "$CI_PIPELINE_URL")"

if [ "$rows" -eq 0 ]; then
    [ -n "$iid" ] && curl -sS --fail-with-body -X PUT "${H[@]}" "${API}/issues/${iid}?state_event=close" > /dev/null
    echo "no expiring rows"
    exit 0
fi
payload="$(jq -n --arg d "$body" '{title: "Release-control ledger: rows expiring soon", description: $d, labels: "ledger-expiry"}')"
if [ -n "$iid" ]; then
    curl -sS --fail-with-body -X PUT "${H[@]}" -H "Content-Type: application/json" --data "$payload" "${API}/issues/${iid}" > /dev/null
else
    curl -sS --fail-with-body -X POST "${H[@]}" -H "Content-Type: application/json" --data "$payload" "${API}/issues" > /dev/null
fi
echo "${rows} expiring row(s) reported"
```

Read `ledger_watch.py --json`'s real output shape before committing, and adjust
the `rows=` jq expression so it counts exactly the rows the Markdown report lists.

- [ ] **Step 3: Write `renovate.json`**

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "baseBranches": ["dev"],
  "dependencyDashboard": true,
  "packageRules": [
    { "matchManagers": ["npm"], "matchFileNames": ["apps/frontend/**"], "groupName": "frontend", "schedule": ["before 6am on monday"] },
    { "matchManagers": ["npm"], "matchFileNames": ["package.json"], "groupName": "root npm", "schedule": ["before 6am on the first day of the month"] },
    { "matchManagers": ["poetry", "pep621"], "groupName": "backend python", "schedule": ["before 6am on the first day of the month"] },
    { "matchManagers": ["gomod"], "groupName": "agent go", "schedule": ["before 6am on the first day of the month"] }
  ],
  "postUpgradeTasks": {
    "commands": ["python3 scripts/gen_requirements.py"],
    "fileFilters": ["apps/backend/requirements.txt"],
    "executionMode": "branch"
  }
}
```

The schedules and groups mirror `.github/dependabot.yml`'s cadence (npm frontend
weekly; root npm, pip and gomod monthly). Read its `groups:` blocks and carry
over any exclusion they make.

- [ ] **Step 4: Commit**

`chmod +x scripts/ci/gitlab_ledger_issue.sh`, run
`.venv/bin/python -m pytest tests/build/test_gitlab_pipeline.py tests/build/test_promote_to_github.py -q -p no:cacheprovider`,
and commit: `feat(ci): nightly, tag sync, ledger watch and Renovate on GitLab`.

### Task 12: The repo-policy suite follows the move

Each row below comes from reading the file, not from its name. The changes are the
minimum that keeps each guard *checking something*. A guard that goes quiet is
worse than one that fails.

**Files:**
- Modify: `tests/build/test_ci_script_contract.py`
- Modify: `tests/build/test_ci_evidence_retention.py`
- Modify: `tests/build/test_checkov_mono_smoke_exception.py`
- Modify: `tests/build/test_release_promote_contract.py`
- Modify: `tests/build/test_release_approval_gate.py`
- Modify: `tests/build/test_release_paths_run_before_the_tag.py`
- Modify: `tests/build/test_phase2_baseline_contract.py`
- Modify: `tests/build/test_proxy_forwarded_headers.py`
- Modify: `tests/build/test_tier2_wiring.py`
- Modify: `tests/build/test_quarantine_notice.py`
- Modify: `tests/build/test_ledger_watch.py`
- Modify: `tests/build/test_branch_cleanup.py`
- Modify: `tests/build/required_checks.py`
- Modify: `specs/1.0.0/release-control/security-suppressions.json`
- Modify: `plans/2026-09-20-step0-signal-trust.md`
- Modify: `plans/2026-09-20-step3-tier2-and-release-control.md`
- Read first: `tests/build/test_workflow_wiring_resolves.py`
- Read first: `tests/build/test_reusable_workflow_permissions.py`

- [ ] **Step 1: Delete the suites whose subject is gone**

```bash
git rm tests/build/test_dependabot_lockfile_sync.py tests/build/test_dependabot_automerge.py \
  tests/build/test_dispatch_required_checks.py scripts/ci/dispatch_required_checks.sh
```

`dispatch_required_checks.sh` existed only because pushes made with GitHub's
`GITHUB_TOKEN` start no workflows. Its callers (lockfile sync, release follow-up)
are gone, and on GitLab a pushed branch runs its pipeline.

- [ ] **Step 2: Retarget, one file at a time**

| File | Change |
|---|---|
| `test_ci_script_contract.py` | `test_workflow_calls_the_tier0_script_rather_than_inlining_it` (parametrized over `dev-ci.yml`/`ci.yml` at :200): parametrize over `ci/gitlab/verify.yml`, and assert that the `Lint` job's `script` contains `scripts/ci/tier0-static.sh` and no `ruff`/`mypy`. |
| `test_ci_evidence_retention.py` | Point `TEST_WORKFLOWS`/`EVIDENCE_OWING_JOBS` at the GitLab jobs through `test_gitlab_pipeline.load_pipeline()`. "Upload on failure" becomes `artifacts.when == "always"`, and the ≥7-day retention reads `artifacts.expire_in`. The shard-count assertion reads the four `Backend tests (shard N/4)` names against `backend_shard.py`. The browser-e2e and mono-smoke GitHub rows stay. |
| `test_checkov_mono_smoke_exception.py` | `_sources()` (:36, :80) reads the `Checkov (GitHub Actions / IaC)` job in `ci/gitlab/security.yml`. `EXPECTED_PUBLISHER` (:184, :239) becomes `publish-dev.yml:publish`. Update CHECKOV-001's reason in `security-suppressions.json` to name `publish-dev.yml` as the only granting caller. |
| `test_release_promote_contract.py` | :60 asserts that post-publish posts to GitLab's trigger API with `CB_PIPELINE=release-followup`, instead of running `gh workflow run e2e.yml`. :77 asserts that `publish-dev.yml`'s `publish` job `needs: gate`, and that `gate` checks `gitlab/verify`. |
| `test_release_approval_gate.py` | Delete the three follow-up tests (:173, :184, :194). Add one asserting that post-publish's trigger step exists and runs after `promote`. |
| `test_release_paths_run_before_the_tag.py` | :253 names `release-rehearsal.yml` as the push caller of `build.yml` and `artifact-smoke.yml`, where it used to name `dev-ci.yml`/`ci.yml`. |
| `test_phase2_baseline_contract.py` | The three workflow tests (:167, :198, :218) read `"Nightly: baseline"` in `ci/gitlab/scheduled.yml`. "continue-on-error" becomes `allow_failure: true`; "upload ≥30 days" reads `artifacts.expire_in`; "runtime secrets" asserts the four `openssl rand` lines and no literal secret. The cron assertion becomes "the job extends `.scheduled` with `CB_SCHEDULE: nightly`"; GitLab keeps the cron in the schedule, not in the file. |
| `test_proxy_forwarded_headers.py` | Replace the `baseline.yml` row in `UVICORN_LAUNCHERS` (:130) with `ci/gitlab/scheduled.yml`. |
| `test_tier2_wiring.py` | Delete the tests that assert `tier2`'s schedule (:214), `e2e.yml` (:216) and the tier2→composed call (:220–:223) as they stand. Restate them: tier2 has no `schedule:`; `tier2.jobs.composed.uses` is still `composed-e2e.yml`; the GitLab nightly job calls `scripts/ci/tier2-agent-journey.sh`. |
| `test_quarantine_notice.py` | `test_the_real_register_still_covers_the_composed_journey` (:157) also requires that the GitLab `"Nightly: composed agent journey"` job is `allow_failure: true` **only while** QUAR-001 is active. |
| `test_ledger_watch.py` | Replace the `gh label create --force` test (:365) with one asserting that the nightly job calls `scripts/ci/gitlab_ledger_issue.sh`. |
| `test_branch_cleanup.py` | Delete the file and `scripts/ci/branch_cleanup.py`. GitLab MRs delete their source branch on merge (`remove_source_branch`, which Task 14 makes the project default). |
| `required_checks.py` | Keep the tuple. Rewrite the docstring: these are the gate jobs GitLab's pipeline must contain (`test_gitlab_pipeline.test_every_required_check_is_a_gitlab_job`), which EXC-002's compensating control names; GitHub rulesets require none of them after the cutover. |
| `plans/2026-09-20-step0-signal-trust.md:248`, `plans/2026-09-20-step3-tier2-and-release-control.md:52` | These `Read …:` lines name files Task 9 deletes, and `test_plan_references.py` fails on them. Append ` (deleted 2026-09 by the GitLab cutover; see git history)` to each, and change the prefix from `Read …:` to `Historical:` so the checker no longer treats them as references. |

`test_workflow_wiring_resolves.py`, `test_reusable_workflow_permissions.py`,
`test_scheduled_workflows_pin_their_ref.py` and `test_release_artifact_patterns.py`
need **no** change, because `composed-e2e.yml` is kept. Run them anyway.

- [ ] **Step 3: The split guard**

Append to `tests/build/test_gitlab_pipeline.py`:

```python
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
KEPT_ON_GITHUB = {
    "release.yml", "release-dry-run.yml", "build.yml", "artifact-smoke.yml",
    "installer-journey.yml", "browser-e2e.yml", "mono-smoke.yml", "tier2.yml",
    "composed-e2e.yml", "pages.yml", "codeql.yml", "notify.yml",
    "publish-dev.yml", "release-rehearsal.yml",
}


def test_github_keeps_only_publication():
    assert {p.name for p in WORKFLOWS.glob("*.yml")} == KEPT_ON_GITHUB


def test_publication_requires_gitlab_verify():
    for name in ("release.yml", "publish-dev.yml"):
        assert 'select(.context=="gitlab/verify")' in (WORKFLOWS / name).read_text(encoding="utf-8"), name


def test_no_signing_or_registry_push_on_gitlab():
    for path in sorted((REPO_ROOT / "ci" / "gitlab").glob("*.yml")) + [ENTRY]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ("AGENT_SIGNING_PRIVATE_KEY", "docker push", "cosign", "id-token"):
            assert forbidden not in text, f"{path.name} contains {forbidden}"
```

- [ ] **Step 4: Run the whole repo-policy suite and `make verify`**

```bash
.venv/bin/python -m pytest tests/build -q -p no:cacheprovider
make verify
```
Expected: both green. This is the covering suite for Tasks 8–12's repo-side
changes. Commit: `test(build): repo-policy suites follow the GitLab cutover`.

### Task 13: Governance and docs say what is now true

**Files:**
- Modify: `.github/branch-protection.md`
- Modify: `specs/1.0.0/evidence/gov-15-branch-protection-enabled.md`
- Modify: `specs/1.0.0/release-control/requirement-ledger.csv`
- Modify: `specs/1.0.0/release-control/exception-register.csv`
- Modify: `.github/CODEOWNERS`
- Modify: `CLAUDE.md`
- Modify: `CONTRIBUTING.md`
- Modify: `.claude/skills/cb-automation/SKILL.md`
- Modify: `.claude/skills/cb-build-test/SKILL.md`
- Modify: `.claude/skills/cb-release/SKILL.md`
- Modify: `.claude/skills/cb-code-quality/SKILL.md`

- [ ] **Step 1: Branch protection and GOV-15**

Rewrite `.github/branch-protection.md` into two sections, **GitLab (enforcing)** and
**GitHub (publish mirror)**, with the Task 14 settings. The **GitLab** section
covers `dev`/`main`: MR required, pipeline must succeed, no force push, nobody
allowed to push. The **GitHub** section covers updates restricted to the promote
deploy key, zero required checks, and why. A required status check cannot be
satisfied, because GitHub evaluates it before the ref moves and `gitlab/verify`
is posted after. Keep the strings listed in Global Constraints.

`specs/1.0.0/evidence/gov-15-branch-protection-enabled.md` is pinned by digest in
`requirement-ledger.csv:117`, and `scripts/validate_v1_release_control.py`
(Tier 0) fails on a stale digest. Do not edit it in place. Instead:

1. (Task 14 Step 6 does this, on cutover day.) Create `specs/1.0.0/evidence/gov-15-branch-protection-gitlab.md` with the same
   section layout (What was wrong / Method / Review model / Applied configuration /
   Verification / Standing caveat). Its "Verification" section contains the actual
   API output from Task 14 Step 6 (GitLab `protected_branches`, GitHub
   `rulesets`), so it can only be finished **on cutover day**.
2. In `requirement-ledger.csv:117`, point GOV-15's evidence at the new file with
   its new digest. Change the procedure text from "generated by parsing every
   `.github/workflows/*.yml` with a `pull_request` trigger" to "the gate jobs in
   `.gitlab-ci.yml` (tests/build/test_gitlab_pipeline.py)". Leave the old file in
   place as history.

- [ ] **Step 2: EXC-002**

Its `compensating_control` cell names "21 required status checks" that GitHub
enforces. Restate it: the same gates run as GitLab jobs (19, plus CodeQL on
GitHub after promote); GitLab protected branches refuse a merge whose pipeline
did not succeed; GitHub accepts only the promote deploy key; `release.yml`
refuses any SHA without `gitlab/verify`.

- [ ] **Step 3: Everything that tells a person how to work**

- `.github/CODEOWNERS`: add `/.gitlab-ci.yml` and `/ci/` with the same owner as `/.github/workflows/`.
- `CLAUDE.md`: in "Before pushing", `origin` becomes GitLab. Rule 4 names `git ls-remote gitlab`.
  The "What the gates do NOT cover" table gains a "Runs on" column: GitLab
  pipeline / GitLab nightly / GitHub release / local only. The Repo line names
  both URLs.
- `CONTRIBUTING.md`: contributions are merge requests on GitLab. A GitHub PR is
  still welcome, and the maintainer carries it over with
  `git fetch github pull/N/head:contrib/N` followed by a GitLab MR. The lychee link
  check is not in CI; run `lychee docs/` locally before a docs-heavy MR.
- The four skills: replace workflow names and procedures with their GitLab
  equivalents. `cb-release` in particular: post-publish now triggers GitLab, the
  follow-up MR appears on GitLab, and tags arrive on GitLab through tag sync.

- [ ] **Step 4: Verify and commit**

Run: `make verify`
Expected: green. The GOV-15 ledger row is untouched by this task, so
`validate_v1_release_control.py` still checks the old evidence digest. The new
evidence file and the ledger row change together on cutover day (Task 14 Step 6),
because the file records settings that only exist from then on.
Commit: `docs: governance and contributor docs for the GitLab cutover`.

---

## Phase 3 — Cutover day

### Task 14: The runbook

Do every step in order, in one sitting. Each step names its check, and a failed
check means **stop and roll back** (below), not improvise.

**Files:**
- Create: `specs/1.0.0/evidence/gov-15-branch-protection-gitlab.md`
- Modify: `specs/1.0.0/release-control/requirement-ledger.csv`

- [ ] **Step 1: Freeze GitHub**

Merge or close every open PR on GitHub, Dependabot's included:
`gh pr list -R BlkLeg/CircuitBreaker --state open` must print nothing. Post in
Discord #maintainer: "GitHub frozen for the GitLab cutover".

- [ ] **Step 2: Land the payload on GitHub, the last merges ever made there**

1. Open a PR `chore/gitlab-cutover` → `dev`. `Dev CI` still exists on this PR's
   **base**, so GitHub runs it. It must be green. Merge it.
2. Open a PR `dev` → `main`. This carries the cutover to `main` so `release.yml`'s
   status gate is live. It is not a release, and no tag is cut. Merge it once green.

- [ ] **Step 3: Final sync to GitLab, then compare by target**

```bash
git fetch origin
git push gitlab 'refs/remotes/origin/dev:refs/heads/dev' 'refs/remotes/origin/main:refs/heads/main'
CB_GITHUB_URL=https://github.com/BlkLeg/CircuitBreaker.git \
  CB_GITLAB_PUSH_URL=https://gitlab.blkleg.app/BlkLeg/circuitbreaker.git \
  bash scripts/ci/sync_tags_from_github.sh
norm() { grep -E 'refs/(heads/(main|dev)|tags/v)' | grep -v '\^{}' | sort; }
diff <(git ls-remote gitlab | norm) <(git ls-remote origin | norm) && echo IDENTICAL
```
Expected: `IDENTICAL`.

- [ ] **Step 4: Secrets and variables**

GitLab → Settings → CI/CD → Variables (all **masked** and **protected**):

| Variable | Type | Value |
|---|---|---|
| `GH_PROMOTE_DEPLOY_KEY` | File | private half of a new ed25519 key; the public half is a **write** deploy key on GitHub named `gitlab-promote` |
| `GH_STATUS_TOKEN` | Variable | fine-grained GitHub PAT, repo `BlkLeg/CircuitBreaker` only, "Commit statuses: write" only |
| `GITLAB_PUSH_TOKEN` | Variable | GitLab project access token, Maintainer, scopes `api`, `write_repository` |
| `PROMOTE_ENABLED` | Variable | `true` |

GitLab → Settings → CI/CD → Pipeline trigger tokens: create one named
`github-release`. Put it on GitHub as secret `GITLAB_TRIGGER_TOKEN` in the
`release` environment. None of these values is written into any file, chat or
commit.

- [ ] **Step 5: Branch protection, both sides**

GitLab → Settings → Repository → Protected branches, for `dev` and `main`: set
**Allowed to merge** to Maintainers, **Allowed to push and merge** to No one, and
**Allowed to force push** to off. Settings → Merge requests: turn on "Pipelines
must succeed" and "Enable 'Delete source branch' option by default".

GitHub rulesets `Dev-Branch` and `Main-Branch`: remove all 21 required status checks,
and restrict updates to the `gitlab-promote` deploy key. Keep "block force pushes".
Confirm that Dependabot security alerts are on (Settings → Code security).

- [ ] **Step 6: Record the evidence (GOV-15)**

```bash
curl -s -H "PRIVATE-TOKEN: $(cat ~/.config/cb/gitlab-token)" \
  https://gitlab.blkleg.app/api/v4/projects/1/protected_branches | jq .
gh api repos/BlkLeg/CircuitBreaker/rulesets --jq '.[].id' \
  | xargs -I{} gh api repos/BlkLeg/CircuitBreaker/rulesets/{} | jq '{name, enforcement, rules, bypass_actors}'
```
Write both outputs into `specs/1.0.0/evidence/gov-15-branch-protection-gitlab.md`
(Task 13 Step 1), update `requirement-ledger.csv:117` with its digest, and commit
both on a branch. That branch becomes the acceptance test in Step 8.

- [ ] **Step 7: Schedules, integrations, remotes**

GitLab → Build → Pipeline schedules, all on `dev`:

| Description | Cron (UTC) | Variable |
|---|---|---|
| nightly | `0 3 * * *` | `CB_PIPELINE=nightly` |
| tag sync | `*/30 * * * *` | `CB_PIPELINE=tag-sync` |
| renovate | `0 5 * * *` | `CB_PIPELINE=renovate` |

GitLab → Settings → Integrations → Discord Notifications: point the webhook at
#maintainer, with triggers "pipeline (failed)" on `dev`/`main` and "issue".

On the laptop and on thebaratie:
```bash
git remote rename origin github
git remote set-url --push github DISABLED
git remote rename gitlab origin
git remote -v
```
Expected: `origin` is GitLab for fetch and push, and `github` is fetch-only (its
push URL is the literal `DISABLED`, so a push fails).

- [ ] **Step 8: The acceptance test: one change, end to end**

Push the Step 6 branch to GitLab (`origin`), open an MR into `dev`, and merge it
when its pipeline is green. Then check each of these:

1. The `dev` pipeline for the merge commit is green, and its `promote` job logs
   `GitHub dev: <old> -> <sha>`.
2. `git ls-remote github refs/heads/dev` shows that SHA.
3. `gh api repos/BlkLeg/CircuitBreaker/commits/<sha>/status --jq '.statuses[] | select(.context=="gitlab/verify") | .state'` prints `success`.
4. GitHub `Publish dev image` ran on that SHA, and its `gate` job passed.
5. `ghcr.io/blkleg/circuitbreaker:dev-<short sha>` exists.
6. A direct push to GitHub is refused:
   `git push git@github.com:BlkLeg/CircuitBreaker.git HEAD:refs/heads/dev` is rejected by the ruleset.

All six are the cutover's exit criterion. Post the result in #maintainer and
update `plans/README.md`'s row for this plan to **Complete**, with the
acceptance SHA.

### Rollback

It is available until Step 8 passes, and afterwards while nothing new has merged
on GitLab.

1. GitHub rulesets: restore the 21 required checks from
   `specs/1.0.0/evidence/gov-15-branch-protection-enabled.md` §4, and remove the
   deploy-key-only restriction.
2. On GitHub, `git revert -m 1 <cutover merge on dev>` and the same on `main`, via
   PRs. The deleted workflows come back intact, because nothing was rewritten in place.
3. Set GitLab `PROMOTE_ENABLED` to `false`, and pause the three schedules.
4. Laptop remotes: reverse Step 7's renames.
5. Post in #maintainer. Record the reason in this plan under "Rollback log".

---

## Runner facts (recorded)

Task 1 Step 4 fills this in.

## Parity result

Task 7 Step 3 fills this in.
