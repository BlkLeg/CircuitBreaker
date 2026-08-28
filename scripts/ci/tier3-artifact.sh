#!/usr/bin/env bash
# Tier 3 — install, boot and exercise a candidate package on a clean host.
#
# Runs INSIDE an ephemeral VM, as root, over SSH. Deliberately self-contained:
# the repository does not exist here, only this file and the candidate. That is
# also what keeps it identical across every matrix row (P1) -- a script with no
# repo to reach into cannot quietly grow distro-specific branches.
#
# The contract is autopkgtest's: test the installed package AS INSTALLED. Nothing
# below may reach into a source tree, and nothing may reconfigure the package to
# make an assertion pass. If the package's own generated config does not work,
# that is the finding.
set -euo pipefail

PACKAGE="${1:?usage: tier3-artifact.sh <path-to-candidate-package>}"
EVIDENCE=/tmp/cb-tier3-evidence
BASE_URL="http://127.0.0.1:8000/api/v1"
mkdir -p "$EVIDENCE"

section() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
# Evidence is written by root here and fetched by an unprivileged user there, so
# every exit path opens it up first. Without this a single 0600 file -- the
# redacted env copy below inherits that mode from its source -- makes scp
# return non-zero and the whole collection read as failed.
readable_evidence() {
    # Guarded so a chmod failure cannot abort fail() before it prints the real
    # error, but reported rather than swallowed: if this does not work the
    # collector is about to come back empty, and the reason belongs on stderr
    # where the run can still show it.
    chmod -R a+rX "$EVIDENCE" 2>/dev/null && return 0
    printf '::warning::could not make %s world-readable — evidence collection will likely fail\n' \
        "$EVIDENCE" >&2
}
fail()    { readable_evidence; printf '::error::%s\n' "$1" >&2; exit 1; }

# Evidence collection that can neither abort the run nor lie about itself.
#
# `|| true` was the obvious way to stop a collector killing the failure it was
# sent to explain, and it is wrong for the same reason a missing scanner reading
# as a clean scan is wrong (#106): the evidence directory ends up missing a file
# with nothing anywhere saying why. An empty journal.log then means either "the
# service logged nothing" or "journalctl is not installed", and the reader cannot
# tell which. capture keeps the run alive AND writes the reason down.
capture() {
    local out=$1; shift
    # rc is captured on the failing command itself. `if ! cmd; then ... $? ...`
    # reports 0, because $? there is the status of the negation rather than of
    # cmd -- so the log would have said "COLLECTION FAILED (exit 0)" for every
    # failure, which is its own small lie in a file that exists to be trusted.
    local rc=0
    "$@" > "$out" 2>&1 || rc=$?
    if [ "$rc" -ne 0 ]; then
        printf 'COLLECTION FAILED (exit %s): %s\n' "$rc" "$*" \
            >> "$EVIDENCE/collection-errors.log"
    fi
}

# ── install ─────────────────────────────────────────────────────────────────
section "Install $(basename "$PACKAGE")"
# `dnf install` on a local file resolves the package's own dependencies, which is
# what a user gets. The rpm lists postgresql-server/redis/nats-server under
# `recommends` (weak), so this pulls them but does not configure them -- the VM
# fixture already did that, because nothing in the package ever will.
dnf install -y "$PACKAGE" 2>&1 | tee "$EVIDENCE/install.log"

section "Assert the package installed what it claims"
for path in \
    /usr/local/bin/circuit-breaker \
    /usr/local/share/circuit-breaker/VERSION \
    /usr/local/share/circuit-breaker/frontend \
    /usr/local/share/circuit-breaker/backend \
    /lib/systemd/system/circuit-breaker.service \
    /etc/circuit-breaker/circuit-breaker.env; do
    [ -e "$path" ] || fail "package did not install $path"
done
# postinstall.sh generates this env with a fresh CB_VAULT_KEY and NATS token, so
# it must not be world-readable. Checked here rather than trusted: it is created
# by a shell script at install time, which is exactly where a mode gets missed.
mode="$(stat -c '%a' /etc/circuit-breaker/circuit-breaker.env)"
[ "$mode" = "600" ] || fail "env file mode is $mode, expected 600"
cp /etc/circuit-breaker/circuit-breaker.env "$EVIDENCE/installed.env.redacted"
sed -i 's/=.*/=<redacted>/' "$EVIDENCE/installed.env.redacted"

section "Assert the installed binary reports the shipped version"
SHIPPED="$(cat /usr/local/share/circuit-breaker/VERSION)"
REPORTED="$(/usr/local/bin/circuit-breaker --version)"
printf 'shipped=%s reported=%s\n' "$SHIPPED" "$REPORTED" | tee "$EVIDENCE/version.txt"
[ "$SHIPPED" = "$REPORTED" ] \
    || fail "binary reports '$REPORTED' but the shipped VERSION says '$SHIPPED'"

# The `cb` CLI is NOT shipped by nfpm.yaml -- contents: installs the
# circuit-breaker binary, the frontend and backend trees, VERSION, the agent
# binaries, the config template and the unit, and nothing else. Recorded rather
# than asserted: this tier reports what the package does, and "the operator CLI
# the docs reference is absent from the package" is a finding for the phase
# report, not something to quietly assert into existence.
if [ -x /usr/local/bin/cb ]; then
    /usr/local/bin/cb --help > "$EVIDENCE/cb-help.txt" 2>&1
else
    printf 'SKIPPED (not shipped by nfpm.yaml): the cb operator CLI\n' \
        | tee "$EVIDENCE/cb-cli.txt"
fi

# ── boot ────────────────────────────────────────────────────────────────────
section "Start the service"
systemctl daemon-reload
systemctl start circuit-breaker

# Liveness first: it is the weaker claim, and separating the two makes the
# failure legible. "Alive but never ready" is a database or migration problem;
# "never alive" is a packaging or unit problem. A single combined wait would
# report both as one timeout.
section "Wait for /livez"
deadline=$(( SECONDS + 120 ))
until curl -fsS "$BASE_URL/livez" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        capture "$EVIDENCE/journal.log" journalctl -u circuit-breaker --no-pager -n 200
        fail "service never became live within 120s"
    fi
    sleep 2
done
curl -fsS "$BASE_URL/livez" > "$EVIDENCE/livez.json"

section "Wait for /readyz"
# This is the assertion the tier exists for. A package that installs, launches
# and can never reach its database satisfies every check the pipeline had before
# this one.
deadline=$(( SECONDS + 180 ))
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")" = "200" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        capture "$EVIDENCE/readyz.json" curl -s "$BASE_URL/readyz"
        capture "$EVIDENCE/journal.log" journalctl -u circuit-breaker --no-pager -n 200
        fail "service never became ready within 180s — see readyz.json and journal.log"
    fi
    sleep 3
done
curl -fsS "$BASE_URL/readyz" | tee "$EVIDENCE/readyz.json"

section "Assert readiness means what it says"
python3 - "$EVIDENCE/readyz.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body["ready"] is True, body
assert body["state"] == "ready", body
for dep, verdict in body["checks"].items():
    assert verdict == "ok", f"{dep} reported {verdict}: {body}"
print("readyz:", body["checks"])
PY

# ── exercise ────────────────────────────────────────────────────────────────
section "Assert migrations reached head"
# The schema is what /readyz's contract check probes, so this is partly implied
# above -- but implied is not reported. A named revision in the evidence is what
# makes an upgrade test possible in Phase 3.
sudo -u postgres psql -d circuitbreaker -tAc \
    'SELECT version_num FROM alembic_version' > "$EVIDENCE/alembic_version.txt"
[ -s "$EVIDENCE/alembic_version.txt" ] \
    || fail "alembic_version is empty — migrations did not run against the packaged database"

section "Exercise a real API path"
# Not another health endpoint: those share a code path with the probes above and
# would re-assert the same thing. A route that touches the ORM and serialises a
# model is what proves the packaged backend tree is complete -- issue #104's
# class, where a module is missing only in the packaged build.
code="$(curl -s -o "$EVIDENCE/api-probe.json" -w '%{http_code}' "$BASE_URL/health")"
printf 'GET /health -> %s\n' "$code" | tee -a "$EVIDENCE/api-probe.txt"
[ "$code" = "200" ] || fail "GET /api/v1/health returned $code"

section "Collect evidence"
capture "$EVIDENCE/journal.log" journalctl -u circuit-breaker --no-pager -n 500
capture "$EVIDENCE/unit-state.txt" systemctl show circuit-breaker -p ActiveState -p SubState -p ExecMainStatus
capture "$EVIDENCE/data-dir.txt" ls -la /var/lib/circuit-breaker
capture "$EVIDENCE/package-contents.txt" rpm -ql circuit-breaker

readable_evidence

section "Tier 3 complete"
