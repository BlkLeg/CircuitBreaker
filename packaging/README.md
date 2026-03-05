# Circuit Breaker — Packaging & Installation

This directory contains the packaging artifacts and install helpers for
deploying Circuit Breaker outside of a container-first environment.

## Directory layout

```
packaging/
├── systemd/
│   └── circuit-breaker.service   # systemd unit for Linux hosts
└── README.md                      # this file
```

## One-liner install (Docker)

The canonical install scripts live at the **repo root** so that their
`curl | bash` URLs remain stable:

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash

# Uninstall
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash
```

## systemd service (Linux native)

For environments where you want Circuit Breaker to auto-start via systemd
rather than relying on Docker's `--restart unless-stopped`:

```bash
# Copy the unit file
sudo cp packaging/systemd/circuit-breaker.service /etc/systemd/system/

# Optional: override defaults without editing the unit file
sudo mkdir -p /etc/systemd/system/circuit-breaker.service.d
cat <<EOF | sudo tee /etc/systemd/system/circuit-breaker.service.d/override.conf
[Service]
Environment=CB_PORT=9090
Environment=CB_VOLUME=/opt/circuit-breaker-data
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now circuit-breaker

# Check status
sudo systemctl status circuit-breaker

# Pull a new image and restart
sudo systemctl reload circuit-breaker
```

## Supported platforms

| Platform | Method |
|---|---|
| Linux x86_64 | Docker (recommended), systemd unit |
| Linux arm64 (Raspberry Pi) | Docker (recommended), systemd unit |
| Linux arm/v7 | Docker |
| macOS | Docker Desktop |
| Windows | Docker Desktop |

## Environment variables

All configuration is passed through environment variables, either on the
`docker run` command line or via the systemd override drop-in:

| Variable | Default | Description |
|---|---|---|
| `CB_PORT` | `8080` | Host port to expose |
| `CB_VOLUME` | `circuit-breaker-data` | Docker volume or host path for data |
| `CB_IMAGE` | `ghcr.io/blkleg/circuitbreaker:latest` | Image to pull |
| `CB_CONTAINER` | `circuit-breaker` | Container name |
| `DEV_MODE` | `false` | Enable developer mode (bypasses auth) |
