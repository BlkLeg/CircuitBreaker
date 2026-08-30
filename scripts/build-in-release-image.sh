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

# Root inside the container, because the build installs apt packages. That
# leaves the artifacts owned by root on the host under docker, where container
# root is host root -- so the build chowns what it touched back to the caller.
# Under rootless podman container-root already maps to the invoking user, and a
# chown to a host uid would land on a subuid instead, so it is skipped there.
chown_to=""
if [ "$runtime" = "docker" ]; then
    chown_to="$(id -u):$(id -g)"
fi

exec "$runtime" run --rm -i \
    -v "$REPO_ROOT":/src \
    -w /src \
    -e "CB_CHOWN_TO=$chown_to" \
    "$IMAGE" \
    bash -euo pipefail -c '
        export DEBIAN_FRONTEND=noninteractive

        cleanup() {
            # Always, even on failure: a half-built tree owned by root is worse
            # than a failed build, because the next `make build` cannot write to
            # it and the error names a permission, not a cause.
            if [ -n "${CB_CHOWN_TO:-}" ]; then
                chown -R "$CB_CHOWN_TO" \
                    dist build .venv-release \
                    apps/frontend/node_modules apps/frontend/dist 2>/dev/null || true
            fi
        }
        trap cleanup EXIT

        # software-properties-common for the deadsnakes PPA: 22.04 ships 3.10 and
        # the release job pins 3.12, which is the version whose libpython ends up
        # inside the bundle.
        apt-get update -qq
        # gnupg and gpg-agent explicitly: add-apt-repository shells out to gpg to
        # import the PPA key, and the minimal 22.04 image ships neither. The
        # GitHub runner has them preinstalled, which is why the release job never
        # meets this and a from-scratch image does.
        apt-get install -y -qq --no-install-recommends \
            software-properties-common gnupg gpg-agent \
            curl ca-certificates git build-essential file
        add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends \
            python3.12 python3.12-venv python3.12-dev
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
        apt-get install -y -qq --no-install-recommends nodejs

        # install-build-deps.sh is written for a normal host, where privileged
        # steps go through sudo. This container is already root and has no sudo,
        # so give it a shim that just runs the command. Installing the real
        # package would pull in PAM configuration for a throwaway image to no
        # benefit, and patching the script for a container would make it lie
        # about how it behaves on a host.
        # A symlink to env rather than a written shim: env execs its arguments,
        # which is exactly what sudo does here, and it needs no quoting at all --
        # this whole block is inside a single-quoted -c string, where a printf
        # spelling of the same shim collapsed into `exec: $@n: not found`.
        ln -sf /usr/bin/env /usr/local/bin/sudo

        # python3.12 ahead of the image default of 3.10, so install-build-deps.sh and the
        # venv below both resolve the version the release job pins rather than
        # trying to install it a second time.
        update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 >/dev/null

        # The repo is bind-mounted and owned by the host user, so git inside the
        # container refuses it for dubious ownership and exits 128. The Go agent
        # build stamps VCS info, so that surfaces as an opaque
        # `error obtaining VCS status: exit status 128` from `make manifest`.
        # CI never meets this because the runner owns its checkout.
        git config --global --add safe.directory /src

        bash scripts/install-build-deps.sh

        rm -rf .venv-release
        python3.12 -m venv .venv-release
        .venv-release/bin/pip install --upgrade pip -q
        .venv-release/bin/pip install -q -e "apps/backend/[dev]"

        cd apps/frontend && npm ci --silent && npm run build && cd /src

        .venv-release/bin/python scripts/build_native_release.py --clean
        echo "==> provenance of this build:"
        cat dist/native/bundle/share/build-info.json
    '
