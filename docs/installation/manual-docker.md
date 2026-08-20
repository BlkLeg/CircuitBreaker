# Single Docker Container

Run Circuit Breaker as a single Docker container with a `docker run` command. This is the most minimal setup — no Compose file, no extra services. The published image is the mono image: Postgres, Redis, NATS, the backend, the workers and nginx all run inside it.

The container serves the application over HTTPS on port `8443` with a self-signed certificate it generates on first start. Port `8080` only redirects to HTTPS (the health endpoint is the one exception).

---

## Prerequisites

- **Docker Engine 20+**
- Outbound internet access to pull from `ghcr.io`

---

## Minimal Run Command

The container refuses to start without its secrets, so the smallest working command still sets four of them. Generate them first:

```bash
export CB_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export CB_VAULT_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export CB_DB_PASSWORD=$(openssl rand -base64 24)
export NATS_AUTH_TOKEN=$(openssl rand -base64 32)
```

```bash
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8443:8443 \
  -v circuit-breaker-data:/data \
  -e CB_JWT_SECRET="$CB_JWT_SECRET" \
  -e CB_VAULT_KEY="$CB_VAULT_KEY" \
  -e CB_DB_PASSWORD="$CB_DB_PASSWORD" \
  -e NATS_AUTH_TOKEN="$NATS_AUTH_TOKEN" \
  -e CB_ALLOW_DIRECT_EGRESS=true \
  ghcr.io/blkleg/circuitbreaker:latest
```

Then open `https://localhost:8443` and accept the self-signed certificate warning.

**Required environment:**

| Variable | Notes |
|---|---|
| `CB_JWT_SECRET` | At least 32 characters, and different from `CB_VAULT_KEY`. The entrypoint aborts otherwise. |
| `NATS_AUTH_TOKEN` | At least 32 characters. The entrypoint aborts otherwise. |
| `CB_VAULT_KEY` | Fernet key for the credential vault. |
| `CB_DB_PASSWORD` | Needed for the embedded Postgres initial setup. |
| `CB_ALLOW_DIRECT_EGRESS` | Startup fails without either this set to `true` or `CB_EGRESS_PROXY_URL` pointing at a forward proxy. Unlike Compose, a plain `docker run` has no default behind it. |

`CB_ALLOW_DIRECT_EGRESS=true` waives only the forward-proxy requirement. SSRF and outbound URL policy still apply, and Redis, NATS, rate-limit storage and secrets still fail closed. On a host that does have a proxy, use `-e CB_EGRESS_PROXY_URL=http://proxy:3128` instead.

---

## Port Binding

The example above binds to `127.0.0.1:8443` — the container is only reachable from the host itself. This is the safest default when you plan to put a reverse proxy in front.

To make Circuit Breaker reachable from other machines on your network (no reverse proxy):

```bash
-p 8443:8443
```

Publish `8080` as well if you want visitors on plain HTTP to be redirected to HTTPS.

> **Security note:** Binding to `0.0.0.0` exposes the port on all network interfaces including public ones. Use a host firewall to control access if you do this.

---

## Persistent Storage

The `-v circuit-breaker-data:/data` flag mounts a named Docker volume at `/data` inside the container. This is where the Postgres data directory, NATS and Redis state, TLS certificates, the vault key, and all uploads are stored.

To use a host directory instead (useful for easier backups):

```bash
-v /opt/circuit-breaker/data:/data
```

---

## Setting a Vault Key

The vault key encrypts stored credentials at rest. Generate a key with:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Pass it as `-e CB_VAULT_KEY=...` alongside the other required variables shown above. It must not be the same value as `CB_JWT_SECRET`.

If the vault key is rotated later, the new value is written to `/data/.env` inside the volume and the entrypoint picks it up from there on the next start, even if the `-e` value is stale.

---

## Enabling ARP Scanning (Optional)

To allow the discovery engine to use ARP for MAC address resolution, add the Linux capabilities:

```bash
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8443:8443 \
  -v circuit-breaker-data:/data \
  --cap-add NET_RAW \
  --cap-add NET_ADMIN \
  -e CB_JWT_SECRET="$CB_JWT_SECRET" \
  -e CB_VAULT_KEY="$CB_VAULT_KEY" \
  -e CB_DB_PASSWORD="$CB_DB_PASSWORD" \
  -e NATS_AUTH_TOKEN="$NATS_AUTH_TOKEN" \
  -e CB_ALLOW_DIRECT_EGRESS=true \
  ghcr.io/blkleg/circuitbreaker:latest
```

> Only use this on trusted, isolated networks. Without these capabilities, Circuit Breaker skips ARP and uses nmap TCP/ICMP instead.

---

## HTTPS / TLS

The container terminates TLS itself. On first start the entrypoint generates a self-signed certificate at `/data/tls/fullchain.pem` and `/data/tls/privkey.pem` if neither file exists. To use your own certificate, drop the two files into the same paths in the volume and restart the container.

To front it with your own reverse proxy, proxy to the container's HTTPS port:

```nginx
server {
    listen 443 ssl;
    server_name circuitbreaker.local;
    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    location / {
        proxy_pass https://127.0.0.1:8443;
        proxy_ssl_verify off;   # the container's cert is self-signed
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

**Important:** Set the **External App URL** in Circuit Breaker's Settings (or during OOBE) to your public HTTPS URL so that password reset emails and invite links work correctly.

---

## Managing the Container

```bash
# View logs
docker logs circuit-breaker
docker logs -f circuit-breaker   # follow

# Stop
docker stop circuit-breaker

# Start
docker start circuit-breaker

# Restart
docker restart circuit-breaker

# Update to latest image
docker pull ghcr.io/blkleg/circuitbreaker:latest
docker stop circuit-breaker && docker rm circuit-breaker
# Re-run the original docker run command with the same volume

# Remove container only (data preserved in volume)
docker rm circuit-breaker

# Remove container and data
docker rm circuit-breaker
docker volume rm circuit-breaker-data
```

---

## Health Check

Circuit Breaker exposes four probe endpoints, and which one you use matters:

| Endpoint | Answers | Use it for |
| --- | --- | --- |
| `GET /api/v1/livez` | Is the process able to serve at all? | Restart decisions — Docker `HEALTHCHECK`, systemd, Kubernetes liveness |
| `GET /api/v1/readyz` | Can it safely serve traffic right now? (includes Postgres and Redis) | Load-balancer membership, Kubernetes readiness |
| `GET /api/v1/startupz` | Has initialisation finished? | Holding a liveness probe off during a slow migration |
| `GET /api/v1/health` | Combined legacy view | Dashboards and the built-in frontend poll |

```
GET http://127.0.0.1:8080/api/v1/livez
```

Point restart-deciding probes at `/livez` and nothing else. `/health` and `/readyz` both fold Postgres and Redis into their verdict, so wiring either one to a restart turns a brief dependency outage into a restart loop against a backend that is working fine.

These four are the only paths on port `8080` that are not redirected to HTTPS, which is what makes them usable as a Docker `HEALTHCHECK` or a plain-HTTP monitoring probe. Publish port `8080` if you want to reach them from outside the container.

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for all environment variables.
