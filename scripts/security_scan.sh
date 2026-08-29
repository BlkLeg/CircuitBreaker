#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export HOME="${SECURITY_SCAN_HOME:-/tmp/cb-security-scan-home}"
export XDG_CACHE_HOME="${SECURITY_SCAN_CACHE:-/tmp/cb-security-scan-cache}"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-/tmp/cb-security-npm-cache}"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$NPM_CONFIG_CACHE"

# ---------------------------------------------------------------------------
# Gate mode: --gate exits non-zero when HIGH/CRIT findings are detected.
# Default (no flag): report-only, never fails.
# ---------------------------------------------------------------------------
GATE_MODE=false
[[ "${1:-}" == "--gate" ]] && GATE_MODE=true

GATE_FAILURES=0
# Tools that could not run at all, tracked apart from tools that ran and found
# something. Both must fail the gate -- "a gate that passes because the scanner
# is absent is not a gate" -- but they are different problems with different
# fixes, and collapsing them into one number sent at least one developer hunting
# for HIGH/CRIT vulnerabilities that did not exist while the actual cause was
# two uninstalled binaries.
GATE_UNAVAILABLE=0
GATE_MISSING_TOOLS=()

# Record a scanner that could not run. Fails the gate exactly as a finding does;
# reported differently because "install this" and "fix this" are not the same
# instruction.
gate_unavailable() {
    local tool="$1" what="$2" install_hint="$3"
    GATE_FAILURES=$((GATE_FAILURES + 1))
    GATE_UNAVAILABLE=$((GATE_UNAVAILABLE + 1))
    GATE_MISSING_TOOLS+=("$tool — $install_hint")
    echo "  ⚠ GATE FAILURE: $tool unavailable — cannot attest $what" >> "$REPORT_FILE"
}

REPORT_FILE="security_scan_report.md"
echo "# Security Scan Report - $(date)" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
$GATE_MODE && echo "_Gate mode active — HIGH/CRIT findings will cause non-zero exit._" >> "$REPORT_FILE"
echo ""
echo "Running security scans... This may take a few minutes."
$GATE_MODE && echo "(gate mode: will fail on HIGH/CRIT)"

# ── 0. Suppression metadata ─────────────────────────────────────────────────
echo "## 0. Suppression metadata" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Validating scanner suppression metadata..."
if ! python3 scripts/validate_security_suppressions.py >> "$REPORT_FILE" 2>&1; then
    GATE_FAILURES=$((GATE_FAILURES + 1))
    echo "  ⚠ GATE FAILURE: scanner suppression metadata invalid" >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── Scanner toolchain venv ──────────────────────────────────────────────────
# Deliberately not .venv. In this repo .venv is the backend *development*
# environment — `make lint` runs "$SCAN_BIN"/ruff and "$SCAN_BIN"/mypy out of it,
# and lint-staged calls the same paths on every commit. The scanners pin
# dependencies that conflict with the application's: installing semgrep drags
# opentelemetry-instrumentation down to 0.58b0, below the 0.65b0 the backend's
# instrumentation needs, and leaves `import app.main` raising
#
#   ImportError: cannot import name 'detect_synthetic_user_agent'
#
# So `make security-check` used to break `make lint` and the app itself on the
# same host, silently, as a side effect of scanning. CI never saw it because
# each job builds a throwaway .venv on a fresh runner.
#
# Keeping the toolchain outside the repo also means no scanner ever scans its
# own dependencies, so this needs no .gitignore, .trivyignore or SEC-18
# suppression entry to stay out of the results. Point SECURITY_SCAN_VENV
# somewhere durable to avoid reinstalling after /tmp is cleared; the default is
# under this script's existing scratch root and is always safe to delete.
SCAN_VENV="${SECURITY_SCAN_VENV:-$XDG_CACHE_HOME/scanner-venv}"
SCAN_BIN="$SCAN_VENV/bin"
if [ ! -x "$SCAN_BIN/python" ]; then
    echo "Creating scanner toolchain venv at $SCAN_VENV..."
    python3 -m venv "$SCAN_VENV"
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

docker_available() {
    command -v docker > /dev/null 2>&1 && docker ps > /dev/null 2>&1
}

# ── 1. Bandit (Python SAST) ─────────────────────────────────────────────────
echo "## 1. Bandit (Python SAST)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Bandit..."
if ! "$SCAN_BIN"/bandit --version > /dev/null 2>&1; then
    "$SCAN_BIN"/pip install bandit --quiet
fi
# Gate: -lll = HIGH severity only, --skip B101 (assert in tests is fine)
if $GATE_MODE; then
    if ! "$SCAN_BIN"/bandit -r apps/backend/src/ -lll --skip B101 -f txt >> "$REPORT_FILE" 2>&1; then
        GATE_FAILURES=$((GATE_FAILURES + 1))
        echo "  ⚠ GATE FAILURE: Bandit HIGH findings" >> "$REPORT_FILE"
    fi
else
    "$SCAN_BIN"/bandit -r apps/backend/src/ -ll --skip B101 -f txt >> "$REPORT_FILE" 2>&1 || true
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 2. Semgrep (SAST) ───────────────────────────────────────────────────────
echo "## 2. Semgrep (SAST)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Semgrep..."
if ! "$SCAN_BIN"/semgrep --version > /dev/null 2>&1; then
    "$SCAN_BIN"/pip install semgrep --quiet
fi
if $GATE_MODE; then
    if ! "$SCAN_BIN"/semgrep scan --config=p/default --error --severity ERROR \
        apps/backend/src/ apps/frontend/src/ docker/ >> "$REPORT_FILE" 2>&1; then
        GATE_FAILURES=$((GATE_FAILURES + 1))
        echo "  ⚠ GATE FAILURE: Semgrep ERROR findings" >> "$REPORT_FILE"
    fi
else
    "$SCAN_BIN"/semgrep scan --config=p/default apps/backend/src/ apps/frontend/src/ docker/ >> "$REPORT_FILE" 2>&1 || true
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
    # -v and no --report-path, matching the Docker branch below. The previous
    # `--report-path /dev/stdout` was wrong twice over: gitleaks infers the
    # report format from the path's extension, /dev/stdout has none, so it died
    # with "Unknown report format:" and exit 1 on every run — which this branch
    # then recorded as "Gitleaks found secrets" no matter what was in the tree.
    # And opening /dev/stdout truncated the report this same command appends
    # to, taking sections 0-3 with it. CI never saw either: no gitleaks binary
    # is installed on the runners, so it always took the Docker branch.
    if $GATE_MODE; then
        if ! gitleaks detect --no-git --source . $GITLEAKS_CONFIG -v >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: Gitleaks found secrets" >> "$REPORT_FILE"
        fi
    else
        gitleaks detect --no-git --source . $GITLEAKS_CONFIG -v >> "$REPORT_FILE" 2>&1 || true
    fi
elif docker_available; then
    GITLEAKS_RAN=true
    GITLEAKS_DOCKER_ARGS="detect --no-git --source=/repo -v"
    [ -f .gitleaks.toml ] && GITLEAKS_DOCKER_ARGS="detect --no-git --source=/repo --config=/repo/.gitleaks.toml -v"
    if $GATE_MODE; then
        if ! docker run --rm -v "$(pwd):/repo" ghcr.io/gitleaks/gitleaks:v8.30.1 $GITLEAKS_DOCKER_ARGS >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: Gitleaks found secrets" >> "$REPORT_FILE"
        fi
    else
        docker run --rm -v "$(pwd):/repo" ghcr.io/gitleaks/gitleaks:v8.30.1 $GITLEAKS_DOCKER_ARGS 2>&1 >> "$REPORT_FILE" || true
    fi
fi
if ! $GITLEAKS_RAN; then
    echo "gitleaks not found (install: https://github.com/gitleaks/gitleaks/releases), skipping." >> "$REPORT_FILE"
    # Fail closed: a gate that "passes" because the scanner is absent is not a
    # gate. An RC rerun on a host without gitleaks would otherwise regress
    # silently. Report-only mode keeps skipping.
    if $GATE_MODE; then
        gate_unavailable Gitleaks "secret scanning" \
            "go install github.com/zricethezav/gitleaks/v8@latest, or a release binary from https://github.com/gitleaks/gitleaks/releases"
    fi
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 4. ESLint + security (Frontend) — informational only ────────────────────
echo "## 4. ESLint + security (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running ESLint (includes eslint-plugin-security)..."
# Informational, not a gate — the Lint job runs ESLint as a real gate. But an
# informational section still has to distinguish "ran and was clean" from "never
# ran", which this one did not: CI installs no frontend dependencies for the
# Security Gate job, so every run recorded a bare `sh: 1: eslint: not found`
# that read exactly like a clean scan (#106). Follows the Hadolint section's
# shape below rather than inventing a second convention.
if [ -x "$REPO_ROOT/apps/frontend/node_modules/.bin/eslint" ]; then
    (cd apps/frontend && npm run lint) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
else
    echo "ESLint skipped (frontend dependencies not installed; run 'npm ci' in apps/frontend)." >> "$REPORT_FILE"
fi
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
    elif docker_available; then
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
if ! "$SCAN_BIN"/checkov --version > /dev/null 2>&1; then
    "$SCAN_BIN"/pip install checkov --quiet
fi
if $GATE_MODE; then
    if ! "$SCAN_BIN"/checkov -d docker/ -d .github/workflows/ --quiet >> "$REPORT_FILE" 2>&1; then
        GATE_FAILURES=$((GATE_FAILURES + 1))
        echo "  ⚠ GATE FAILURE: Checkov findings" >> "$REPORT_FILE"
    fi
else
    "$SCAN_BIN"/checkov -d docker/ -d .github/workflows/ --quiet >> "$REPORT_FILE" 2>&1 || true
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 7. Trivy (Filesystem) ───────────────────────────────────────────────────
echo "## 7. Trivy (Filesystem)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Trivy filesystem..."
TRIVY_RAN=false
TRIVY_IGNORE=""
[ -f .trivyignore ] && TRIVY_IGNORE="--ignorefile .trivyignore"
TRIVY_SKIP_DIRS="--skip-dirs .venv --skip-dirs node_modules --skip-dirs dist"

# Trivy's vulnerability database is ~110MB and `docker run --rm` throws the
# container away with it, so without a host cache mount every single run
# redownloads it. Measured 2026-08-27: `make verify` at 4m55s against a 3m17s
# baseline and a 4-minute hard budget, with "[vulndb] Downloading vulnerability
# DB..." in the log on a machine that had just run the same scan. It is also an
# offline problem -- a gate that needs 110MB of network per invocation fails red
# on a train with nothing wrong in the tree. Native trivy already caches here by
# default; this gives the dockerised path the same durability.
TRIVY_CACHE="${TRIVY_CACHE:-$XDG_CACHE_HOME/trivy}"
mkdir -p "$TRIVY_CACHE"
TRIVY_CACHE_MOUNT=(-v "$TRIVY_CACHE:/root/.cache/trivy")
# Native-first: prefer local trivy binary over Docker
if command -v trivy > /dev/null 2>&1; then
    TRIVY_RAN=true
    if $GATE_MODE; then
        if ! trivy fs --exit-code 1 --severity HIGH,CRITICAL $TRIVY_IGNORE $TRIVY_SKIP_DIRS . >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: Trivy HIGH/CRIT findings" >> "$REPORT_FILE"
        fi
    else
        trivy fs --severity HIGH,CRITICAL,MEDIUM $TRIVY_IGNORE $TRIVY_SKIP_DIRS . >> "$REPORT_FILE" 2>&1 || true
    fi
elif docker_available; then
    TRIVY_RAN=true
    if $GATE_MODE; then
        if ! docker run --rm -v "$(pwd):/workspace" "${TRIVY_CACHE_MOUNT[@]}" -w /workspace aquasec/trivy fs \
            --exit-code 1 --severity HIGH,CRITICAL --ignorefile /workspace/.trivyignore $TRIVY_SKIP_DIRS . >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: Trivy HIGH/CRIT findings" >> "$REPORT_FILE"
        fi
    else
        docker run --rm -v "$(pwd):/workspace" "${TRIVY_CACHE_MOUNT[@]}" -w /workspace aquasec/trivy fs \
            --ignorefile /workspace/.trivyignore $TRIVY_SKIP_DIRS . >> "$REPORT_FILE" 2>&1 || true
    fi
fi
if ! $TRIVY_RAN; then
    echo "Trivy not found (install: https://aquasecurity.github.io/trivy/latest/getting-started/installation/), skipping." >> "$REPORT_FILE"
    # Fail closed — see the Gitleaks note above.
    if $GATE_MODE; then
        gate_unavailable Trivy "filesystem scanning" \
            "https://trivy.dev/latest/getting-started/installation/"
    fi
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 8. Trivy (Config / IaC) ─────────────────────────────────────────────────
echo "## 8. Trivy (Config / IaC)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running Trivy config..."
if command -v trivy > /dev/null 2>&1; then
    if $GATE_MODE; then
        if ! trivy config --exit-code 1 --severity HIGH,CRITICAL $TRIVY_IGNORE $TRIVY_SKIP_DIRS . >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: Trivy config HIGH/CRIT" >> "$REPORT_FILE"
        fi
    else
        trivy config $TRIVY_IGNORE $TRIVY_SKIP_DIRS . >> "$REPORT_FILE" 2>&1 || true
    fi
elif docker_available; then
    if $GATE_MODE; then
        if ! docker run --rm -v "$(pwd):/workspace" "${TRIVY_CACHE_MOUNT[@]}" -w /workspace aquasec/trivy config \
            --exit-code 1 --severity HIGH,CRITICAL --ignorefile /workspace/.trivyignore $TRIVY_SKIP_DIRS /workspace >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: Trivy config HIGH/CRIT" >> "$REPORT_FILE"
        fi
    else
        docker run --rm -v "$(pwd):/workspace" "${TRIVY_CACHE_MOUNT[@]}" -w /workspace aquasec/trivy config \
            --ignorefile /workspace/.trivyignore $TRIVY_SKIP_DIRS /workspace >> "$REPORT_FILE" 2>&1 || true
    fi
else
    echo "Trivy not found, skipping config scan." >> "$REPORT_FILE"
    # Fail closed — see the Gitleaks note above.
    if $GATE_MODE; then
        gate_unavailable Trivy "config/IaC scanning" \
            "https://trivy.dev/latest/getting-started/installation/"
    fi
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 9. npm audit (Frontend) — informational only ────────────────────────────
echo "## 9. npm audit (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running npm audit..."
if $GATE_MODE; then
    if ! (cd apps/frontend && npm audit --audit-level=high) >> "$REPO_ROOT/$REPORT_FILE" 2>&1; then
        GATE_FAILURES=$((GATE_FAILURES + 1))
        echo "  ⚠ GATE FAILURE: npm audit HIGH findings" >> "$REPORT_FILE"
    fi
else
    (cd apps/frontend && npm audit --audit-level=high) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 9b. pip-audit (Python dependencies) ─────────────────────────────────────
# SEC-18 claims Python dependency scanning, but the local gate ran none — only
# the CI job did, and that one skipped requirements-pg.txt entirely. Both
# manifests are audited here so a local `--gate` run attests what CI attests.
echo "## 9b. pip-audit (Python dependencies)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running pip-audit..."
if ! "$SCAN_BIN"/pip-audit --version > /dev/null 2>&1; then
    "$SCAN_BIN"/pip install pip-audit --quiet
fi
PIP_AUDIT_ARGS="-r apps/backend/requirements.txt"
[ -f apps/backend/requirements-pg.txt ] && PIP_AUDIT_ARGS="$PIP_AUDIT_ARGS -r apps/backend/requirements-pg.txt"
if "$SCAN_BIN"/pip-audit --version > /dev/null 2>&1; then
    if $GATE_MODE; then
        if ! "$SCAN_BIN"/pip-audit $PIP_AUDIT_ARGS >> "$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: pip-audit findings" >> "$REPORT_FILE"
        fi
    else
        "$SCAN_BIN"/pip-audit $PIP_AUDIT_ARGS >> "$REPORT_FILE" 2>&1 || true
    fi
else
    echo "pip-audit unavailable (install: pip install pip-audit), skipping." >> "$REPORT_FILE"
    # Fail closed — see the Gitleaks note above.
    if $GATE_MODE; then
        gate_unavailable pip-audit "Python dependencies" \
            "installed automatically into the scanner venv; a failure here means that bootstrap failed"
    fi
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── 10. Go vulnerability scan (Agent) ────────────────────────────────────────
echo "## 10. Go vulnerability scan (Agent)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running govulncheck..."
export GOBIN="${GOBIN:-/tmp/cb-security-go-bin}"
export PATH="$GOBIN:$PATH"
mkdir -p "$GOBIN"
if ! command -v govulncheck > /dev/null 2>&1 && $GATE_MODE && command -v go > /dev/null 2>&1; then
    go install golang.org/x/vuln/cmd/govulncheck@v1.7.0 >> "$REPORT_FILE" 2>&1 || true
fi
if command -v govulncheck > /dev/null 2>&1; then
    if $GATE_MODE; then
        if ! (cd apps/agent && govulncheck ./...) >> "$REPO_ROOT/$REPORT_FILE" 2>&1; then
            GATE_FAILURES=$((GATE_FAILURES + 1))
            echo "  ⚠ GATE FAILURE: govulncheck findings" >> "$REPORT_FILE"
        fi
    else
        (cd apps/agent && govulncheck ./...) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
    fi
else
    echo "govulncheck not found (install: go install golang.org/x/vuln/cmd/govulncheck@v1.7.0), skipping." >> "$REPORT_FILE"
    if $GATE_MODE; then
        GATE_FAILURES=$((GATE_FAILURES + 1))
        echo "  ⚠ GATE FAILURE: govulncheck unavailable" >> "$REPORT_FILE"
    fi
fi
echo "\`\`\`" >> "$REPORT_FILE"

# ── Summary ──────────────────────────────────────────────────────────────────
echo "" >> "$REPORT_FILE"
if $GATE_MODE; then
    if [ $GATE_FAILURES -gt 0 ]; then
        GATE_FINDINGS=$((GATE_FAILURES - GATE_UNAVAILABLE))
        echo "## ❌ Gate Result: $GATE_FAILURES gate failure(s) — $GATE_FINDINGS finding(s), $GATE_UNAVAILABLE unavailable tool(s)" >> "$REPORT_FILE"
        if [ ${#GATE_MISSING_TOOLS[@]} -gt 0 ]; then
            echo "" >> "$REPORT_FILE"
            echo "Scanners that could not run (install these; nothing below was found in your tree):" >> "$REPORT_FILE"
            for _missing in "${GATE_MISSING_TOOLS[@]}"; do
                echo "  - $_missing" >> "$REPORT_FILE"
            done
        fi
        echo ""
        echo "❌ GATE FAILED: $GATE_FAILURES gate failure(s)."
        # A full `if`, not `[ ... ] && echo`. This script runs under `set -e`, and
        # a bare `test && cmd` whose test is false makes the list return non-zero
        # -- the exact shape that ends a script early depending on where it sits.
        # The line below is reached precisely when GATE_FINDINGS is 0, which is
        # the common case for a missing-tool failure, so getting it wrong would
        # have swallowed the install hints underneath it.
        if [ $GATE_FINDINGS -gt 0 ]; then
            echo "   $GATE_FINDINGS scanner(s) reported HIGH/CRIT findings — review $REPORT_FILE."
        fi
        if [ $GATE_UNAVAILABLE -gt 0 ]; then
            echo "   $GATE_UNAVAILABLE scanner(s) could NOT RUN. This is a missing tool, not a vulnerability:"
            for _missing in "${GATE_MISSING_TOOLS[@]}"; do
                echo "     - $_missing"
            done
        fi
        exit 1
    else
        echo "## ✅ Gate Result: All scans passed (zero HIGH/CRIT)" >> "$REPORT_FILE"
        echo ""
        echo "✅ Gate passed. Zero HIGH/CRIT findings. Report saved to $REPORT_FILE"
    fi
else
    echo "✅ Scan complete. Report saved to $REPORT_FILE"
fi
