# Remote Access

Circuit Breaker runs entirely on your LAN by default. This guide covers how to reach it from
outside that LAN, and — more importantly — what you have to configure so the app behaves correctly
once something else is terminating TLS in front of it.

It is also the reference for the operational questions that come with exposing anything: which
[ports](#firewall-and-ports) must be open and which must not, [who owns and renews the TLS
certificate](#who-owns-tls-and-who-renews-it), what
[connectivity an agent needs](#agent-connectivity-requirements) at a remote site, and what
[air-gap mode](#air-gap-limitations) does and does not cover.

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

## Firewall and ports

Only two ports need to reach the host from anywhere. Everything else is loopback, and should stay
that way.

### Mono container

| Port | Direction | Who needs it | Notes |
|---|---|---|---|
| `${CB_PORT_HTTPS:-443}` → container `8443` | Inbound | Browsers, `cb-agent`, API clients | The port to publish |
| `${CB_PORT:-80}` → container `8080` | Inbound | HTTP-01 ACME validation; plain-HTTP health probes | `301`-redirects everything except `/api/v1/health`, `/livez`, `/readyz`, `/startupz` and the ACME challenge path. Close it if you neither use HTTP-01 nor probe over plain HTTP |
| `5432`, `6432`, `6379`, `4222` | — | Nobody | PostgreSQL, PgBouncer, Redis and NATS run **inside** the container. They are not published and must not be |

### Native systemd

| Port | Direction | Bound to | Notes |
|---|---|---|---|
| `443` | Inbound | All interfaces | HTTPS, terminated by nginx |
| `${CB_PORT}` (installer default `8088`) | Inbound | All interfaces | HTTP; `301`-redirects to HTTPS, except the ACME challenge path |
| `8000` | — | `127.0.0.1` | The backend. nginx proxies to it; nothing else should reach it |
| `5432` / `6432` | — | `127.0.0.1` | PostgreSQL / PgBouncer |
| `6379` | — | `127.0.0.1` | Redis |
| `4222` | — | `127.0.0.1` | NATS |
| `2375` | — | Local | The optional Docker API proxy, only when `DOCKER_PROXY_ENABLED=true` |

The native installer opens the two public ports for you when a firewall is already running: with
`firewall-cmd` it adds `${CB_PORT}/tcp` and — unless `--no-tls` — `443/tcp`, then reloads; with
`ufw` it does the same, but **only if ufw is already active**, so it never enables a firewall you
had deliberately left off. `cb doctor` re-checks that the port is actually open off-box, and on
SELinux hosts that the port carries an SELinux label.

### Outbound

What the server itself dials. Both shipped install paths work with **no inbound rules beyond the
two above** and these outbound allowances:

| Destination | Needed for | Optional? |
|---|---|---|
| `api.github.com:443` | The daily release check | Yes — `CB_UPDATE_CHECK=false` or `CB_AIRGAP=true` |
| Let's Encrypt ACME endpoints, `:443` | Certificate issuance and renewal | Yes — only if you use Let's Encrypt |
| Your SMTP server | Invite email | Yes — only if SMTP is configured |
| Your OAuth/OIDC provider, `:443` | OAuth sign-in | Yes — only if OAuth is configured |
| `services.nvd.nist.gov:443` | CVE feed sync | Yes |
| `urlhaus.abuse.ch`, `threatfox.abuse.ch`, `small.oisd.nl`, `:443` | Threat feeds | Yes |
| `api.macvendors.com:443` | MAC vendor lookup, only when offline OUI sources miss | Yes |
| Your LAN | Discovery, monitor checks, hardware telemetry (SNMP `161/udp`, Redfish `443`) | Depends on what you monitor |

The complete list of what leaves the deployment, with what each request contains, is in
[Privacy § What leaves your deployment](security/privacy.md#what-leaves-your-deployment).
`CB_EGRESS_PROXY_URL` routes the public HTTP clients through a forward proxy.

---

## Who owns TLS, and who renews it

Ownership has to be unambiguous, because a certificate that two systems both think they manage is a
certificate nobody renews. Pick exactly one row.

| Model | Who terminates TLS | Who renews | What you must do |
|---|---|---|---|
| **Bundled, self-signed** (default) | The shipped nginx | Nobody — it is valid for 10 years on native installs | Nothing. Browsers warn on first visit. Fine on a LAN |
| **Bundled, Let's Encrypt via the Certificates page** | The shipped nginx | Circuit Breaker. Renewal of the **active** certificate re-activates it automatically | Set `CB_TLS_EMAIL`, own a publicly-resolvable domain, and keep port 80 reachable for HTTP-01 (or use DNS-01) |
| **Bundled, your own certificate** | The shipped nginx | **You** | Place `fullchain.pem` and `privkey.pem` in `$CB_DATA_DIR/tls/` and restart, or import them on the Certificates page and press **Activate**. Repeat at every renewal |
| **Your reverse proxy terminates** | Your proxy | **You**, in your proxy | Point it at the published HTTPS port; set `CB_TRUSTED_PROXY_CIDRS` to the proxy's source range. The app keeps its own certificate for the internal hop |

Two rules that catch people:

- **Creating or renewing a certificate does not change what is served.** Only **Activate** writes
  `fullchain.pem` and `privkey.pem` and reloads nginx. At most one certificate is active, enforced
  as a database constraint.
- **A LAN-only install cannot obtain a publicly-trusted certificate.** `.local`, `.internal`,
  `.lan`, `.home`, `.test`, bare hostnames and IP literals are refused by preflight, instantly,
  because no public CA will ever issue for them. That is not a limitation of this software.

Full procedure, challenge types and the ACME rate limits: [TLS Certificates](tls-certificates.md).

---

## Agent connectivity requirements

`cb-agent` is designed for the remote-site case: **no inbound firewall rule at the agent's site.**

| Requirement | Detail |
|---|---|
| Direction | Outbound only. The agent binds **no listening socket** |
| Destination | Whatever `server_url` in `agent.toml` says — the published HTTPS port of your server |
| Protocols | `wss://…/api/v1/agents/enroll` and `…/agents/link` (WebSocket over TLS), plus `https://…/api/v1/agents/binary/…` for self-update and `https://…/install-agent.sh` once at install |
| Ports | Only the port in `server_url`. The agent has no port of its own and never falls back to a different one |
| Proxies | `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY` (and lowercase forms) are honoured for all of the above, WebSocket dials included |
| Certificate | With a publicly-trusted certificate the agent uses the system trust store. With a self-signed one the server hands the agent a **pin** — the base64 SHA-256 of the served leaf's SubjectPublicKeyInfo — and chain and hostname verification are replaced by an exact match against it |

Consequences for your topology:

- **If a reverse proxy or tunnel sits in front, it must forward `Upgrade` and `Connection` headers**,
  or agents connect and immediately fail. So do the browser's live-update sockets.
- **If that proxy re-terminates TLS with its own certificate**, a pinned agent will refuse it — the
  pin is computed from the certificate *your nginx* serves. Either give the agent a `server_url`
  that reaches nginx directly, or move to a publicly-trusted certificate so pinning is not used.
- **`CB_WS_REQUIRE_WSS=true` needs `CB_TRUSTED_PROXY_CIDRS` set first.** Behind a TLS-terminating
  proxy the handshake reaching the backend is plain `ws://`, and `X-Forwarded-Proto` is ignored from
  an untrusted peer — so every agent is refused as insecure.
- **Changing the published port changes the agent's world.** The agent uses the port in
  `server_url`; a changed `CB_PORT_HTTPS` needs the agents' configuration updated.
- **The WebSocket per-IP cap and `ws_allowed_cidrs` also depend on `CB_TRUSTED_PROXY_CIDRS`.**
  Every `/ws/` endpoint now resolves the client address through the same trusted-proxy check the
  rest of the app uses, instead of trusting the leftmost `X-Forwarded-For` value. That closes a real
  hole — an off-network client could previously satisfy an operator's `ws_allowed_cidrs` allowlist by
  setting a header — but it fails *closed*: behind a proxy that is **not** listed in
  `CB_TRUSTED_PROXY_CIDRS`, the forwarded address is ignored, every client is seen as the proxy's own
  address, and so they share one connection-cap bucket and any `ws_allowed_cidrs` entry naming a real
  client subnet stops matching. The shipped topologies are unaffected — nginx proxies over
  `127.0.0.1`, which is in the default — but a custom proxy needs its source range listed here for
  the same reason `CB_WS_REQUIRE_WSS` does.

The full destination list, the enrollment limits, and what the agent sends to your network:
[cb-agent § Outbound endpoints](agent.md#outbound-endpoints).

---

## Air-gap limitations

Two different things are often called "air-gapped". Circuit Breaker supports one of them.

**Air-gapped operation — supported.** A running instance can be told never to make an outbound
request of its own:

```env
CB_AIRGAP=true
```

or the `airgap_mode` switch in **Settings** — either is enough. That refuses network scans with
`403` and stops the release check opening a socket at all. `CB_UPDATE_CHECK=false` turns off the
release check alone, for an operator who wants scanning egress but no contact with GitHub.

What still requires egress when you use the feature, and what to disable if you have none:

| Feature | Needs egress | Turn off by |
|---|---|---|
| Release check | `api.github.com` | `CB_UPDATE_CHECK=false` (or air-gap mode) |
| Let's Encrypt | ACME endpoints | Use a self-signed or imported certificate |
| CVE sync | `services.nvd.nist.gov` | Do not trigger a sync |
| Threat feeds | `abuse.ch`, `oisd.nl` | Do not enable them |
| MAC vendor fallback | `api.macvendors.com` | Air-gap mode prevents the scan that reaches it |
| OAuth sign-in | Your provider | Use local accounts |
| Gravatar, Google Fonts, weather widget | The **user's browser**, not the server | Tighten the CSP at your reverse proxy |

**Air-gapped installation — [unsupported for 1.0.0](release/1.0.0-support-contract.md#deployment-support-matrix).**
Getting the software onto the host still requires downloading artifacts and dependencies. There is
no signed offline bundle in this release, and `ACC-8` has not passed. Staging the artifacts yourself
on a connected machine and carrying them across may well work; it is simply not a supported,
evidenced path, and `cb update` on a native install fetches the installer over the internet.

---

## Security Considerations

!!! warning "Exposing the app puts your inventory on the internet"
    Confirm authentication is enforced and admin accounts have MFA enabled before you expose
    Circuit Breaker beyond your LAN.

- Enable MFA on admin accounts.
- Set `CB_WS_REQUIRE_WSS=true` so plain-WebSocket connections are refused — and make sure
  `CB_TRUSTED_PROXY_CIDRS` is correct first, or this will reject everything.
- Set `CB_TRUSTED_PROXY_CIDRS` to the proxy's real source range, and nothing wider. Every
  WebSocket stream now derives the client address the same way the rate limiter does: it
  believes `X-Forwarded-For` only from a peer inside this list, and otherwise uses the socket
  peer. That is what stops an off-net client from writing itself an address inside the
  WebSocket CIDR allowlist (`ws_allowed_cidrs` in app settings), but it also means a proxy
  missing from this list makes every WebSocket client look like the proxy.
- Review the [Audit Log](audit-log.md) periodically for unexpected access.
- Consider an authenticating layer (zero-trust access policies, VPN, or client certificates) in
  front of the app rather than exposing it directly.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser warns about the certificate | The shipped certificate is self-signed | Expected on a fresh install. Terminate TLS at a proxy with a real certificate, or place a valid `fullchain.pem` / `privkey.pem` in the TLS directory |
| Redirect loop on the HTTP port | Something upstream is speaking HTTP to a port that always redirects to HTTPS | Point the upstream at the HTTPS port, or have it set `X-Forwarded-Proto: https` and terminate TLS itself |
| The WebSocket CIDR allowlist (`ws_allowed_cidrs`) suddenly rejects everyone (`ip_not_allowed`) | `CB_TRUSTED_PROXY_CIDRS` does not include the proxy, so the allowlist is matched against the proxy's own address instead of the client's | Add the proxy's source CIDR and restart. Adding the proxy's address to the WebSocket allowlist instead would let *any* client through, since they all arrive with that address |
| WebSocket connections rejected with `connection_limit_exceeded` under load | Same cause: with the proxy untrusted every client shares one per-IP bucket (`CB_WS_*_MAX_PER_IP`) | Add the proxy's source CIDR to `CB_TRUSTED_PROXY_CIDRS`; raise the cap only if the real per-client count justifies it |
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
- [TLS Certificates](tls-certificates.md)
- [cb-agent](agent.md)
- [Threat model](security/threat-model.md) — the trusted-proxy boundary analysed
- [Privacy](security/privacy.md) — everything that leaves the deployment
