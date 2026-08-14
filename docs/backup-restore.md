# Backup & Restore

Use backup and restore to protect your inventory data and recover quickly when needed.

For v1.0 release candidates, recovery targets are defined in the
[1.0 service objectives](release/1.0.0-service-objectives.md). Candidate targets are 24-hour RPO for
scheduled backups and 4-hour RTO for documented restore to a clean supported host, pending ACC-14 and
ACC-15 evidence.

There are two separate things called "backup" in Circuit Breaker, and they cover different ground:

| | JSON export | Full-state snapshot |
|---|---|---|
| Contains | Entities, tags, docs, relationships | Database dump, vault key, uploads, native config |
| Created by | Settings UI or `GET /api/v1/admin/export` | The daily 02:00 scheduler job, or `POST /api/v1/admin/db/snapshot` |
| Restores with | `POST /api/v1/admin/import` | `deploy/scripts/restore.sh` |
| Good for | Moving inventory data between instances | Disaster recovery of a whole install |

---

## What the JSON Export Includes

The export is a versioned JSON document (currently `version: 2`) covering hardware, compute units,
services, storage, networks, misc items, docs, tags, and the relationships between them.

It **does not** export users, application settings, audit logs, or graph layouts — these are treated
as per-instance operational data, not portable entity data. Do not treat the JSON export as a
full-instance backup; use the full-state snapshot for that.

---

## Export a Backup

1. Open **Settings**.
2. Go to the **System** tab.
3. In the **Data Management** section, find **Full Backup**.
4. Click **Download Backup** and save the file somewhere safe.

The equivalent API call is `GET /api/v1/admin/export`, which requires the **admin** role.

Tip: keep date-stamped backups so you can roll back to a known point in time.

---

## Import a Backup

Import is **API-only in this release** — there is no import control in the UI.

`POST /api/v1/admin/import` accepts the exported document and requires the **admin** role:

```json
{
  "wipe_before_import": false,
  "data": { "version": 2, "...": "..." }
}
```

The whole restore runs in a single transaction; if any part fails, nothing is written.

### Wipe and restore

Setting `wipe_before_import: true` deletes all current entity data first, so it is gated behind
confirmation headers. All three are required, or the request is rejected and the denial is written
to the audit log:

| Header | Value |
|---|---|
| `x-cb-confirmation` | `RESTORE_WITH_WIPE` |
| `idempotency-key` | A stable key of at least 12 characters |
| `x-cb-backup-verified` | `true` |

Only set `wipe_before_import` when you intentionally want to remove current data before restoring.

---

## Scheduled Snapshots and Off-site Copies

Circuit Breaker takes a **full-state snapshot every day at 02:00** (scheduler job
`daily_db_snapshot`). Each snapshot is a gzip-compressed tarball named
`cb-snapshot-<timestamp>.tar.gz`, written to `$CB_DATA_DIR/backups/` and created with mode `0600`.

The tarball contains:

| Entry | Contents |
|---|---|
| `db.sql.gz` | `pg_dump` output, gzip-compressed |
| `vault.key` | **The vault key in plaintext** |
| `uploads/` | A recursive copy of the uploads directory |
| `config/` | Native-install config files — the Caddyfile, TLS certs, and the full `/etc/circuitbreaker/.env`. Absent on Docker installs, skipped gracefully |
| `manifest.json` | Metadata, the SHA-256 checksum of the database dump, and the list of captured config files |

!!! warning "The snapshot tarball is the security boundary"
    It holds the vault key in plaintext, and on native installs the entire environment file. Anyone
    with the tarball can decrypt every stored credential. Store it accordingly.

### Configuring retention and off-site replication

Open **Settings → System → Backup & Recovery**. Under **S3 Off-site Replication** you can configure
any S3-compatible target — AWS S3, MinIO, or Cloudflare R2:

| Field | Notes |
|---|---|
| Bucket | Leave blank to disable S3 upload entirely |
| Endpoint URL | Custom endpoint for MinIO, R2, and similar. Leave blank for AWS S3 |
| Access Key ID | |
| Secret Access Key | Stored encrypted in the vault |
| Region | Defaults to `us-east-1` |
| Key Prefix | Object path prefix, defaults to `circuitbreaker/backups/` |
| Local Retention | Number of snapshots kept on disk (default 7) |
| S3 Retention | Number of snapshots kept in the bucket (default 30) |

Older snapshots beyond each retention count are pruned automatically after every run. Use the test
button in that panel to verify credentials before relying on the schedule.

### Admin API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/admin/db/backup` | Run an immediate `pg_dump` backup |
| `POST /api/v1/admin/db/snapshot` | Run an immediate full-state snapshot |
| `GET /api/v1/admin/db/snapshots` | List local snapshot tarballs |
| `GET /api/v1/admin/settings/backup` | Read backup settings (secret key masked) |
| `PUT /api/v1/admin/settings/backup` | Update backup settings |
| `POST /api/v1/admin/settings/backup/test` | Test the configured S3 target |

All of these require the **admin** role.

---

## Database Backup from the Command Line

On native installs, the `cb` CLI takes an immediate database dump:

```bash
cb backup
```

It runs `pg_dump` through pgbouncer on `127.0.0.1:6432` as the `breaker` user and writes
`${CB_DATA_DIR}/backups/cb-backup-<YYYYmmdd-HHMMSS>.sql`. This is the database only — no uploads,
no vault key. See [cb CLI Tool](cb-cli.md#cb-backup).

---

## Full Restore (Disaster Recovery)

`deploy/scripts/restore.sh` restores a whole native install from a snapshot tarball.

```bash
sudo deploy/scripts/restore.sh /path/to/cb-snapshot-20260814-020000.tar.gz
```

Requires `tar`, `gzip`, `psql`, `rsync`, `jq`, `sed`, and `sha256sum` on the host.

What it does:

1. Validates the tarball contains `db.sql.gz`, `vault.key`, and `manifest.json`, and that the vault
   key is non-empty.
2. Prints the manifest and verifies the database dump against the SHA-256 checksum recorded in it.
3. Prompts for confirmation — it will stop the service, drop the existing database, and replace all
   data.
4. Stops `circuitbreaker.target`.
5. Drops and recreates the `circuitbreaker` database and loads the dump.
6. Syncs `uploads/` back into `$CB_DATA_DIR/uploads` with `rsync --delete`.
7. Writes `CB_VAULT_KEY` back into `/etc/circuitbreaker/.env`.
8. Restores the config files from the snapshot if it contains a `config/` directory.
9. Starts `circuitbreaker.target`.

!!! warning "Handle the snapshot as a secret"
    The snapshot contains the vault key in plaintext. After a restore, treat both the machine and
    the snapshot file as sensitive.

If you restore a database without the matching vault key, encrypted secrets such as Proxmox API
tokens and SMTP passwords will no longer be readable and must be re-entered in **Settings**.

---

## Clear Lab Data

Clear Lab is a destructive action that removes all entities while keeping your documentation. It
lives in **Settings → System → Data Management → Clear Lab**.

Use this only when you are intentionally resetting your environment.

Best practice:

- Download a fresh backup first.
- Confirm the backup file opens and is valid.

---

## Recovery Checklist

- Keep multiple backups (recent + weekly baseline).
- Configure S3 off-site replication, or copy snapshots off the host some other way — a local-only
  backup does not survive the failure it is meant to protect against.
- Store the vault key somewhere separate from the snapshots.
- Test a restore occasionally in a safe environment. The RTO target above assumes you have run
  `restore.sh` before, not that you are reading it for the first time during an outage.

---

## Related Guides

- [Settings](settings.md)
- [cb CLI Tool](cb-cli.md)
- [Deployment & Security](deployment-security.md)
