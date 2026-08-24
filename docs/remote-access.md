# Remote Access

Circuit Breaker runs entirely on your LAN by default. This guide covers how to reach it from
outside that LAN, and — more importantly — what you have to configure so the app behaves correctly
once something else is terminating TLS in front of it.

> **v1.0 release-candidate boundary:** directly internet-exposed operation is not a supported
> deployment boundary for a 1.0 release candidate unless the release owner records an approved
> exception. Prefer VPN or trusted-network access.

!!! note "No tunnel integration ships in this release"
    There is no bundled Cloudflare Tunnel, Tailscale, or similar service in any shipped install
    path. `docker-compose.yml` defines exactly one service, `circuitbreaker`, and there are no
    optional profiles. If you want a tunnel, run it yourself alongside Circuit Breaker and point it
    at the published ports described below.

---

## What Circuit Breaker already terminates

Both shipped install paths put **nginx** in front of the backend and terminate TLS themselves. You
do not need a second reverse proxy unless you want a real public certificate or a tunnel.

### Docker (single container)

The mono image runs nginx inside the container (`docker/nginx.mono.conf`):

| Container port | Behaviour |
|---|---|
| `8080` | HTTP. `301` redirects everything to HTTPS, except `/api/v1/health`, `/api/v1/livez`, `/api/v1/readyz` and `/api/v1/startupz`, which are proxied so the Docker healthcheck (which polls `/api/v1/livez`) and plain-HTTP monitoring probes still work |
| `8443` | HTTPS. Reads `/data/tls/fullchain.pem` and `/data/tls/privkey.pem` |

`docker-compose.yml` publishes those as `${CB_PORT:-80}:8080` and `${CB_PORT_HTTPS:-443}:8443`.
If no certificate is present at startup, `docker/entrypoint-mono.sh` generates a self-signed one
into `/data/tls`, so the container always comes up with HTTPS available.

### Native (systemd)

`deploy/nginx/circuitbreaker-tls.conf` is rendered at install time:

| Host port | Behaviour |
|---|---|
| `${CB_PORT}` | HTTP. `301` redirects to `https://$host$request_uri` |
| `443` | HTTPS. Reads `${CB_DATA_DIR}/tls/fullchain.pem` and `privkey.pem`, proxies to `127.0.0.1:8000` |

See [Deployment & Security](deployment-security.md) for how those certificates are produced.

---

## Putting your own proxy or tunnel in front

Point your upstream at the **published HTTPS port** (`${CB_PORT_HTTPS:-443}` for Docker, `443` for
native). If your proxy cannot validate a self-signed certificate, either disable certificate
verification for that origin or point it at the HTTP port instead — but be aware the HTTP port
`301`-redirects everything, so an HTTP-only upstream will loop unless your proxy rewrites the
scheme.

Whatever you put in front must forward the standard headers, and you must tell Circuit Breaker to
trust it.

---

## Trusted proxies

This is the setting people miss, and it fails quietly.

Circuit Breaker only believes `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host` when
the socket peer is inside `CB_TRUSTED_PROXY_CIDRS`. The default is:

```env
CB_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
```

That default is correct for the bundled nginx, which connects over loopback. It is **not** correct
for a proxy or tunnel container that reaches the backend from any other address — in that case every
forwarded header is discarded and the request falls back to the socket peer.

Two things break when that happens, and neither produces an obvious error:

- **Rate limiting collapses onto the proxy's IP.** The rate-limit key comes from
  `trusted_client_identity()`, which only uses the forwarded chain behind a trusted peer. With an
  untrusted peer, every user in the world shares one bucket — so one busy client can lock everyone
  out of login.
- **`CB_WS_REQUIRE_WSS` rejects valid connections.** If TLS is terminated upstream, the handshake
  reaching the backend is plain `ws://` and the `X-Forwarded-Proto: https` header is ignored, so the
  connection is refused as insecure.

Set the CIDR your proxy actually connects from:

```env
CB_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128,172.18.0.0/16
```

The value is a comma-separated list. Invalid entries are ignored with a warning rather than causing
a startup failure, so check the logs after changing it.

Only list ranges you control. Any host inside these CIDRs can assert any client IP it likes.

---

## Set the App URL

Circuit Breaker auto-detects a LAN URL on startup. Once you are reaching it through a different
hostname, set the URL explicitly or invite links and OAuth redirects will point at the wrong place.

1. Open **Settings → Connectivity**
2. Under **External Access**, set **App URL (used in invite links)** to your external URL, e.g.
   `https://cb.example.com`
3. Save

---

## Register OAuth redirect URIs

If you use GitHub or Google OAuth, update the callback URLs at each provider to match the App URL:

**GitHub** — [GitHub OAuth Apps](https://github.com/settings/developers), Authorization callback URL:

```
https://cb.example.com/api/v1/auth/oauth/github/callback
```

**Google** — [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials),
authorised redirect URI:

```
https://cb.example.com/api/v1/auth/oauth/google/callback
```

See [Authentication & Access](auth-access.md) for full OAuth setup instructions.

---

## Security Considerations

!!! warning "Exposing the app puts your inventory on the internet"
    Confirm authentication is enforced and admin accounts have MFA enabled before you expose
    Circuit Breaker beyond your LAN.

- Enable MFA on admin accounts.
- Set `CB_WS_REQUIRE_WSS=true` so plain-WebSocket connections are refused — and make sure
  `CB_TRUSTED_PROXY_CIDRS` is correct first, or this will reject everything.
- Set `CB_TRUSTED_PROXY_CIDRS` to the proxy's real source range, and nothing wider.
- Review the [Audit Log](audit-log.md) periodically for unexpected access.
- Consider an authenticating layer (zero-trust access policies, VPN, or client certificates) in
  front of the app rather than exposing it directly.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser warns about the certificate | The shipped certificate is self-signed | Expected on a fresh install. Terminate TLS at a proxy with a real certificate, or place a valid `fullchain.pem` / `privkey.pem` in the TLS directory |
| Redirect loop on the HTTP port | Something upstream is speaking HTTP to a port that always redirects to HTTPS | Point the upstream at the HTTPS port, or have it set `X-Forwarded-Proto: https` and terminate TLS itself |
| Everyone gets rate-limited at once | `CB_TRUSTED_PROXY_CIDRS` does not include the proxy, so all requests share the proxy's IP as the rate-limit key | Add the proxy's source CIDR and restart |
| WebSockets refused when `CB_WS_REQUIRE_WSS=true` | `X-Forwarded-Proto` is being ignored because the peer is untrusted | Add the proxy's source CIDR to `CB_TRUSTED_PROXY_CIDRS` |
| Live updates never arrive | The proxy is not forwarding `Upgrade` / `Connection` headers | Enable WebSocket support on the upstream proxy |
| OAuth `redirect_uri_mismatch` | Provider still has the old callback URL | Update the redirect URIs in GitHub/Google to match the App URL |
| Invite links point at a LAN IP | App URL not set | Set it under **Settings → Connectivity → External Access** |

---

## Related Guides

- [Deployment & Security](deployment-security.md)
- [Authentication & Access](auth-access.md)
- [Audit Log](audit-log.md)
