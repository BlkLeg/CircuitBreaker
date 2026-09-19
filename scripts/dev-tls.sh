#!/usr/bin/env bash
# TLS front door for the native dev stack, so the agent feature is reachable
# locally.
#
# `make dev` runs uvicorn (:8000) and vite (:5173) over plain HTTP. Nothing
# terminates TLS and nothing writes ${CB_DATA_DIR}/tls/fullchain.pem, so
# `agent_install._tls_mode_and_pin` has no certificate to derive an agent's
# SPKI pin from and fails closed — "Add an agent" answers 503 and the enroll →
# approve → report path cannot be exercised without pushing to a real host
# first. This puts nginx in front of both dev servers with a self-signed
# certificate at the exact path the backend reads, which is all the pin
# derivation was ever missing. See docker/nginx.dev.conf.
#
# Usage: scripts/dev-tls.sh {cert|up|down|restart|status|logs|url|pin}
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB_DATA_DIR="${CB_DATA_DIR:-$REPO_ROOT/apps/backend/.dev-data}"
TLS_DIR="$CB_DATA_DIR/tls"
CONF_DIR="$CB_DATA_DIR/dev-tls"
CERT="$TLS_DIR/fullchain.pem"
KEY="$TLS_DIR/privkey.pem"

CONTAINER="${CB_DEV_TLS_CONTAINER:-cb-dev-tls}"
IMAGE="${CB_DEV_TLS_IMAGE:-nginx:1.27-alpine}"
# 443, matching docker-compose.yml's CB_PORT_HTTPS default, so the dev front
# door has the shape a default install has. Another port works too: nginx sends
# it in X-Forwarded-Host and `forwarded_base_url` keeps it, so the generated
# server_url stays reachable. That was not true before the proxy-header fix
# (nginx never sent the header, and `core.forwarded` could not have trusted it
# if it had), which is the defect `app/middleware/proxy_headers.py` documents.
PORT="${CB_DEV_TLS_PORT:-443}"

die() { echo "dev-tls: $*" >&2; exit 1; }

lan_ip() { ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || true; }

# The URL to browse and to hand an agent. The LAN address rather than
# localhost, because `forwarded_base_url` turns whatever Host you browsed into
# the server_url baked into every generated install — and "localhost" is the
# one value that resolves to the wrong machine on the host being enrolled.
front_door_url() {
  local ip
  ip="$(lan_ip)"
  ip="${ip:-127.0.0.1}"
  [[ "$PORT" == "443" ]] && { echo "https://$ip"; return; }
  echo "https://$ip:$PORT"
}

cmd_cert() {
  mkdir -p "$TLS_DIR"
  if [[ -f "$CERT" && -f "$KEY" ]]; then
    echo "dev-tls: reusing existing certificate at $CERT"
    return 0
  fi
  local ip san
  ip="$(lan_ip)"
  # circuitbreaker.lab is in vite's server.allowedHosts and in Caddyfile.dev,
  # so it stays a valid name for this cert whether or not it resolves here.
  san="DNS:localhost,DNS:circuitbreaker.lab,IP:127.0.0.1"
  [[ -n "$ip" ]] && san="$san,IP:$ip"

  echo "dev-tls: generating self-signed certificate (SAN: $san)"
  # Mirrors deploy/setup.sh's self-signed branch — same key type, same subject
  # shape, same filenames — so the pin this produces is derived exactly the way
  # a real self-hosted install's is.
  openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/CN=circuitbreaker-dev/O=CircuitBreaker" \
    -addext "subjectAltName=$san" 2>/dev/null \
    || die "certificate generation failed"

  # 644 on the certificate, matching setup.sh: it is the server's public
  # certificate — every TLS client is handed a copy during the handshake — and
  # the backend must be able to read it to compute the pin. The key stays 600.
  chmod 644 "$CERT"
  chmod 600 "$KEY"
  echo "dev-tls: wrote $CERT"
}

# The pin an agent will verify, computed the same way
# agent_install._spki_pin does: base64(sha256(DER SubjectPublicKeyInfo)).
# Printed so a mismatch between this file and what the API hands out is
# something you can see directly rather than infer from a failed handshake.
cmd_pin() {
  [[ -f "$CERT" ]] || die "no certificate at $CERT — run: $0 cert"
  openssl x509 -in "$CERT" -pubkey -noout \
    | openssl pkey -pubin -outform der \
    | openssl dgst -sha256 -binary \
    | openssl base64
}

cmd_up() {
  command -v docker >/dev/null 2>&1 || die "docker is required"
  cmd_cert

  mkdir -p "$CONF_DIR"
  # Copied rather than bind-mounted from the repo: SELinux is enforcing here,
  # so a bind mount needs a relabel (:z), and relabelling a tracked file in the
  # working tree is a side effect this script has no business causing.
  sed "s/^\( *\)listen 443 ssl;/\1listen $PORT ssl;/" \
    "$REPO_ROOT/docker/nginx.dev.conf" > "$CONF_DIR/nginx.conf"
  grep -q "listen $PORT ssl;" "$CONF_DIR/nginx.conf" \
    || die "could not set the listen port to $PORT — docker/nginx.dev.conf's listen line changed shape"

  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

  local mounts=(
    -v "$CONF_DIR/nginx.conf:/etc/nginx/nginx.conf:ro,z"
    -v "$TLS_DIR:/data/tls:ro,z"
  )

  # Fail on a bad config here, where nginx prints the offending line, rather
  # than as a container that exits three seconds after `docker run -d` returns
  # success.
  docker run --rm --network host "${mounts[@]}" "$IMAGE" nginx -t >/dev/null 2>&1 \
    || { docker run --rm --network host "${mounts[@]}" "$IMAGE" nginx -t; die "nginx config rejected"; }

  # --network host is not a shortcut: on a bridge network the backend sees the
  # docker gateway as the socket peer, which is not in `trusted_proxy_cidrs`,
  # so core.forwarded discards X-Forwarded-Proto and every agent gets an
  # http:// server_url for an https server. See docker/nginx.dev.conf.
  # on-failure, not unless-stopped: this binds 443 on your workstation, and a
  # dev tool that silently comes back after a reboot is a port conflict you
  # debug months later. `make dev-tls` starts it; `make dev-tls-down` ends it.
  docker run -d --name "$CONTAINER" --restart on-failure:3 \
    --network host "${mounts[@]}" "$IMAGE" >/dev/null

  local url
  url="$(front_door_url)"
  echo "dev-tls: nginx up on :$PORT"
  echo "dev-tls: browse   $url"
  echo "dev-tls: pin      $(cmd_pin)"
  echo
  echo "Browse the LAN URL above, not localhost — the Host you use becomes the"
  echo "server_url written into every agent's config."
  if [[ "$PORT" != "443" ]]; then
    echo
    echo "Note: on port $PORT the generated server_url carries :$PORT, which is"
    echo "      what an agent dials. Confirm it does before trusting a run —"
    echo "      that only works because the backend now reads X-Forwarded-Host."
  fi
}

cmd_down() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "dev-tls: stopped" || echo "dev-tls: not running"
}

cmd_restart() { cmd_down; cmd_up; }

cmd_status() {
  if ! docker inspect -f '{{.State.Status}}' "$CONTAINER" >/dev/null 2>&1; then
    echo "dev-tls: container $CONTAINER does not exist"
    return 1
  fi
  echo "dev-tls: container  $(docker inspect -f '{{.State.Status}}' "$CONTAINER")"
  echo "dev-tls: url        $(front_door_url)"
  [[ -f "$CERT" ]] && echo "dev-tls: pin        $(cmd_pin)"
  # -k because the whole point is a certificate no CA vouches for; the pin
  # above is what an agent verifies instead.
  echo -n "dev-tls: backend    "
  curl -fsS -k -o /dev/null -w '%{http_code}\n' "https://127.0.0.1:$PORT/api/v1/health" \
    || echo "unreachable (is \`make dev\` running?)"
}

cmd_logs() { docker logs -f "$CONTAINER"; }

cmd_url() { front_door_url; }

case "${1:-}" in
  cert)    cmd_cert ;;
  up)      cmd_up ;;
  down)    cmd_down ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  logs)    cmd_logs ;;
  url)     cmd_url ;;
  pin)     cmd_pin ;;
  *) die "usage: $0 {cert|up|down|restart|status|logs|url|pin}" ;;
esac
