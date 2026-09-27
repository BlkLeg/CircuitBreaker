"""The status checks the `Main-Branch` and `Dev-Branch` rulesets require.

The single copy of the list. Both rulesets require the same 21 names (see
specs/1.0.0/evidence/gov-15-branch-protection-enabled.md, section 4); the
rulesets themselves live in GitHub settings, not in this repository, so this
module is the in-repo statement of them that tests check the workflows
against. Change it in the same commit as the ruleset.
"""

from __future__ import annotations

REQUIRED_CHECKS: tuple[str, ...] = (
    "Lint",
    "Security Gate",
    "Backend tests (shard 1/4)",
    "Backend tests (shard 2/4)",
    "Backend tests (shard 3/4)",
    "Backend tests (shard 4/4)",
    "Backend coverage gate",
    "Fresh-install migrations",
    "Test",
    "Security Suppression Metadata",
    "Trivy Filesystem Scan",
    "Trivy Config / IaC Scan",
    "Semgrep (SAST)",
    "Bandit (Python SAST)",
    "Gitleaks (Secret Scanning)",
    "Checkov (GitHub Actions / IaC)",
    "Python Dependency Audit",
    "Frontend Dependency Audit",
    "Go Vulnerability Scan",
    "Analyze (Python)",
    "Analyze (JavaScript / TypeScript)",
)
