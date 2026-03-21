#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Gate mode: --gate exits non-zero when HIGH/CRIT findings are detected.
# Default (no flag): report-only, never fails.
# ---------------------------------------------------------------------------
GATE_MODE=false
[[ "${1:-}" == "--gate" ]] && GATE_MODE=true

GATE_FAILURES=0
REPORT_FILE="security_scan_report.md"
echo "# Security Scan Report - $(date)" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
$GATE_MODE && echo "_Gate mode active — HIGH/CRIT findings will cause non-zero exit._" >> "$REPORT_FILE"
echo ""
echo "Running security scans... This may take a few minutes."
$GATE_MODE && echo "(gate mode: will fail on HIGH/CRIT)"

# Ensure .venv exists for Python tools
if [ ! -d .venv ]; then
    echo "Creating .venv for security tools..."
    python3 -m venv .venv
fi

# Helper: run a tool, optionally gate on its exit code
# Usage: run_scan <gate_this_tool> <description> <command...>
run_gated() {
    local gate_this="$1"; shift
    if $GATE_MODE && $gate_this; then
        "$@"
        local rc=$?
        if [ $rc -ne 0 ]; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE (exit $rc)" >> "$REPORT_FILE"
        fi
        return 0  # never abort mid-report
    else
        "$@" || true
    fi
}

# ── 1. Bandit (Python SAST) ─────────────────────────────────────────────────
echo "## 1. Bandit (Python SAST)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Bandit..."
if ! .venv/bin/bandit --version > /dev/null 2>&1; then
    .venv/bin/pip install bandit --quiet
fi
# Gate: -lll = HIGH severity only, --skip B101 (assert in tests is fine)
if $GATE_MODE; then
    .venv/bin/bandit -r apps/backend/src/ -lll --skip B101 -f txt >> "$REPORT_FILE" 2>&1
    [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Bandit HIGH findings" >> "$REPORT_FILE"
else
    .venv/bin/bandit -r apps/backend/src/ -ll --skip B101 -f txt >> "$REPORT_FILE" 2>&1 || true
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 2. Semgrep (SAST) ───────────────────────────────────────────────────────
echo "## 2. Semgrep (SAST)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Semgrep..."
if ! .venv/bin/semgrep --version > /dev/null 2>&1; then
    .venv/bin/pip install semgrep --quiet
fi
if $GATE_MODE; then
    .venv/bin/semgrep scan --config=p/default --error --severity ERROR \
        apps/backend/src/ apps/frontend/src/ docker/ >> "$REPORT_FILE" 2>&1
    [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Semgrep ERROR findings" >> "$REPORT_FILE"
else
    .venv/bin/semgrep scan --config=p/default apps/backend/src/ apps/frontend/src/ docker/ >> "$REPORT_FILE" 2>&1 || true
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 3. Gitleaks (Secret Scanning) ───────────────────────────────────────────
echo "## 3. Gitleaks (Secret Scanning)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Gitleaks..."
GITLEAKS_CONFIG=""
[ -f .gitleaks.toml ] && GITLEAKS_CONFIG="--config .gitleaks.toml"
GITLEAKS_RAN=false
if command -v gitleaks > /dev/null 2>&1; then
    GITLEAKS_RAN=true
    if $GATE_MODE; then
        gitleaks detect --no-git --source . $GITLEAKS_CONFIG --report-path /dev/stdout 2>&1 >> "$REPORT_FILE"
        [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Gitleaks found secrets" >> "$REPORT_FILE"
    else
        gitleaks detect --no-git --source . $GITLEAKS_CONFIG --report-path /dev/stdout 2>&1 >> "$REPORT_FILE" || true
    fi
elif command -v docker > /dev/null 2>&1; then
    GITLEAKS_RAN=true
    GITLEAKS_DOCKER_ARGS="detect --source=/repo -v"
    [ -f .gitleaks.toml ] && GITLEAKS_DOCKER_ARGS="detect --source=/repo --config=/repo/.gitleaks.toml -v"
    if $GATE_MODE; then
        docker run --rm -v "$(pwd):/repo" ghcr.io/gitleaks/gitleaks:latest $GITLEAKS_DOCKER_ARGS 2>&1 >> "$REPORT_FILE"
        [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Gitleaks found secrets" >> "$REPORT_FILE"
    else
        docker run --rm -v "$(pwd):/repo" ghcr.io/gitleaks/gitleaks:latest $GITLEAKS_DOCKER_ARGS 2>&1 >> "$REPORT_FILE" || true
    fi
fi
if ! $GITLEAKS_RAN; then
    echo "gitleaks not found (install: https://github.com/gitleaks/gitleaks/releases), skipping." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 4. ESLint + security (Frontend) — informational only ────────────────────
echo "## 4. ESLint + security (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running ESLint (includes eslint-plugin-security)..."
(cd apps/frontend && npm run lint) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

# ── 5. Hadolint (Dockerfile lint) — informational only ──────────────────────
echo "## 5. Hadolint (Dockerfile lint)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Hadolint..."
# Native-first: scan Dockerfile.mono (the production image)
for f in Dockerfile.mono Dockerfile; do
    [ -f "$f" ] || continue
    if command -v hadolint > /dev/null 2>&1; then
        hadolint "$f" >> "$REPORT_FILE" 2>&1 || true
    elif command -v docker > /dev/null 2>&1; then
        docker run --rm -v "$(pwd):/repo" -w /repo hadolint/hadolint hadolint "$f" >> "$REPORT_FILE" 2>&1 || true
    fi
done
if ! grep -q 'hadolint\|DL' "$REPORT_FILE" 2>/dev/null; then
    echo "Hadolint skipped (binary not found; install: https://github.com/hadolint/hadolint/releases)." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 6. Checkov (IaC) — informational only ───────────────────────────────────
echo "## 6. Checkov (IaC)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Checkov..."
if ! .venv/bin/checkov --version > /dev/null 2>&1; then
    .venv/bin/pip install checkov --quiet
fi
.venv/bin/checkov -d docker/ -d . --skip-path apps/ --skip-path node_modules/ --quiet >> "$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

# ── 7. Trivy (Filesystem) ───────────────────────────────────────────────────
echo "## 7. Trivy (Filesystem)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Trivy filesystem..."
TRIVY_RAN=false
TRIVY_IGNORE=""
[ -f .trivyignore ] && TRIVY_IGNORE="--ignorefile .trivyignore"
# Native-first: prefer local trivy binary over Docker
if command -v trivy > /dev/null 2>&1; then
    TRIVY_RAN=true
    if $GATE_MODE; then
        trivy fs --exit-code 1 --severity HIGH,CRITICAL $TRIVY_IGNORE . >> "$REPORT_FILE" 2>&1
        [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Trivy HIGH/CRIT findings" >> "$REPORT_FILE"
    else
        trivy fs --severity HIGH,CRITICAL,MEDIUM $TRIVY_IGNORE . >> "$REPORT_FILE" 2>&1 || true
    fi
elif command -v docker > /dev/null 2>&1; then
    TRIVY_RAN=true
    if $GATE_MODE; then
        docker run --rm -v "$(pwd):/workspace" -w /workspace aquasec/trivy fs \
            --exit-code 1 --severity HIGH,CRITICAL --ignorefile /workspace/.trivyignore . >> "$REPORT_FILE" 2>&1
        [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Trivy HIGH/CRIT findings" >> "$REPORT_FILE"
    else
        docker run --rm -v "$(pwd):/workspace" -w /workspace aquasec/trivy fs \
            --ignorefile /workspace/.trivyignore . >> "$REPORT_FILE" 2>&1 || true
    fi
fi
if ! $TRIVY_RAN; then
    echo "Trivy not found (install: https://aquasecurity.github.io/trivy/latest/getting-started/installation/), skipping." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 8. Trivy (Config / IaC) ─────────────────────────────────────────────────
echo "## 8. Trivy (Config / IaC)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Trivy config..."
if command -v trivy > /dev/null 2>&1; then
    if $GATE_MODE; then
        trivy config --exit-code 1 --severity HIGH,CRITICAL $TRIVY_IGNORE . >> "$REPORT_FILE" 2>&1
        [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Trivy config HIGH/CRIT" >> "$REPORT_FILE"
    else
        trivy config $TRIVY_IGNORE . >> "$REPORT_FILE" 2>&1 || true
    fi
elif command -v docker > /dev/null 2>&1; then
    if $GATE_MODE; then
        docker run --rm -v "$(pwd):/workspace" -w /workspace aquasec/trivy config \
            --exit-code 1 --severity HIGH,CRITICAL --ignorefile /workspace/.trivyignore /workspace >> "$REPORT_FILE" 2>&1
        [ $? -ne 0 ] && GATE_FAILURES=$((GATE_FAILURES + 1)) && echo "  ⚠ GATE FAILURE: Trivy config HIGH/CRIT" >> "$REPORT_FILE"
    else
        docker run --rm -v "$(pwd):/workspace" -w /workspace aquasec/trivy config \
            --ignorefile /workspace/.trivyignore /workspace >> "$REPORT_FILE" 2>&1 || true
    fi
else
    echo "Trivy not found, skipping config scan." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 9. npm audit (Frontend) — informational only ────────────────────────────
echo "## 9. npm audit (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running npm audit..."
(cd apps/frontend && npm audit --audit-level=high) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
echo "\`\`\`" >> "$REPORT_FILE"

# ── Summary ──────────────────────────────────────────────────────────────────
echo "" >> "$REPORT_FILE"
if $GATE_MODE; then
    if [ $GATE_FAILURES -gt 0 ]; then
        echo "## ❌ Gate Result: $GATE_FAILURES tool(s) reported HIGH/CRIT findings" >> "$REPORT_FILE"
        echo ""
        echo "❌ GATE FAILED: $GATE_FAILURES tool(s) reported HIGH/CRIT findings."
        echo "   Review $REPORT_FILE for details."
        exit 1
    else
        echo "## ✅ Gate Result: All scans passed (zero HIGH/CRIT)" >> "$REPORT_FILE"
        echo ""
        echo "✅ Gate passed. Zero HIGH/CRIT findings. Report saved to $REPORT_FILE"
    fi
else
    echo "✅ Scan complete. Report saved to $REPORT_FILE"
fi
