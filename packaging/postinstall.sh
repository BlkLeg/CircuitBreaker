#!/bin/bash
# nfpm scripts.postinstall — rpm %post, deb postinst, apk .post-install.
set -e

# ── is this an upgrade? ─────────────────────────────────────────────────────
# Everything below the config/env section is identical either way; what differs
# is the closing act. A fresh install needs the "next steps" text and a service
# the operator starts once they have pointed CB_DB_URL somewhere. An upgrade
# needs the running service to come back on the new binary, and needs to name
# the backup preinstall.sh just took -- printing "Next steps: 1. Edit the env
# file" at an operator who has been running this for a year is noise that hides
# the one line that matters.
#
#   dpkg postinst : "configure" with the OLD version as $2 on upgrade, empty on install
#   rpm  %post    : 1 on a fresh install, 2 or more on upgrade
#   apk           : no argument
case "${1:-}" in
    configure) if [ -n "${2:-}" ]; then IS_UPGRADE=1; else IS_UPGRADE=0; fi ;;
    "")        IS_UPGRADE=0 ;;
    *)         if [ "$1" -ge 2 ] 2>/dev/null; then IS_UPGRADE=1; else IS_UPGRADE=0; fi ;;
esac

# Create system user if it doesn't exist
if ! id -u circuitbreaker >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin \
    --home-dir /var/lib/circuit-breaker circuitbreaker
fi

# Create directories
mkdir -p /var/lib/circuit-breaker /var/lib/circuit-breaker/uploads \
         /var/log/circuit-breaker /etc/circuit-breaker
chown -R circuitbreaker:circuitbreaker /var/lib/circuit-breaker
chown circuitbreaker:circuitbreaker /var/log/circuit-breaker
chmod 750 /var/lib/circuit-breaker /var/log/circuit-breaker
chmod 755 /etc/circuit-breaker

# Install default config if not present
if [ ! -f /etc/circuit-breaker/config.toml ]; then
  if [ -f /usr/local/share/circuit-breaker/config.toml.default ]; then
    cp /usr/local/share/circuit-breaker/config.toml.default \
       /etc/circuit-breaker/config.toml
    chmod 640 /etc/circuit-breaker/config.toml
    chown root:circuitbreaker /etc/circuit-breaker/config.toml
  fi
fi

# Generate env file with secrets if not present
if [ ! -f /etc/circuit-breaker/circuit-breaker.env ]; then
  VAULT_KEY=$(openssl rand -base64 32)
  NATS_TOKEN=$(openssl rand -hex 16)
  cat > /etc/circuit-breaker/circuit-breaker.env <<EOF
# Circuit Breaker environment — auto-generated during install
CB_DB_URL=postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker
CB_VAULT_KEY=${VAULT_KEY}
CB_REDIS_URL=redis://127.0.0.1:6379/0
NATS_AUTH_TOKEN=${NATS_TOKEN}
STATIC_DIR=/usr/local/share/circuit-breaker/frontend
CB_ALEMBIC_INI=/usr/local/share/circuit-breaker/backend/alembic.ini
CB_AGENT_BINARIES_DIR=/usr/local/share/circuit-breaker/agent-binaries
CB_DATA_DIR=/var/lib/circuit-breaker
UPLOADS_DIR=/var/lib/circuit-breaker/uploads
EOF
  chmod 600 /etc/circuit-breaker/circuit-breaker.env
  chown root:circuitbreaker /etc/circuit-breaker/circuit-breaker.env
fi

# Backfill CB_DATA_DIR into an env file that predates it.
#
# The block above writes the env only when it is absent, so without this an
# existing install upgrades straight back into the crash: the file it already
# has is precisely the one missing this line. Four modules fall back to `/data`
# when CB_DATA_DIR is unset -- the container path -- and the unit runs under
# ProtectSystem=strict, so the service starts, tries to write, and dies with
# `OSError: [Errno 30] Read-only file system: '/data'` on a loop. Found by the
# Tier 3 boot check (ADR 0005 Phase 2), which is the first thing in this
# project's history to install the package and start it on a clean host.
#
# /var/lib/circuit-breaker is not a new choice: the package already creates it,
# owns it to the service user, and the unit already grants it write access. The
# env simply never said so.
#
# UPLOADS_DIR is here for the same reason and was found the same way: fixing
# CB_DATA_DIR moved the crash one layer down to
# `FileNotFoundError: 'data/uploads'`. Its default is *relative*, so it resolves
# against the working directory -- and the unit sets none, so systemd runs the
# service from `/`. A relative default is invisible in review and fatal on a
# packaged host.
for _kv in \
  "CB_DATA_DIR=/var/lib/circuit-breaker" \
  "UPLOADS_DIR=/var/lib/circuit-breaker/uploads"; do
  _key="${_kv%%=*}"
  if [ -f /etc/circuit-breaker/circuit-breaker.env ] \
     && ! grep -q "^${_key}=" /etc/circuit-breaker/circuit-breaker.env; then
    echo "${_kv}" >> /etc/circuit-breaker/circuit-breaker.env
    echo "Added ${_kv} to the existing environment file."
  fi
done

# Enable and reload systemd
systemctl daemon-reload
systemctl enable circuit-breaker.service

if [ "$IS_UPGRADE" -eq 1 ]; then
  # try-restart, not restart: it acts only on a unit that was already running,
  # so an upgrade cannot start a service the operator had deliberately stopped.
  # Without this the upgrade leaves the OLD binary running -- rpm replaces the
  # files underneath a live process and nothing tells systemd -- so the operator
  # sees a successful upgrade and a service still serving the previous version
  # until something restarts it.
  systemctl try-restart circuit-breaker.service

  echo ""
  echo "Circuit Breaker upgraded successfully."
  echo ""
  # Name the newest pre-upgrade dump rather than a glob. This is the rollback
  # artifact preinstall.sh just wrote, and the operator who needs it is not in a
  # position to go looking.
  _latest_backup=""
  for _candidate in /var/lib/circuit-breaker/backups/pre-upgrade-*.sql; do
    [ -f "$_candidate" ] && _latest_backup="$_candidate"
  done
  if [ -n "$_latest_backup" ]; then
    echo "  Rolling back this upgrade:"
    echo "    1. sudo systemctl stop circuit-breaker"
    echo "    2. reinstall the previous package (dnf downgrade / apt install circuit-breaker=<old>)"
    echo "    3. sudo circuit-breaker-rollback $_latest_backup"
    echo ""
    echo "  Step 2 is not optional. Migrations have run, and the pre-upgrade dump"
    echo "  restores the OLD schema — the new binary cannot serve it."
  else
    echo "  No pre-upgrade backup was taken, so this upgrade cannot be rolled back."
    echo "  See docs/installation/upgrading.md."
  fi
  echo ""
else
  echo ""
  echo "Circuit Breaker installed successfully."
  echo ""
  echo "  Next steps:"
  echo "    1. Edit /etc/circuit-breaker/circuit-breaker.env"
  echo "       - Set CB_DB_URL to your PostgreSQL connection string"
  echo "       - Ensure PostgreSQL, Redis, and NATS are running"
  echo "    2. sudo systemctl start circuit-breaker"
  echo "    3. Open http://localhost:8080"
  echo ""
fi
