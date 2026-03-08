# Remote Access & Tunnels

Circuit Breaker runs entirely on your LAN by default. This guide covers how to securely expose it to the internet — or to yourself when away from home — using a **Cloudflare Tunnel**.

---

## Why a Tunnel?

| Without a tunnel | With a Cloudflare Tunnel |
|---|---|
| Only accessible on your LAN | Accessible from anywhere |
| No TLS certificate for a real domain | Cloudflare provides a real TLS certificate |
| Google OAuth blocked (private IP) | Google OAuth works with a real domain |
| Port-forwarding your router required | No open inbound ports — outbound-only connection |

A Cloudflare Tunnel creates an encrypted, outbound-only connection from your server to Cloudflare's edge. Cloudflare then routes traffic to your app over that tunnel. Nothing opens in your firewall.

---

## Prerequisites

- A free [Cloudflare account](https://cloudflare.com)
- A domain added to Cloudflare (free plan works)
- Circuit Breaker running via Docker Compose

---

## Step 1 — Create the Tunnel

1. Go to [Cloudflare Zero Trust](https://one.cloudflare.com/) → **Networks → Tunnels**
2. Click **Create a tunnel** → **Cloudflared**
3. Give it a name (e.g. `circuit-breaker`)
4. Skip the install step — you'll run it in Docker
5. Copy the **Tunnel Token** shown on screen

---

## Step 2 — Configure the Tunnel Origin

Still in the tunnel configuration:

1. Under **Public Hostnames**, add a route:
   - **Subdomain**: `cb` (or whatever you prefer)
   - **Domain**: your domain (e.g. `yourdomain.com`)
   - **Service**: `http://caddy:80`  *(not HTTPS — Caddy is on the same Docker network)*
   
   Or if you prefer to route directly to Caddy's HTTPS port:
   - **Service**: `https://caddy:443`
   - Enable **No TLS Verify** (Caddy uses a local self-signed cert internally)

2. Save the tunnel

---

## Step 3 — Add the Token to Your `.env`

Open `.env` in the project root and set:

```env
CLOUDFLARE_TUNNEL_TOKEN=eyJh...your-token-here...
```

---

## Step 4 — Start the Tunnel

Start the entire stack including the tunnel profile:

```bash
make tunnel-up
```

Or manually:

```bash
docker compose --profile tunnel up -d
```

To stop just the tunnel without stopping the rest of the stack:

```bash
make tunnel-down
```

To start the full stack + tunnel from scratch:

```bash
docker compose --profile tunnel up --build -d
```

---

## Step 5 — Set the Application Base URL

This is **critical for OAuth** and for proper redirect behaviour.

1. Open Circuit Breaker in your browser at the new tunnel URL (e.g. `https://cb.yourdomain.com`)
2. Go to **Settings → Application**
3. Set **Application Base URL** to your tunnel URL:
   ```
   https://cb.yourdomain.com
   ```
4. Save

---

## Step 6 — Register OAuth Redirect URIs

If you use GitHub or Google OAuth, update the callback URLs in each provider:

**GitHub** — go to [GitHub OAuth Apps](https://github.com/settings/developers) and set the Authorization callback URL to:
```
https://cb.yourdomain.com/api/v1/auth/oauth/github/callback
```

**Google** — go to [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) and add the redirect URI:
```
https://cb.yourdomain.com/api/v1/auth/oauth/google/callback
```

See [Authentication & Access](auth-access.md) for full OAuth setup instructions.

---

## Verifying the Tunnel

Check that the tunnel is connected and the app is reachable:

```bash
# Check container is running and connected to Cloudflare
docker logs cb-cloudflared

# Confirm the app responds via the public URL
curl -I https://cb.yourdomain.com
```

A healthy `docker logs cb-cloudflared` output shows lines like:
```
INF Registered tunnel connection connIndex=0 ... location=phx01 protocol=quic
INF Registered tunnel connection connIndex=1 ... location=lax05 protocol=quic
```

Four connections across different Cloudflare edge locations is normal and means the tunnel is healthy.

---

## How It Fits Together

```
Browser (internet)
    ↓  HTTPS — Cloudflare terminates TLS
Cloudflare Edge
    ↓  Encrypted tunnel (QUIC)
cb-cloudflared container
    ↓  http://caddy:80 (Docker internal network)
cb-caddy (reverse proxy)
    ↓
cb-frontend / cb-backend
```

All inbound traffic enters via the tunnel. No ports need to be open on your router or firewall.

---

## Security Considerations

!!! warning "The tunnel exposes your app to the internet"
    Make sure authentication is enabled in Circuit Breaker before starting the tunnel. Go to **Settings → Security** and confirm **Require authentication** is on.

- Enable authentication before exposing the tunnel
- Enable MFA on admin accounts
- Review the [Audit Log](audit-log.md) periodically for unexpected access
- Consider using [Cloudflare Access](https://one.cloudflare.com/) policies to add an additional layer (email-based zero-trust access) in front of the tunnel

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `HTTP 530` from Cloudflare | Tunnel container not running or token invalid | Run `docker logs cb-cloudflared` to check. Verify `CLOUDFLARE_TUNNEL_TOKEN` is set in `.env` |
| Tunnel token not picked up | Running `docker compose` from `docker/` subdirectory | Use `make tunnel-up` from project root, or `docker compose --env-file .env --profile tunnel up -d` |
| `failed to set up container networking: network ... not found` | A stale `cb-cloudflared` container still points at a deleted Docker network | Run `make tunnel-up` again after pulling the latest changes. The target now removes and recreates `cb-cloudflared` automatically |
| OAuth `redirect_uri_mismatch` after setting up tunnel | Provider still has the old callback URL | Update redirect URIs in GitHub/Google to use the tunnel domain |
| App loads but API calls fail | Application Base URL not set | Set it to your tunnel URL in **Settings → Application** |
| `No such container: cb-cloudflared` | Stack started without `--profile tunnel` | Run `make tunnel-up` |
