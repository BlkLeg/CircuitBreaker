# Contributing to CircuitBreaker ⚡

First off, thank you for being part of the surge of interest in CircuitBreaker! Whether you’re reporting a bug, suggesting a feature, or submitting code, your help is what makes this project viable for the home lab community.

As we are currently in the **1.0.0 release-candidate** stage, we are prioritizing **stability, security, and performance** over new feature bloat.

---

## 🚀 Your First PR

New here? Follow these six steps in order — they're the difference between a
smooth first PR and losing an hour to something this file could have told you
up front.

1. Read [`README.md`](README.md) (what the product is) and
   [`docs/overview.md`](docs/overview.md) (what users do with it).
2. Read [`CLAUDE.md`](CLAUDE.md) (how this repo works — conventions, product
   principles) and [`docs/architecture.md`](docs/architecture.md) (the request
   path, process topology, and which files are still fatter than the
   "routes thin, services hold logic" rule wants).
3. Run `make install && make dev`. Open the UI and complete the first-run setup
   (OOBE) against your local Postgres.
4. Run `make lint`, then `make verify`, before your first push. See
   [Local Setup](#local-setup) below for the Go + `govulncheck` install
   commands `make verify`'s security scan needs — `make install` does not
   bootstrap them.
5. Don't start in `specs/1.0.0/slices/` unless your change is a release
   requirement. For an ordinary bugfix, the code plus a regression test is
   enough.
6. Never lower a coverage gate to make a build green. Never commit `.env`,
   `artifacts/`, or scan reports.

---

## 🛑 Before You Start

1. **Check the Issues:** Someone might already be working on your idea or bug.
2. **Give Us the Details:** Use the issue form (`.github/ISSUE_TEMPLATE/bug_report.yml`) and fill in the pull-request template (`.github/PULL_REQUEST_TEMPLATE.md`); GitHub offers both automatically. They ask for the same information listed under "How to Report Bugs" below.
3. **Start a Discussion:** For major architectural changes or new features, please open an Issue or raise it in [Discord](https://discord.gg/SBdBRfmD) before writing code.

---

## 🐛 How to Report Bugs

If you find a bug, please help us squash it by opening an **Issue**. To get it fixed quickly, include:

* A clear, descriptive title.
* Steps to reproduce the behavior.
* Your environment (OS, Docker version, hardware architecture).
* Relevant logs (remove any sensitive data like internal IPs or API keys first!).

---

## 🛠️ Development Workflow

Branch off of `dev`, and open your pull request against `dev` — never target `main`.

1. **Fork** the repository and clone it locally.
2. **Branch:** Create a branch for your fix/feature off of the `dev` branch.

* *Example:* `git checkout -b feature/improved-ui-scaling` or `git checkout -b fix/memory-leak`.

3. **Develop:** Ensure your code follows our style guides (see below).
4. **Test:** If you’re adding a feature, please include tests. We aim for "it works on my machine" to actually be true for everyone.
5. **Submit:** Open a Pull Request (PR) against the **`dev`** branch. **Do not target `main`.**

### Local Setup

```bash
make install   # once: creates .venv, installs the backend editable, runs npm install for the frontend
make dev       # backend + frontend + monitor workers + Dockerized Postgres/Redis/NATS
make lint      # ruff + mypy on the backend, eslint on the frontend
```

| Command | What actually runs |
|---|---|
| `make test` | `make test-backend` + `make test-frontend` |
| `make test-backend` | **only** `tests/integration/` (`pytest ../../tests/integration`), against a live PostgreSQL — **not** the ~310-file `apps/backend/tests` suite |
| `make test-frontend` | frontend Vitest (`npm test` in `apps/frontend`) |
| `make verify` | Tier 0 + Tier 1 with `CB_VERIFY_BACKEND=off` — the pre-push gate (measured 3m17s) |
| `make verify-full` | Tier 0 + Tier 1 with `CB_VERIFY_BACKEND=shards` — includes the backend suite (measured 6m43s) |

**`make test-backend` does not run the backend unit suite.** If you touched code
under `apps/backend/src/app`, run `make verify-full` (or let CI's sharded gate run
it) before assuming your change is covered.

`make install` installs the frontend deps under `apps/frontend`. Run `npm install` once at the repo
root as well — its `prepare` script installs the husky pre-commit hook (`npx lint-staged
--concurrent false`). There are two lint-staged configs, and lint-staged v16 groups each staged
file to its *nearest* one: `apps/frontend/package.json`'s `*.{ts,tsx,js,jsx,mjs,cjs}` glob owns
every staged frontend file — JS/JSX and TS alike — running `eslint --fix` and `prettier --write`
on it. The root `package.json`'s `*.{js,jsx,py}` glob runs `make lint`, but today it is reached
only by staged `.py` files: this repo has no root-level `.js`/`.jsx` file for its `js,jsx` half to
match (`git ls-files '*.js' '*.jsx' | grep -v '^apps/'` is empty), and it stays as a harmless
safety net in case one ever appears. The frontend is JavaScript/JSX — do not add `.ts`/`.tsx`
under `apps/frontend/src/`. (`vite.config.ts`, `vitest.config.ts`, and `playwright.config.ts` at the
`apps/frontend` package root, and the Playwright specs under `apps/frontend/e2e/`, are the
documented exceptions: real, intentionally-maintained TypeScript, linted by that same
`apps/frontend/package.json` config alongside the rest of the frontend.) `.pre-commit-config.yaml`
additionally pins `gitleaks protect --staged`, `ruff` (with `ruff-format`), and `mypy --strict` if
you also use `pre-commit`.

`make install` does **not** install Go. `.husky/pre-push` now runs `make verify`, which applies Tier 0 gates matching CI plus local Tier 1 (not yet in workflows; see design §4 for differences), and that gate's security scan calls `govulncheck` — it
fails closed if the tool is missing, so every push needs it. Install both before your first push:

```bash
sudo dnf install golang    # or your platform's equivalent
go install golang.org/x/vuln/cmd/govulncheck@v1.7.0
```

---

## 🧭 Where to Look

A short tour, in the order a request actually flows — not a reference. For the
full picture (process topology, the request path end to end, and which files
are still bigger than the rule below says they should be), read
[`docs/architecture.md`](docs/architecture.md).

* **Backend:** `apps/backend/src/app/api/` — thin route modules (parse,
  authorize, delegate, shape) — call into `apps/backend/src/app/services/`,
  where the actual logic lives. Both talk to
  `apps/backend/src/app/db/models/`, a package of 21 modules split by bounded
  context (`hardware.py`, `discovery.py`, `networks.py`, and so on) — it used
  to be one 3,000-line file, so don't be surprised it isn't a single module
  anymore.
* **Frontend:** `apps/frontend/src/pages/` holds the route-level page
  components. `apps/frontend/src/features/` is for anything large enough to
  need its own folder of components/hooks/model — `features/map/` is the one
  example today, and `pages/MapPage.jsx` is now just a 46-line shell that
  mounts it. Every API call goes through the single axios client at
  `apps/frontend/src/api/client.jsx` — new code should never add an inline
  `fetch` (a handful of existing ones are deliberate exceptions; see
  Coding Standards below).
* **Agent:** `apps/agent/cmd/cb-agent/` is the Go agent's entry point.

---

## 🔏 Code-Owner Review (the honest version)

A handful of paths require code-owner review before they can merge — see
[`.github/CODEOWNERS`](.github/CODEOWNERS). Today every one of them maps to a
single maintainer, `@blkleg`, not a team:

* The endpoint policy/inventory pair (`apps/backend/src/app/security/endpoint_policy.json`,
  `endpoint_inventory.json`, and the generator/test that keep them in sync) — the
  SEC-07 review for any change to the public-endpoint allowlist.
* Alembic migrations (`apps/backend/migrations/`) — a bad revision is
  unrecoverable on a customer database.
* Packaging (`packaging/`, `nfpm.yaml`, `PKGBUILD`) — what lands on an end
  user's machine.
* The agent wire protocol (`apps/agent/internal/frame/` and
  `apps/backend/src/app/schemas/agent_frame.py`) — the Go framing and the
  Python schema are one contract and must change together.
* The release workflow (`.github/workflows/release.yml`).

That isn't a team standing by — it's one person, so a PR that touches any of
the above will wait on that reviewer's availability rather than on whoever
else happens to be online. `.github/CODEOWNERS` says as much: the mapping
holds "until RC-3 assigns a narrower team/person." If your change can avoid
these paths, it will move faster; if it can't, budget for the wait rather than
being surprised by it.

---

## 🔒 Security Policy

As a project built for home servers, security is our top priority.
[`SECURITY.md`](SECURITY.md) is the authoritative policy — supported versions,
scope, and response targets live there, not here.

* **Do not report security vulnerabilities via public Issues.**
* Report privately through [GitHub Security Advisories](https://github.com/BlkLeg/CircuitBreaker/security/advisories/new)
  — the only reporting channel [`SECURITY.md`](SECURITY.md#reporting-a-vulnerability) documents.
* Response targets are in [`SECURITY.md`](SECURITY.md#what-to-expect).

---

## 📜 Coding Standards

* **Keep it Lean:** We target home labbers who might be running this on a Raspberry Pi or an old Optiplex. Efficiency matters.
* **Python:** Full type annotations everywhere — `mypy` runs with
  `disallow_untyped_defs`, so an untyped `def` fails CI, not just review.
  Docstrings on classes and public functions. Routes stay thin — parse,
  authorize, delegate, shape — and services hold the logic (see "Where to
  Look" above). Get a DB session via `Depends(get_db)`,
  never by constructing one yourself. Catch specific exceptions, not bare
  `except Exception`, and log through `logger` (never `print()`) with a
  `[module_name]` prefix, e.g. `logger.warning("[telemetry_cache] Redis
  unavailable for hw:%s: %s", hardware_id, exc)`.
* **Frontend:** All HTTP to *this application's own API* goes through the
  axios client in `apps/frontend/src/api/client.jsx` — no inline `fetch`. It
  owns request IDs, auth, CSRF, and retries; a bare `fetch` to our own API
  silently opts out of all of that. A handful of bare `fetch` calls already
  exist in `apps/frontend/src` and are deliberate, not bugs: calls to a
  third-party or other-origin URL (geocoding/weather, downloading a
  reverse-proxy TLS cert), one static-asset load, and one pre-auth liveness
  probe that has to keep working while the server itself is down. Don't
  "fix" one of these on sight — if you're unsure whether a bare `fetch` you
  find is one of them, `docs/architecture.md` names every call site. Always
  render a loading state and an error state — never assume the happy path
  is the only path.
* **Secrets:** Never hardcode credentials, tokens, signing material, JWT
  secrets, or vault keys — and that includes CI workflows, tests, examples,
  and fixtures, not just application code. Generate ephemeral values at
  runtime or inject them through the platform's secret store.
* **Backward-compatible migrations:** Self-hosters upgrade on their own
  schedule, and a half-updated deployment must keep working. Migrations use
  `ADD COLUMN IF NOT EXISTS`; add fields alongside old ones instead of
  renaming or dropping them.
* **Documentation:** If you add a feature, update the `README.md` or internal docs.
* **Commits:** Prefix with `feat:` / `fix:` / `chore:` / `docs:` and write a
  descriptive summary (e.g., `fix: resolve auth-loop in Firefox` instead of
  `fixed stuff`).
* **Generated output:** Never commit `make verify`/`make test` output or the artifacts they write —
  `artifacts/`, `apps/frontend/coverage/`, and `.coverage` are gitignored and must stay that way.

---

## ⚖️ License

By contributing, you agree that your contributions will be licensed under the project's MIT License.

---
