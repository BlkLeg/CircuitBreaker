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

# Only chown if we are actually running as root (allows dev runs as non-root).
if [ "$(id -u)" = "0" ]; then
    chown -R breaker26:breaker26 /data
    exec gosu breaker26 "$@"
else
    exec "$@"
fi
