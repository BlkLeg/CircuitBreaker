# Configuration Reference

Circuit Breaker is configured via environment variables. All variables can be passed to the container at runtime — either in your `docker-compose.yml`, a `.env` file, or with `-e` flags on `docker run`.

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:////data/app.db` | SQLAlchemy database connection string. Override with a PostgreSQL URL when using the `--profile pg` compose profile. |
| `CB_VAULT_KEY` | _(auto-generated)_ | Fernet encryption key for the credential vault. Auto-generated and persisted to `/data/.env` during OOBE if not set. See [Vault Key](#vault-key). |
| `CB_API_TOKEN` | _(none)_ | Optional static bearer token for programmatic API access. Set to protect write endpoints independently of user auth. |
| `UPLOADS_DIR` | `/data/uploads` | Path for runtime uploads (icons, branding assets). Must be inside the mounted data volume. |
| `CB_DATA_DIR` | `/app/data` | Backend data directory root. Only relevant when overriding the default volume mount path. |
| `DEBUG` | `false` | Set to `true` to enable verbose backend logging. Not recommended in production. |

### Discovery

| Variable | Default | Description |
|---|---|---|
| `DISCOVERY_MODE` | `safe` | Discovery scan mode. `safe` uses nmap TCP/ICMP (no elevated privileges needed). `full` adds ARP scanning (requires `NET_RAW` + `NET_ADMIN` capabilities). |
| `NATS_URL` | `nats://nats:4222` | NATS JetStream connection URL used by workers. Only relevant in Compose installs with a NATS service. |

### TLS / HTTPS (Compose installs with Caddy)

| Variable | Default | Description |
|---|---|---|
| `CB_DOMAIN` | `circuitbreaker.local` | Domain Caddy listens on. Set to a public FQDN for automatic ACME / Let's Encrypt certificates. |
| `CB_TLS_EMAIL` | `admin@circuitbreaker.local` | Email for ACME / Let's Encrypt. Required when `CB_LOCAL_CERTS` is empty and `CB_DOMAIN` is a public domain. |
| `CB_LOCAL_CERTS` | `local_certs` | Set to `local_certs` to use Caddy's local self-signed CA (default, for `.local` / LAN domains). Set to an empty string to enable ACME/Let's Encrypt. |

### PostgreSQL (Compose `--profile pg`)

| Variable | Default | Description |
|---|---|---|
| `CB_DB_URL` | _(none)_ | Full PostgreSQL connection string, e.g. `postgresql://breaker:pass@postgres:5432/circuitbreaker`. Overrides `DATABASE_URL` when set. |
| `CB_DB_PASSWORD` | `breaker` | Password for the `breaker` PostgreSQL user. Used when the `pg` compose profile spins up the bundled PostgreSQL service. |

### Cloudflare Tunnel (Compose `--profile tunnel`)

| Variable | Default | Description |
|---|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | _(required)_ | Cloudflare Zero Trust tunnel token. Set in `.env` before starting the `tunnel` profile. |

---

## Vault Key

The vault key is a [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption key used to encrypt credentials stored in the database (SMTP passwords, Proxmox API tokens, SNMP community strings).

### Auto-generated (default)

If `CB_VAULT_KEY` is not set, Circuit Breaker generates a key during the first-run wizard and writes it to `/data/.env` (or `/app/data/.env` in Compose installs) inside the data volume. The key is loaded from this file on subsequent starts.

**This key is shown once during the [first-run wizard](first-run.md).** Back it up before closing the wizard.

### Pre-seeding a key

Generate a key before first launch and set it in your environment:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In `docker-compose.yml`:
```yaml
environment:
  - CB_VAULT_KEY=<your-key-here>
```

In a `.env` file:
```
CB_VAULT_KEY=<your-key-here>
```

Pre-seeding is recommended for production deployments — it ensures the key survives a volume recreation and avoids the vault key ceremony during OOBE.

### Recovery

If the vault key is lost or uninitialized (e.g. after an accidental volume deletion or a headless deploy), use the `cb` CLI:

```bash
cb vault-recover
```

This generates a fresh key and re-initializes the vault. All previously encrypted credentials will need to be re-entered in **Settings**.

---

## Volumes and Persistence

| Volume / Path | Stores | Notes |
|---|---|---|
| `circuit-breaker-data:/data` | SQLite DB, vault key file, runtime uploads | Single-container installs. Must be preserved across updates. |
| `backend-data:/app/data` | SQLite DB, vault key file, runtime data | Compose installs (source). Same contents as above. |
| `../data/uploads/icons:/app/data/uploads/icons` | Custom icons | Compose only. Bind mount — host path relative to `docker/`. |
| `../data/uploads/branding:/app/data/uploads/branding` | Branding assets (logos, login backgrounds) | Compose only. Bind mount. |
| `caddy_data:/data` | Caddy local CA, ACME certificate state | Compose only. Prevents cert regeneration on restart. |
| `caddy_config:/config` | Caddy autosave / config state | Compose only. Low risk, keep alongside `caddy_data`. |
| `nats_data:/data/nats` | NATS JetStream state | Compose only. Keeps worker messaging state durable. |
| `postgres_data:/var/lib/postgresql/data` | PostgreSQL data files | Compose `--profile pg` only. |

**Backup priority:** At minimum, back up the volume containing `app.db` and `.env` (the vault key file). If you restore `app.db` without the matching vault key, all encrypted credentials become unreadable. See [Backup & Restore](../backup-restore.md).

### Data directory vs database (full reset)

When **CB_DB_URL** points to an external host (e.g. `postgresql://...@postgres:5432/circuitbreaker`), **users and sessions live only in that database**. The **CB_DATA_DIR** bind mount (and any target that wipes it, e.g. `make compose-clean`) does **not** touch that database. Changing or wiping CB_DATA_DIR will not log you out or remove your account; the app will still use the same Postgres and the same identity.

**Full reset with external Postgres** requires one of:

- **Drop and recreate the database** that CB_DB_URL points to. From the repo root you can run `make compose-down` then `make compose-reset-db` (requires `psql` and CB_DB_URL in `.env`). Or manually: connect to the `postgres` database and run `DROP DATABASE circuitbreaker;` then `CREATE DATABASE circuitbreaker;`, then restart the app so migrations run.
- **Use embedded Postgres** so the DB lives under CB_DATA_DIR: leave CB_DB_URL unset or set it to `postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker`. Then wiping CB_DATA_DIR (e.g. `make compose-clean`) also removes the database and gives you a fresh identity.

---

## TLS / HTTPS

### Local self-signed CA (default)

Caddy generates a local certificate authority and issues certificates for your `CB_DOMAIN`. This is the default for `.local` and LAN hostnames.

The CA root certificate is served at:
```
http://circuitbreaker.local/caddy-root-ca.crt
https://circuitbreaker.local/caddy-root-ca.crt
```

You must install it in your OS/browser trust store to avoid certificate warnings.

### Public domain with ACME / Let's Encrypt

Set a public FQDN and your email:

```yaml
environment:
  - CB_DOMAIN=cb.example.com
  - CB_TLS_EMAIL=admin@example.com
  - CB_LOCAL_CERTS=
```

Caddy will automatically obtain and renew a trusted certificate via Let's Encrypt. No manual CA installation needed.

---

## Trusting the Self-Signed CA Certificate

### macOS

1. Download the certificate:
   ```bash
   curl -k -o caddy-root-ca.crt http://circuitbreaker.local/caddy-root-ca.crt
   ```
2. Open **Keychain Access** → drag the `.crt` file in → set trust to **Always Trust**.

   Or via the command line:
   ```bash
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-root-ca.crt
   ```
3. Restart your browser.

### Linux

```bash
curl -k -o /usr/local/share/ca-certificates/circuit-breaker.crt \
  http://circuitbreaker.local/caddy-root-ca.crt
sudo update-ca-certificates
```

For Firefox on Linux (which uses its own NSS trust store):
```bash
certutil -A -n "Circuit Breaker Caddy CA" -t "CT,," \
  -i caddy-root-ca.crt \
  -d sql:$HOME/.mozilla/firefox/*.default-release
```

### Windows

1. Download the certificate from `http://circuitbreaker.local/caddy-root-ca.crt`.
2. Double-click the file → **Install Certificate** → **Local Machine** → **Place all certificates in the following store** → **Trusted Root Certification Authorities**.
3. Restart your browser.

### Chrome / Edge (all platforms)

Chrome and Edge use the OS trust store. Trusting the cert in your OS trust store (above) is sufficient — restart the browser afterward.

### Firefox (all platforms)

Firefox manages its own trust store. Go to **Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import** and import the `.crt` file. Enable **Trust this CA to identify websites**.

Alternatively, use `make trust-ca` (Compose from source installs) to extract and install the CA automatically.

---

## Related

- [Deployment & Security](../deployment-security.md) — hardening, vault best practices
- [Remote Access & Tunnels](../remote-access.md) — Cloudflare Tunnel setup
- [Backup & Restore](../backup-restore.md)
