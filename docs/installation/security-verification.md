# Security Verification Checklist

Run after installation or upgrades to confirm non-root operation and security hardening.

## Quick Verification (30 seconds)

```bash
make check-user
```

Expected output:
- `whoami` → `breaker` (never `root`)
- `id` → `uid=1000(breaker) gid=1000(breaker)`
- `/data` files owned by `1000:1000`
- `touch /test_root_write` → permission denied

## Full Security Audit (2 minutes)

```bash
make check-security
```

Acceptance criteria:
- ✅ Container user: uid=1000 gid=1000 (breaker)
- ✅ NoNewPrivs: 1
- ✅ Root filesystem read-only (touch / fails)
- ✅ /tmp writable (tmpfs)
- ✅ /data writable (volume)

## Manual Volume Remediation

If install.sh didn't auto-fix ownership or you're upgrading manually:

```bash
docker compose down
docker run --rm -v circuitbreaker-data:/data alpine sh -c "chown -R 1000:1000 /data && chmod -R 750 /data"
docker compose up -d
```

## Troubleshooting

### Permission denied on /data during startup

**Symptoms:**
- Container fails to start with "permission denied" errors
- Logs show "Cannot write to /data"
- Health check fails immediately

**Diagnosis:**
```bash
docker run --rm -v circuitbreaker-data:/data alpine ls -lan /data
```

If files are owned by uid 0 (root), run manual remediation above.

### Container starts as root despite Dockerfile USER directive

**Symptoms:**
- `docker compose exec circuitbreaker whoami` returns `root`
- Security checks fail

**Diagnosis:**
1. Check docker-compose.yml doesn't override with `user: "0:0"`
2. Verify image was built correctly:
   ```bash
   docker inspect ghcr.io/blkleg/circuitbreaker:mono-latest --format '{{.Config.User}}'
   ```
   Should return `breaker:breaker` or `1000:1000`

**Fix:**
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Volume ownership breaks after downgrade

If you downgrade from a non-root version to an older root version and then upgrade again, the volume may have mixed ownership.

**Fix:**
```bash
docker compose down
docker run --rm -v circuitbreaker-data:/data alpine sh -c "chown -R 1000:1000 /data && chmod -R 750 /data"
docker compose up -d
```

## Security Best Practices

### After Fresh Install

1. Run security verification:
   ```bash
   make check-security
   ```

2. Verify health endpoint:
   ```bash
   curl -sf http://localhost/api/v1/health | jq .
   ```

3. Test file upload functionality to confirm writable paths work correctly.

### After Upgrades

1. Let install.sh auto-fix volume ownership (it checks automatically)

2. Run verification after upgrade:
   ```bash
   make check-user
   ```

3. Check logs for permission errors:
   ```bash
   docker compose logs circuitbreaker | grep -i "permission denied"
   ```

### Regular Audits

Run security verification monthly or after any Docker/system updates:

```bash
make check-security
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

All processes should run as `breaker` (uid 1000), not root, except for the initial tini/supervisord parent process which drops privileges immediately.

## Related Documentation

- [Configuration Guide](configuration.md) - Environment variables and settings
- [Upgrading](upgrading.md) - Upgrade procedures
- [Docker Compose Installation](docker-compose.md) - Full deployment guide
