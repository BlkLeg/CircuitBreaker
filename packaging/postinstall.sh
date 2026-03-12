#!/bin/bash
set -e

# Create system user if it doesn't exist
if ! id -u circuitbreaker >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin \
    --home-dir /var/lib/circuit-breaker circuitbreaker
fi

# Create directories
mkdir -p /var/lib/circuit-breaker /var/log/circuit-breaker /etc/circuit-breaker
chown circuitbreaker:circuitbreaker /var/lib/circuit-breaker /var/log/circuit-breaker
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
EOF
  chmod 600 /etc/circuit-breaker/circuit-breaker.env
  chown root:circuitbreaker /etc/circuit-breaker/circuit-breaker.env
fi

# Enable and reload systemd
systemctl daemon-reload
systemctl enable circuit-breaker.service

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
