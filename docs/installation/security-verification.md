# Security Verification Checklist

Run after installation or upgrades to confirm artifact provenance, non-root operation, and security hardening.

## What changed for operators

Native installs ship a hermetic runtime under `/opt/circuitbreaker/` (own
Python, application, wheels). `circuit-breaker` is a launcher;
`/usr/local/bin/circuit-breaker` on package hosts is a symlink into that tree.
Provenance for the tree lives in `share/build-info.json` alongside the usual
checksums and signatures.

## What to do

Verify checksums and signatures as before, then optionally cross-check the
`build-info.json` fields below. Upgrades need no extra verification steps —
`install.sh --upgrade` / `cb update` still verify the bundle they fetch.

## Rollback

If an upgrade fails health checks, `python.prev` is kept until `/readyz`
succeeds; restore with `restore.sh` / `circuit-breaker-rollback` as in
[Upgrading — Rollback](upgrading.md#rollback).

## Release channels

`--channel candidate` and the `:candidate` / `:nightly` image tags are opt-in;
stable remains the default. Draft candidates are not fetched by unauthenticated
`install.sh`.

## Artifact Verification

Every release ships checksums, GPG signatures, SBOMs, and a cosign signature on the container image.

`install.sh` verifies the SHA256 of the release bundle it downloads automatically, unless you pass `--skip-checksum`.

### Release artifacts

Download `SHA256SUMS` and `SHA256SUMS.asc` from the [GitHub release](https://github.com/BlkLeg/CircuitBreaker/releases) alongside whatever packages you fetched, then:

```bash
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
```

Each individual artifact also has its own detached `.asc` signature.

### `build-info.json` (hermetic runtime)

After install, `/opt/circuitbreaker/share/build-info.json` (also linked from
`/usr/local/share/circuit-breaker/build-info.json` on package hosts) records
what the tree was built from. Operators can check:

| Field | What to compare |
|---|---|
| `runtime` | Must be `"pbs"` for a hermetic install (legacy PyInstaller installs omit it or differ). |
| `pbs_release` | The python-build-standalone release tag the build pinned. |
| `pbs_sha256` | Must match the distributor's `.sha256` sidecar for that PBS asset (the pin file records the same digests). |
| `runtime_digest` | Must match the published mono image's `build-info.json` for the same version/arch — CI asserts this with `scripts/ci/assert_runtime_parity.py`. |

```bash
python3 -m json.tool /opt/circuitbreaker/share/build-info.json
```

Inside a running mono container:

```bash
docker compose exec circuitbreaker cat /opt/circuitbreaker/share/build-info.json
```

### Container image

The GHCR image is signed keylessly with cosign (OIDC identity, no public key to distribute):

```bash
cosign verify ghcr.io/blkleg/circuitbreaker:<version> \
  --certificate-identity-regexp 'https://github.com/BlkLeg/CircuitBreaker/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

### SBOMs

Each release publishes CycloneDX and SPDX SBOMs for the backend and the frontend, plus a CycloneDX SBOM for the container image. The container SBOM is also attached to the image with `cosign attach sbom`, so `cosign download sbom` retrieves it.

## Quick Verification (30 seconds)

The container's entrypoint deliberately starts as **root** so it can fix volume ownership and wire up the embedded services; supervisord then launches every application process as `breaker` (uid 1000). `docker compose exec circuitbreaker whoami` returning `root` is expected — the invariant to check is the process list:

```bash
docker compose exec circuitbreaker ps aux
```

Expected: `postgres`, `pgbouncer`, `redis-server`, `nats-server`, the backend API and `nginx` all run as `breaker`; only `supervisord` and the worker launcher run as root. If `ps` is unavailable in your image, the same privilege drop can be read from the supervisor config:

```bash
docker compose exec circuitbreaker grep -E '^\[program|^user=' /etc/supervisor/conf.d/supervisord.conf
```

```bash
docker inspect circuitbreaker --format '{{json .HostConfig.SecurityOpt}}'
docker compose exec circuitbreaker id breaker
```

Expected: `["no-new-privileges:true"]` and `uid=1000(breaker) gid=1000(breaker)`.

## Full Security Audit (2 minutes)

From a repository checkout:

```bash
make security-check    # gate mode — exits non-zero on HIGH/CRIT findings
make security-report   # full report, never fails
```

Both run `scripts/security_scan.sh` and write `security_scan_report.md`.

## Manual Volume Remediation

The entrypoint chowns `/data` to `breaker:breaker` and sets `/data/pgdata` to `0700` on every start. Remediate by hand only if the logs show `chown /data not permitted`:

```bash
docker compose down
sudo chown -R 1000:1000 ./circuitbreaker-data
sudo chmod -R 750 ./circuitbreaker-data
sudo chmod 700 ./circuitbreaker-data/pgdata
docker compose up -d
```

Substitute your own `CB_DATA_DIR` if you set one.

**Note:** PostgreSQL requires strict `0700` permissions on `pgdata` (owner-only access). The commands above set general permissions to `750` but correct pgdata to `700`.

## Troubleshooting

### Permission denied on /data during startup

**Symptoms:**
- Container fails to start with "permission denied" errors
- Logs show `chown /data not permitted` or "Cannot write to /data"
- Health check fails immediately

**Diagnosis:**
```bash
ls -lan ./circuitbreaker-data
```

If files are owned by uid 0 (root), run manual remediation above.

### PostgreSQL data directory permission error

**Symptoms:**
```
FATAL: data directory "/data/pgdata" has invalid permissions
DETAIL: Permissions should be u=rwx (0700) or u=rwx,g=rx (0750).
```

**Cause:** PostgreSQL requires **exactly** `0700` permissions on its data directory. If the volume was remediated with bulk `chmod -R 750`, pgdata ends up with group-readable permissions (750), which PostgreSQL rejects.

**Fix:**
```bash
docker compose down
sudo chmod 700 ./circuitbreaker-data/pgdata
docker compose up -d
```

### Volume ownership breaks after downgrade

If you downgrade from a non-root version to an older root version and then upgrade again, the volume may have mixed ownership.

**Fix:**
```bash
docker compose down
sudo chown -R 1000:1000 ./circuitbreaker-data
sudo chmod -R 750 ./circuitbreaker-data
sudo chmod 700 ./circuitbreaker-data/pgdata
docker compose up -d
```

## Security Best Practices

### After Fresh Install

1. Verify the artifacts you downloaded, as described above.

2. Verify health endpoint:
   ```bash
   curl -sf http://localhost/api/v1/health | jq .
   ```

3. Test file upload functionality to confirm writable paths work correctly.

### After Upgrades

1. Let the container entrypoint fix data-directory ownership (it does this on every start)

2. Re-run the process check after upgrade:
   ```bash
   docker compose exec circuitbreaker ps aux
   ```

3. Check logs for permission errors:
   ```bash
   docker compose logs circuitbreaker | grep -i "permission denied"
   ```

### Regular Audits

Run the scanners monthly or after any Docker/system updates, from a repository checkout:

```bash
make security-check
```

## Advanced Verification

### Inspect Container Security Context

```bash
docker inspect circuitbreaker --format '{{json .HostConfig.SecurityOpt}}' | jq .
docker inspect circuitbreaker --format '{{json .HostConfig.CapDrop}}' | jq .
docker inspect circuitbreaker --format '{{json .HostConfig.CapAdd}}' | jq .
```

Expected:
- SecurityOpt: `["no-new-privileges:true"]`
- CapDrop: `["ALL"]`
- CapAdd: `["NET_RAW", "NET_BIND_SERVICE", "CHOWN", "FOWNER", "SETUID", "SETGID", "DAC_OVERRIDE"]`

### Check Filesystem Mount Options

```bash
docker compose exec circuitbreaker mount | grep " / "
```

Should show `ro` (read-only) for the root filesystem.

### Verify Process Tree

```bash
docker compose exec circuitbreaker ps aux
```

All application processes should run as `breaker` (uid 1000). `supervisord` itself stays root so it can launch the discovery workers through `setpriv` with ambient `CAP_NET_RAW`; those workers drop to `breaker` themselves.

## Related Documentation

- [Configuration Guide](configuration.md) - Environment variables and settings
- [Upgrading](upgrading.md) - Upgrade procedures
- [Docker Compose Installation](docker-compose.md) - Full deployment guide
