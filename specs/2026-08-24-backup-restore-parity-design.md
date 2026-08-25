# Backup/Restore Parity — Design

**Date:** 2026-08-24
**Status:** Approved design, not yet implemented
**Branch context:** `dev` at `de9ff24c`; `VERSION` = `1.0.0-rc.3`
**Register:** Batch C — INC-15.
**Follows:** Batch A (`specs/2026-08-24-reachability-authorization-design.md`) and Batch B
(`specs/2026-08-24-tls-and-honest-surfaces-design.md`).

**Standing policy for 1.0.0:** *when a surface promises more than the build delivers, remove
the scaffolding and state the boundary.* This batch finishes rather than removes, because
what is missing is the other half of a feature the product already sells: `docs/backup-restore.md:7`
states a four-hour RTO, and a backup with no restore has no RTO at all.

## 1. Problem

INC-15 records that "restore is native-install-only and absent from the CLI". That is the
outcome; the mechanism is two separate gaps, and the second is worse than the first.

### 1.1 There are two backup artifacts and they are not interchangeable

| Producer | Contents |
|---|---|
| `POST /admin/db/snapshot` → `services/backup/snapshot.py` | `db.sql.gz`, `vault.key`, `uploads/`, `config/`, `manifest.json` |
| `cb backup` (`cb:435-516`) | `database.sql`, `data.env`, `install.env`, `install.conf`, `manifest.txt` |

`deploy/scripts/restore.sh:70` requires `db.sql.gz`, `vault.key`, and `manifest.json`, and
verifies `db_checksum_sha256` from the JSON manifest. A `cb backup` archive has none of those
names, is not gzip-compressed, carries a plain-text manifest, and omits both the uploads and
the vault key — `cb:516` says so: *"Uploads are not included; see docs/backup-restore.md for
a full-state snapshot."*

So the one-command backup that works in all three modes produces an artifact that **nothing
in the repository can restore.**

### 1.2 The restorable artifact has a restore path for one mode of three

`restore.sh` writes `/etc/circuitbreaker/.env` and drives a host `psql` and `systemd`
directly. `cb` supports `docker`, `compose`, and `binary` (`cb:22-25`). Restore exists for
`binary` only.

Nothing else fills the gap: `POST /admin/db/snapshot` and `GET /admin/db/snapshots` have no
restore counterpart, by omission rather than by decision. §3.3 makes that omission a
decision.

### 1.3 What the documentation claims

`docs/backup-restore.md:7` states a four-hour RTO target. Backup is one command in every
mode; restore is a manual, mode-specific procedure available in one of three, against an
artifact that command does not produce.

## 2. Decisions

1. **One backup artifact.** The full-state snapshot format becomes the only one, produced by
   `cb backup` in all three modes. §3.1.
2. **One restore command.** `cb restore <archive>` consumes it in all three modes.
   `restore.sh` becomes the binary-mode implementation detail behind it. §3.2.
3. **Restore is offline and CLI-only.** No API endpoint, and the reason is stated in the
   docs rather than left as a gap. §3.3.
4. **Restore is destructive and behaves like it.** §4.

## 3. Architecture

### 3.1 One artifact

`services/backup/snapshot.py` already produces the right thing and is already tested
(`tests/services/test_snapshot.py`). It stays the single builder. `cb backup` stops
assembling its own archive and invokes it:

| Mode | How |
|---|---|
| `docker`, `compose` | `docker exec <container> python -m app.services.backup.snapshot`, then copy the tarball out to `$CB_BACKUP_DIR` |
| `binary` | run the same module in the install's virtualenv |

That needs a CLI entry point. The orchestrator is
`services/db_backup.py:run_full_snapshot(db)` — it resolves the database URL, vault key and
uploads directory from a session, calls `backup/snapshot.py:build_snapshot`, prunes old local
snapshots, and uploads to S3 when configured. `api/admin_db.py:165` and
`core/scheduler.py:52` (a daily 02:00 job) already call it; the CLI becomes the third caller
rather than a second implementation.

`app/cli.py` already exists and already serves `cb` — `cb:534` runs
`docker exec … python -m app.cli config validate`. A `snapshot` group joins `config` there:

- `python -m app.cli snapshot create [--out DIR]` — prints the resulting path.
- `python -m app.cli snapshot verify <archive>` — §3.2 step 1, exit non-zero on any problem.

Putting verification in Python rather than in `cb`'s bash makes it testable without a
database and lets both the docker and binary branches share one implementation. Note that
`cli.py`'s `_refuse_dns` context manager is scoped to the config-validate pass
(`cli.py:450`), not to the module, so a snapshot subcommand can reach Postgres.

**What `cb backup` gains by this:** uploads and the vault key, neither of which it captured.
A restore from the old artifact could not have recovered credentials at all, because the
vault key was not in it — every encrypted column would have been unreadable. That is the
sharpest reason not to keep two formats.

**What it loses:** `install.env` and `install.conf`, the CLI's mode-specific host config.
Those are folded into the snapshot's existing `config/` section, which already captures
native-install config files and skips gracefully where they are absent.

**The manifest gains two fields**, because restore has to make decisions from it:

```json
{
  "format_version": 1,
  "install_mode": "docker",
  "cb_version": "1.0.0",
  ...
}
```

`format_version` lets a future change be detected rather than misread — a restore that
silently half-understands an archive is the failure this whole batch exists to prevent.
`install_mode` is advisory: restoring a `binary` snapshot into a `docker` install is
legitimate and is exactly what a migration looks like, so it warns and continues rather than
refusing.

**Compatibility.** `cb restore` must still accept an archive produced by the current
snapshot service, which has no `format_version`. A missing field reads as version 0 and is
accepted; the fields restore actually needs (`db_checksum_sha256`, `db_name`) are already
there. Old `cb backup` archives are **not** restorable and never were — `cb restore` detects
the shape (`database.sql` at the root, `manifest.txt`) and says so specifically, rather than
failing on a missing `db.sql.gz`.

### 3.2 One restore command, three modes

`cb restore <archive>` runs the same sequence everywhere, with three mode-specific steps:

1. **Verify before touching anything.** Archive readable, required members present, manifest
   parses, `db_checksum_sha256` matches the actual `db.sql.gz`, `vault.key` non-empty. All of
   this happens before a single service is stopped — `restore.sh` already gets this right
   (lines 70-105) and the ordering is preserved.
2. **Confirm.** §4.
3. **Take a safety snapshot** of the current state, unless `--no-safety-snapshot`. A restore
   that goes wrong must not be the end of the story.
4. **Stop the application**, leaving the database reachable.
   - `docker`: `docker stop` the app container; Postgres is in the same mono container, so
     instead stop the supervised app programs via `supervisorctl stop backend workers`.
   - `compose`: `docker compose stop` the app services, leave the `db` service up.
   - `binary`: `systemctl stop circuitbreaker`.
5. **Restore the database** — `psql` against the same connection the mode uses, dropping and
   recreating the target schema.
6. **Restore uploads** — `rsync -a --delete` into the data directory, as `restore.sh:157`
   does.
7. **Restore the vault key** into the mode's env file, and **the config files** the snapshot
   captured.
8. **Start**, then **verify**: wait for `/api/v1/livez`, then confirm the vault decrypts a
   known-encrypted row. A restore that starts the app but cannot read its own secrets has not
   succeeded, and the vault key is the single most likely thing to be wrong.

`deploy/scripts/restore.sh` is not deleted. It becomes the `binary` branch's implementation,
invoked by `cb restore`, keeping its existing verification. Retiring it outright would
discard working, reviewed code and break anyone whose runbook calls it directly.

### 3.3 Restore is offline and CLI-only — stated, not omitted

There is no `POST /admin/db/restore` and there will not be one. Restoring the database from
inside the application connected to that database means replacing the store mid-request: the
process holds open connections to the database it is dropping, the vault key changes under a
running worker, and the request that ordered the restore cannot survive its own completion.

The absence is currently indistinguishable from an oversight — `GET /admin/db/snapshots`
lists archives the product cannot restore, and offers no explanation. The snapshot list gains
a line naming `cb restore` as the way to use what it is listing, and `docs/backup-restore.md`
states the boundary: **snapshot creation is online, restore is offline.**

This is the standing policy applied to a gap rather than to scaffolding: the product stops
implying a capability by leaving a symmetrical hole where one would be.

## 4. Restore is destructive and behaves like it

Restore replaces the database, the uploads, and the vault key. The precedent is
`HighRiskConfirmDialog` (INC-13), which the UI uses for rotation and audit-chain repair, and
the CLI equivalent is the same idea:

- Print what will be replaced, with the archive's `created_at`, `cb_version`, `install_mode`,
  and `uploads_count` — the operator confirms against the archive's identity, not against a
  filename they may have mistyped.
- Require typing `RESTORE` when the target is not empty. `--yes` skips it for scripted use.
- Refuse when `cb_version` in the manifest is **newer** than the installed version, unless
  `--force`. A newer schema restored into an older binary is a corrupted install, and the
  migration state is the one thing a restore cannot repair.
- Every outcome is one of: verified success, refusal before any change, or failure after a
  safety snapshot whose path is printed. "Partially restored, no idea what state" is not an
  outcome this command may produce.

## 5. Testing

Restore is the hardest thing here to test honestly, because the real thing needs a real
Postgres and a real service manager.

- **Archive verification** is pure and gets the most coverage: checksum mismatch, missing
  member, empty `vault.key`, unparseable manifest, an old `cb backup` archive, a `cb_version`
  newer than installed. Each refuses with its own message and touches nothing. These are the
  paths an operator hits at 3am and they are all testable without a database.
- **`cb backup` shape parity**: the archive `cb backup` produces satisfies the same assertions
  `tests/services/test_snapshot.py` already makes, so the two cannot drift apart again. The
  two formats disagreeing *is* this finding, and this is the pin against its return.
- **Round-trip**, in CI against the existing Postgres test service: snapshot a seeded
  database, restore into a scratch database, assert row counts and that a vault-encrypted
  column decrypts. This is the one test that proves the artifact is actually restorable.
- **Mode branches** are exercised with the service-control commands stubbed, asserting the
  ordering: nothing is stopped before verification passes, and the safety snapshot is taken
  before the first destructive step.
- **Shell**: `deploy/helper/test_cb_helperd.py` establishes that this repository tests its
  shell tooling with Python; `cb restore`'s branches follow it.

## 6. Documentation

`docs/backup-restore.md` is rewritten around one artifact and one command:

- The four-hour RTO claim is either substantiated by the round-trip procedure and its measured
  time, or replaced with what the procedure actually achieves. It must not survive unexamined
  — an unmet stated target is what made INC-15 a finding rather than a gap.
- One table: what the snapshot contains, what restore replaces, what it does not.
- The boundary from §3.3, stated positively.
- The plaintext-vault-key warning `restore.sh:11` already carries, promoted to the document.

## 7. Files touched

**CLI:** `cb` (`cmd_backup` rewritten, `cmd_restore` added, usage and the command table),
`deploy/scripts/restore.sh` (becomes the binary-mode branch).

**Backend:** `app/cli.py` (a `snapshot` group with `create` and `verify`),
`services/backup/snapshot.py` (`format_version` and `install_mode` in the manifest),
`services/backup/verify.py` (new — the archive checks, shared by CLI and tests),
`api/admin_db.py` (the snapshot list names `cb restore`).

**Tests:** `tests/services/test_snapshot.py` (manifest fields), a new archive-verification
suite, a round-trip test, and `cb restore` branch tests.

**Docs:** `docs/backup-restore.md`, `docs/1.0.0-incomplete-features.md` (INC-15 closed).

## 8. Out of scope

- **Point-in-time recovery / WAL archiving.** The RTO target is four hours and the product
  ships a snapshot model; continuous archiving is a different product decision.
- **Remote or scheduled backup destinations.** `cb backup` writes locally; where the archive
  goes afterwards is the operator's.
- **Restoring across major Postgres versions.** `pg_dump` output is version-sensitive; the
  manifest records `cb_version` and restore refuses forward, which is the guard this design
  makes. Cross-version restore is not solved here.
- **A restore API or UI.** §3.3.
- **The Caddy/nginx inconsistency.** `snapshot.py:9-10` captures `/etc/caddy/Caddyfile` while
  `deploy/helper/cb_helperd.py:28-29` manages nginx configuration and reloads nginx. One of
  them is stale about what the native install runs. It affects which config files a restore
  should replace, so it must be resolved during implementation — but establishing which is
  correct is a question for whoever owns the native install, not something this design
  decides from reading both.
