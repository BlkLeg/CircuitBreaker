# Contributing to CircuitBreaker ⚡

First off, thank you for being part of the surge of interest in CircuitBreaker! Whether you’re reporting a bug, suggesting a feature, or submitting code, your help is what makes this project viable for the home lab community.

As we are currently in **Beta**, we are prioritizing **stability, security, and performance** over new feature bloat.

---

## 🛑 Before You Start

1. **Check the Issues:** Someone might already be working on your idea or bug.
2. **Use the Templates:** Please use the provided Issue and Pull Request templates. It saves us both time.
3. **Start a Discussion:** For major architectural changes or new features, please start a thread in [GitHub Discussions] before writing code.

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
2. **Branch:** Create a branch for your fix/feature off of the `develop` branch.

* *Example:* `git checkout -b feature/improved-ui-scaling` or `git checkout -b fix/memory-leak`.

3. **Develop:** Ensure your code follows our style guides (see below).
4. **Test:** If you’re adding a feature, please include tests. We aim for "it works on my machine" to actually be true for everyone.
5. **Submit:** Open a Pull Request (PR) against the **`develop`** branch. **Do not target `main`.**

---

## 🔒 Security Policy

As a project built for home servers, security is our top priority.

* **Do not report security vulnerabilities via public Issues.**
* Please email [Insert Your Secure Email/Method Here] to report vulnerabilities privately.
* We aim to acknowledge security reports within 24 hours.

---

## 📜 Coding Standards

* **Keep it Lean:** We target home labbers who might be running this on a Raspberry Pi or an old Optiplex. Efficiency matters.
* **Documentation:** If you add a feature, update the `README.md` or internal docs.
* **Commits:** Use descriptive commit messages (e.g., `fix: resolve auth-loop in Firefox` instead of `fixed stuff`).

---

## ⚖️ License

By contributing, you agree that your contributions will be licensed under the project's [MIT/GPL/Apache] License.

---
