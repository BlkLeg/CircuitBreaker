# 1. CODE_OF_CONDUCT.md

I’ve used the **Contributor Covenant v2.1**, which is the industry standard. It’s fair, firm, and protects both you and your contributors.

```markdown
# Contributor Covenant Code of Conduct

## Our Pledge
We as members, contributors, and leaders pledge to make participation in our community a harassment-free experience for everyone, regardless of age, body size, visible or invisible disability, ethnicity, sex characteristics, gender identity and expression, level of experience, education, socio-economic status, nationality, personal appearance, race, caste, color, religion, or sexual identity and orientation.

## Our Standards
Examples of behavior that contributes to a positive environment include:
* Using welcoming and inclusive language
* Being respectful of differing viewpoints and experiences
* Gracefully accepting constructive criticism
* Focusing on what is best for the community
* Showing empathy towards other community members

Examples of unacceptable behavior include:
* The use of sexualized language or imagery and unwelcome sexual attention or advances
* Trolling, insulting/derogatory comments, and personal or political attacks
* Public or private harassment
* Publishing others' private information without explicit permission
* Other conduct which could reasonably be considered inappropriate in a professional setting

## Enforcement Responsibilities
The project maintainer(s) are responsible for clarifying and enforcing our standards of acceptable behavior and will take appropriate and fair corrective action in response to any behavior that they deem inappropriate, threatening, offensive, or harmful.

## Scope
This Code of Conduct applies within all project spaces, and also applies when an individual is officially representing the project in public spaces.

## Enforcement
Instances of abusive, harassing, or otherwise unacceptable behavior may be reported by contacting the project team at [INSERT EMAIL]. All complaints will be reviewed and investigated promptly and fairly.

```

---

## 2. ISSUE_TEMPLATE.md

For a home lab project like **CircuitBreaker**, you need to know the hardware and environment immediately. Are they on a Pi? A Proxmox VM? An old laptop? This template forces them to tell you.

*Note: Save this as `.github/ISSUE_TEMPLATE/bug_report.md*`

```markdown
---
name: 🐛 Bug Report
about: Create a report to help us improve CircuitBreaker
title: '[BUG] '
labels: bug
assignees: ''

---

## 📝 Description
A clear and concise description of what the bug is.

## 🚀 Steps to Reproduce
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## 💻 Environment Information
* **OS:** (e.g. Ubuntu 22.04, Debian, Windows 11)
* **Hardware:** (e.g. Raspberry Pi 4, Proxmox VM, Intel NUC)
* **Docker Version:** (e.g. 24.0.5)
* **Browser:** (e.g. Firefox, Chrome)
* **CircuitBreaker Version:** (e.g. v0.1.0-beta)

## 📋 Relevant Logs
Please paste your `docker logs circuitbreaker` output here. **Remove any sensitive data (Passwords, API Keys, Public IPs) first.**

```text
[PASTE LOGS HERE]

```

## 🖼️ Screenshots

If applicable, add screenshots to help explain your problem.

## 🎯 Expected Behavior

A clear and concise description of what you expected to happen.

## 🛑 Additional Context

Add any other context about the problem here (e.g., using a reverse proxy like Nginx or Traefik, using Authentik for SSO, etc.).

```text
[PASTE LOGS HERE]
---
