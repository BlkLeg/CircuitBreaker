#!/usr/bin/env bash
# deploy/native/upgrade.sh — Circuit Breaker Native Upgrade Script
# Usage: sudo bash deploy/native/upgrade.sh [version]
set -euo pipefail

# ── Colors / helpers ─────────────────────────────────────────────────────────
RESET="\033[0m"; BOLD="\033[1m"; GREEN="\033[32m"
ORANGE="\033[33m"; RED="\033[31m"; DIM="\033[2m"; CYAN="\033[36m"

ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
info() { echo -e "  ${CYAN}→${RESET} $*"; }
warn() { echo -e "  ${ORANGE}⚠${RESET} $*"; }
die()  { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }

step() {
  STEP_NUM=$((STEP_NUM + 1))
  echo
  echo -e "  ${BOLD}[${STEP_NUM}/${TOTAL_STEPS}]${RESET} $*"
}

STEP_NUM=0
TOTAL_STEPS=8

# ── Constants ────────────────────────────────────────────────────────────────
CB_APP_ROOT="/opt/circuitbreaker"
CB_CONFIG_DIR="/etc/circuitbreaker"
CB_DATA_DIR="/var/lib/circuitbreaker"
CB_LOG_DIR="/var/log/circuitbreaker"
CB_USER="breaker"
TARGET_VERSION="${1:-latest}"
BACKUP_DIR="${CB_DATA_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# ── Banner ───────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${ORANGE}"
cat <<'BANNER'
   ___  _                   _ _   ___
  / __\(_)_ __ ___ _   _(_) |_  / __\_ __ ___  __ _| | _____ _ __
 / /   | | '__/ __| | | | | __| /__\// '__/ _ \/ _` | |/ / _ \ '__|
/ /____| | | | (__| |_| | | |_/ \/  \ | |  __/ (_| |   <  __/ |
\______|_|_|  \___|\__,_|_|\__\_____/_|  \___|\__,_|_|\_\___|_|
BANNER
echo -e "${RESET}"
echo -e "  ${BOLD}Native Upgrade${RESET}  ${DIM}Target: ${TARGET_VERSION}${RESET}"
echo

# ═════════════════════════════════════════════════════════════════════════════
#  Step 1: Check privileges
# ═════════════════════════════════════════════════════════════════════════════
step "Checking privileges"

if [ "$(id -u)" -ne 0 ]; then
  die "This script must be run as root. Try: sudo bash $0"
fi
ok "Running as root"

# Verify existing installation
if [ ! -d "$CB_APP_ROOT" ]; then
  die "Circuit Breaker is not installed at ${CB_APP_ROOT}. Run install.sh first."
fi

if [ ! -f "${CB_CONFIG_DIR}/config.env" ]; then
  die "Config not found at ${CB_CONFIG_DIR}/config.env. Is Circuit Breaker installed?"
fi

# Source config
set -a
# shellcheck disable=SC1091
source "${CB_CONFIG_DIR}/config.env"
set +a

ok "Existing installation verified"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 2: Stop services
# ═════════════════════════════════════════════════════════════════════════════
step "Stopping services"

systemctl stop circuitbreaker.target 2>/dev/null || true

# Wait for services to fully stop
sleep 2
ok "Services stopped"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 3: Backup database
# ═════════════════════════════════════════════════════════════════════════════
step "Backing up database"

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/pre-upgrade-${TIMESTAMP}.sql"

# Find pg_dump
PG_DUMP=""
for pg_dir in /usr/lib/postgresql/*/bin /usr/pgsql-*/bin; do
  if [ -x "${pg_dir}/pg_dump" ]; then
    PG_DUMP="${pg_dir}/pg_dump"
    break
  fi
done

if [ -z "$PG_DUMP" ] && command -v pg_dump &>/dev/null; then
  PG_DUMP="$(command -v pg_dump)"
fi

if [ -z "$PG_DUMP" ]; then
  warn "pg_dump not found — skipping database backup"
else
  # Find pg_ctl to start Postgres temporarily for the backup
  PG_BIN="$(dirname "$PG_DUMP")"
  PGDATA="${CB_DATA_DIR}/pgdata"

  if [ -f "${PGDATA}/PG_VERSION" ]; then
    info "Starting PostgreSQL for backup..."
    sudo -u "$CB_USER" "${PG_BIN}/pg_ctl" \
      -D "$PGDATA" \
      -l "${CB_LOG_DIR}/pg-backup.log" \
      -o "-k ${CB_DATA_DIR}/run/postgresql" \
      start -w 2>/dev/null || true

    # Wait for ready
    TRIES=0
    until sudo -u "$CB_USER" "${PG_BIN}/pg_isready" -h "${CB_DATA_DIR}/run/postgresql" -q 2>/dev/null; do
      TRIES=$((TRIES + 1))
      [ $TRIES -ge 15 ] && break
      sleep 1
    done

    info "Dumping database to ${BACKUP_FILE}..."
    sudo -u "$CB_USER" "$PG_DUMP" \
      -h "${CB_DATA_DIR}/run/postgresql" \
      circuitbreaker > "$BACKUP_FILE" 2>/dev/null

    sudo -u "$CB_USER" "${PG_BIN}/pg_ctl" -D "$PGDATA" stop -w 2>/dev/null || true

    if [ -s "$BACKUP_FILE" ]; then
      BACKUP_SIZE=$(du -sh "$BACKUP_FILE" | awk '{print $1}')
      ok "Database backed up (${BACKUP_SIZE}) to ${BACKUP_FILE}"
    else
      warn "Backup file is empty — database may be empty or backup failed"
    fi
  else
    warn "PostgreSQL data directory not found — skipping backup"
  fi
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 4: Update application code
# ═════════════════════════════════════════════════════════════════════════════
step "Updating application code"

# Detect if this is a git repo
if [ -d "${CB_APP_ROOT}/.git" ]; then
  info "Git repository detected — pulling latest..."
  cd "$CB_APP_ROOT"

  if [ "$TARGET_VERSION" != "latest" ]; then
    git fetch --all --tags 2>&1 | tail -3
    git checkout "$TARGET_VERSION" 2>&1 | tail -3
  else
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    git pull origin "$CURRENT_BRANCH" 2>&1 | tail -3
  fi
  cd /

  # Ensure convenience symlinks exist after git pull
  ln -sfn "$CB_APP_ROOT/apps/backend"  "$CB_APP_ROOT/backend"
  ln -sfn "$CB_APP_ROOT/apps/frontend" "$CB_APP_ROOT/frontend"

  ok "Code updated via git"
else
  # Download release archive
  if [ "$TARGET_VERSION" = "latest" ]; then
    ARCHIVE_URL="https://github.com/BlkLeg/CircuitBreaker/archive/refs/heads/main.tar.gz"
  else
    ARCHIVE_URL="https://github.com/BlkLeg/CircuitBreaker/archive/refs/tags/${TARGET_VERSION}.tar.gz"
  fi

  info "Downloading release archive..."
  TMP_DIR=$(mktemp -d)
  curl -fsSL "$ARCHIVE_URL" -o "${TMP_DIR}/release.tar.gz"
  tar -xzf "${TMP_DIR}/release.tar.gz" -C "$TMP_DIR"

  # Find the extracted directory (CircuitBreaker-main or CircuitBreaker-vX.Y.Z)
  EXTRACTED_DIR=$(find "$TMP_DIR" -maxdepth 1 -type d -name 'CircuitBreaker*' | head -1)
  if [ -z "$EXTRACTED_DIR" ]; then
    rm -rf "$TMP_DIR"
    die "Failed to extract release archive"
  fi

  # Sync files, preserving .venv, node_modules, and local config
  if command -v rsync &>/dev/null; then
    rsync -a --delete \
      --exclude='.venv' \
      --exclude='node_modules' \
      --exclude='.env' \
      --exclude='__pycache__' \
      "$EXTRACTED_DIR/" "$CB_APP_ROOT/"
  else
    # Preserve venv and node_modules
    [ -d "${CB_APP_ROOT}/apps/backend/.venv" ] && mv "${CB_APP_ROOT}/apps/backend/.venv" /tmp/_cb_venv_bak
    [ -d "${CB_APP_ROOT}/apps/frontend/node_modules" ] && mv "${CB_APP_ROOT}/apps/frontend/node_modules" /tmp/_cb_nm_bak
    rm -rf "${CB_APP_ROOT:?}/"*
    cp -a "$EXTRACTED_DIR/." "$CB_APP_ROOT/"
    [ -d /tmp/_cb_venv_bak ] && mv /tmp/_cb_venv_bak "${CB_APP_ROOT}/apps/backend/.venv"
    [ -d /tmp/_cb_nm_bak ] && mv /tmp/_cb_nm_bak "${CB_APP_ROOT}/apps/frontend/node_modules"
  fi

  rm -rf "$TMP_DIR"
  chown -R "$CB_USER":"$CB_USER" "$CB_APP_ROOT"

  # Recreate convenience symlinks (may have been removed by rm -rf)
  ln -sfn "$CB_APP_ROOT/apps/backend"  "$CB_APP_ROOT/backend"
  ln -sfn "$CB_APP_ROOT/apps/frontend" "$CB_APP_ROOT/frontend"

  ok "Code updated from archive"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 5: Rebuild Python venv
# ═════════════════════════════════════════════════════════════════════════════
step "Rebuilding backend dependencies"

BACKEND_DIR="${CB_APP_ROOT}/apps/backend"
VENV_DIR="${BACKEND_DIR}/.venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  sudo -u "$CB_USER" python3 -m venv "$VENV_DIR"
fi

sudo -u "$CB_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip setuptools wheel

if [ -f "${BACKEND_DIR}/requirements.txt" ]; then
  sudo -u "$CB_USER" "$VENV_DIR/bin/pip" install --quiet -r "${BACKEND_DIR}/requirements.txt"
elif [ -f "${BACKEND_DIR}/pyproject.toml" ]; then
  sudo -u "$CB_USER" "$VENV_DIR/bin/pip" install --quiet "${BACKEND_DIR}"
fi

ok "Backend dependencies updated"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 6: Rebuild frontend
# ═════════════════════════════════════════════════════════════════════════════
step "Rebuilding frontend"

FRONTEND_DIR="${CB_APP_ROOT}/apps/frontend"

cd "$FRONTEND_DIR"
info "Running npm ci..."
sudo -u "$CB_USER" npm ci --silent 2>&1 | tail -3

info "Running npm run build..."
sudo -u "$CB_USER" npm run build --silent 2>&1 | tail -3
cd /

if [ -d "${FRONTEND_DIR}/dist" ]; then
  ok "Frontend rebuilt"
else
  warn "Frontend build may have failed — dist/ directory not found"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 7: Run migrations
# ═════════════════════════════════════════════════════════════════════════════
step "Running database migrations"

MIGRATE_SCRIPT="${CB_APP_ROOT}/deploy/common/20-migrate.sh"
if [ -f "$MIGRATE_SCRIPT" ]; then
  # Start Postgres for migrations
  PG_BIN_DIR=""
  for pg_dir in /usr/lib/postgresql/*/bin /usr/pgsql-*/bin; do
    if [ -x "${pg_dir}/pg_ctl" ]; then
      PG_BIN_DIR="$pg_dir"
      break
    fi
  done
  [ -z "$PG_BIN_DIR" ] && PG_BIN_DIR="$(dirname "$(command -v pg_ctl 2>/dev/null)" || true)"

  PGDATA="${CB_DATA_DIR}/pgdata"

  if [ -n "$PG_BIN_DIR" ] && [ -f "${PGDATA}/PG_VERSION" ]; then
    sudo -u "$CB_USER" "${PG_BIN_DIR}/pg_ctl" \
      -D "$PGDATA" \
      -l "${CB_LOG_DIR}/pg-migrate.log" \
      -o "-k ${CB_DATA_DIR}/run/postgresql" \
      start -w 2>/dev/null || true

    TRIES=0
    until sudo -u "$CB_USER" "${PG_BIN_DIR}/pg_isready" -h "${CB_DATA_DIR}/run/postgresql" -q 2>/dev/null; do
      TRIES=$((TRIES + 1))
      [ $TRIES -ge 15 ] && break
      sleep 1
    done
  fi

  export CB_DEPLOY_MODE=native
  export CB_DATA_DIR CB_APP_ROOT CB_DB_PASSWORD
  export APP_ROOT="$CB_APP_ROOT"
  export DATA_DIR="$CB_DATA_DIR"

  bash "$MIGRATE_SCRIPT" || warn "Migration script returned non-zero — check logs"

  # Stop Postgres — systemd will manage it
  if [ -n "$PG_BIN_DIR" ] && [ -f "${PGDATA}/PG_VERSION" ]; then
    sudo -u "$CB_USER" "${PG_BIN_DIR}/pg_ctl" -D "$PGDATA" stop -w 2>/dev/null || true
  fi

  ok "Migrations complete"
else
  warn "Migration script not found at ${MIGRATE_SCRIPT} — skipping"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 8: Restart services and healthcheck
# ═════════════════════════════════════════════════════════════════════════════
step "Restarting services"

# Reload unit files in case they changed
systemctl daemon-reload
systemctl start circuitbreaker.target
ok "Services started"

# ── Healthcheck ──────────────────────────────────────────────────────────────
info "Waiting for Circuit Breaker to become healthy..."
sleep 3

CB_PORT="${CB_PORT:-80}"
TRIES=0
HEALTHY=false
until curl -sf "http://localhost:${CB_PORT}/api/v1/health" 2>/dev/null | grep -q '"status"'; do
  TRIES=$((TRIES + 1))
  if [ $TRIES -ge 30 ]; then
    break
  fi
  sleep 2
done

if curl -sf "http://localhost:${CB_PORT}/api/v1/health" 2>/dev/null | grep -q '"status"'; then
  HEALTHY=true
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

if [ "$HEALTHY" = true ]; then
  echo -e "  ${BOLD}${GREEN}Upgrade complete! Circuit Breaker is healthy.${RESET}"
else
  echo -e "  ${BOLD}${ORANGE}Upgrade complete but health check did not pass.${RESET}"
  echo -e "  ${DIM}Check logs: journalctl -u circuitbreaker-backend.service -n 50${RESET}"
  echo -e "  ${DIM}Restore backup: psql -U ${CB_USER} -f ${BACKUP_FILE:-N/A}${RESET}"
fi

echo
echo -e "  ${BOLD}Backup:${RESET} ${DIM}${BACKUP_FILE:-none}${RESET}"
echo -e "  ${BOLD}Version:${RESET} ${DIM}${TARGET_VERSION}${RESET}"
echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
