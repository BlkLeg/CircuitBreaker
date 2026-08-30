#!/usr/bin/env bash
# Run one Tier 3 matrix row end to end: provision, push, execute, collect, destroy.
#
# The ordering in the cleanup path is load-bearing. Collection happens BEFORE
# destroy, on every exit path including failure and interrupt, because the run
# that fails is the run whose journal you need. A trap that destroys first is a
# trap that reliably deletes the evidence for the only outcome anyone will ask
# about.
#
# Nothing here uses `|| true`. Teardown and collection are precisely the places
# where a swallowed failure costs most: one leaks a virtual machine, the other
# discards the account of a failure. Where an outcome is genuinely informational,
# it is announced with cb::skipped; where it is not, it fails.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

FLEET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROW_ID="${1:?usage: dispatch.sh <row-id> <package-path> [previous-package-path]}"
PACKAGE="${2:?usage: dispatch.sh <row-id> <package-path> [previous-package-path]}"
# Optional, and required for exactly the rows that declare mode: upgrade.
PREVIOUS="${3:-}"

cb::require_file "$PACKAGE" "build it with 'make build' — dist/native/ holds the candidates"
cb::require_tool scp
cb::require_tool ssh

# ── the row and the arguments have to agree ────────────────────────────────
# The matrix says what each row claims; the arguments say what this invocation
# can actually prove. Silently running an install-only journey for a row that
# publishes an upgrade guarantee is the failure mode this whole tier exists to
# stop -- a green result standing in for an observation nobody made.
ROW_MODE="$(cb::matrix_field "$ROW_ID" mode "$FLEET_DIR/matrix.yaml")"
# The cloud image's default account. Hardcoding `fedora` worked while there was
# one row; Debian's image has no such user and every scp and ssh below would
# have failed with "Permission denied (publickey)", which reads like a broken
# key rather than a wrong username.
SSH_USER="$(cb::matrix_field "$ROW_ID" ssh_user "$FLEET_DIR/matrix.yaml")"
if [ -z "$SSH_USER" ]; then
    printf '::error::row %s declares no ssh_user\n' "$ROW_ID" >&2
    exit 1
fi
if [ -z "$ROW_MODE" ]; then
    printf '::error::row %s is not in %s, or declares no mode\n' "$ROW_ID" "$FLEET_DIR/matrix.yaml" >&2
    exit 1
fi
case "$ROW_MODE" in
    upgrade)
        if [ -z "$PREVIOUS" ]; then
            printf '::error::row %s declares mode: upgrade and needs a previous package to upgrade FROM.\n' "$ROW_ID" >&2
            printf 'Pass it as the third argument, or use CB_CANDIDATE_PREVIOUS with make verify-fleet-upgrade.\n' >&2
            exit 2
        fi
        cb::require_file "$PREVIOUS" "the version to upgrade from — build it from the previous tag, or keep the last release artifact"
        if [ "$(basename "$PACKAGE")" = "$(basename "$PREVIOUS")" ]; then
            printf '::error::candidate and previous are the same file name (%s).\n' "$(basename "$PACKAGE")" >&2
            printf 'An upgrade from a version to itself proves nothing; dnf treats it as a no-op.\n' >&2
            exit 2
        fi
        ;;
    install)
        if [ -n "$PREVIOUS" ]; then
            printf '::error::row %s declares mode: install but a previous package was passed.\n' "$ROW_ID" >&2
            printf 'Use the mode: upgrade row (%s-upgrade) to exercise upgrade and rollback.\n' "$ROW_ID" >&2
            exit 2
        fi
        ;;
    *)
        printf '::error::row %s declares an unknown mode: %s\n' "$ROW_ID" "$ROW_MODE" >&2
        exit 1
        ;;
esac

EVIDENCE_ROOT="$(cb::evidence_dir)"
ROW_EVIDENCE="$EVIDENCE_ROOT/diagnostics/tier3-$ROW_ID"
rm -rf "$ROW_EVIDENCE"
mkdir -p "$ROW_EVIDENCE"

VM_DIR=""; SSH_PORT=""; SSH_KEY=""

fleet::ssh() {
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR -i "$SSH_KEY" -p "$SSH_PORT" "$@"
}

fleet::collect() {
    [ -n "$VM_DIR" ] || return 0
    cb::section "Collect evidence → $ROW_EVIDENCE"

    # Best-effort by necessity -- the guest may be wedged, and a failure to
    # collect must not mask the failure being collected -- but never silent. A
    # missing journal with nothing explaining why reads exactly like a service
    # that logged nothing.
    if [ -n "$SSH_PORT" ]; then
        if ! scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
                 -o LogLevel=ERROR -i "$SSH_KEY" -P "$SSH_PORT" -r \
                 "$SSH_USER"@127.0.0.1:/tmp/cb-tier3-evidence/. "$ROW_EVIDENCE/" 2>/dev/null; then
            cb::skipped "guest evidence" "scp from the guest failed — the VM may not have reached the tier script"
        fi
    else
        cb::skipped "guest evidence" "no SSH endpoint — provisioning did not complete"
    fi

    # The console log is the only evidence that exists when the guest never came
    # up far enough to have any of its own, so its absence is worth saying.
    if [ -f "$VM_DIR/console.log" ]; then
        cp "$VM_DIR/console.log" "$ROW_EVIDENCE/"
    else
        cb::skipped "console log" "$VM_DIR/console.log was never created"
    fi
}

fleet::destroy() {
    [ -n "$VM_DIR" ] || return 0
    cb::section "Destroy $ROW_ID"

    if [ -f "$VM_DIR/qemu.pid" ]; then
        local pid
        pid="$(cat "$VM_DIR/qemu.pid")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            # SIGKILL after a grace period: a disposable VM on a disposable
            # overlay has nothing to shut down cleanly and nothing to lose.
            for _ in 1 2 3 4 5; do
                kill -0 "$pid" 2>/dev/null || break
                sleep 1
            done
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null
            fi
            # A VM that survives its own teardown is a leak on a machine that
            # will run this again, so it is reported rather than shrugged off.
            if kill -0 "$pid" 2>/dev/null; then
                printf '::error::qemu pid %s survived SIGKILL — VM leaked, dir %s\n' \
                    "$pid" "$VM_DIR" >&2
                return 1
            fi
        fi
    fi
    rm -rf "$VM_DIR"
}

cleanup() {
    local rc=$?
    fleet::collect
    fleet::destroy
    return "$rc"
}
trap cleanup EXIT INT TERM

cb::section "Provision $ROW_ID"
read -r SSH_PORT SSH_KEY VM_DIR < <("$FLEET_DIR/provision.sh" "$ROW_ID")

cb::section "Push the candidate and the tier script"
# Double quotes, not single: $SSH_USER has to expand here. The single-quoted
# version hardcoded `fedora` one line below a correctly parameterised
# destination, so the deb row failed at this step with `chown: invalid user:
# 'fedora'` -- the ownership, not the login, which is why it survived a test that
# only looked for `fedora@`.
fleet::ssh "$SSH_USER"@127.0.0.1 \
    "sudo mkdir -p /opt/cb-tier3/previous && sudo chown -R $SSH_USER /opt/cb-tier3"
# Companion packages beside the candidate go too. `dnf install circuit-breaker`
# on a real Fedora host also pulls circuit-breaker-nats, since the rpm recommends
# it and dnf installs weak dependencies by default; installing from local files
# cannot resolve that, so the set is pushed and installed together. Testing the
# application package alone would test a configuration no user ends up with.
PUSH=("$PACKAGE" "$CB_REPO_ROOT/scripts/ci/tier3-artifact.sh")
for companion in "$(dirname "$PACKAGE")"/circuit-breaker-nats_*."${PACKAGE##*.}"; do
    [ -f "$companion" ] && PUSH+=("$companion")
done
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -i "$SSH_KEY" -P "$SSH_PORT" \
    "${PUSH[@]}" \
    "$SSH_USER"@127.0.0.1:/opt/cb-tier3/

# The previous version goes to its own directory rather than beside the
# candidate. tier3-artifact.sh installs a whole directory at a time -- that is
# how the companion nats package gets in -- so two versions in one directory
# would hand dnf both and let it pick, which is not an upgrade test.
GUEST_PREVIOUS=""
if [ -n "$PREVIOUS" ]; then
    cb::section "Push the previous version ($(basename "$PREVIOUS"))"
    PUSH_PREVIOUS=("$PREVIOUS")
    for companion in "$(dirname "$PREVIOUS")"/circuit-breaker-nats_*."${PREVIOUS##*.}"; do
        [ -f "$companion" ] && PUSH_PREVIOUS+=("$companion")
    done
    scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -i "$SSH_KEY" -P "$SSH_PORT" \
        "${PUSH_PREVIOUS[@]}" \
        "$SSH_USER"@127.0.0.1:/opt/cb-tier3/previous/
    GUEST_PREVIOUS="/opt/cb-tier3/previous/$(basename "$PREVIOUS")"
fi

cb::section "Execute tier3-artifact.sh in the guest ($ROW_MODE)"
fleet::ssh "$SSH_USER"@127.0.0.1 \
    "sudo bash /opt/cb-tier3/tier3-artifact.sh /opt/cb-tier3/$(basename "$PACKAGE") $GUEST_PREVIOUS"

# Collect explicitly on the success path too, so the emptiness check below runs
# against real content. The trap's copy is idempotent.
fleet::collect

if [ -z "$(ls -A "$ROW_EVIDENCE" 2>/dev/null)" ]; then
    printf '::error::evidence directory %s is empty — the tier cannot report a pass it did not observe (P7)\n' \
        "$ROW_EVIDENCE" >&2
    exit 1
fi

# A recorded collection failure means part of the account is missing even though
# the row passed. Surfaced, not buried in a file nobody opens.
if [ -s "$ROW_EVIDENCE/collection-errors.log" ]; then
    cb::section "Evidence collection reported failures"
    cat "$ROW_EVIDENCE/collection-errors.log" >&2
fi

cb::section "Row $ROW_ID passed — evidence in $ROW_EVIDENCE"
ls -la "$ROW_EVIDENCE"
