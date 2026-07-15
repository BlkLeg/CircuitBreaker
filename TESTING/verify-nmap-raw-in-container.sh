#!/usr/bin/env bash
set -euo pipefail
# Verifies the mono container's discovery workers hold ambient CAP_NET_RAW
# (bit 13, mask 0x2000) so nmap children can open raw sockets as breaker.
# Run from the repo root with the stack up: docker compose up -d --build
#
# Note: setpriv must run from the container's root context (as supervisord
# does) — a breaker-uid process has no caps in its permitted set to raise,
# so `exec -u breaker ... setpriv --ambient-caps` can never succeed.

CONTAINER="${1:-circuitbreaker}"
CAP_NET_RAW_MASK=$((1 << 13))

echo "1) setpriv present in image"
docker compose exec -T "$CONTAINER" sh -c 'command -v setpriv >/dev/null' \
  || { echo "FAIL: setpriv missing"; exit 1; }
echo "   OK"

echo "2) launcher grants breaker a raw socket (same invocation supervisord uses)"
docker compose exec -T "$CONTAINER" \
  setpriv --reuid breaker --regid breaker --init-groups \
    --ambient-caps +net_raw --inh-caps +net_raw \
    python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP); print('   RAW OK')" \
  || { echo "FAIL: raw socket denied via launcher"; exit 1; }

echo "3) live discovery worker (worker-00) has ambient CAP_NET_RAW"
# /proc scan instead of pgrep (absent in the slim image); match only python
# processes so the search doesn't find its own shell, whose cmdline also
# contains the --type=0 pattern.
CAPAMB=$(docker compose exec -T "$CONTAINER" sh -c '
  for d in /proc/[0-9]*; do
    c=$(tr "\0" "\n" < "$d/cmdline" 2>/dev/null | head -1)
    case "$c" in *python*)
      if tr "\0" " " < "$d/cmdline" | grep -q "app.workers.main --type=0"; then
        awk "/^CapAmb:/{print \$2}" "$d/status"; exit 0
      fi;;
    esac
  done')
[ -n "$CAPAMB" ] || { echo "FAIL: worker-00 process not found"; exit 1; }
if [ $((16#$CAPAMB & CAP_NET_RAW_MASK)) -ne 0 ]; then
  echo "   CapAmb=$CAPAMB — NET_RAW present. OK"
else
  echo "FAIL: worker-00 CapAmb=$CAPAMB lacks NET_RAW"; exit 1
fi

echo "PASS: discovery worker context can open raw sockets"
