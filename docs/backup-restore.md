# Backup & Restore

Use backup and restore to protect your inventory data and recover quickly when needed.

There are two separate things called "backup" in Circuit Breaker, and they cover different ground:

| | JSON export | Full-state snapshot |
|---|---|---|
| Contains | Entities, tags, docs, relationships | Database dump, vault key, uploads, native config |
| Created by | Settings UI or `GET /api/v1/admin/export` | `cb backup`, the daily 02:00 scheduler job, or `POST /api/v1/admin/db/snapshot` |
| Restores with | `POST /api/v1/admin/import` | `cb restore <archive>` |
| Good for | Moving inventory data between instances | Disaster recovery of a whole install |

The full-state snapshot is **one artifact with one builder**. `cb backup`, the scheduled job, and
the admin API all call `services/backup/snapshot.py`, so all three produce the same tarball and
`cb restore` accepts any of them.

!!! danger "The snapshot tarball is the security boundary"
    It contains **the vault key in plaintext**, and on native installs the entire environment file.
    Anyone holding the tarball can decrypt every stored credential. It is written mode `0600`;
    treat the file, and any machine it is copied to, as a secret.

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

## The Full-State Snapshot

Each snapshot is a gzip-compressed tarball named `cb-snapshot-<YYYYmmdd-HHMMSS>.tar.gz`, created
with mode `0600`. One table, for what it holds and what a restore does with it:

| Entry | Contents | What `cb restore` does with it |
|---|---|---|
| `db.sql.gz` | `pg_dump` of the whole database, gzip-compressed | Drops the existing schema and replays the dump — **all current data is replaced** |
| `vault.key` | **The vault key in plaintext** | Written back as `CB_VAULT_KEY`; without it the dump's encrypted columns are unreadable |
| `uploads/` | A recursive copy of the uploads directory | Replaces the contents of `$CB_DATA_DIR/uploads` |
| `config/nginx/circuitbreaker.conf` | `/etc/nginx/conf.d/circuitbreaker.conf`, the reverse-proxy site config the installer writes | Copied back, validated with `nginx -t`, and reloaded only if it validates (native installs) |
| `config/.env` | `/etc/circuitbreaker/.env` — the full environment file, not just the vault key | Copied back (native installs) |
| `manifest.json` | Format version, install mode, `cb` version, timestamp, database name, uploads count, the `db.sql.gz` SHA-256, and the config files captured | Read and checked before anything is touched; printed for confirmation |

The `config/` entries exist only on native installs — on Docker and Compose those host paths are
not present and are skipped, which the manifest records by listing no config files.

TLS key material is **not** in the snapshot, deliberately. The installer keeps it under
`${CB_DATA_DIR}/tls`, and certificate activation writes those same files from the database, so the
certificates already travel inside the database dump. Copying the private key a second time would
widen the blast radius of an archive that is already a secret, for no recovery benefit.

### Snapshots taken before this release are not restorable

An archive produced by the old `cb backup` — `database.sql` plus `manifest.txt` — is a different,
older format. It is **not** restorable, and it never was: it carried no vault key and no uploads, so
even a successful database load would have left every encrypted credential unreadable, and the
restore script structurally rejected the shape. `cb restore` recognises one and says so by name
rather than reporting a missing file. Take a fresh `cb backup`; there is no upgrade path for the
old archive.

---

## Online Backup, Offline Restore

**Snapshot creation is online. Restore is offline.** That asymmetry is deliberate, not a missing
feature:

- Creating a snapshot only reads. It runs safely against a live install, which is why
  `POST /api/v1/admin/db/snapshot` exists and why the scheduler can take one at 02:00 without a
  maintenance window.
- Restoring **replaces the database the application is running on**. An API request cannot do that:
  the request handler, its connection pool, and its session state all live inside the thing being
  replaced. There is therefore no `POST /admin/db/restore`, and adding one is not a planned gap —
  `GET /api/v1/admin/db/snapshots` names `cb restore <archive>` in its response for that reason.

Restore is a host operation. Run it on the machine, from the CLI, with the application stopped by
the tool itself.

---

## Back Up From the Command Line

```bash
cb backup
```

In `docker`, `compose`, and `binary` modes this produces the full-state snapshot described above —
the same artifact the scheduler and the admin API produce — into
`${CB_BACKUP_DIR:-~/.circuit-breaker/backups}`. It prints the path and the `cb restore` command for
it. See [cb CLI Tool](cb-cli.md#cb-backup).

!!! note "Native installs"
    The `cb` shipped by the native installer (`deploy/cli/cb`) still writes a database-only
    `pg_dump` to `${CB_DATA_DIR}/backups/cb-backup-<stamp>.sql`. On a native install the full-state
    snapshot comes from the 02:00 scheduled job or `POST /api/v1/admin/db/snapshot`, and is
    restored with `deploy/scripts/restore.sh` — see below.

---

## Scheduled Snapshots and Off-site Copies

Circuit Breaker takes a **full-state snapshot every day at 02:00** (scheduler job
`daily_db_snapshot`), written to `$CB_DATA_DIR/backups/`.

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
| `GET /api/v1/admin/db/snapshots` | List local snapshot tarballs, with the `cb restore` command to use |
| `GET /api/v1/admin/settings/backup` | Read backup settings (secret key masked) |
| `PUT /api/v1/admin/settings/backup` | Update backup settings |
| `POST /api/v1/admin/settings/backup/test` | Test the configured S3 target |

All of these require the **admin** role. There is no restore endpoint — see
[Online Backup, Offline Restore](#online-backup-offline-restore).

---

## Full Restore (Disaster Recovery)

```bash
cb restore /path/to/cb-snapshot-20260814-020000.tar.gz
```

**This is destructive.** It replaces the database, the uploads, and the vault key of the install it
is run on.

| Flag | Effect |
|---|---|
| `--yes` | Skip the interactive `RESTORE` confirmation |
| `--force` | Proceed even though the snapshot is from a newer Circuit Breaker version |
| `--no-safety-snapshot` | Do not take a snapshot of the current state first |

### The order, and why it is the order

1. **Verify.** The archive is checked by the backend's own verifier — required members present,
   `vault.key` non-empty, `manifest.json` parseable, the `db.sql.gz` SHA-256 matching the manifest,
   and the snapshot not newer than the installed build. **Nothing is stopped until this passes**, so
   a bad archive costs you a failed command, not an outage.
2. **Confirm.** The manifest is printed and you type `RESTORE`. Declining changes nothing. The
   confirmation is against the archive's own identity, not its filename.
3. **Safety snapshot.** A fresh `cb backup` of the current state is taken before anything is
   destroyed, unless you passed `--no-safety-snapshot`. If it fails, the restore refuses to proceed.
4. **Stop, restore, start.** The application processes are stopped, the database schema is dropped
   and the dump replayed, uploads and the vault key are put back, and the service is restarted — a
   restart rather than a resume, because the vault key changed in the environment the process reads
   at startup.
5. **Verify the result.** `cb` polls `/api/v1/livez` until the application answers. If `curl` is not
   installed the check is skipped with a notice rather than reported as a failure.

Do not rearrange those steps. Verification before stopping and a safety snapshot before destroying
are the two properties that make the command safe to run under pressure.

### Per-mode mechanics

| Mode | How the restore is carried out |
|---|---|
| `docker`, `compose` | The archive is copied into the backend container, verified there, and replayed with `psql` inside it. Postgres stays up — it is what is being restored into; only `backend` and `workers` are stopped. The container is restarted at the end |
| `binary` | `cb restore` drives `deploy/scripts/restore.sh`, which is the native/binary implementation. `cb` verifies, confirms, and takes the safety snapshot first, then hands the archive over |

`deploy/scripts/restore.sh` remains directly callable:

```bash
sudo deploy/scripts/restore.sh /path/to/cb-snapshot-20260814-020000.tar.gz
```

Use it directly when `cb` or its `install.conf` is part of what was lost. It requires `tar`, `gzip`,
`psql`, `rsync`, `jq`, `sed`, and `sha256sum` on the host. It stops `circuitbreaker.target`, drops
and recreates the `circuitbreaker` database and loads the dump, syncs `uploads/` with
`rsync --delete`, writes `CB_VAULT_KEY` back into `/etc/circuitbreaker/.env`, and restores the nginx
site config — validating it with `nginx -t` before reloading, so a config that fails validation
cannot take the site down at the end of a recovery.

If `cb` cannot find the script it says where to get it; `CB_RESTORE_SCRIPT` in `install.conf`
overrides the search.

!!! warning "Handle the snapshot as a secret"
    The snapshot contains the vault key in plaintext. After a restore, treat both the machine and
    the snapshot file as sensitive.

If you restore a database without the matching vault key, encrypted secrets such as Proxmox API
tokens and SMTP passwords will no longer be readable and must be re-entered in **Settings**.

---

## Recovery Time

This document previously stated a four-hour RTO as though it established one. It does not: the
target lives in the [1.0 service objectives](release/1.0.0-service-objectives.md) — 24-hour RPO for
scheduled backups, four-hour RTO for a documented restore to a clean supported host at the approved
medium dataset — and both remain **candidate targets pending ACC-14 and ACC-15 evidence**. That
target covers the whole recovery: provisioning a host, installing, restoring, and verifying.

What the restore *procedure* costs, measured against the round-trip test
(`apps/backend/tests/services/test_snapshot_roundtrip.py`) on the CI dataset:

| Step | Measured |
|---|---|
| Build the snapshot (`pg_dump`, compress, pack) | 0.5 s |
| Verify the archive (checksum, manifest, version) | under 0.01 s |
| Replay the dump into a database and read a row back | 2.2 s |
| Whole round-trip, snapshot to restored row | 2.7 s |
| Refusing an old `cb backup` archive | 0.2 s, nothing touched |
| Refusing a file that is not there | immediate, nothing touched |

Those are developer-workstation figures on a deliberately small dataset — a 24 KB archive from a
219 KB dump — so read the table as the shape of the cost, not the number for your install:
everything except the database load is effectively constant, and the database load scales with dump
size. The operator-facing consequences are what matter and
do not scale: **a restore is one command**, a bad archive is refused before anything stops, and a
declined confirmation changes nothing.

Time your own restore at your own data volume before quoting a recovery target to anyone. The RTO
figure in the service objectives is not evidence until ACC-14 and ACC-15 supply it.

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
- Test a restore occasionally in a safe environment. A recovery target assumes you have run
  `cb restore` before, not that you are reading this page for the first time during an outage.

---

## Related Guides

- [Settings](settings.md)
- [cb CLI Tool](cb-cli.md)
- [Deployment & Security](deployment-security.md)
