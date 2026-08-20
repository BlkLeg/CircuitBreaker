# Contributing to CircuitBreaker ⚡

First off, thank you for being part of the surge of interest in CircuitBreaker! Whether you’re reporting a bug, suggesting a feature, or submitting code, your help is what makes this project viable for the home lab community.

As we are currently in the **1.0.0 release-candidate** stage, we are prioritizing **stability, security, and performance** over new feature bloat.

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

We use a **Git Flow**-inspired branching model.

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
make test      # backend integration suite + frontend tests
```

`make install` installs the frontend deps under `apps/frontend`. Run `npm install` once at the repo
root as well — its `prepare` script installs the husky pre-commit hook, which runs `make lint` on
staged `.ts`, `.tsx`, and `.py` files. `.pre-commit-config.yaml` additionally pins
`gitleaks protect --staged`, `ruff` (with `ruff-format`), and `mypy --strict` if you also use
`pre-commit`.

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
* **Documentation:** If you add a feature, update the `README.md` or internal docs.
* **Commits:** Use descriptive commit messages (e.g., `fix: resolve auth-loop in Firefox` instead of `fixed stuff`).

---

## ⚖️ License

By contributing, you agree that your contributions will be licensed under the project's MIT License.

---
