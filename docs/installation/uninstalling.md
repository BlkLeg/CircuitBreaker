# Uninstalling

> **Warning:** Removing the data volume permanently deletes your database, vault key, and all uploads. Export a backup first — see [Backup & Restore](../backup-restore.md).

---

## Quick Install (Script) — Using `cb uninstall`

If you installed with `install.sh` and the `cb` CLI is available:

```bash
cb uninstall
```

The command prompts you to confirm, then:
1. Stops the running container.
2. Removes the container.
3. Asks whether to remove the data volume (your database and vault key).
4. Removes the `cb` CLI binary from `/usr/local/bin/cb`.
5. Removes the systemd service (if installed).

---

## Quick Install (Script) — One-Liner Uninstall

If the `cb` CLI is not available, run the uninstall script directly:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/uninstall.sh | bash
```

The script:
- Stops and removes the Circuit Breaker container.
- Stops and removes the Caddy proxy container (if installed).
- Removes associated Docker networks and volumes (with your confirmation).
- Removes the self-signed CA certificate from the system trust store and Firefox NSS databases.
- Removes the `cb` CLI and systemd service.
- Removes `~/.circuit-breaker/install.conf`.

---

## Docker Compose — Prebuilt

Stop and remove containers only (data preserved):

```bash
docker compose down
```

Stop and remove containers **and** the data volume:

```bash
docker compose down -v
```

---

## Docker Compose — From Source

```bash
docker compose -f docker/docker-compose.yml down
```

With volume removal:

```bash
docker compose -f docker/docker-compose.yml down -v
```

---

## Single Docker Container — Manual Steps

```bash
# 1. Stop and remove the container
docker stop circuit-breaker
docker rm circuit-breaker

# 2. (Optional) Remove the data volume
docker volume rm circuit-breaker-data

# 3. (Optional) Remove the image
docker rmi ghcr.io/blkleg/circuitbreaker:latest
```

---

## Removing the CA Certificate

If you used HTTPS with Caddy's self-signed CA, remove the certificate from your trust store:

### Linux (system store)

```bash
sudo rm /usr/local/share/ca-certificates/circuit-breaker-caddy-ca.crt
sudo update-ca-certificates
```

### macOS

```bash
sudo security delete-certificate -c "Circuit Breaker Caddy CA"
```

Or open **Keychain Access**, find the Circuit Breaker CA under **System**, and delete it.

### Windows

Open **Manage Computer Certificates** → **Trusted Root Certification Authorities** → locate the Circuit Breaker CA entry → right-click → **Delete**.

### Firefox

**Settings → Privacy & Security → Certificates → View Certificates → Authorities** → find the Circuit Breaker CA → **Delete or Distrust**.

---

## Removing Hosts File Entries

If you added `circuitbreaker.local` to your hosts file:

```bash
# Linux / macOS — remove the line
sudo sed -i '/circuitbreaker\.local/d' /etc/hosts
```

On Windows, edit `C:\Windows\System32\drivers\etc\hosts` in a text editor running as Administrator.

---

## Related

- [Backup & Restore](../backup-restore.md) — export your data before uninstalling
- [cb CLI Tool](../cb-cli.md) — `cb uninstall` reference
