"""Generates install-agent.sh and the two curl command forms shown in-app
(spec §2.3). No secret is embedded — only the server's public identity."""

from __future__ import annotations

import base64
import hashlib
import shlex
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import agent_crypto
from app.db.models import Certificate
from app.schemas.agents import InstallCommandResponse
from app.services import agent_update

_INSTALL_SCRIPT_TEMPLATE = """#!/bin/sh
set -eu

CB_SERVER_URL="{server_url}"
CB_SERVER_STATIC_PK="{server_static_pk_hex}"
CB_TLS_PIN="{tls_pin}"

echo "Installing cb-agent from ${{CB_SERVER_URL}}..."

# Every fetch below goes through cb_curl, which applies the same TLS trust the
# agent itself will use once installed. Under self-signed TLS the target host
# has no CA that can validate this server, so curl verifies the leaf's SPKI
# against CB_TLS_PIN -- the identical check internal/tlsdial makes. curl
# enforces --pinnedpubkey independently of --insecure, so the pair means "skip
# the CA chain, require exactly this key", not "trust anything": a certificate
# that does not match fails with exit 90. An empty pin is a publicly trusted
# certificate, where the system trust store already applies and relaxing
# verification would be a straight downgrade.
if [ -n "${{CB_TLS_PIN}}" ] && ! curl --pinnedpubkey "sha256//" --version >/dev/null 2>&1; then
  echo "curl here cannot verify this server's certificate:" >&2
  echo "--pinnedpubkey needs curl 7.39 or newer." >&2
  exit 1
fi
cb_curl() {{
  if [ -n "${{CB_TLS_PIN}}" ]; then
    curl -fsSL --insecure --pinnedpubkey "sha256//${{CB_TLS_PIN}}" "$@"
  else
    curl -fsSL "$@"
  fi
}}

# Reachability preflight. The server cannot test this for us: it never connects
# to an agent, so the first machine that can answer "is this address reachable
# from here?" is this one. Failing here, before a user or a systemd unit exists,
# means a wrong CB_SERVER_URL costs nothing and says so precisely.
if ! cb_curl "${{CB_SERVER_URL}}/api/v1/health" >/dev/null 2>&1; then
  echo "Cannot reach ${{CB_SERVER_URL}} from this machine." >&2
  echo "The agent would dial that address forever and never appear in the UI." >&2
  echo "Check that the address is correct for THIS network, that DNS resolves" >&2
  echo "it here, and that outbound HTTPS to it is permitted." >&2
  exit 1
fi

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
cb_curl "$CB_BINARY_URL" -o "$TMP_BIN"
echo "${{CB_BINARY_SHA256}}  ${{TMP_BIN}}" | sha256sum -c

mkdir -p /etc/circuit-breaker /var/lib/cb-agent
chown cb-agent:cb-agent /var/lib/cb-agent
install -d -m 0755 -o cb-agent -g cb-agent "/var/lib/cb-agent/versions/{latest_version}"
install -m 0755 -o cb-agent -g cb-agent "$TMP_BIN" \
  "/var/lib/cb-agent/versions/{latest_version}/cb-agent"
rm -f "$TMP_BIN"
ln -sfn "versions/{latest_version}/cb-agent" /var/lib/cb-agent/current
chown -h cb-agent:cb-agent /var/lib/cb-agent/current
ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent
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
# The agent's ICMP prober opens *datagram* ICMP and holds no CAP_NET_RAW, so it
# can only send an echo request when the cb-agent group falls inside
# net.ipv4.ping_group_range. Checking whether a line merely exists was not
# enough: the kernel default is `1 0`, which disables the feature for everyone,
# and a host that already carried a narrower range made the installer skip and
# left every ICMP probe failing for a reason nothing reported.
#
# Read the effective value, and widen it only if it does not already cover the
# agent — as a union, so groups the host already allowed keep their ping. That
# is also why this no longer opens the range to every group on the machine.
SYSCTL_CONF="${{SYSCTL_CONF:-/etc/sysctl.conf}}"
configure_unprivileged_icmp() {{
  cb_gid="$(getent group cb-agent 2>/dev/null | cut -d: -f3)"
  [ -n "$cb_gid" ] || return 0

  current="$(sysctl -n net.ipv4.ping_group_range 2>/dev/null || echo "1 0")"
  low="$(printf '%s' "$current" | awk '{{print $1}}')"
  high="$(printf '%s' "$current" | awk '{{print $2}}')"
  case "$low$high" in *[!0-9]*|"") low=1; high=0 ;; esac

  if [ "$low" -le "$high" ] && [ "$cb_gid" -ge "$low" ] && [ "$cb_gid" -le "$high" ]; then
    return 0
  fi

  if [ "$low" -gt "$high" ]; then
    # Disabled: this group becomes the whole range rather than a union with
    # a sentinel that means "nobody".
    new_low="$cb_gid"; new_high="$cb_gid"
  else
    new_low="$low"; new_high="$high"
    [ "$cb_gid" -lt "$new_low" ] && new_low="$cb_gid"
    [ "$cb_gid" -gt "$new_high" ] && new_high="$cb_gid"
  fi

  echo "net.ipv4.ping_group_range = $new_low $new_high" >> "$SYSCTL_CONF"
  sysctl -w "net.ipv4.ping_group_range=$new_low $new_high" >/dev/null 2>&1 || true
}}
configure_unprivileged_icmp

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
# AF_NETLINK is not optional: Go's net.Interfaces() has no /sys fallback on
# Linux and the neighbour-cache dump (RTM_GETNEIGH) both go over a
# NETLINK_ROUTE socket. Without it the daemon cannot enumerate its own
# interfaces, so the derived direct_private scope arrives empty and every
# discovery target and probe destination is refused before a packet is sent.
# AF_PACKET stays out — this is a read-only route dump, not raw packet access.
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
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


def _live_nginx_cert_path() -> Path:
    import os

    return Path(os.environ.get("CB_DATA_DIR", "/data")) / "tls" / "fullchain.pem"


def _live_nginx_cert_pem() -> str | None:
    """Read nginx's actual TLS listener cert straight off disk.

    The `Certificate` table (certificate_service.py) manages a separate,
    unrelated concern — nginx's own `ssl_certificate` always points at
    {CB_DATA_DIR}/tls/fullchain.pem regardless of what that table contains,
    and both entrypoint-mono.sh and deploy/setup.sh generate that file's
    self-signed cert themselves, so this is the only source that reliably
    matches what an agent's TLS handshake actually sees.

    Returns None when there is genuinely no file — a legitimate "fall back to
    the database row" case. A file that exists but cannot be read is a
    different situation and raises: quietly pinning a `Certificate` row that
    is not what nginx serves would hand agents a pin that fails their TLS
    handshake, surfacing far from here as an unexplained enrollment failure.
    """
    path = _live_nginx_cert_path()
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
    except PermissionError as exc:
        raise ValueError(
            f"The TLS certificate at {path} exists but is not readable by the "
            f"backend service user ({exc.strerror}). It is the server's public "
            "certificate, so it should be world-readable; only the private key "
            "beside it needs to stay restricted. Re-run the installer or fix it "
            f"with: chmod 644 {path}"
        ) from exc
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
        "Cannot obtain TLS pin for the self-signed certificate: no cert at "
        f"{_live_nginx_cert_path()} and no certificate record in the database. "
        "An agent needs the pin to trust this server, so the install command "
        "cannot be generated without it."
    )


def tls_policy_for_certificate(cert: Certificate) -> tuple[str, str]:
    """The wire trust policy `cert` implies, derived from the row alone.

    Deliberately *not* `_tls_mode_and_pin`. That function prefers the live
    nginx certificate over the row it is handed, which is right for the
    install command — a new agent must be given the pin its very next
    handshake will see. It is wrong for a successor: on any real install
    `{CB_DATA_DIR}/tls/fullchain.pem` exists, so deriving a slice 4.1
    successor through it would advertise the pin the fleet already trusts.
    Every agent would report convergence on a policy nothing changed, and
    the activation gate would wave through the cutover that strands them.

    Lives here rather than in `agent_tls_pin` so the DB `type` -> wire mode
    mapping ("selfsigned" -> "self_signed", "letsencrypt" -> "public") has
    exactly one implementation, next to the other one that needs it.
    """
    if cert.type == "letsencrypt":
        return "public", ""
    return "self_signed", _spki_pin(cert.cert_pem)


def served_tls_policy() -> tuple[str, str] | None:
    """The wire trust policy nginx is presenting right now, or None when this
    install serves no certificate yet.

    Read from the live file rather than the `Certificate` table because that
    is what an agent's handshake actually sees — `_live_nginx_cert_pem`'s
    docstring has the full reason. None is a real answer, not an error: an
    install with nothing on disk has no policy for an agent to have pinned.

    The mode is reported as "self_signed" for anything on disk. This function
    cannot tell a publicly-trusted leaf from a self-signed one by inspection,
    and it does not need to: its only caller compares the *pin*, and two
    certificates with the same SPKI digest are the same trust decision
    whatever issued them.
    """
    pem = _live_nginx_cert_pem()
    if pem is None:
        return None
    return "self_signed", _spki_pin(pem)


def served_trust_policy(db: Session) -> tuple[str, str] | None:
    """The trust policy the fleet is actually operating under, or None when
    this install serves no certificate yet.

    `served_tls_policy` reads the bytes on disk, which is what an agent's
    handshake sees — but it cannot tell a publicly-trusted leaf from a
    self-signed one by inspection, so it reports "self_signed" for both. That
    is the right conservative answer for comparing a *pin* and the wrong one
    for comparing a *mode*: an agent enrolled against a Let's Encrypt server
    is in "public" mode and pins nothing, so a renewal changes nothing it
    verifies. Reading the mode off disk called every such renewal a trust
    change, which made `activation_block_reason` refuse an activation its own
    docstring lists as always safe.

    The mode comes from the active `Certificate` row, because that is the
    server's own record of what it advertised to the fleet. The pin still
    comes from the live file: when the two disagree the bytes win, since the
    bytes are what an agent checks.
    """
    served = served_tls_policy()
    if served is None:
        return None
    active = db.execute(select(Certificate).filter(Certificate.is_active)).scalars().first()
    mode = "public" if active is not None and active.type == "letsencrypt" else "self_signed"
    return mode, served[1]


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


def _script_download_arg(server_url: str, endpoint_id: str | None) -> str:
    """The `/install-agent.sh` URL as it appears in the emitted command.

    The id is *only* a link-builder here: `server_url` still decides the
    address, exactly as it did before. But the command is run on the target
    machine, and that machine's curl is the only thing `/install-agent.sh`
    ever sees — so without `?endpoint=<id>` on this URL the route takes its
    "absent" branch and re-derives the address from `forwarded_base_url`,
    which is the derivation the endpoint feature exists to eliminate (design
    §1.1). It also breaks the published `script_sha256`, since that digest is
    computed over the endpoint variant while the download would be the
    fallback one.

    Shell-quoted, because `?` is a glob character. `shlex.quote` leaves an
    ordinary URL untouched, so a command with no endpoint is byte-identical
    to what shipped before endpoints existed.
    """
    url = f"{server_url}/install-agent.sh"
    if endpoint_id is not None:
        url = f"{url}?endpoint={quote(endpoint_id, safe='')}"
    return shlex.quote(url)


def build_install_command(
    db: Session, server_url: str, endpoint_id: str | None = None
) -> InstallCommandResponse:
    # Task 28: once a server-key rotation has begun, a freshly generated
    # install prefers the successor identity key over the current one — it's
    # the key this install will still be valid under once the current key is
    # retired at the end of the overlap window (agent_crypto.
    # complete_ik_handshake accepts either for that window's duration, but a
    # *new* install has no reason to pin the key that's on its way out).
    state = agent_crypto.load_server_key_rotation_state(db)
    server_pub = state.successor_pub if state.successor_pub is not None else state.current_pub
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
    download = _script_download_arg(server_url, endpoint_id)

    if tls_mode == "public":
        command = f"curl -fsSL {download} | sudo sh"
    else:
        # --pinnedpubkey is what actually verifies this fetch (curl enforces it
        # even alongside -k, which is only here because the chain cannot
        # validate). The digest check below stays as an independent second
        # check rather than, as before, the only thing between -k and a
        # MITM'd installer.
        command = (
            f'curl -fsSL --insecure --pinnedpubkey "sha256//{tls_pin}" '
            f"{download} -o /tmp/cb-agent-install.sh && "
            f'echo "{script_sha256}  /tmp/cb-agent-install.sh" | sha256sum -c && '
            f"sudo sh /tmp/cb-agent-install.sh"
        )

    return InstallCommandResponse(tls_mode=tls_mode, command=command, script_sha256=script_sha256)
