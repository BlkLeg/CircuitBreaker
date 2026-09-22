#!/usr/bin/env bash
#
# Run install.sh end to end and prove the result works, upgrades, recovers and
# uninstalls.
#
# Nothing had ever executed this installer. pages.yml published it, release.yml
# attached it, and tests/build/ greps its text — so every defect in the most
# prominently documented install path was found by users. That is also how
# uninstall.sh came to skip the install.sh layout entirely (its native section
# matched only the packaged `circuit-breaker` spelling, never `circuitbreaker`)
# and still report success: nothing had ever run it against a native install.
#
# One file, run identically in CI and locally, because a journey that only
# exists as workflow YAML cannot be reproduced when it fails.
#
# Usage: installer-journey.sh <bundle.tar.gz>
set -euo pipefail

BUNDLE="${1:?usage: installer-journey.sh <bundle.tar.gz>}"
# 8088 is nginx's front port (install.sh:40 CB_PORT), and nginx proxies
# `location /api/` to the backend on 127.0.0.1:8000
# (deploy/systemd/circuitbreaker-backend.service:39 forces --port 8000).
# Health routes live under the v1 prefix (api/routing.py:522), so the paths
# below are /api/v1/..., not bare. NOTE: the PACKAGED deb/rpm unit uses 8080
# instead — do not copy this port into that gate, or that one into this.
PORT="${CB_JOURNEY_PORT:-8088}"
READY_BUDGET="${CB_JOURNEY_READY_BUDGET:-180}"
EVIDENCE="${CB_JOURNEY_EVIDENCE:-/tmp/installer-journey}"

BASE="http://127.0.0.1:${PORT}/api/v1"
ENV_FILE=/etc/circuitbreaker/.env
DATA_DIR=/var/lib/circuitbreaker

# Every unit install.sh creates. Used by the enablement, reboot-equivalent and
# uninstall assertions, so the three cannot drift apart from each other.
CB_UNITS=(
  circuitbreaker-postgres
  circuitbreaker-pgbouncer
  circuitbreaker-redis
  circuitbreaker-nats
  circuitbreaker-backend
)

# The worker instances install.sh enables. Kept apart from CB_UNITS because they
# are instances of one template unit, so the uninstall assertion's per-unit file
# check does not apply to them.
#
# Nothing here used to look at them at all, and their absence is invisible from
# the outside: the API serves, /readyz passes, migrations run and bootstrap
# succeeds with all five dead. On Arch every one of them exits at startup, and
# the only reason that ever surfaced was a side effect — the workers declared
# the same RuntimeDirectory as the backend, so their exit deleted
# /run/circuitbreaker, and the journey failed on the missing directory three
# assertions later. Fixing that would have made Arch green with the whole
# background tier dead, which is the exact shape of the v0.4.2 failure: a fully
# green pipeline attesting nothing.
CB_WORKER_UNITS=(
  circuitbreaker-worker@discovery
  circuitbreaker-worker@notification
  circuitbreaker-worker@telemetry
  circuitbreaker-worker@monitor_scheduler
  circuitbreaker-worker@monitor_poll
)

mkdir -p "$EVIDENCE"

section() { printf '\n=== %s ===\n' "$1"; }

# Collected on every failure, not just the install one. The previous version
# dumped the last 200 lines of the install log and a unit listing, which is why
# a Rocky Linux failure whose cause was the rendered Redis config could only be
# guessed at from the journal: the rendered config was never captured.
#
# Secrets are stripped by value, not by key name: `cb_redacted_env` rewrites
# every VALUE, so a key added to .env later is redacted by default rather than
# leaking until someone remembers to extend a deny-list.
collect_evidence() {
  { systemctl status 'circuitbreaker-*' --no-pager -l || true; } > "$EVIDENCE/systemd-status.txt" 2>&1
  { journalctl -u 'circuitbreaker-*' --no-pager -n 400 || true; } > "$EVIDENCE/journal.txt" 2>&1
  { systemctl list-unit-files 'circuitbreaker*' --no-pager || true; } > "$EVIDENCE/unit-files.txt" 2>&1
  cp /var/lib/circuitbreaker/logs/install.log "$EVIDENCE/install.log" 2>/dev/null || true

  # Rendered configuration, with every value blanked. The SHAPE is the
  # evidence — which keys exist, which paths a unit names, which binary an
  # ExecStart resolved to — and none of that needs a value to be readable.
  sed -E 's/=.*/=<redacted>/' "$ENV_FILE" > "$EVIDENCE/env.redacted" 2>/dev/null || true
  sed -E 's/^(requirepass|masterauth|user)[[:space:]]+.*/\1 <redacted>/' \
    /etc/redis/redis.conf > "$EVIDENCE/redis.conf.redacted" 2>/dev/null || true
  for unit in "${CB_UNITS[@]}"; do
    cp "/etc/systemd/system/${unit}.service" "$EVIDENCE/${unit}.service" 2>/dev/null || true
  done
  { ls -la /etc/circuitbreaker /opt/circuitbreaker "$DATA_DIR" || true; } > "$EVIDENCE/ownership.txt" 2>&1
  { getcap /opt/circuitbreaker/bin/circuit-breaker || true; } > "$EVIDENCE/capabilities.txt" 2>&1
  { nginx -T || true; } > "$EVIDENCE/nginx.txt" 2>&1
}

fail() {
  printf '::error::%s\n' "$1" >&2
  section "Diagnostics"
  collect_evidence
  tail -n 200 "$EVIDENCE/install.log" 2>/dev/null || true
  cat "$EVIDENCE/systemd-status.txt" 2>/dev/null || true
  tail -n 200 "$EVIDENCE/journal.txt" 2>/dev/null || true
  echo "--- rendered configuration (values redacted) ---"
  cat "$EVIDENCE/env.redacted" 2>/dev/null || true
  cat "$EVIDENCE/redis.conf.redacted" 2>/dev/null || true
  echo "Full evidence under: $EVIDENCE"
  exit 1
}

# The value of one key in .env, without sourcing the file. Sourcing would run
# whatever is in there, and this script reads it while asserting things about
# how it was rendered.
env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }

wait_for_ready() {
  local budget="$1" deadline code=000
  deadline=$(( SECONDS + budget ))
  while [ "$SECONDS" -lt "$deadline" ]; do
    code="$(curl -s -o "$EVIDENCE/readyz.json" -w '%{http_code}' "${BASE}/readyz")" || code=000
    [ "$code" = "200" ] && return 0
    sleep 2
  done
  echo "$code"
  return 1
}

# ─────────────────────────────────────────────────────────────────────────────
section "Install from the staged bundle"
# --local-bundle, so the journey does not depend on a published release and
# makes no outbound request for the artifact under test. --unattended, because
# there is no operator. --no-tls, because a self-signed certificate adds a
# failure mode this job is not trying to characterise.
#
# Output is captured rather than streamed so the phase ledger can be asserted
# below; it is echoed back on both paths so a failure is still readable.
set +e
bash install.sh --local-bundle "$BUNDLE" --unattended --no-tls \
  > "$EVIDENCE/install-stdout.log" 2>&1
INSTALL_RC=$?
set -e
cat "$EVIDENCE/install-stdout.log"
[ "$INSTALL_RC" -eq 0 ] || fail "install.sh exited $INSTALL_RC"

section "Assert the installer reported every phase"
# --unattended selects the renderer's plain mode, which prints one timestamped
# line per phase transition. The final phase is the one that proves the run
# reached the end rather than exiting early with status 0 from a subshell.
for phase in \
  "Pre-flight checks" \
  "Downloading bundle" \
  "Installing files" \
  "System dependencies" \
  "Preparing database" \
  "Services and networking" \
  "Starting Circuit Breaker"; do
  grep -qF "$phase" "$EVIDENCE/install-stdout.log" \
    || fail "installer never reported the phase: $phase"
done

section "Wait for /livez"
for _ in $(seq 1 60); do
  curl -fsS "${BASE}/livez" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "${BASE}/livez" > "$EVIDENCE/livez.json" \
  || fail "service never answered /livez"

section "Wait for /readyz"
READY_CODE="$(wait_for_ready "$READY_BUDGET")" \
  || fail "service never became ready (last /readyz was $READY_CODE)"
cat "$EVIDENCE/readyz.json"

# ─────────────────────────────────────────────────────────────────────────────
section "Assert every generated secret is real and private"
# install.sh generates five secrets. A blank or placeholder one does not fail
# the install — the backend simply refuses to authenticate anything later — and
# an .env readable by every account on the host hands over the vault key.
for key in CB_JWT_SECRET CB_VAULT_KEY CB_DB_PASSWORD CB_REDIS_PASSWORD CB_NATS_TOKEN; do
  value="$(env_value "$key")"
  [ -n "$value" ] || fail "$key is empty in $ENV_FILE"
  case "${value,,}" in
    changeme|change_me|placeholder|todo|password|secret)
      fail "$key holds the placeholder value '$value'" ;;
  esac
done

ENV_MODE="$(stat -c '%a' "$ENV_FILE")"
ENV_OWNER="$(stat -c '%U:%G' "$ENV_FILE")"
echo "$ENV_FILE is $ENV_MODE $ENV_OWNER"
case "$ENV_MODE" in
  600|640) : ;;
  *) fail "$ENV_FILE is mode $ENV_MODE — the vault key and every password are in it" ;;
esac
[ "$ENV_OWNER" = "root:breaker" ] \
  || fail "$ENV_FILE is owned by $ENV_OWNER, expected root:breaker"

# ─────────────────────────────────────────────────────────────────────────────
section "Assert the readiness probe authenticates against the rendered Redis config"
# The regression test for the Rocky Linux 10 failure, exercising the rendered
# config and the real readiness command rather than grepping either for a
# string.
#
# That failure looked like this: Redis was healthy, `cb doctor` reported it OK,
# the password was correct — and the backend died with "Redis did not accept
# authenticated connections within 60s" because wait-for-services.sh invoked a
# hardcoded `redis-cli`, which does not exist on a host that ships Valkey.
# Nothing in the suite could tell that apart from a wrong password, so it was
# guessed at twice.
#
# Three properties, in the order they fail:
#   1. the config the server loaded and the password the client will use are
#      the same string — a render that dropped the substitution fails here;
#   2. the readiness command resolves a client that exists on THIS distro;
#   3. it actually authenticates, run exactly as the unit runs it.
[ -f /etc/redis/redis.conf ] || fail "install.sh did not render /etc/redis/redis.conf"

REDIS_CONF_PASS="$(sed -n 's/^requirepass[[:space:]]\+//p' /etc/redis/redis.conf | tail -n1)"
REDIS_ENV_PASS="$(env_value CB_REDIS_PASSWORD)"
[ -n "$REDIS_CONF_PASS" ] \
  || fail "/etc/redis/redis.conf has no requirepass — Redis is unauthenticated"
[ "$REDIS_CONF_PASS" = "$REDIS_ENV_PASS" ] \
  || fail "the requirepass in /etc/redis/redis.conf is not the CB_REDIS_PASSWORD in $ENV_FILE (lengths ${#REDIS_CONF_PASS} vs ${#REDIS_ENV_PASS}) — the backend can never authenticate"

RESOLVED_CLI="$(command -v redis-cli 2>/dev/null || command -v valkey-cli 2>/dev/null || true)"
[ -n "$RESOLVED_CLI" ] \
  || fail "neither redis-cli nor valkey-cli is installed, so nothing can verify Redis"
echo "readiness client on this distro: $RESOLVED_CLI"
printf '%s\n' "$RESOLVED_CLI" > "$EVIDENCE/redis-client.txt"

# The shipped script, at its installed path, run as the account the unit runs
# it as. Running it as root would not prove the backend can — .env is mode 0640
# root:breaker, so root would read it either way.
#
# `runuser`, not `sudo`: sudo is absent from the debian:12 and fedora base
# images this journey runs on, and this script is already root. The redirection
# is performed by this shell (which owns $EVIDENCE) rather than by the
# unprivileged child, which is what shellcheck's SC2024 is about; here it is
# what we want.
if ! runuser -u breaker -- /opt/circuitbreaker/scripts/wait-for-services.sh \
     > "$EVIDENCE/wait-for-services.log" 2>&1; then
  cat "$EVIDENCE/wait-for-services.log"
  fail "wait-for-services.sh failed against a healthy install"
fi
cat "$EVIDENCE/wait-for-services.log"

# ─────────────────────────────────────────────────────────────────────────────
section "Assert migrations reached the database"
# /readyz reports db:ok from a connection, which an empty database satisfies
# too. alembic_version is the row that proves migrations ran.
# Through pgbouncer on 6432 with the application's own credentials: the same
# path the backend uses, so a pooler that is up but refusing the pool fails here
# rather than later.
REVISION="$(PGPASSWORD="$(env_value CB_DB_PASSWORD)" psql -h 127.0.0.1 -p 6432 -U breaker \
  -d circuitbreaker -tAc 'SELECT version_num FROM alembic_version' 2>"$EVIDENCE/psql-err.txt" \
  | tr -d '[:space:]')"
[ -n "$REVISION" ] \
  || fail "alembic_version is empty — the service is running against an unmigrated database"
echo "migrations at revision $REVISION"
printf '%s\n' "$REVISION" > "$EVIDENCE/alembic_version.txt"

# ─────────────────────────────────────────────────────────────────────────────
section "Complete first-run bootstrap and make an authenticated request"
# /livez and /readyz are both unauthenticated, so everything above passes on a
# build whose auth stack never loaded. This section is what separates "the
# process is listening" from "the application works".
#
# Generated per run and thrown away with the container, per CLAUDE.md's rule
# that no credential is committed — including in fixtures.
ADMIN_EMAIL="journey-admin@local.invalid"
ADMIN_PASSWORD="Journey-$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9')!aA1"

# The setup token is minted lazily, by this call. Nothing writes it at install
# time, so looking for the file first finds nothing — and `setup_token_path` is
# the server's own answer for where it put it, which beats this script
# reconstructing the path from CB_DATA_DIR.
STATUS="$(curl -fsS "${BASE}/bootstrap/status")" \
  || fail "GET /bootstrap/status failed on a freshly installed host"
printf '%s\n' "$STATUS" > "$EVIDENCE/bootstrap-status.json"

# jq, not python3. The archlinux base image ships no Python, and the journey's
# container bootstrap installs curl/jq/openssl/ca-certificates — the tools
# install.sh itself needs — on every family. A `$(python3 ...)` here failed
# with "command not found" inside a command substitution, and the `|| fail`
# that followed reported it as "this database is not clean": a true statement
# about the exit status and a false one about the cause.
NEEDS_BOOTSTRAP="$(jq -r '.needs_bootstrap' < "$EVIDENCE/bootstrap-status.json")"
[ "$NEEDS_BOOTSTRAP" = "true" ] \
  || fail "a freshly installed host reports needs_bootstrap=${NEEDS_BOOTSTRAP} — this database is not clean"

TOKEN_FILE="$(jq -r '.setup_token_path // empty' < "$EVIDENCE/bootstrap-status.json")"
[ -n "$TOKEN_FILE" ] || TOKEN_FILE="$DATA_DIR/bootstrap-setup-token"
[ -f "$TOKEN_FILE" ] \
  || fail "no bootstrap setup token at $TOKEN_FILE — first-run setup is unreachable on a fresh install"
[ "$(stat -c '%a' "$TOKEN_FILE")" = "600" ] \
  || fail "the setup token at $TOKEN_FILE is mode $(stat -c '%a' "$TOKEN_FILE") — it grants admin until it is used"
SETUP_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"

ADMIN_TOKEN="$(curl -fsS -H 'Content-Type: application/json' \
  -d "{\"setup_token\":\"${SETUP_TOKEN}\",\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\",\"theme_preset\":\"gruvbox-dark\"}" \
  "${BASE}/bootstrap/initialize" \
  | jq -er '.token')" \
  || fail "first-run bootstrap failed on a freshly installed host"

# Asserted AFTER bootstrap, deliberately. Before it, `auth_enabled` is false
# and core/security.py hands the admin sentinel to the first-run setup surface
# — /api/v1/bootstrap, /api/v1/auth, and the settings read the wizard needs —
# so an unauthenticated GET /auth/me answers 200 by design. Asserting the 401
# there would have been asserting the opposite of the documented behaviour.
# Once an admin exists, the guard is the real property, and without this check
# the 200 below would also be satisfied by a service that authenticates nobody.
UNAUTHED="$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/auth/me")"
[ "$UNAUTHED" = "401" ] \
  || fail "after bootstrap, GET /auth/me without a token answered $UNAUTHED, expected 401 — the API is not guarded"

curl -fsS -H "Authorization: Bearer ${ADMIN_TOKEN}" "${BASE}/auth/me" \
  > "$EVIDENCE/auth-me.json" \
  || fail "an authenticated request failed after bootstrap"
PROFILE_EMAIL="$(jq -r '.email // empty' < "$EVIDENCE/auth-me.json")"
[ "$PROFILE_EMAIL" = "$ADMIN_EMAIL" ] \
  || fail "/auth/me returned ${PROFILE_EMAIL:-<no email>}, expected ${ADMIN_EMAIL} — the token authenticated something other than the account bootstrap just created"
echo "authenticated as ${PROFILE_EMAIL}"

# ─────────────────────────────────────────────────────────────────────────────
section "Assert the installed layout, ownership, capabilities and ordering"
# The binary needs CAP_NET_RAW to send ICMP without running as root; the unit
# also declares it as an ambient capability. If setcap silently did nothing,
# discovery fails at runtime with a permission error and nothing here notices.
getcap /opt/circuitbreaker/bin/circuit-breaker | grep -q 'cap_net_raw' \
  || fail "CAP_NET_RAW was not granted to the installed binary — ICMP discovery cannot work"

[ "$(stat -c '%U' "$DATA_DIR")" = "breaker" ] \
  || fail "$DATA_DIR is not owned by breaker (found $(stat -c '%U' "$DATA_DIR"))"

# /run/circuitbreaker holds the vault key the backend reads at every start and
# the socket cb-helperd binds. It is created by
# /usr/lib/tmpfiles.d/circuitbreaker.conf rather than by any unit's
# RuntimeDirectory=, because systemd removes a runtime directory when any one
# declaring unit stops — which used to let a worker exit delete it from under
# the running backend.
[ -d /run/circuitbreaker ] \
  || fail "/run/circuitbreaker was not created — /usr/lib/tmpfiles.d/circuitbreaker.conf did not take effect"

# Every background worker has to be running, not merely enabled. A worker that
# exits at startup takes discovery, telemetry, notifications and monitoring with
# it while every foreground check above still passes.
for unit in "${CB_WORKER_UNITS[@]}"; do
  systemctl is-active --quiet "$unit" || fail \
    "$unit is not running (Result=$(systemctl show -p Result --value "$unit" 2>/dev/null)); \
background work — discovery, telemetry, notifications, monitoring — is dead while the API looks healthy"
done
echo "all ${#CB_WORKER_UNITS[@]} workers running"

# Ordering: the backend must come after its dependencies, or a reboot races it
# against a database that has not started.
for dependency in circuitbreaker-pgbouncer.service circuitbreaker-redis.service circuitbreaker-nats.service; do
  systemctl show circuitbreaker-backend.service -p After --value | grep -qw "$dependency" \
    || fail "circuitbreaker-backend.service is not ordered After=$dependency"
done

nginx -t >/dev/null 2>&1 || fail "the nginx configuration install.sh wrote does not validate"

# ─────────────────────────────────────────────────────────────────────────────
section "Restart recovery"
systemctl restart circuitbreaker-backend || fail "circuitbreaker-backend failed to restart"
READY_CODE="$(wait_for_ready 120)" \
  || fail "service did not become ready again after a restart (last /readyz was $READY_CODE)"
echo "ready again after restart"

# ─────────────────────────────────────────────────────────────────────────────
section "Reboot-equivalent recovery"
# A container cannot reboot, so this asserts the two properties a reboot
# depends on, separately and for real:
#
#   1. every unit is ENABLED — that, not the fact it is currently running, is
#      what starts it again after a power cycle;
#   2. the whole tree comes back from fully stopped, in dependency order,
#      without any of the configuration steps being re-run.
#
# Asserting only the second would pass on a host where nothing is enabled and
# therefore nothing comes back after an actual reboot.
for unit in "${CB_UNITS[@]}"; do
  state="$(systemctl is-enabled "$unit" 2>&1 || true)"
  [ "$state" = "enabled" ] \
    || fail "$unit is '$state', not enabled — it would not come back after a reboot"
done

systemctl stop circuitbreaker.target >/dev/null 2>&1 || true
for unit in circuitbreaker-backend "${CB_UNITS[@]}"; do
  systemctl stop "$unit" >/dev/null 2>&1 || true
done
# `if`, never `cmd && fail`: under `set -e` an AND-list whose left side fails is
# itself a failing statement, so the healthy case — is-active returning
# non-zero for a stopped unit — would end the journey right here.
if systemctl is-active --quiet circuitbreaker-backend; then
  fail "circuitbreaker-backend is still active after being stopped"
fi

for unit in "${CB_UNITS[@]}"; do
  systemctl start "$unit" || fail "$unit did not start from a fully stopped state"
done
READY_CODE="$(wait_for_ready 180)" \
  || fail "service did not come back from a full stop (last /readyz was $READY_CODE)"
echo "ready again from a fully stopped state"

# ─────────────────────────────────────────────────────────────────────────────
section "Rerun the installer (upgrade path) and assert it is idempotent"
# Self-hosters re-run install.sh to upgrade, and CLAUDE.md's backward-
# compatibility rule means a re-run on an already-installed host has to work
# and has to preserve the deployment. The two ways that goes wrong are both
# silent: regenerated secrets (which orphan the vault-encrypted data) and a
# service left down.
SECRETS_BEFORE="$(for key in CB_JWT_SECRET CB_VAULT_KEY CB_DB_PASSWORD CB_REDIS_PASSWORD CB_NATS_TOKEN; do
  env_value "$key"
done | sha256sum | cut -d' ' -f1)"

set +e
bash install.sh --local-bundle "$BUNDLE" --unattended --no-tls \
  > "$EVIDENCE/upgrade-stdout.log" 2>&1
UPGRADE_RC=$?
set -e
cat "$EVIDENCE/upgrade-stdout.log"
[ "$UPGRADE_RC" -eq 0 ] || fail "re-running install.sh on an installed host exited $UPGRADE_RC"

SECRETS_AFTER="$(for key in CB_JWT_SECRET CB_VAULT_KEY CB_DB_PASSWORD CB_REDIS_PASSWORD CB_NATS_TOKEN; do
  env_value "$key"
done | sha256sum | cut -d' ' -f1)"
[ "$SECRETS_BEFORE" = "$SECRETS_AFTER" ] \
  || fail "re-running the installer regenerated the secrets — every vault-encrypted value on this host is now unreadable"

READY_CODE="$(wait_for_ready 180)" \
  || fail "service is not ready after an installer re-run (last /readyz was $READY_CODE)"

# The account created before the re-run must survive it: that is what makes
# this an upgrade rather than a reinstall.
curl -fsS -H "Authorization: Bearer ${ADMIN_TOKEN}" "${BASE}/auth/me" >/dev/null 2>&1 \
  || curl -fsS -H 'Content-Type: application/json' \
       -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
       "${BASE}/auth/login" >/dev/null \
  || fail "the admin account did not survive the installer re-run"
echo "upgrade preserved secrets, data and the admin account"

# ─────────────────────────────────────────────────────────────────────────────
section "Assert the installed binary contains its application"
/opt/circuitbreaker/bin/circuit-breaker --selftest \
  || fail "the installed binary failed its self-test"

# ─────────────────────────────────────────────────────────────────────────────
section "Uninstall and assert nothing is left running"
# uninstall.sh is what the docs tell operators to run, and until this ran it had
# never been executed against an install.sh deployment. It skipped the whole
# layout — its native section matched only the packaged `circuit-breaker`
# paths — and exited 0 with every service still running.
#
# --purge is consent expressed on the command line; there is no terminal here to
# answer the prompt with, and answering it any other way would not be consent.
collect_evidence

# The uninstaller the INSTALL put there, not a copy from the source tree: that
# is what `cb uninstall` runs and what an operator with no checkout has. Its
# absence used to be the whole story — `cb uninstall` told them to run it from
# a checkout of a host installed from a tarball.
[ -x /usr/local/bin/uninstall-circuit-breaker ] \
  || fail "the install left no uninstaller at /usr/local/bin/uninstall-circuit-breaker; 'cb uninstall' has nothing to run"

# Through `cb uninstall`, which is what the CLI's help text and the docs tell
# an operator to run, rather than calling the uninstaller directly. That
# exercises both halves: the CLI resolving and forwarding to the installed
# uninstaller, and the uninstaller itself. `cb uninstall`'s native branch used
# to remove things on its own — and left every unit file enabled, pointing at a
# directory it had just deleted.
#
# --purge is consent expressed on the command line; there is no terminal here to
# answer the prompt with, and answering it any other way would not be consent.
[ -x /usr/local/bin/cb ] || fail "the install left no cb CLI at /usr/local/bin/cb"
if ! cb uninstall --purge > "$EVIDENCE/uninstall-stdout.log" 2>&1; then
  cat "$EVIDENCE/uninstall-stdout.log"
  fail "cb uninstall --purge exited non-zero"
fi
cat "$EVIDENCE/uninstall-stdout.log"

for unit in "${CB_UNITS[@]}"; do
  if systemctl is-active --quiet "$unit"; then
    fail "$unit is still running after uninstall"
  fi
  [ ! -e "/etc/systemd/system/${unit}.service" ] \
    || fail "uninstall left /etc/systemd/system/${unit}.service behind"
done

for path in /opt/circuitbreaker /usr/local/bin/cb /etc/circuitbreaker "$DATA_DIR"; do
  [ ! -e "$path" ] || fail "uninstall left $path behind"
done

# The port has to be free again. A listener that outlives the uninstall is the
# symptom operators actually report: "I removed it and it is still there."
#
# Waited for, not sampled once. uninstall.sh removes the nginx site and calls
# `systemctl reload nginx`, which returns as soon as nginx's master accepts the
# SIGHUP — the master then reconfigures and retires its old workers on its own
# schedule, so the listening socket on this port outlives the reload by a short,
# variable interval. Probing immediately therefore fails or passes depending on
# timing: debian12 failed this exact assertion on one run and passed it on a
# re-run of the identical commit, while every other distro passed both times.
#
# A real leak is still caught, and is still the point: what an operator reports
# is a listener that is still there minutes later, not one that is still there
# for two hundred milliseconds. Anything answering after the budget below is
# that leak.
#
# curl deliberately has no -f: a 502 from an nginx that is still listening but
# has nothing to proxy to is exactly the state being looked for, so any HTTP
# response counts as "still serving", not only a healthy one.
# Overridable so the repo-policy test can exercise the leak path without
# waiting out the real budget; the journey itself never sets it.
uninstall_port_wait="${CB_JOURNEY_UNINSTALL_WAIT:-30}"
uninstall_port_deadline=$(( SECONDS + uninstall_port_wait ))
while curl -sS --max-time 5 "${BASE}/livez" >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$uninstall_port_deadline" ]; then
    fail "something is still serving :${PORT} ${uninstall_port_wait}s after uninstall"
  fi
  sleep 1
done
echo "uninstall clean"

section "Journey complete"
