# TLS Certificates

Circuit Breaker serves HTTPS from nginx, which reads one certificate pair out of
`$CB_DATA_DIR/tls/`. The **Certificates** page is how that pair gets there.

**Where:** Certificates page. Admin only.

## The three types

| Type | Where the certificate comes from |
|---|---|
| **Self-signed** | Generated here. Browsers will warn; nothing else is affected. |
| **Let's Encrypt** | Issued by a public CA over ACME. Requires a publicly-resolvable domain. |
| **Imported** | You paste a certificate and private key that were issued elsewhere. |

The type you pick is the type you get. Choosing Let's Encrypt when issuance cannot
succeed produces an error and **no row** — it never quietly falls back to a self-signed
certificate under another type's name.

## Activation is what makes a certificate served

Creating or renewing a certificate stores it. It does not change what the server
presents. **Activate** does both halves:

1. Writes `fullchain.pem` (`0644`) and `privkey.pem` (`0600`) into `$CB_DATA_DIR/tls/`.
2. Reloads nginx so the running listener picks them up.

At most one certificate is active. That is a database constraint, not a convention —
"which certificate are we serving?" is a question that must have exactly one answer.

Activation reports three outcomes, and *written but not reloaded* is a real one: the bytes
are on disk and the running server has not picked them up yet. It is shown as a warning
rather than as either success or failure, because the fix differs.

A renewal of the **active** certificate re-activates it automatically. A renewal of an
inactive one does not — renewing a certificate must never change which one the server
presents.

## Let's Encrypt

### CB_TLS_EMAIL

Set `CB_TLS_EMAIL` in your environment file. Let's Encrypt requires an account address and
uses it for expiry notices. Issuance refuses without one rather than inventing an address.

- **Docker Compose:** set it in `.env`; `docker-compose.yml` passes it through.
- **Native install:** `install.sh --email you@example.com` writes it.

### Before it will try

Preflight refuses, naming the specific unmet condition, before an attempt is spent:

- The domain must be publicly resolvable. `.local`, `.internal`, `.lan`, `.home`, `.test`,
  a bare hostname and IP literals are refused instantly — no public CA will ever issue for
  them.
- `CB_TLS_EMAIL` must be set.
- For HTTP-01, a token written under the challenge webroot must come back through the
  public name.

This matters because production ACME allows only **five failed validations per hostname
per hour**. A refusal that costs nothing is better than a rate limit.

### HTTP-01

The CA fetches `http://your-domain/.well-known/acme-challenge/<token>` with no credentials,
over port 80, before any certificate exists. So:

- Port 80 must reach this host from the internet.
- The ACME path must be **answered**, not redirected to HTTPS. All three shipped nginx
  configurations serve it directly, above the HTTPS redirect. If you have your own reverse
  proxy in front, it must do the same — a 301 here is the single most common way webroot
  validation fails, because on a first issuance there is no certificate to redirect to.

### DNS-01

DNS-01 proves control by publishing a DNS record, so it needs no inbound access at all.
For a homelab install, that is usually the only option that can work.

Configure a provider in the **Let's Encrypt DNS-01** panel on the Certificates page, then
choose DNS-01 when adding the certificate.

| Provider | Fields |
|---|---|
| **Cloudflare** | API token — scoped, with `Zone:DNS:Edit` on the zone. Not the Global API Key. |
| **RFC2136** | Nameserver, port (default 53), TSIG key name, TSIG secret, algorithm (default HMAC-SHA512). Works with BIND, Knot and PowerDNS. |

**Only these two.** Cloudflare covers the common managed case and RFC2136 is standard DNS
UPDATE, which covers any self-hosted nameserver. A provider nobody has exercised is worse
than one that is absent — see the same reasoning applied to integration providers in
[the 1.0.0 support contract](release/1.0.0-support-contract.md).

The credential is encrypted with the vault key, never returned by the API in any form, and
written to a `0600` file only for the seconds certbot needs it. Rotating the vault key
re-encrypts it. Setting the provider back to *Not configured* erases it.

### Staging

**Use Let's Encrypt Staging** issues against the staging directory. The resulting
certificate is **not trusted by browsers** — it is for checking that DNS credentials and
network paths work without spending production rate limits. It is off by default, and the
choice is recorded on the certificate, so a staging certificate renews against staging.

### Renewal

The nightly job at 03:45 renews anything expiring within the threshold and re-activates it
if it was the served certificate. It reissues using the same challenge and staging setting
the certificate was created with.

A renewal that fails **fails**: the API answers non-200, the stored expiry does not move,
and an audit entry is written with status `error` and the reason. One certificate's failure
does not abandon the rest.

## LAN-only installs

If this install has no public domain name, a public certificate authority cannot issue for
it, and no amount of configuration changes that. **Stay on a self-signed certificate.**
Trust it once in your browser, or add it to your clients' trust stores. This is a
deliberate boundary, not a missing feature.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "No public certificate authority will issue for …" | The domain is a reserved suffix or an IP. Use self-signed. |
| "CB_TLS_EMAIL is not set" | The variable is not reaching the process. Check `.env` and restart. |
| "… did not serve a file this install just wrote" | Port 80 is not reaching this host, or something in front is redirecting the ACME path. |
| "DNS-01 credentials are not configured" | No provider is set in the DNS-01 panel, or the credential field is empty. |
| "certbot is not available in this image" | An image built before certbot was packaged. Pull a current one. |
| Renewed, but the browser still shows the old certificate | The certificate was not the active one. Activate it. |
| Activated, but "TLS did not reload" | The bytes are written. nginx did not reload — check its logs and reload it. |
