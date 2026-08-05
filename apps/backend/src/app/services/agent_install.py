"""Generates install-agent.sh and the two curl command forms shown in-app
(spec §2.3). No secret is embedded — only the server's public identity."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.agent_crypto import get_server_static_keypair
from app.db.models import Certificate
from app.schemas.agents import InstallCommandResponse
from app.services import agent_update

_INSTALL_SCRIPT_TEMPLATE = """#!/bin/sh
set -eu

CB_SERVER_URL="{server_url}"
CB_SERVER_STATIC_PK="{server_static_pk_hex}"
CB_TLS_PIN="{tls_pin}"

echo "Installing cb-agent from ${{CB_SERVER_URL}}..."

if ! id cb-agent >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) CB_ARCH="amd64" ;;
  aarch64|arm64) CB_ARCH="arm64" ;;
  *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

{binary_digest_cases}

TMP_BIN="$(mktemp)"
CB_BINARY_URL="${{CB_SERVER_URL}}/api/v1/agents/binary/{latest_version}/linux/${{CB_ARCH}}"
curl -fsSL "$CB_BINARY_URL" -o "$TMP_BIN"
echo "${{CB_BINARY_SHA256}}  ${{TMP_BIN}}" | sha256sum -c
install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent
rm -f "$TMP_BIN"

mkdir -p /etc/circuit-breaker /var/lib/cb-agent
chown cb-agent:cb-agent /var/lib/cb-agent
cat > /etc/circuit-breaker/agent.toml <<EOF
server_url = "${{CB_SERVER_URL}}"
server_static_pk = "${{CB_SERVER_STATIC_PK}}"
tls_pin = "${{CB_TLS_PIN}}"
log_level = "info"
spool_cap_bytes = 67108864
EOF

if command -v docker >/dev/null 2>&1; then
  usermod -aG docker cb-agent || true
fi
if ! grep -q '^net.ipv4.ping_group_range' /etc/sysctl.conf 2>/dev/null; then
  echo "net.ipv4.ping_group_range = 0 2147483647" >> /etc/sysctl.conf
  sysctl -p >/dev/null 2>&1 || true
fi

cat > /etc/systemd/system/cb-agent.service <<'EOF'
[Unit]
Description=Circuit Breaker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cb-agent
Group=cb-agent
ExecStart=/usr/local/bin/cb-agent
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallFilter=@system-service
ReadWritePaths=/var/lib/cb-agent

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

echo "Enrolling — compare the fingerprint below against the one shown in the approval screen."
sudo -u cb-agent /usr/local/bin/cb-agent enroll

systemctl enable --now cb-agent
echo "cb-agent installed and running."
"""


def _spki_pin(cert_pem: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    der = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


def _active_certificate(db: Session) -> Certificate | None:
    return db.execute(select(Certificate).order_by(Certificate.updated_at.desc())).scalars().first()


def _live_nginx_cert_pem() -> str | None:
    """Read nginx.mono.conf's actual TLS listener cert straight off disk.

    The `Certificate` table (certificate_service.py) manages a separate,
    unrelated concern — nginx's own `ssl_certificate` always points at
    {CB_DATA_DIR}/tls/fullchain.pem regardless of what that table contains,
    and entrypoint-mono.sh generates that file's default self-signed cert
    with a CN-only subject (no SAN), so this is the only source that
    reliably matches what an agent's TLS handshake actually sees.
    """
    import os

    path = Path(os.environ.get("CB_DATA_DIR", "/data")) / "tls" / "fullchain.pem"
    try:
        return path.read_text()
    except OSError:
        return None


def _tls_mode_and_pin(cert: Certificate | None) -> tuple[str, str]:
    """Public (Let's Encrypt) certs are already trusted by the OS/agent's TLS
    stack — no pin needed. Self-signed needs a pin computed from the cert
    nginx actually serves (see `_live_nginx_cert_pem`), falling back to a
    `Certificate` row's cert_pem. Fails closed if neither source is available."""
    if cert is not None and cert.type == "letsencrypt":
        return "public", ""
    live_pem = _live_nginx_cert_pem()
    if live_pem is not None:
        return "self_signed", _spki_pin(live_pem)
    if cert is not None:
        return "self_signed", _spki_pin(cert.cert_pem)
    raise ValueError(
        "Cannot obtain TLS pin for self-signed certificate: "
        "neither live nginx cert nor database cert available"
    )


def render_install_script(
    *,
    server_url: str,
    server_static_pk_hex: str,
    tls_pin: str,
    manifest: dict,
) -> str:
    # Highest semver-ordered version, not the lexicographically-last key —
    # a plain string sort puts "0.10.0" before "0.2.0" (agent_update.py's
    # latest_version has the same fix, for the same reason).
    latest = max(manifest.keys(), key=agent_update.semver_key) if manifest else "0.0.0"
    per_arch = manifest.get(latest, {})
    # The generated script always installs the linux/${CB_ARCH} binary (see
    # CB_BINARY_URL below), so only "linux-*" manifest entries are eligible
    # digest sources — a same-arch, different-OS key (e.g. "darwin-amd64"
    # alongside "linux-amd64") must never satisfy the `$CB_ARCH` match below,
    # or the script could embed a digest for a binary it isn't downloading.
    cases = (
        "\n".join(
            f'if [ "$CB_ARCH" = "{arch.split("-", 1)[1]}" ]; then CB_BINARY_SHA256="{digest}"; fi'
            for arch, digest in per_arch.items()
            if arch.split("-", 1)[0] == "linux"
        )
        or 'CB_BINARY_SHA256=""'
    )
    return _INSTALL_SCRIPT_TEMPLATE.format(
        server_url=server_url,
        server_static_pk_hex=server_static_pk_hex,
        tls_pin=tls_pin,
        binary_digest_cases=cases,
        latest_version=latest,
    )


def build_install_command(db: Session, server_url: str) -> InstallCommandResponse:
    _, server_pub = get_server_static_keypair()
    server_static_pk_hex = server_pub.hex()

    cert = _active_certificate(db)
    tls_mode, tls_pin = _tls_mode_and_pin(cert)

    manifest = agent_update.load_manifest()
    script = render_install_script(
        server_url=server_url,
        server_static_pk_hex=server_static_pk_hex,
        tls_pin=tls_pin,
        manifest=manifest,
    )
    script_sha256 = hashlib.sha256(script.encode()).hexdigest()

    if tls_mode == "public":
        command = f"curl -fsSL {server_url}/install-agent.sh | sudo sh"
    else:
        command = (
            f"curl -fsSLk {server_url}/install-agent.sh -o /tmp/cb-agent-install.sh && "
            f'echo "{script_sha256}  /tmp/cb-agent-install.sh" | sha256sum -c && '
            f"sudo sh /tmp/cb-agent-install.sh"
        )

    return InstallCommandResponse(tls_mode=tls_mode, command=command, script_sha256=script_sha256)
