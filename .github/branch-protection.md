# GitHub Branch Protection Settings

This document outlines the required branch protection rules for `main` and `dev` branches.

## Configuration for `main` and `dev` branches

Apply the following settings via GitHub Settings > Branch protection rules:

### Pull Request Requirements
- **Require a pull request before merging**: ✓ Enabled
  - Minimum 1 approving review required
  - Dismiss stale pull request approvals when new commits are pushed: ✓ Enabled

### Status Checks
- **Require status checks to pass before merging**: ✓ Enabled
  - Required status checks:
    - `test` — Test suite must pass
    - `lint` — Linting must pass
    - `trivy-scan` — Trivy security scan must pass (no CRITICAL/HIGH vulnerabilities)
  - **Require branches to be up to date before merging**: ✓ Enabled

### Administration
- **Enforce all above rules for administrators**: ✓ Enabled
  - Administrators are subject to the same restrictions

### Optional Recommendations
- Enable auto-delete of head branches after merge
- Require conversation resolution before merging (if using PR comments)

---

**Note**: These rules prevent direct pushes to `main` and `dev`. All changes must go through pull requests with at least one approval and passing security/quality checks.
