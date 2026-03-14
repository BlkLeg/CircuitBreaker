# Advanced Single Container Reference

Run Circuit Breaker as a single Docker container with a `docker run` command when you explicitly want a custom proxy-managed deployment.

This is an advanced reference, not the primary supported install path. For the standard tested Docker experience, use [Quick Install (Script)](quick-install.md) or [Docker Compose — Prebuilt Full Stack](docker-compose-prod.md).

---

## Prerequisites

- **Docker Engine 20+**
- Outbound internet access to pull from `ghcr.io`

---

## Example Run Command

```bash
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v circuit-breaker-data:/data \
  ghcr.io/blkleg/circuitbreaker:latest
```

Then open `http://localhost:8080`.

---

## Port Binding

The example above binds to `127.0.0.1:8080` — the container is only reachable from the host itself. This is the safest default when you plan to put a reverse proxy in front.

To make Circuit Breaker reachable from other machines on your network (no reverse proxy):

```bash
-p 8080:8080
```

> **Security note:** Binding to `0.0.0.0` exposes the port on all network interfaces including public ones. Use a host firewall to control access if you do this.

---

## Persistent Storage

The `-v circuit-breaker-data:/data` flag mounts a named Docker volume at `/data` inside the container. This is where the SQLite database, vault key, and all uploads are stored.

To use a host directory instead (useful for easier backups):

```bash
-v /opt/circuit-breaker/data:/data
```

---

## Setting a Vault Key

The vault key encrypts stored credentials at rest. Pass it as an environment variable:

```bash
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v circuit-breaker-data:/data \
  -e CB_VAULT_KEY=your-fernet-key-here \
  ghcr.io/blkleg/circuitbreaker:latest
```

Generate a key with:

```bash
openssl rand -base64 32
```

If `CB_VAULT_KEY` is not set, Circuit Breaker auto-generates one during the [first-run wizard](first-run.md) and writes it to `/data/.env` inside the volume. This persists as long as the volume is not deleted.

---

## Full Example with Environment Variables

```bash
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v circuit-breaker-data:/data \
  -e DATABASE_URL=sqlite:////data/app.db \
  -e UPLOADS_DIR=/data/uploads \
  -e CB_VAULT_KEY=your-fernet-key-here \
  ghcr.io/blkleg/circuitbreaker:latest
```

---

## Enabling ARP Scanning (Optional)

To allow the discovery engine to use ARP for MAC address resolution, add the Linux capabilities:

```bash
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v circuit-breaker-data:/data \
  --cap-add NET_RAW \
  --cap-add NET_ADMIN \
  ghcr.io/blkleg/circuitbreaker:latest
```

> Only use this on trusted, isolated networks. Without these capabilities, Circuit Breaker skips ARP and uses nmap TCP/ICMP instead.

---

## HTTPS / TLS

This method has no built-in HTTPS. To serve Circuit Breaker over HTTPS, place it behind a reverse proxy that handles TLS termination:

**Caddy** (simplest — automatic self-signed or ACME certs):

```caddy
circuitbreaker.local {
    reverse_proxy localhost:8080
}
```

**nginx:**

```nginx
server {
    listen 443 ssl;
    server_name circuitbreaker.local;
    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
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

Circuit Breaker exposes a health endpoint:

```
GET http://localhost:8080/api/v1/health
```

You can use this in your monitoring stack or as a Docker `HEALTHCHECK`.

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for all environment variables.
