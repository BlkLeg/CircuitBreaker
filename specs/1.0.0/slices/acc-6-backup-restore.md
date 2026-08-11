# ACC-6 — Live Backup and Clean Restore

**Requirements:** ACC-14, ACC-15
**Depends on:** ACC-2, RC-06

## Primary touchpoints

- `apps/backend/src/app/services/backup/`, `db_backup.py`
- `deploy/scripts/restore.sh`, `docs/backup-restore.md`
- Upload/data directories, vault/encryption, audit chain, agent server keys

## Build sequence

1. Define the backup manifest and trust boundary: database, uploads/object data, configuration,
   encrypted secrets, vault-key handling, agent keys/state, checksums, schema/app version, timestamps,
   consistency point, and excluded regenerable data.
2. Seed representative data and continuous writes. Take a live backup with a defined consistency
   mechanism and record earliest/latest durable transaction to measure RPO.
3. Restore to a clean same-version host and to the supported post-upgrade path. Never rely on stale
   environment secrets outside the documented restore inputs.
4. Automatically compare table/entity counts and sampled hashes, then exercise login/MFA, decrypted
   integration, upload retrieval, audit verification, monitor history, agent reconnect, and new writes.
5. Inject corrupt manifest/archive, checksum mismatch, missing/wrong vault key, permissions, disk full,
   incompatible schema, partial DB/files snapshot, interrupted restore, and malicious archive paths.
6. Test retention/pruning without deleting the last valid recovery point; measure RPO/RTO.

## Verification and safety

Use production commands and release artifacts on a clean host. Restore-with-wipe requires SEC-17
safeguards and a pre-mutation validation phase. Done means functional data recovery meets RC-06;
process health or row count alone cannot pass.
