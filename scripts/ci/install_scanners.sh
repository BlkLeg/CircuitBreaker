#!/usr/bin/env bash
#
# Install the security gate's binary scanners (gitleaks, trivy, hadolint) at
# pinned versions, verified by SHA-256, into one directory.
#
# Why this exists: scripts/security_scan.sh falls back to
# `docker run -v "$(pwd):/repo" ...` for any of these it cannot find. On a
# GitHub-hosted runner that works, because the Docker daemon shares the job's
# filesystem. On a self-hosted runner whose jobs are containers talking to the
# host's daemon through a mounted socket (GitLab Runner's Docker executor with
# /var/run/docker.sock bound in, or any act-style runner), `$(pwd)` names a
# path that does not exist on the host: the bind mount comes up empty, the
# scanner scans nothing, and the gate passes. Installing the binaries means the fallback is
# never taken, and the final require_tool calls make "not installed" fail
# closed rather than read as "found nothing" (ADR 0005, P2).
#
# Versions: gitleaks matches the image security_scan.sh pins; trivy matches
# the default of aquasecurity/trivy-action@v0.36.0, which security.yml's
# scanner jobs use, so both systems run the same scanner.
#
# Usage: install_scanners.sh <dest-dir>
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

DEST="${1:?usage: install_scanners.sh <dest-dir>}"
mkdir -p "$DEST"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

GITLEAKS_VERSION="8.30.1"
GITLEAKS_SHA256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
TRIVY_VERSION="0.70.0"
TRIVY_SHA256="8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9"
HADOLINT_VERSION="2.15.1"
HADOLINT_SHA256="c7187db94eeeeca956519a6af171adc31453941a1e777961f6e680f697c8c507"

# Download $1 to $2 and refuse it unless its SHA-256 is $3.
fetch_verified() {
    local url="$1" out="$2" sha="$3"
    curl -fsSL --retry 3 -o "$out" "$url"
    echo "${sha}  ${out}" | sha256sum --check --strict -
}

cb::section "gitleaks ${GITLEAKS_VERSION}"
fetch_verified \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    "$WORK/gitleaks.tar.gz" "$GITLEAKS_SHA256"
tar -xzf "$WORK/gitleaks.tar.gz" -C "$WORK" gitleaks
install -m 0755 "$WORK/gitleaks" "$DEST/gitleaks"

cb::section "trivy ${TRIVY_VERSION}"
fetch_verified \
    "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
    "$WORK/trivy.tar.gz" "$TRIVY_SHA256"
tar -xzf "$WORK/trivy.tar.gz" -C "$WORK" trivy
install -m 0755 "$WORK/trivy" "$DEST/trivy"

cb::section "hadolint ${HADOLINT_VERSION}"
fetch_verified \
    "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-linux-x86_64" \
    "$WORK/hadolint" "$HADOLINT_SHA256"
install -m 0755 "$WORK/hadolint" "$DEST/hadolint"

export PATH="$DEST:$PATH"
cb::require_tool gitleaks
cb::require_tool trivy
cb::require_tool hadolint
gitleaks version
trivy --version | head -1
hadolint --version
