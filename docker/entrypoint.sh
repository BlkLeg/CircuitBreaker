#!/bin/sh
# Entrypoint: fix /data ownership, then exec the app as the non-root user (breaker26:1000).
#
# Why this pattern?
#   Docker named volumes are created with root ownership the first time, and keep
#   that ownership on upgrades. The image-layer `chown -R breaker26 /data` only
#   applies when the volume is *empty*. Re-owning at startup is the canonical
#   solution (used by Gitea, Portainer, Traefik, etc.).
#
# Why gosu instead of su/sudo?
#   gosu performs a single execve after setuid/setgid so no root parent process
#   remains after the drop. It is also compatible with no-new-privileges:true
#   because we are dropping *from* root, not gaining privileges.
set -e

# ── Phase 7: Vault key presence check ────────────────────────────────────────
# Warn early (before exec) so the message appears at the top of container logs.
# The app loads the key from /data/.env at startup via the fallback chain:
#   env CB_VAULT_KEY → /data/.env → AppSettings.vault_key in DB
# If none are present this is a fresh install — the key is generated at OOBE.
if [ -z "${CB_VAULT_KEY}" ]; then
    if [ ! -f /data/.env ] || ! grep -q "CB_VAULT_KEY" /data/.env 2>/dev/null; then
        echo "WARN [vault]: No CB_VAULT_KEY found in environment or /data/.env."
        echo "WARN [vault]: Fresh install: vault key will be generated during OOBE."
        echo "WARN [vault]: Existing install: ensure /data/.env contains CB_VAULT_KEY."
    fi
fi

# Only chown if we are actually running as root (allows dev runs as non-root).
if [ "$(id -u)" = "0" ]; then
    chown -R breaker26:breaker26 /data
    exec gosu breaker26 "$@"
else
    exec "$@"
fi
