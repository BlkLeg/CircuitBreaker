#!/usr/bin/env bash
# A throwaway containerised cb-agent enrolled against the dev server, so the
# enroll → approve → report path can be exercised without a second machine and
# without creating a cb-agent user or a systemd unit on your workstation.
#
# It deliberately takes the same route a real install does rather than a
# shortcut: it fetches /install-agent.sh through the pinned curl the generated
# command uses, and reads server_url, server_static_pk and tls_pin out of that
# script. So a defect in pin derivation, in the embedded binary digest, or in
# the server_url the front door reports fails here the same way it would fail
# on a user's machine.
#
# Requires `make dev` and `make dev-tls` to be up.
#
# Usage: scripts/dev-agent.sh {up|enroll|down|logs|status|toml}
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB_DATA_DIR="${CB_DATA_DIR:-$REPO_ROOT/apps/backend/.dev-data}"
WORK_DIR="$CB_DATA_DIR/dev-agent"
TOML="$WORK_DIR/agent.toml"

CONTAINER="${CB_DEV_AGENT_CONTAINER:-cb-dev-agent}"
VOLUME="${CB_DEV_AGENT_VOLUME:-cb-dev-agent-state}"
IMAGE="${CB_DEV_AGENT_IMAGE:-cb-agent-dev:latest}"

die() { echo "dev-agent: $*" >&2; exit 1; }

server_url() { "$REPO_ROOT/scripts/dev-tls.sh" url; }

# The same fetch the generated install command performs: --pinnedpubkey is what
# actually verifies this download (curl enforces it even alongside --insecure,
# which is only here because no CA can validate a self-signed leaf).
fetch_install_script() {
  local url pin
  url="$(server_url)"
  pin="$("$REPO_ROOT/scripts/dev-tls.sh" pin)"
  curl -fsSL --insecure --pinnedpubkey "sha256//$pin" "$url/install-agent.sh" \
    || die "could not fetch $url/install-agent.sh — is \`make dev-tls\` up and \`make dev\` running?"
}

cmd_toml() {
  mkdir -p "$WORK_DIR"
  local script server_pk tls_pin agent_url version
  script="$(fetch_install_script)"

  server_pk="$(printf '%s' "$script" | sed -n 's/^CB_SERVER_STATIC_PK="\([0-9a-f]*\)".*/\1/p')"
  tls_pin="$(printf '%s' "$script" | sed -n 's/^CB_TLS_PIN="\([^"]*\)".*/\1/p')"
  agent_url="$(printf '%s' "$script" | sed -n 's/^CB_SERVER_URL="\([^"]*\)".*/\1/p')"
  version="$(printf '%s' "$script" | sed -n 's|.*/api/v1/agents/binary/\([^/]*\)/linux/.*|\1|p' | head -1)"

  [[ -n "$server_pk" ]] || die "install script carried no CB_SERVER_STATIC_PK"
  [[ -n "$agent_url" ]] || die "install script carried no CB_SERVER_URL"
  # An empty pin here would mean the server believes it is publicly trusted.
  # On a dev box with a self-signed certificate that is always wrong, and it is
  # the exact shape of the bug that made this whole path unusable, so it is
  # worth failing on rather than passing through into agent.toml.
  [[ -n "$tls_pin" ]] || die "install script carried an EMPTY CB_TLS_PIN — the server thinks its certificate is publicly trusted"

  if [[ "$version" == "0.0.0" ]]; then
    die "the server is advertising agent version 0.0.0, which means it found no
       manifest. Run: make agent-binaries — and restart \`make dev\` so the
       backend picks up CB_AGENT_BINARIES_DIR."
  fi

  # The same five keys the generated install script writes, in the same order.
  cat > "$TOML" <<TOMLEOF
server_url = "$agent_url"
server_static_pk = "$server_pk"
tls_pin = "$tls_pin"
log_level = "debug"
spool_cap_bytes = 67108864
TOMLEOF

  echo "dev-agent: server_url  $agent_url"
  echo "dev-agent: tls_pin     $tls_pin"
  echo "dev-agent: version     $version"
  echo "dev-agent: wrote       $TOML"
}

cmd_build() {
  echo "dev-agent: building $IMAGE"
  # The e2e image, reused rather than duplicated: it already mirrors the real
  # install's versioned-symlink layout under /var/lib/cb-agent and runs as the
  # unprivileged cb-agent user, which is what makes a self-update in dev behave
  # the way it does in production.
  docker build -q -t "$IMAGE" -f "$REPO_ROOT/apps/agent/e2e/Dockerfile" "$REPO_ROOT/apps/agent" >/dev/null \
    || die "agent image build failed"
}

# Runs in the foreground on purpose: this is the step that prints the pairing
# code and the device fingerprint you compare against the approval screen.
cmd_enroll() {
  [[ -f "$TOML" ]] || cmd_toml
  docker run --rm -i --name "${CONTAINER}-enroll" \
    -v "$VOLUME:/var/lib/cb-agent" \
    -v "$TOML:/etc/circuit-breaker/agent.toml:ro,z" \
    "$IMAGE" enroll
}

cmd_up() {
  command -v docker >/dev/null 2>&1 || die "docker is required"
  cmd_toml
  cmd_build
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

  echo
  echo "── enrolling ────────────────────────────────────────────────────────"
  echo "This BLOCKS until you approve the agent in the UI — that wait is a"
  echo "human pressing a button and is deliberately unbounded (enroll.go:37)."
  echo "Until you approve, the agent reads 'offline (pending)': the row exists,"
  echo "but the daemon that opens the /link session starts only after this"
  echo "returns — the same order the real install script uses (enroll, then"
  echo "systemctl enable --now)."
  echo
  cmd_enroll
  echo "─────────────────────────────────────────────────────────────────────"
  echo

  # Mirrors the systemd unit's Restart=on-failure/RestartSec=5s: the daemon's
  # startup enroll is fatal if the server is briefly unreachable, and in
  # production systemd is what retries.
  docker run -d --name "$CONTAINER" --restart on-failure \
    -v "$VOLUME:/var/lib/cb-agent" \
    -v "$TOML:/etc/circuit-breaker/agent.toml:ro,z" \
    --sysctl net.ipv4.ping_group_range="0 2147483647" \
    "$IMAGE" >/dev/null || die "could not start the agent daemon"

  echo "dev-agent: daemon running as container $CONTAINER"
  echo "dev-agent: approve it in the UI, then: make dev-agent-logs"
}

cmd_down() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "dev-agent: container removed" || echo "dev-agent: no container"
  # The volume holds device.key and the enrolled identity. Removing it is what
  # makes the next `up` a genuinely new agent rather than the same one
  # reconnecting, which matters when testing the enroll path itself.
  docker volume rm "$VOLUME" >/dev/null 2>&1 && echo "dev-agent: identity wiped" || true
  rm -f "$TOML"
}

cmd_logs() { docker logs -f "$CONTAINER"; }

cmd_status() {
  docker inspect -f 'dev-agent: container  {{.State.Status}}' "$CONTAINER" 2>/dev/null \
    || echo "dev-agent: container  not running"
  [[ -f "$TOML" ]] && { echo "dev-agent: config"; sed 's/^/  /' "$TOML"; }
}

case "${1:-}" in
  up)     cmd_up ;;
  enroll) cmd_build; cmd_enroll ;;
  down)   cmd_down ;;
  logs)   cmd_logs ;;
  status) cmd_status ;;
  toml)   cmd_toml ;;
  *) die "usage: $0 {up|enroll|down|logs|status|toml}" ;;
esac
