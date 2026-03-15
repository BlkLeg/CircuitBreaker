#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REPORT_FILE="security_scan_report.md"
echo "# Security Scan Report - $(date)" > "$REPORT_FILE"
echo "Running security scans... This may take a few minutes."

# Ensure .venv exists for Python tools
if [ ! -d .venv ]; then
    echo "Creating .venv for security tools..."
    python3 -m venv .venv
fi

echo "## 1. Bandit (Python SAST)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Bandit..."
if ! .venv/bin/bandit --version > /dev/null 2>&1; then
    .venv/bin/pip install bandit --quiet
fi
.venv/bin/bandit -r apps/backend/src/ -f txt >> "$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 2. Semgrep (SAST)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Semgrep..."
if ! .venv/bin/semgrep --version > /dev/null 2>&1; then
    .venv/bin/pip install semgrep --quiet
fi
.venv/bin/semgrep scan --config=p/default apps/backend/src/ apps/frontend/src/ docker/ >> "$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 3. Gitleaks (Secret Scanning)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Gitleaks..."
# Use .gitleaks.toml allowlist when present (e.g. to ignore Alembic revision IDs in migrations).
GITLEAKS_CONFIG=""
[ -f .gitleaks.toml ] && GITLEAKS_CONFIG="--config .gitleaks.toml"
if command -v gitleaks > /dev/null 2>&1; then
    gitleaks detect --no-git --source . $GITLEAKS_CONFIG --report-path /dev/stdout 2>&1 >> "$REPORT_FILE" || true
elif command -v docker > /dev/null 2>&1; then
    if [ -f .gitleaks.toml ]; then
        docker run --rm -v "$(pwd):/repo" ghcr.io/gitleaks/gitleaks:latest detect --source="/repo" --config="/repo/.gitleaks.toml" -v 2>&1 >> "$REPORT_FILE" || true
    else
        docker run --rm -v "$(pwd):/repo" ghcr.io/gitleaks/gitleaks:latest detect --source="/repo" -v 2>&1 >> "$REPORT_FILE" || true
    fi
else
    echo "gitleaks and Docker not found, skipping." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 4. ESLint + security (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running ESLint (includes eslint-plugin-security)..."
(cd apps/frontend && npm run lint) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 5. Hadolint (Dockerfile lint)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Hadolint..."
for f in Dockerfile docker/backend.Dockerfile docker/frontend.Dockerfile docker/Dockerfile.prod docker/Dockerfile.native; do
    [ -f "$f" ] || continue
    if command -v hadolint > /dev/null 2>&1; then
        hadolint "$f" >> "$REPORT_FILE" 2>&1 || true
    elif command -v docker > /dev/null 2>&1; then
        docker run --rm -v "$(pwd):/repo" -w /repo hadolint/hadolint hadolint "$f" >> "$REPORT_FILE" 2>&1 || true
    fi
done
if ! grep -q 'hadolint\|DL' "$REPORT_FILE" 2>/dev/null; then
    echo "Hadolint skipped (binary/docker not found)." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 6. Checkov (IaC)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Checkov..."
if ! .venv/bin/checkov --version > /dev/null 2>&1; then
    .venv/bin/pip install checkov --quiet
fi
.venv/bin/checkov -d docker/ -d . --skip-path apps/ --skip-path node_modules/ --quiet >> "$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 7. Trivy (Filesystem)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Trivy filesystem..."
if command -v docker > /dev/null 2>&1; then
    docker run --rm -v "$(pwd):/workspace" -w /workspace aquasec/trivy fs \
        --ignorefile /workspace/.trivyignore . >> "$REPORT_FILE" 2>&1 || true
else
    echo "Docker not found, skipping Trivy fs." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 8. Trivy (Config / IaC)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Trivy config..."
if command -v docker > /dev/null 2>&1; then
    docker run --rm -v "$(pwd):/workspace" -w /workspace aquasec/trivy config \
        --ignorefile /workspace/.trivyignore /workspace >> "$REPORT_FILE" 2>&1 || true
else
    echo "Docker not found, skipping Trivy config." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

echo "## 9. npm audit (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running npm audit..."
(cd apps/frontend && npm audit) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

echo "✅ Scan complete. Report saved to $REPORT_FILE"
