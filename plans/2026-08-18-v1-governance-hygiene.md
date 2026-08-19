# Governance and Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public repository describe the product it actually ships — remove tracked junk and user data, add the missing governance files, close the npm question with a decision, and document the agent, which currently ships with no user documentation at all.

**Architecture:** Deletions are paired with a tracked-file policy test so the junk cannot come back (GOV-12 requires exactly this). The npm decision becomes an ADR, which is what closes fifteen requirements without writing a package. Documentation gaps are filled from what the code actually does, verified against the source rather than written from memory.

**Tech Stack:** Git, Python 3.12 + pytest, MkDocs, GitHub Actions, `lychee` link checker.

**Spec:** `specs/1.0.0/07-documentation-repository-governance.md` (GOV-01, GOV-06, GOV-07, GOV-08, GOV-10, GOV-11, GOV-12, GOV-14, GOV-16), `specs/1.0.0/08-npm-distribution.md` (NPM-01 through NPM-15)

## Global Constraints

- License is MIT. Every manifest, `LICENSE`, and package metadata must agree (GOV-11).
- `VERSION` is the sole hand-edited version (GOV-09). Nothing in this plan may add another hand-edited copy.
- Security contact must be real and monitored — do not invent an address. If none exists, use GitHub private vulnerability reporting, which needs no new mailbox.
- Removing tracked files does not remove them from history. Anything credential-shaped needs a rotation decision, not just a `git rm`.
- `docs/` is canonical; `site/` is generated output (GOV-08).

---

### Task 1: Remove tracked junk and user data, and keep it out

`git ls-files` currently tracks: `-H` (0 bytes) and `=1.9.0` (0 bytes), both shell-quoting accidents; `-d` (169 bytes), a captured nginx `301 Moved Permanently` page from a stray `curl -d`; **44 files** of generated MkDocs output under `site/`; **24 user profile images** under `apps/backend/data/uploads/profiles/`; and `apps/agent/e2e/.env`, which holds test-only credentials.

**Files:**
- Delete: `-H`, `-d`, `=1.9.0`, `site/**`, `apps/backend/data/uploads/profiles/**`
- Modify: `.gitignore`
- Create: `tests/build/test_tracked_file_policy.py`

**Interfaces:**
- Produces: `tracked_files() -> list[str]` (a `git ls-files` wrapper) used by the policy test.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_tracked_file_policy.py
"""GOV-12: a tracked-file policy test that prevents recurrence.

Removing the junk once is not the requirement — the requirement is that it
cannot come back. Each rule below corresponds to something that was actually
found tracked in this repository, not a hypothetical.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_no_shell_quoting_accidents_are_tracked():
    """Files literally named for a curl/shell flag: -H, -d, =1.9.0."""
    offenders = [f for f in tracked_files() if re.fullmatch(r"-{1,2}[A-Za-z]|=.+", Path(f).name)]
    assert not offenders, f"shell-quoting accidents tracked: {offenders}"


def test_generated_site_output_is_not_tracked():
    """GOV-08: docs/ is canonical; site/ is MkDocs build output."""
    offenders = [f for f in tracked_files() if f.startswith("site/")]
    assert not offenders, f"{len(offenders)} generated site/ files tracked"


def test_no_user_uploads_are_tracked():
    """Profile images are user data, not source."""
    offenders = [f for f in tracked_files() if "data/uploads/" in f]
    assert not offenders, f"user uploads tracked: {offenders[:5]}"


def test_no_env_files_are_tracked():
    """Even documented test-only credentials belong in a template, not a .env."""
    offenders = [f for f in tracked_files() if Path(f).name == ".env"]
    assert not offenders, f".env files tracked: {offenders}"


def test_no_ide_or_tool_output_is_tracked():
    patterns = (".idea/", "eslint_output.json", ".DS_Store")
    offenders = [f for f in tracked_files() if any(p in f for p in patterns)]
    assert not offenders, f"IDE/tool output tracked: {offenders}"


def test_root_npm_manifest_stays_private():
    """NPM-02: the repository root must never be publishable."""
    import json

    manifest = json.loads((ROOT / "package.json").read_text())
    assert manifest.get("private") is True, "root package.json must remain private"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/build/test_tracked_file_policy.py -v`
Expected: FAIL on the first five tests (junk, site/, uploads, .env, and possibly IDE output)

- [ ] **Step 3: Decide the `.env` credential question before deleting anything**

The tracked `apps/agent/e2e/.env` documents itself as test-only, but it contains `CB_DB_PASSWORD`, `CB_VAULT_KEY`, `CB_JWT_SECRET` and `NATS_AUTH_TOKEN`. `git rm` does not remove them from history.

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
git log --oneline -- apps/agent/e2e/.env | tail -5
grep -c . apps/agent/e2e/.env
```

Confirm from the harness that these values are used **only** by `apps/agent/e2e/docker-compose.yml` and reach no deployed environment:

```bash
grep -rn "CB_VAULT_KEY\|NATS_AUTH_TOKEN" apps/agent/e2e/ deploy/ docker/ --include="*.yml" --include="*.sh" | head
```

If any value is shared with a real deployment template, **rotate it first** and record that in the commit. If they are genuinely harness-local, converting the file to a tracked `.env.example` and gitignoring the real one is sufficient — note the decision in the commit message either way.

- [ ] **Step 4: Remove the junk**

```bash
cd /home/shawnji/projects/CircuitBreaker
git rm --cached -- "-H" "-d" "=1.9.0"
rm -f -- "-H" "-d" "=1.9.0"
git rm -r --cached site/
git rm -r --cached apps/backend/data/uploads/profiles/
git mv apps/agent/e2e/.env apps/agent/e2e/.env.example
```

- [ ] **Step 5: Prevent recurrence in `.gitignore`**

Append to the repo-root `.gitignore`:

```gitignore
# GOV-08: MkDocs build output. docs/ is canonical; site/ is generated.
/site/

# GOV-12: user-uploaded content is runtime data, never source.
apps/backend/data/uploads/

# GOV-12: real env files. Templates are tracked as *.env.example.
.env
**/.env

# GOV-12: shell-quoting accidents that have been committed before
/-H
/-d
/=*

# IDE and tool output
.idea/
eslint_output.json
```

- [ ] **Step 6: Verify the policy test passes**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python -m pytest tests/build/test_tracked_file_policy.py -v
git status --short | head -20
```
Expected: 6 passed; `git status` shows the deletions staged and no newly untracked junk.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore(repo): remove tracked junk and user data, enforce a tracked-file policy (GOV-12)

Removed: -H, -d and =1.9.0 (shell-quoting accidents; -d was a captured nginx
301 page), 44 files of generated site/ output, 24 user profile images under
data/uploads, and the agent e2e .env (now .env.example). A policy test
asserts each of these categories stays untracked, since GOV-12 asks for
prevention of recurrence rather than a one-time cleanup."
```

---

### Task 2: Add the missing governance files

GOV-11 requires a root `SECURITY.md` with a real, monitored contact; there is none at the root or in `.github/`. GOV-16 requires standard issue and PR template paths; `.github/CODEOWNERS` exists but `.github/ISSUE_TEMPLATE/` and a PR template do not. GOV-10 requires removing contradictory package identity; `apps/backend/pyproject.toml:232-236` still carries a `[tool.poetry]` block declaring `version = "0.2.0"` and `authors = ["Admin <admin@example.com>"]` alongside the correct `[tool.hatch.version]` block at `:120-124` that reads the root `VERSION`.

**Files:**
- Create: `SECURITY.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Modify: `apps/backend/pyproject.toml:232-236`
- Modify: `package.json` (root `test` script)
- Test: `tests/build/test_repo_governance.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_repo_governance.py
"""GOV-10, GOV-11, GOV-14, GOV-16: the repository's governance surface."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_root_security_policy_exists():
    """GOV-11: GitHub only surfaces SECURITY.md from the root, .github/ or docs/."""
    assert (ROOT / "SECURITY.md").exists(), "GOV-11 requires a root SECURITY.md"


def test_security_policy_names_a_real_reporting_channel():
    text = (ROOT / "SECURITY.md").read_text()
    assert "security/advisories" in text or "@" in text, "no reporting channel named"
    assert "example.com" not in text, "placeholder contact in SECURITY.md"


def test_issue_and_pr_templates_are_at_paths_github_recognises():
    assert (ROOT / ".github" / "ISSUE_TEMPLATE").is_dir()
    assert any((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
    assert (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").exists()


def test_backend_has_no_contradictory_poetry_version():
    """GOV-10: VERSION is canonical; a stale [tool.poetry] version contradicts it."""
    data = tomllib.loads((ROOT / "apps" / "backend" / "pyproject.toml").read_text())
    poetry = data.get("tool", {}).get("poetry", {})
    assert "version" not in poetry, "stale [tool.poetry] version contradicts VERSION"
    assert "authors" not in poetry, "placeholder [tool.poetry] authors remain"


def test_backend_version_still_derives_from_the_version_file():
    data = tomllib.loads((ROOT / "apps" / "backend" / "pyproject.toml").read_text())
    assert data["tool"]["hatch"]["version"]["path"] == "../../VERSION"


def test_root_npm_test_does_not_fail_by_design():
    """GOV-14: a documented root command must not exit 1 on purpose."""
    scripts = json.loads((ROOT / "package.json").read_text())["scripts"]
    assert "exit 1" not in scripts.get("test", ""), "root npm test still fails by design"


def test_license_metadata_agrees():
    """GOV-11: LICENSE and every manifest must say the same thing."""
    assert "MIT" in (ROOT / "LICENSE").read_text()
    assert json.loads((ROOT / "package.json").read_text())["license"] == "MIT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/build/test_repo_governance.py -v`
Expected: FAIL on `SECURITY.md`, templates, the poetry block, and the root `npm test`

- [ ] **Step 3: Write `SECURITY.md`**

```markdown
# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | ✅ Security fixes |
| < 1.0 | ❌ Pre-release; upgrade to 1.0.x |

The full support boundary — platforms, architectures, deployment modes and
browsers — is in the [1.0.0 support contract](docs/release/1.0.0-support-contract.md).

## Reporting a vulnerability

Report privately through GitHub:
**[Security → Report a vulnerability](https://github.com/blkleg/CircuitBreaker/security/advisories/new)**

Please do not open a public issue for a security report.

Include where practical: affected version and deployment mode (native, mono
container, split Compose), reproduction steps, impact, and whether the issue
is reachable without authentication.

## What to expect

| Stage | Target |
|---|---|
| Acknowledgement | 3 business days |
| Initial assessment | 10 business days |
| Fix or mitigation plan for a confirmed high-impact issue | 30 days |

We will credit reporters in the release notes unless you ask us not to.

## Scope

In scope: the server (API, workers, web UI), `cb-agent`, the installers and
packaging, and the published container images.

Out of scope: findings that require an already-compromised host or database;
denial of service by resource exhaustion on a self-hosted deployment the
reporter controls; missing hardening headers with no demonstrated impact.

## Verifying releases

Release artifacts are checksummed, GPG-signed, and shipped with SBOMs;
container images are signed with cosign. Verification steps are in
[security verification](docs/installation/security-verification.md).
```

Verify the advisory URL resolves before committing:

Run: `curl -sfI https://github.com/blkleg/CircuitBreaker/security/advisories/new >/dev/null && echo "advisory URL ok" || echo "CHECK the repo slug in SECURITY.md"`

- [ ] **Step 4: Add the issue and PR templates**

```yaml
# .github/ISSUE_TEMPLATE/bug_report.yml
name: Bug report
description: Something does not work as documented
labels: ["bug"]
body:
  - type: input
    id: version
    attributes:
      label: Version
      description: Output of `cb version`
    validations:
      required: true
  - type: dropdown
    id: install-mode
    attributes:
      label: Install mode
      options:
        - Native (systemd)
        - Mono container
        - Split Docker Compose
        - Proxmox LXC helper
    validations:
      required: true
  - type: input
    id: platform
    attributes:
      label: OS and architecture
      placeholder: "Ubuntu 24.04, arm64"
    validations:
      required: true
  - type: textarea
    id: what-happened
    attributes:
      label: What happened
      description: What you expected, what happened instead, and how to reproduce it.
    validations:
      required: true
  - type: textarea
    id: diagnostics
    attributes:
      label: Diagnostics
      description: "Output of `cb doctor`. Redact secrets before pasting."
      render: shell
```

```yaml
# .github/ISSUE_TEMPLATE/config.yml
blank_issues_enabled: false
contact_links:
  - name: Security vulnerability
    url: https://github.com/blkleg/CircuitBreaker/security/advisories/new
    about: Report privately. Please do not open a public issue.
```

```markdown
<!-- .github/PULL_REQUEST_TEMPLATE.md -->
## What this changes

<!-- One or two sentences. -->

## Why

<!-- The problem this solves. Link the issue if there is one. -->

## Release requirements touched

<!-- Any RC-/SEC-/AGT-/SRV-/ACC-/REL-/GOV-/NPM-/EXEC- IDs from specs/1.0.0/.
     Per the change-control rule in 09-release-execution.md, a change after a
     requirement passes must re-run its evidence or record why it still holds.
     Write "none" if this touches no tested surface. -->

## Verification

- [ ] Tests added or updated for the behaviour changed
- [ ] `cd apps/backend && python -m pytest` passes
- [ ] `cd apps/frontend && npm test` passes
- [ ] Docs updated if user-facing behaviour changed
```

- [ ] **Step 5: Remove the contradictory Poetry metadata and fix the root test script**

```bash
cd /home/shawnji/projects/CircuitBreaker
sed -n '230,240p' apps/backend/pyproject.toml
```

Confirm what `[tool.poetry]` still carries, then reduce it to only what `poetry.lock` generation actually needs — `package-mode = false` — deleting the contradictory `version`, `authors`, `name` and `description`:

```toml
[tool.poetry]
# Retained only so `poetry lock` can regenerate poetry.lock, which
# scripts/gen_requirements.py reads. GOV-10: the version and authors that used
# to sit here said 0.2.0 and admin@example.com, contradicting the root VERSION
# file and the real project metadata in [project] above.
package-mode = false
```

Then make the root `test` script do something useful (GOV-14):

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("package.json")
d = json.loads(p.read_text())
d["scripts"]["test"] = "npm --prefix apps/frontend test"
p.write_text(json.dumps(d, indent=2) + "\n")
print(d["scripts"])
PY
```

- [ ] **Step 6: Verify everything**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python -m pytest tests/build/test_repo_governance.py -v
python -c "import tomllib; d=tomllib.load(open('apps/backend/pyproject.toml','rb')); print('hatch version path:', d['tool']['hatch']['version']['path'])"
cd apps/backend && python -c "import app; print('backend imports fine')" 2>/dev/null || echo "check backend import after pyproject edit"
```
Expected: 7 passed; hatch version path `../../VERSION`; backend still imports.

- [ ] **Step 7: Commit**

```bash
git add SECURITY.md .github/ISSUE_TEMPLATE/ .github/PULL_REQUEST_TEMPLATE.md \
        apps/backend/pyproject.toml package.json tests/build/test_repo_governance.py
git commit -m "chore(repo): add SECURITY.md and templates, drop contradictory metadata

GOV-11: there was no root SECURITY.md at all. GOV-16: CODEOWNERS existed but
no issue or PR templates. GOV-10: [tool.poetry] still declared version 0.2.0
and admin@example.com beside the hatch block that correctly reads VERSION.
GOV-14: root npm test exited 1 by design and now runs the frontend suite."
```

---

### Task 3: Close the npm question with an ADR

NPM-01 requires a documented decision on whether npm is a supported 1.0 channel. No package exists, no publish workflow exists, and the root manifest is correctly `private: true`. Fifteen requirements are open on a decision nobody has written down. The decision is: **out of scope for 1.0.**

**Files:**
- Create: `docs/adr/0004-npm-out-of-scope-for-1.0.md`
- Modify: `specs/1.0.0/release-control/exception-register.csv`
- Modify: `specs/1.0.0/release-control/requirement-ledger.csv`

- [ ] **Step 1: Read the existing ADR format so the new one matches**

Run: `cat docs/adr/0003-defer-true-multi-tenancy.md`

- [ ] **Step 2: Write the ADR**

```markdown
# ADR 0004: npm is not a supported distribution channel for 1.0

**Status:** Accepted
**Date:** 2026-08-18
**Requirements:** NPM-01 through NPM-15, RC-03, EXEC-06
**Supersedes:** nothing

## Context

`specs/1.0.0/08-npm-distribution.md` treats npm as a conditional channel: "If
npm is a supported 1.0 channel...". Fifteen requirements sit behind that
condition, and nobody has recorded an answer.

The tree gives no evidence npm was ever started. There is no `@blkleg/*`
package, no publish workflow, and the root `package.json` is `private: true`.
`apps/frontend/package.json` is a workspace manifest for the bundled UI, not a
publishable artifact.

The channels that do exist and are tested are: native systemd packages
(deb/rpm/apk/Arch/AppImage/tar for amd64 and arm64), the mono container, and
split Docker Compose. Each has signing, checksums, SBOMs and an installation
gate. Adding npm would mean a new package identity, a registry namespace with
its own MFA and access review, trusted publishing via OIDC, cross-platform
tarball smoke tests on Linux/macOS/Windows, and a compromise-and-revocation
procedure — NPM-12 through NPM-15 — for a channel with no current users.

## Decision

npm is **not** a supported distribution channel for Circuit Breaker 1.0.

1. The root repository manifest stays `private: true`, and a test asserts it
   (`tests/build/test_tracked_file_policy.py`).
2. No package is published to npmjs under any name for 1.0.
3. NPM-01 through NPM-15 are recorded as **not applicable** for 1.0 under
   exception `EXC-002`, not as unmet requirements.
4. Documentation names native, mono and split Compose as the only supported
   installation methods, and does not present `npm`/`npx` examples.

## Consequences

**Positive.** Fifteen release requirements close without writing a package.
The supply-chain surface stays at three governed channels. No namespace to
defend, no registry access review, no publish credential to rotate.

**Negative.** Users who expect a `npx @blkleg/circuitbreaker` installer do not
get one; `install.sh` is the equivalent entry point and is documented as such.

**Revisiting.** If npm becomes desirable post-1.0, `08-npm-distribution.md`
already specifies it. NPM-01's first question — installer CLI or SDK — must be
answered before any implementation, and the SDK path (NPM-04) would need the
API contract stability that RC-03 currently does not promise.

## Alternatives considered

**Publish an installer CLI now.** Rejected: a wrapper that downloads and
verifies signed artifacts duplicates `install.sh` while adding a registry
account, a publish credential and three new platform test matrices to the
release gate.

**Reserve the namespace without publishing.** Rejected as insufficient on its
own — NPM-12 asks for MFA, two maintainers and periodic access review, which is
ongoing governance for an unused name. Worth doing as squatting defence, but it
is not a release requirement and does not change this decision.

**Leave the decision open.** Rejected: NPM-01 blocks EXEC-06, so an open
question is indistinguishable from an unmet requirement at the release gate.
```

- [ ] **Step 3: Record the exception**

Inspect the register's columns, then append the row:

```bash
cd /home/shawnji/projects/CircuitBreaker
head -1 specs/1.0.0/release-control/exception-register.csv
cat specs/1.0.0/release-control/exception-register.csv
```

Add `EXC-002` following the exact column order the header shows, with: the covered requirement IDs `NPM-01..NPM-15`, owner `shawnji (release)`, rationale pointing at ADR-0004, compensating control "npm is not published; root manifest is private and asserted by test", and no expiry (the decision is permanent for the 1.0 line, not time-boxed).

- [ ] **Step 4: Update the ledger**

Set all fifteen `NPM-*` rows to `status=excepted`, `exception_id=EXC-002`, `evidence_url=docs/adr/0004-npm-out-of-scope-for-1.0.md`, `invalidation_state=current`:

```bash
python3 - <<'PY'
import csv
from pathlib import Path

path = Path("specs/1.0.0/release-control/requirement-ledger.csv")
rows = list(csv.DictReader(path.open()))
changed = 0
for row in rows:
    if row["requirement_id"].startswith("NPM-"):
        row["status"] = "excepted"
        row["exception_id"] = "EXC-002"
        row["evidence_url"] = "docs/adr/0004-npm-out-of-scope-for-1.0.md"
        row["invalidation_state"] = "current"
        row["notes"] = "npm is not a 1.0 channel per ADR-0004; not applicable rather than unmet."
        changed += 1

with path.open("w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"updated {changed} NPM rows")
PY
```
Expected: `updated 15 NPM rows`

- [ ] **Step 5: Verify the ledger still validates**

Run: `python3 scripts/validate_v1_release_control.py`
Expected: `release-control validation ok: 145 ledger rows, 145 canonical IDs`

- [ ] **Step 6: Commit**

```bash
git add docs/adr/0004-npm-out-of-scope-for-1.0.md \
        specs/1.0.0/release-control/exception-register.csv \
        specs/1.0.0/release-control/requirement-ledger.csv
git commit -m "docs(adr): npm is not a supported 1.0 distribution channel (NPM-01)

Fifteen requirements sat behind an unanswered conditional. No package,
namespace or publish workflow was ever started, and the three channels that
do exist are signed, gated and tested. Recorded as EXC-002 — not applicable
rather than unmet."
```

---

### Task 4: Document cb-agent

`grep -rli "cb-agent" docs/*.md` matches exactly one file — the readiness audit itself. `mkdocs.yml`'s nav has no agent entry. A headline 1.0 component ships with no installation, security, permissions, outbound-endpoint, scope, update, uninstall or troubleshooting documentation. GOV-06 requires all of it.

**Files:**
- Create: `docs/agent.md`
- Modify: `mkdocs.yml` (nav)

- [ ] **Step 1: Gather the facts from the code, not from memory**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
echo "== agent commands =="; grep -rn "flag\.\|Command{" apps/agent/cmd/ 2>/dev/null | head -20
echo "== outbound endpoints =="; grep -rn "api/v1/agents" apps/agent/internal/ | head
echo "== service unit =="; find apps/agent packaging deploy -name "*.service" | head
echo "== enroll/link routes =="; grep -n "websocket\|api_route" apps/backend/src/app/api/ws_agents.py | head
echo "== scope enforcement =="; sed -n '1,40p' apps/backend/src/app/services/discovery_eligibility.py
```

Record: the exact CLI commands, the exact outbound URLs the agent dials, the systemd unit name and its sandboxing directives, and how network scope is enforced. **Every claim in the page must come from this step.**

- [ ] **Step 2: Write the page**

Create `docs/agent.md` covering, in this order, using only facts from Step 1:

1. **What it is** — an outbound-only agent giving the server a vantage point inside a remote network. No inbound firewall rule is needed.
2. **Install** — the exact command the UI's install flow generates, per supported platform and architecture.
3. **Enrollment** — pairing code, approval in the UI, what the server pins (TLS), and what happens if a code expires.
4. **What it can see** — network scope, how scope is granted and enforced, and the guarantee that disallowed scope is never scanned (AGT-08).
5. **Outbound endpoints** — every URL and port the agent dials, so an operator can allowlist them.
6. **Permissions** — the service user, the systemd sandboxing directives, and why each elevated capability is needed.
7. **Update and rollback** — how updates are dispatched, what a failed update does, how to roll back.
8. **Revoke and uninstall** — what revocation does server-side, what uninstall removes locally, and what is intentionally left behind.
9. **Troubleshooting** — a symptom→cause tree covering: agent shows offline, enrollment fails, TLS pin mismatch, clock skew, spool pressure, duplicate agent after a host clone.
10. **Recovery runbooks** (AGT-18) — lost server key, cloned machine ID, duplicate agent, hostname/IP change, expired pairing code, restored server.

Write item 10 as short numbered procedures. AGT-18 requires each to be exercised in a tabletop or automated scenario before it counts as evidence — the page is the prerequisite, not the proof.

- [ ] **Step 3: Add it to the nav**

In `mkdocs.yml`, add to the `Features` section after `Auto-Discovery (Beta)`:

```yaml
      - cb-agent: agent.md
```

- [ ] **Step 4: Verify the docs build and every link resolves**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python3 -m mkdocs build --strict 2>&1 | tail -20
```
Expected: builds with no warnings. `--strict` turns broken links and nav references into errors, which is the point.

- [ ] **Step 5: Verify against the code one more time**

Run:
```bash
grep -oE "https?://[^ )\"]+|:[0-9]{2,5}\b" docs/agent.md | sort -u
```
Cross-check every URL and port against Step 1's output. A troubleshooting page that names the wrong port costs more than no page at all.

- [ ] **Step 6: Commit**

```bash
git add docs/agent.md mkdocs.yml
git commit -m "docs: add cb-agent documentation (GOV-06, AGT-18)

The agent shipped with zero user documentation — the only match for 'cb-agent'
in docs/ was the readiness audit itself, and mkdocs nav had no agent entry.
Covers install, enrollment, scope, outbound endpoints, permissions, update,
revoke, uninstall, a troubleshooting tree and the six AGT-18 recovery
runbooks. Every claim was read out of the source rather than written from
memory."
```

---

### Task 5: Link checking in CI

GOV-01 requires every Markdown and media target to be protected by link checking. The tree is currently clean — a full walk of `docs/**/*.md` found zero broken local links — but nothing keeps it that way.

**Files:**
- Create: `.github/workflows/docs.yml`
- Create: `.lycheeignore`

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/docs.yml
name: Docs

# GOV-01: docs and README link targets are protected by link checking.
# GOV-08: the docs build must be reproducible from docs/ alone.
on:
  push:
    branches: [main, dev]
  pull_request:
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "README.md"
      - ".github/workflows/docs.yml"

permissions:
  contents: read

jobs:
  build:
    name: Build docs (strict)
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install MkDocs
        run: pip install mkdocs mkdocs-material

      # --strict turns a broken nav reference or missing page into a failure
      # rather than a warning nobody reads.
      - name: Build
        run: mkdocs build --strict

  links:
    name: Link check
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - name: Check links
        uses: lycheeverse/lychee-action@v2
        with:
          # Local links fail the build. External links are checked but their
          # failures are reported without blocking a PR on someone else's
          # server being briefly down.
          args: >-
            --no-progress
            --include-fragments
            --exclude-loopback
            'docs/**/*.md'
            'README.md'
            'SECURITY.md'
            'CONTRIBUTING.md'
          fail: true
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Add the ignore list**

```
# .lycheeignore
# Placeholders in documentation examples, not real targets.
^https?://example\.(com|test)
^https?://your-server
# Local development URLs that are not reachable from CI.
^https?://(localhost|127\.0\.0\.1)
```

- [ ] **Step 3: Verify locally**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python3 -m mkdocs build --strict 2>&1 | tail -10
docker run --rm -v "$(pwd):/input" -w /input lycheeverse/lychee:latest \
  --no-progress --offline 'docs/**/*.md' 'README.md' 'SECURITY.md' 2>&1 | tail -20
```
Expected: strict build succeeds; the offline link pass reports no broken local links. **Fix any it finds before committing** — the gate is worthless if it lands red.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/docs.yml .lycheeignore
git commit -m "ci(docs): add strict docs build and link checking (GOV-01, GOV-08)

The tree had no broken local links but nothing kept it that way, and a
non-strict mkdocs build turns a missing nav target into a warning nobody
reads."
```

---

### Task 6: Record screenshot provenance

GOV-02 requires each of the 16 restored historical screenshots to record source version, date and reviewer, with no environment secrets or personal data remaining. GOV-03 requires current media for install/OOBE, agent enrollment/fleet, discovery, backup/restore, mobile, empty/error and accessibility states — the directory still holds exactly the original 16, so none was added.

**Files:**
- Create: `docs/assets/screenshots/MANIFEST.md`

- [ ] **Step 1: List what exists and when it was added**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
for f in docs/assets/screenshots/*; do
  printf "%s\t%s\n" "$(basename "$f")" "$(git log -1 --format=%ad --date=short -- "$f")"
done
```

- [ ] **Step 2: Review each image before writing the manifest**

Open all 16. For each, confirm no hostname, IP, email address, real inventory name, token or personal data is legible. Anything found must be blurred or the asset dropped — GOV-02 requires this, and a manifest asserting a review that did not happen is worse than no manifest.

- [ ] **Step 3: Write the manifest**

```markdown
# Screenshot Manifest

GOV-02: every asset in this directory records its source version, capture date
and reviewer. GOV-03: gaps in required media are listed rather than left
implicit.

Reviewed by: shawnji · Review date: 2026-08-18

| Asset | Source version | Captured | Anonymised | Matches RC UI |
|---|---|---|---|---|
<!-- One row per file from Step 1. "Matches RC UI" is no until re-verified
     against the release candidate; do not mark yes without looking. -->

## Required media not yet captured (GOV-03)

These journeys have no current capture. Each blocks GOV-03 until added:

- [ ] Install and OOBE (first-admin creation, setup token)
- [ ] Agent enrollment and fleet view
- [ ] Discovery and import review
- [ ] Agent-vantage monitor creation
- [ ] Backup and restore
- [ ] Mobile layout
- [ ] Empty and error states
- [ ] Accessibility states (focus, keyboard navigation)

Once Plan 3's Playwright harness is in place, most of these can be captured by
automation rather than by hand — `e2e/visual.spec.ts` already renders several
of these surfaces deterministically.
```

Fill the table from Step 1's output, one row per file.

- [ ] **Step 4: Commit**

```bash
git add docs/assets/screenshots/MANIFEST.md
git commit -m "docs(media): record screenshot provenance and name the GOV-03 gaps

GOV-02 requires source version, date and reviewer per asset; GOV-03's required
journeys had no capture at all and were previously invisible. Every existing
asset was reviewed for hostnames, addresses and personal data before this
manifest asserted it."
```

---

### Task 7: Index the historical security reports

GOV-13 requires historical security reports and plans to be indexed with superseded material marked, so a reader can identify the current source of truth. `SECURITY_REPORTS/` holds nine documents dated between 2026-03 and 2026-06 with no index; `plans/` holds seventeen; several describe completed work in the present tense.

**Files:**
- Create: `SECURITY_REPORTS/README.md`
- Create: `plans/README.md`

- [ ] **Step 1: Inventory both directories with dates**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
for f in SECURITY_REPORTS/*.md plans/*.md; do
  printf "%s\t%s\t%s\n" "$f" "$(git log -1 --format=%ad --date=short -- "$f")" "$(head -1 "$f" | cut -c1-70)"
done | sort -k2
```

- [ ] **Step 2: Write both indexes**

`SECURITY_REPORTS/README.md`:

```markdown
# Security Reports — Index

**These are historical records, not the current source of truth.**

The current security posture is defined by:

- [`specs/1.0.0/02-security-and-trust.md`](../specs/1.0.0/02-security-and-trust.md) — the normative requirements
- [`specs/1.0.0/release-control/requirement-ledger.csv`](../specs/1.0.0/release-control/requirement-ledger.csv) — current status per requirement
- [`SECURITY.md`](../SECURITY.md) — reporting policy

A finding in this directory is closed only if the ledger says so. SEC-18
explicitly forbids treating historical reports as the current state.

| Report | Date | Status |
|---|---|---|
<!-- One row per file from Step 1. Status is Superseded, Historical, or Active. -->
```

`plans/README.md`:

```markdown
# Plans — Index

Implementation plans, newest first. A plan is a record of intent at its date;
it is not evidence that the work shipped. The requirement ledger is.

| Plan | Date | Status |
|---|---|---|
<!-- One row per file from Step 1. Status is Complete, Superseded, or Active. -->
```

Fill both tables from Step 1. For each entry, check whether the work landed before marking it Complete — `git log --oneline --grep` against the plan's subject is usually enough.

- [ ] **Step 3: Verify the docs build still passes**

Run: `python3 -m mkdocs build --strict 2>&1 | tail -5`
Expected: no new warnings. These two files sit outside `docs/` and are not in the nav, which is correct — they are repository records, not product documentation.

- [ ] **Step 4: Commit**

```bash
git add SECURITY_REPORTS/README.md plans/README.md
git commit -m "docs: index historical security reports and plans (GOV-13)

Nine security reports and seventeen plans sat unindexed, several describing
completed work in the present tense, with no way for a reader to tell which
was current. Both indexes point at the requirement ledger as the actual
source of truth."
```

---

### Task 8: Reconcile the ledger with what is now true

The audit found the ledger broadly honest but wrong in two places: RC-01/02/03 are marked `not_started` although drafts exist and are published in the MkDocs nav, and REL-14 is `not_started` although a coverage ratchet exists — one that sat *below* its own measured baseline. The other plans in this set also change ledger rows, and EXEC-09 requires the ledger to reconcile exactly at sign-off.

**Files:**
- Modify: `specs/1.0.0/release-control/requirement-ledger.csv`
- Modify: `specs/1.0.0/gap-audit-2026-08-18.md`

- [ ] **Step 1: Correct the two misstated rows**

Set RC-01, RC-02 and RC-03 to `in_progress` with `evidence_url` pointing at their published documents (`docs/release/1.0.0-support-contract.md`, `docs/adr/0001-1.0-support-boundary.md`, `docs/adr/0002-1.0-compatibility-and-service-objectives.md`) and a note recording that the documents are drafted and published but unapproved and unevidenced.

Set REL-14 to `in_progress` noting the ratchet exists at `apps/backend/pyproject.toml` and, before Plan 3 Task 6, sat below the measured baseline.

- [ ] **Step 2: Record the RC-02 contradiction as a risk, not a pass**

Until Plan 1 Task 3 ships, `docs/release/1.0.0-support-contract.md:40` claims arm64 for a container channel the pipeline builds amd64-only. Add a row to `specs/1.0.0/release-control/risk-register.csv` describing it, owned by the release owner, with the mitigation pointing at Plan 1 Task 3.

Inspect the register's columns first:

Run: `head -1 specs/1.0.0/release-control/risk-register.csv && cat specs/1.0.0/release-control/risk-register.csv`

- [ ] **Step 3: Correct the audit note**

`specs/1.0.0/gap-audit-2026-08-18.md` section B4 states the AGT-04 xfail names three unfixed bugs. All three were fixed in `4aab49d5` and `ad197961`, two hours after the xfail was written in `6903d6db`. Rewrite B4 to say the marker is stale rather than accurate, and note that the fixes predate it.

- [ ] **Step 4: Verify the ledger still validates**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python3 scripts/validate_v1_release_control.py
python3 -c "
import csv, collections
rows = list(csv.DictReader(open('specs/1.0.0/release-control/requirement-ledger.csv')))
print(collections.Counter(r['status'] for r in rows))
"
```
Expected: `release-control validation ok: 145 ledger rows, 145 canonical IDs`, and a status count showing 15 more `excepted` (from Task 3) and 4 more `in_progress`.

- [ ] **Step 5: Commit**

```bash
git add specs/1.0.0/release-control/ specs/1.0.0/gap-audit-2026-08-18.md
git commit -m "docs(release-control): reconcile the ledger and correct the audit

RC-01/02/03 were marked not_started although their documents are drafted and
published; REL-14 the same, although a ratchet existed — one set below its own
measured baseline. Records the arm64 container contradiction as a risk until
the pipeline actually builds it, and corrects the audit's claim that the
AGT-04 xfail named three unfixed bugs: all three were fixed two hours after
the marker was written."
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| GOV-01 (link checking) | 5 |
| GOV-02 (screenshot provenance and anonymisation) | 6 |
| GOV-03 (required media) | 6 — gaps named and assigned, capture itself follows Plan 3 |
| GOV-06 (agent security/permissions/outbound/scope/update/uninstall, troubleshooting) | 4 |
| GOV-08 (source canonical, no stale `site/`) | 1, 5 |
| GOV-10 (no contradictory package identity) | 2 |
| GOV-11 (SECURITY.md, real contact, license agreement) | 2 |
| GOV-12 (tracked-file policy preventing recurrence) | 1 |
| GOV-13 (index historical material) | 7 |
| GOV-14 (root commands useful) | 2 |
| GOV-16 (issue/PR templates) | 2 |
| NPM-01 – NPM-15 | 3 |
| AGT-18 (recovery runbooks published) | 4 — published here; tabletop exercise still required for evidence |

**Known gaps left open deliberately:** GOV-07's threat model, hardening guide, privacy statement and API reference are not written here — each is a substantial document, and GOV-06's agent page is the one whose absence actively harms users today. GOV-15 (branch protection evidence) needs repository settings screenshots, not code. GOV-19's provenance for native packages is tracked in Plan 1's self-review.

**Type consistency:** `tracked_files() -> list[str]` (Task 1) is used by every test in that file. `EXC-002` is written identically in the ADR (Task 3 Step 2), the exception register (Step 3) and the ledger rows (Step 4). Task 8 depends on Task 3 having already added the fifteen `excepted` rows — run them in order.
