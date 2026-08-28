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
ROW_ID="${1:?usage: dispatch.sh <row-id> <package-path>}"
PACKAGE="${2:?usage: dispatch.sh <row-id> <package-path>}"

cb::require_file "$PACKAGE" "build it with 'make build' — dist/native/ holds the candidates"
cb::require_tool scp
cb::require_tool ssh

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
                 fedora@127.0.0.1:/tmp/cb-tier3-evidence/. "$ROW_EVIDENCE/" 2>/dev/null; then
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
fleet::ssh fedora@127.0.0.1 'sudo mkdir -p /opt/cb-tier3 && sudo chown fedora /opt/cb-tier3'
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -i "$SSH_KEY" -P "$SSH_PORT" \
    "$PACKAGE" "$CB_REPO_ROOT/scripts/ci/tier3-artifact.sh" \
    fedora@127.0.0.1:/opt/cb-tier3/

cb::section "Execute tier3-artifact.sh in the guest"
fleet::ssh fedora@127.0.0.1 \
    "sudo bash /opt/cb-tier3/tier3-artifact.sh /opt/cb-tier3/$(basename "$PACKAGE")"

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
