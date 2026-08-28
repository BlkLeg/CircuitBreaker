#!/bin/bash
set -e

# The service user belongs to the application package; create it only if this
# package landed first, so the two orders of installation converge.
if ! id -u circuitbreaker >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin \
    --home-dir /var/lib/circuit-breaker circuitbreaker
fi

mkdir -p /var/lib/circuit-breaker/nats
chown -R circuitbreaker:circuitbreaker /var/lib/circuit-breaker/nats
chmod 750 /var/lib/circuit-breaker/nats

systemctl daemon-reload
systemctl enable circuit-breaker-nats.service

echo "Circuit Breaker NATS installed. Start it with:"
echo "    sudo systemctl start circuit-breaker-nats"
