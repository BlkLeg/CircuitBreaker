#!/usr/bin/env bash
# Build the native packages inside the image the release job uses.
#
# ADR 0005 Phase 3, F8. A PyInstaller bundle inherits the glibc floor of the host
# that built it. `make build` on a modern workstation produces packages that run
# only on hosts at or above that host's glibc, with no diagnostic beyond a
# PyInstaller error naming a library the operator never chose:
#
#   Failed to load Python shared library libpython3.14.so.1.0:
#   /lib/x86_64-linux-gnu/libm.so.6: version `GLIBC_2.38' not found
#
# .github/workflows/build.yml builds on ubuntu-22.04 with Python 3.12, a 2.35
# floor that every distro in the support matrix clears. This reproduces that
# environment locally so a developer can produce an artifact the fleet will
# accept, and so the deb rows can be exercised without waiting on CI.
#
# It does NOT make the result a CI artifact: build-info.json still records
# built_by=local, because provenance is about who built it, not only about where.
# For evidence, use the artifact the release job produced.
set -euo pipefail

IMAGE="${CB_RELEASE_IMAGE:-ubuntu:22.04}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

runtime=""
for candidate in docker podman; do
    if command -v "$candidate" >/dev/null 2>&1; then runtime="$candidate"; break; fi
done
if [ -z "$runtime" ]; then
    echo "ERROR: neither docker nor podman is installed." >&2
    echo "       Both are supported; either one can run the release image." >&2
    exit 1
fi

echo "==> Building in $IMAGE via $runtime (matching .github/workflows/build.yml)"

# --userns=keep-id under podman, so the artifacts land owned by the caller rather
# than by root. Docker needs the explicit --user for the same reason.
extra=()
if [ "$runtime" = "podman" ]; then
    extra+=(--userns=keep-id)
else
    extra+=(--user "$(id -u):$(id -g)")
fi

exec "$runtime" run --rm -i \
    -v "$REPO_ROOT":/src \
    -w /src \
    -e HOME=/tmp/cb-build-home \
    "${extra[@]}" \
    "$IMAGE" \
    bash -euo pipefail -c '
        export DEBIAN_FRONTEND=noninteractive
        mkdir -p "$HOME"
        # software-properties-common for the deadsnakes PPA: 22.04 ships 3.10 and
        # the release job pins 3.12, which is the version whose libpython ends up
        # inside the bundle.
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends \
            software-properties-common curl ca-certificates git build-essential file
        add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends \
            python3.12 python3.12-venv python3.12-dev
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
        apt-get install -y -qq --no-install-recommends nodejs

        bash scripts/install-build-deps.sh

        rm -rf .venv-release
        python3.12 -m venv .venv-release
        .venv-release/bin/pip install --upgrade pip -q
        .venv-release/bin/pip install -q -e "apps/backend/[dev]"

        cd apps/frontend && npm ci --silent && npm run build && cd /src

        .venv-release/bin/python scripts/build_native_release.py --clean
        echo "==> glibc floor of this build:"
        cat dist/native/bundle/share/build-info.json
    '
