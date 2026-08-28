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

PACKAGE="${1:?usage: tier3-artifact.sh <candidate-package> [previous-package]}"
# Optional. Present => this row runs the upgrade and rollback contract, which is
# what backs the Tier 1 guarantee's second half (ADR 0005 §8). Absent => the
# install-and-boot contract Phase 2 shipped, unchanged.
PREVIOUS="${2:-}"
EVIDENCE=/tmp/cb-tier3-evidence
BASE_URL="http://127.0.0.1:8000/api/v1"
ENV_FILE=/etc/circuit-breaker/circuit-breaker.env
BACKUP_GLOB='/var/lib/circuit-breaker/backups/pre-upgrade-*.sql'
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

# ── the package manager, chosen by what we were handed ──────────────────────
#
# Slice 2. The design's P1 says tier3-artifact.sh is "identical across every row"
# and Phase 2 satisfied that by only ever having one row: every install, query
# and downgrade below was a bare dnf/rpm call. Identical-because-unshared is not
# the property P1 wants.
#
# So the file is still one file, pushed byte-identical to every guest, and it
# branches on the artifact it is given rather than on a variable the caller sets.
# The candidate's extension is the honest discriminator: a row that hands this
# script a .deb IS a deb row, and a mismatch between the row and the artifact
# becomes a visible failure here instead of a plausible-looking dnf error.
case "$PACKAGE" in
    *.rpm) PKG_FORMAT=rpm ;;
    *.deb) PKG_FORMAT=deb ;;
    *)     fail "unsupported candidate format: $PACKAGE (this tier installs .rpm and .deb)" ;;
esac
if [ -n "$PREVIOUS" ] && [ "${PREVIOUS##*.}" != "$PKG_FORMAT" ]; then
    fail "candidate is .$PKG_FORMAT but previous is .${PREVIOUS##*.} — an upgrade across package formats is not a thing"
fi

pkg::install_dir() {
    # Every package in the directory, not just the named candidate. On a real
    # host `dnf install circuit-breaker` also pulls circuit-breaker-nats, because
    # the rpm recommends it and dnf installs weak dependencies by default.
    # Installing from local files cannot resolve that, so dispatch.sh pushes the
    # companion and this installs the set -- otherwise the tier would test a
    # configuration no user has.
    case "$PKG_FORMAT" in
        rpm) dnf install -y "$1"/*.rpm ;;
        # --install-recommends is explicit rather than relied upon. apt installs
        # recommends by default, but a host with APT::Install-Recommends "false"
        # would silently drop the companion broker and produce an install no user
        # has -- the same class of difference the rpm side pushes the companion to
        # avoid. The paths are absolute, which is what makes apt treat them as
        # files rather than as package names.
        deb) DEBIAN_FRONTEND=noninteractive apt-get install -y --install-recommends "$1"/*.deb ;;
    esac
}

pkg::downgrade_to() {
    # The application package only, not the whole directory. The companion
    # circuit-breaker-nats package is very often the SAME version in both builds
    # -- it tracks the pinned upstream broker, not this project's VERSION -- and
    # both managers error rather than shrugging when a named package has no lower
    # version to move to.
    case "$PKG_FORMAT" in
        rpm) dnf downgrade -y "$1" ;;
        # apt refuses a downgrade unless told; without the flag it reports the
        # newer installed version as satisfying the request and exits zero,
        # which would leave the new binary in place and let the rollback
        # assertion fail somewhere far away from the cause.
        deb) DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades "$1" ;;
    esac
}

pkg::list_contents() {
    case "$PKG_FORMAT" in
        rpm) rpm -ql circuit-breaker ;;
        deb) dpkg -L circuit-breaker ;;
    esac
}

# ── reusable steps ──────────────────────────────────────────────────────────
# Phase 2 ran these once, top to bottom. Phase 3 runs the boot-and-exercise set
# three times against three different states of the same host -- the previous
# version, the upgraded version, and the rolled-back version -- so they are
# functions now. The assertions themselves are unchanged; what changed is that
# each one takes the label its evidence is filed under, because "readyz.json"
# written three times is two thirds of an account of what happened.

t3::install_set() {
    local label=$1 dir=$2
    section "Install $label from $dir ($PKG_FORMAT)"
    # The package's own dependency resolution, which is what a user gets. Both
    # families list postgresql/redis under weak or ordinary dependencies, so this
    # pulls them but does not configure them -- the VM fixture already did that,
    # because nothing in the package ever will.
    pkg::install_dir "$dir" 2>&1 | tee "$EVIDENCE/install-$label.log"
}

t3::assert_installed_paths() {
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
    local mode
    mode="$(stat -c '%a' "$ENV_FILE")"
    [ "$mode" = "600" ] || fail "env file mode is $mode, expected 600"
    cp "$ENV_FILE" "$EVIDENCE/installed.env.redacted"
    sed -i 's/=.*/=<redacted>/' "$EVIDENCE/installed.env.redacted"
}

t3::assert_rollback_tooling_is_shipped() {
    # ADR 0005 Phase 3. The compatibility policy defines rollback as restoring the
    # pre-upgrade backup and the upgrade docs name the script that does it; before
    # this phase neither the script nor a wrapper that knows this layout was in
    # nfpm.yaml's contents, so the documented recovery could not be performed on a
    # packaged host at all. Asserted rather than recorded -- unlike the absent `cb`
    # CLI below -- because a Tier 1 row claims rollback works, and a rollback whose
    # tool is missing is not a gap in coverage, it is the claim being false.
    section "Assert the rollback tooling is shipped"
    for path in \
        /usr/local/bin/circuit-breaker-rollback \
        /usr/local/share/circuit-breaker/deploy/scripts/restore.sh; do
        [ -x "$path" ] || fail "package did not install an executable $path"
    done
    # Not capture(): the wrapper exits 2 when called with no argument, which is
    # its documented "here is what you can restore" behaviour rather than a
    # collection failure. Recording it as one would put a warning in the log
    # dispatch.sh prints on a passing run, and a warnings file that cries wolf
    # is a warnings file nobody reads.
    local rc=0
    /usr/local/bin/circuit-breaker-rollback > "$EVIDENCE/rollback-usage.txt" 2>&1 || rc=$?
    [ "$rc" = "2" ] || fail "circuit-breaker-rollback with no argument exited $rc, expected 2 (usage)"
}

t3::assert_version_matches() {
    local label=$1
    section "Assert the installed binary reports the shipped version ($label)"
    local shipped reported
    shipped="$(cat /usr/local/share/circuit-breaker/VERSION)"
    reported="$(/usr/local/bin/circuit-breaker --version)"
    printf 'shipped=%s reported=%s\n' "$shipped" "$reported" | tee "$EVIDENCE/version-$label.txt"
    [ "$shipped" = "$reported" ] \
        || fail "binary reports '$reported' but the shipped VERSION says '$shipped'"
}

t3::record_cb_cli() {
    # The `cb` CLI is NOT shipped by nfpm.yaml -- contents: installs the
    # circuit-breaker binary, the frontend and backend trees, VERSION, the agent
    # binaries, the config template, the unit and (since Phase 3) the rollback
    # tooling, and nothing else. Recorded rather than asserted: this tier reports
    # what the package does, and "the operator CLI the docs reference is absent
    # from the package" is a finding for the phase report, not something to
    # quietly assert into existence.
    if [ -x /usr/local/bin/cb ]; then
        /usr/local/bin/cb --help > "$EVIDENCE/cb-help.txt" 2>&1
    else
        printf 'SKIPPED (not shipped by nfpm.yaml): the cb operator CLI\n' \
            | tee "$EVIDENCE/cb-cli.txt"
    fi
}

t3::start_and_wait_ready() {
    local label=$1
    section "Start the service ($label)"
    systemctl daemon-reload
    systemctl start circuit-breaker

    # Liveness first: it is the weaker claim, and separating the two makes the
    # failure legible. "Alive but never ready" is a database or migration problem;
    # "never alive" is a packaging or unit problem. A single combined wait would
    # report both as one timeout.
    section "Wait for /livez ($label)"
    local deadline=$(( SECONDS + 120 ))
    until curl -fsS "$BASE_URL/livez" >/dev/null 2>&1; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            capture "$EVIDENCE/journal-$label.log" journalctl -u circuit-breaker --no-pager -n 200
            fail "[$label] service never became live within 120s"
        fi
        sleep 2
    done
    curl -fsS "$BASE_URL/livez" > "$EVIDENCE/livez-$label.json"

    section "Wait for /readyz ($label)"
    # This is the assertion the tier exists for. A package that installs, launches
    # and can never reach its database satisfies every check the pipeline had before
    # this one.
    deadline=$(( SECONDS + 180 ))
    until [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")" = "200" ]; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            capture "$EVIDENCE/readyz-$label.json" curl -s "$BASE_URL/readyz"
            capture "$EVIDENCE/journal-$label.log" journalctl -u circuit-breaker --no-pager -n 200
            fail "[$label] service never became ready within 180s — see readyz-$label.json and journal-$label.log"
        fi
        sleep 3
    done
    curl -fsS "$BASE_URL/readyz" | tee "$EVIDENCE/readyz-$label.json"

    section "Assert readiness means what it says ($label)"
    python3 - "$EVIDENCE/readyz-$label.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body["ready"] is True, body
assert body["state"] == "ready", body
for dep, verdict in body["checks"].items():
    assert verdict == "ok", f"{dep} reported {verdict}: {body}"
print("readyz:", body["checks"])
PY
}

t3::exercise_api() {
    local label=$1
    section "Exercise a real API path ($label)"
    # Not another health endpoint: those share a code path with the probes above and
    # would re-assert the same thing. A route that touches the ORM and serialises a
    # model is what proves the packaged backend tree is complete -- issue #104's
    # class, where a module is missing only in the packaged build.
    local code
    code="$(curl -s -o "$EVIDENCE/api-probe-$label.json" -w '%{http_code}' "$BASE_URL/health")"
    printf 'GET /health -> %s\n' "$code" | tee -a "$EVIDENCE/api-probe.txt"
    [ "$code" = "200" ] || fail "[$label] GET /api/v1/health returned $code"
}

# ── database helpers ────────────────────────────────────────────────────────
# Through CB_DB_URL from the installed env, not `sudo -u postgres`. Two reasons:
# the app's own credential path is the one worth exercising, and a marker table
# created by the superuser is owned by the superuser -- which pg_dump records and
# a restore replaying as the application role can refuse. The marker has to
# survive a real dump/restore cycle to be worth anything.

t3::db_url() {
    sed -n 's/^CB_DB_URL=//p' "$ENV_FILE" | tail -n 1
}

t3::psql() {
    psql "$(t3::db_url)" -v ON_ERROR_STOP=1 -tAc "$1"
}

t3::alembic_revision() {
    t3::psql 'SELECT version_num FROM alembic_version'
}

t3::marker_write() {
    # A table outside Alembic's control, deliberately. Asserting on application
    # rows would couple this tier to whichever schema the two versions happen to
    # share, and the claim under test is not "the model survived" -- it is "the
    # database this host had before the upgrade is the database it has after the
    # rollback". A row nobody migrates answers exactly that and nothing else.
    t3::psql "CREATE TABLE IF NOT EXISTS cb_tier3_marker (tag text PRIMARY KEY, written_at timestamptz DEFAULT now())" >/dev/null
    t3::psql "INSERT INTO cb_tier3_marker (tag) VALUES ('$1') ON CONFLICT DO NOTHING" >/dev/null
}

t3::marker_count() {
    # Missing table counts as absent rather than erroring: after a rollback to a
    # dump taken before the table existed, "no such relation" IS the answer.
    t3::psql "SELECT count(*) FROM cb_tier3_marker WHERE tag = '$1'" 2>/dev/null || printf '0'
}

t3::latest_backup() {
    # Newest by name. The stamp is %Y%m%d-%H%M%S, so lexical order is chronological.
    local newest=""
    for f in $BACKUP_GLOB; do
        [ -f "$f" ] && newest="$f"
    done
    printf '%s' "$newest"
}

t3::collect() {
    local label=$1
    section "Collect evidence ($label)"
    capture "$EVIDENCE/journal-$label.log" journalctl -u circuit-breaker --no-pager -n 500
    capture "$EVIDENCE/unit-state-$label.txt" systemctl show circuit-breaker -p ActiveState -p SubState -p UnitFileState -p ExecMainStatus
    capture "$EVIDENCE/data-dir-$label.txt" ls -la /var/lib/circuit-breaker
    capture "$EVIDENCE/package-contents-$label.txt" pkg::list_contents
}

# ── install and boot: the Phase 2 contract, run against whichever version
#    this row starts from ─────────────────────────────────────────────────────
if [ -n "$PREVIOUS" ]; then
    START_DIR=/opt/cb-tier3/previous
    START_LABEL=previous
    [ -d "$START_DIR" ] || fail "upgrade row: $START_DIR does not exist — dispatch.sh did not push the previous package set"
else
    START_DIR=/opt/cb-tier3
    START_LABEL=candidate
fi

t3::install_set "$START_LABEL" "$START_DIR"
t3::assert_installed_paths
t3::assert_version_matches "$START_LABEL"
VERSION_AT_START="$(cat /usr/local/share/circuit-breaker/VERSION)"
t3::record_cb_cli
t3::start_and_wait_ready "$START_LABEL"

section "Assert migrations reached head ($START_LABEL)"
# The schema is what /readyz's contract check probes, so this is partly implied
# above -- but implied is not reported. A named revision in the evidence is what
# makes the upgrade assertion below possible.
t3::alembic_revision > "$EVIDENCE/alembic_version-$START_LABEL.txt"
[ -s "$EVIDENCE/alembic_version-$START_LABEL.txt" ] \
    || fail "alembic_version is empty — migrations did not run against the packaged database"

t3::exercise_api "$START_LABEL"

if [ -z "$PREVIOUS" ]; then
    # Phase 2's contract ends here, and the row that carries it is unchanged.
    t3::assert_rollback_tooling_is_shipped
    t3::collect "$START_LABEL"
    readable_evidence
    section "Tier 3 complete (install and boot)"
    exit 0
fi

# ── upgrade ─────────────────────────────────────────────────────────────────
# Everything from here backs the half of the Tier 1 guarantee that ADR 0005's
# in-force clause names: "guaranteed to install, boot, upgrade and roll back".

t3::assert_rollback_tooling_is_shipped
t3::collect "$START_LABEL"

REVISION_BEFORE="$(cat "$EVIDENCE/alembic_version-previous.txt")"
section "Seed a marker row and record the pre-upgrade state"
t3::marker_write before-upgrade
printf 'version=%s revision=%s\n' "$VERSION_AT_START" "$REVISION_BEFORE" \
    | tee "$EVIDENCE/state-before-upgrade.txt"
[ "$(t3::marker_count before-upgrade)" = "1" ] || fail "marker row did not persist before the upgrade"

# Every dump that already exists, so the assertion below is about one this
# transaction wrote rather than one that happened to be lying there.
BACKUPS_BEFORE="$(t3::latest_backup)"

section "Upgrade to the candidate"
CANDIDATE_VERSION_EXPECTED="$(basename "$PACKAGE")"
t3::install_set candidate /opt/cb-tier3

section "Assert the upgrade took a pre-upgrade backup"
# preinstall.sh's gate (ADR 0005 Phase 3). Before it existed, `dnf upgrade`
# migrated the schema and wrote nothing, while the compatibility policy told the
# operator to roll back by restoring a pre-upgrade backup that was never taken.
BACKUP="$(t3::latest_backup)"
[ -n "$BACKUP" ] || fail "no pre-upgrade backup under $BACKUP_GLOB — the upgrade cannot be rolled back"
[ "$BACKUP" != "$BACKUPS_BEFORE" ] \
    || fail "the newest pre-upgrade backup ($BACKUP) predates this upgrade — preinstall did not run"
[ -s "$BACKUP" ] || fail "pre-upgrade backup $BACKUP is empty"
printf 'backup=%s bytes=%s\n' "$BACKUP" "$(stat -c '%s' "$BACKUP")" \
    | tee "$EVIDENCE/pre-upgrade-backup.txt"
cp "$BACKUP" "$EVIDENCE/$(basename "$BACKUP")"

section "Assert the upgrade left the service running and enabled"
# The regression this catches: rpm runs the OLD package's %preun AFTER the NEW
# package's %post, so an unconditional stop+disable in preremove.sh undid the
# enable that postinstall.sh had just performed. Every upgrade finished with the
# service stopped and disabled, and no reboot brought it back. Nothing in the
# pipeline had ever upgraded a packaged service, so nothing saw it.
capture "$EVIDENCE/unit-state-upgraded.txt" \
    systemctl show circuit-breaker -p ActiveState -p SubState -p UnitFileState
systemctl is-enabled --quiet circuit-breaker \
    || fail "service is not enabled after the upgrade — preremove ran on an upgrade transaction"
systemctl is-active --quiet circuit-breaker \
    || fail "service is not running after the upgrade — postinstall did not restart it, or preremove stopped it"

VERSION_AFTER="$(cat /usr/local/share/circuit-breaker/VERSION)"
[ "$VERSION_AFTER" != "$VERSION_AT_START" ] \
    || fail "shipped VERSION is still $VERSION_AT_START after upgrading with $CANDIDATE_VERSION_EXPECTED — the candidate must be a different version from the previous package"

section "Wait for the upgraded service to become ready again"
# Not start_and_wait_ready: the unit is already running. Re-waiting on /readyz is
# what proves the new binary reached its database and migrated it, rather than
# crash-looping under Restart=on-failure while systemd reported "activating".
deadline=$(( SECONDS + 180 ))
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")" = "200" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        capture "$EVIDENCE/readyz-upgraded.json" curl -s "$BASE_URL/readyz"
        capture "$EVIDENCE/journal-upgraded.log" journalctl -u circuit-breaker --no-pager -n 300
        fail "upgraded service never became ready within 180s"
    fi
    sleep 3
done
curl -fsS "$BASE_URL/readyz" | tee "$EVIDENCE/readyz-upgraded.json"

t3::assert_version_matches upgraded
t3::exercise_api upgraded

section "Assert the upgrade preserved the data and advanced the schema"
REVISION_AFTER="$(t3::alembic_revision)"
printf '%s' "$REVISION_AFTER" > "$EVIDENCE/alembic_version-upgraded.txt"
[ -n "$REVISION_AFTER" ] || fail "alembic_version is empty after the upgrade"
[ "$(t3::marker_count before-upgrade)" = "1" ] \
    || fail "the pre-upgrade marker row did not survive the upgrade — data was lost"
printf 'revision_before=%s revision_after=%s\n' "$REVISION_BEFORE" "$REVISION_AFTER" \
    | tee "$EVIDENCE/schema-transition.txt"

# Written after the upgrade, so the rollback has something it must remove. Without
# this the rollback assertion could pass over a restore that did nothing at all.
t3::marker_write after-upgrade
[ "$(t3::marker_count after-upgrade)" = "1" ] || fail "post-upgrade marker row was not written"

t3::collect upgraded

# ── rollback ────────────────────────────────────────────────────────────────
# The documented procedure, in the documented order. Downgrading the package
# first is load-bearing rather than tidy: the pre-upgrade dump carries the OLD
# schema, and main.py runs alembic upgrade head at startup, so restoring under
# the NEW binary would migrate the schema straight back forward and the rollback
# would silently undo itself.

section "Roll back: stop the service"
systemctl stop circuit-breaker

section "Roll back: reinstall the previous package"
pkg::downgrade_to "$PREVIOUS" 2>&1 | tee "$EVIDENCE/downgrade.log"
VERSION_ROLLED_BACK="$(cat /usr/local/share/circuit-breaker/VERSION)"
[ "$VERSION_ROLLED_BACK" = "$VERSION_AT_START" ] \
    || fail "after downgrade the shipped VERSION is $VERSION_ROLLED_BACK, expected $VERSION_AT_START"

section "Roll back: restore the pre-upgrade backup"
# Through the shipped wrapper, exactly as an operator would. Calling restore.sh
# directly would test a code path the docs do not name and would skip the layout
# variables the wrapper exists to supply.
/usr/local/bin/circuit-breaker-rollback "$BACKUP" 2>&1 | tee "$EVIDENCE/rollback.log"

section "Wait for the rolled-back service to become ready"
deadline=$(( SECONDS + 180 ))
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")" = "200" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        capture "$EVIDENCE/readyz-rolledback.json" curl -s "$BASE_URL/readyz"
        capture "$EVIDENCE/journal-rolledback.log" journalctl -u circuit-breaker --no-pager -n 300
        fail "service never became ready within 180s after the rollback"
    fi
    sleep 3
done
curl -fsS "$BASE_URL/readyz" | tee "$EVIDENCE/readyz-rolledback.json"

section "Assert the rollback restored the pre-upgrade state"
REVISION_ROLLED_BACK="$(t3::alembic_revision)"
printf '%s' "$REVISION_ROLLED_BACK" > "$EVIDENCE/alembic_version-rolledback.txt"
[ "$REVISION_ROLLED_BACK" = "$REVISION_BEFORE" ] \
    || fail "schema is at $REVISION_ROLLED_BACK after the rollback, expected the pre-upgrade $REVISION_BEFORE"
[ "$(t3::marker_count before-upgrade)" = "1" ] \
    || fail "the pre-upgrade marker row is missing after the rollback — the restore did not replay the dump"
[ "$(t3::marker_count after-upgrade)" = "0" ] \
    || fail "the post-upgrade marker row survived the rollback — the restore did not replace the database"

t3::assert_version_matches rolledback
t3::exercise_api rolledback
t3::collect rolledback

readable_evidence

section "Tier 3 complete (install, boot, upgrade, roll back)"
