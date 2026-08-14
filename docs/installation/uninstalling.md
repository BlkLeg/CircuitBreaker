# Uninstalling

> **Warning:** Uninstalling permanently deletes your database, vault key, and all uploads. Export a backup first — see [Backup & Restore](../backup-restore.md).

---

## Native / Quick Install — `cb uninstall`

If you installed with `install.sh` (or via the Proxmox helper, which uses the same installer inside the container), run:

```bash
cb uninstall
```

There is a single confirmation prompt — **`Remove Circuit Breaker and ALL data? [y/N]`**. Answering `y` deletes the database and the vault key along with everything else; there is no second prompt offering to keep your data. Back up first.

After you confirm, it:

1. Stops and disables `circuitbreaker-postgres`, `-pgbouncer`, `-redis`, `-nats`, `-backend`, every `circuitbreaker-worker@*` unit, `circuitbreaker.target`, and nginx.
2. Removes the `circuitbreaker-*` unit files, `circuitbreaker.target` and `circuitbreaker.slice`, then reloads systemd.
3. Deletes `/opt/circuitbreaker`, `/etc/circuitbreaker`, `/etc/nats` and the data directory (`/var/lib/circuitbreaker` by default).
4. Removes the nginx site config, the `nats-server` binary, and the `cb` CLI from `/usr/local/bin/cb`.
5. Deletes the `breaker` system user and the `/etc/hosts` entry for the configured FQDN.
6. Removes the nginx package and the NodeSource repository files.

It also stops and removes the `cb-docker-proxy` container if the Docker telemetry proxy was set up.

---

## Proxmox LXC

Uninstalling means destroying the container. On the **PVE host**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/cb-proxmox-uninstall.sh)"
```

It asks for the container ID, shows the container's hostname and status, and on confirmation runs `pct stop` followed by `pct destroy --purge`.

The same removal is available as **Uninstall Container** (option 5) in `cb-proxmox-deploy.sh`, which lists the containers on the node and lets you pick one.

Either way the container and all its data are destroyed — there is nothing left to clean up on the host.

---

## Docker Compose

Stop and remove the container:

```bash
cd ~/.circuitbreaker
docker compose down
```

The compose file declares no named volumes, so this leaves your data untouched. Everything lives in the data directory beside `docker-compose.yml` — `./circuitbreaker-data` unless you set `CB_DATA_DIR`. To wipe it:

```bash
rm -rf ./circuitbreaker-data
```

If you built from source, run the same commands from the repository checkout.

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

## Legacy Caddy Deployments

Earlier releases shipped a single `circuit-breaker` container fronted by a `cb-caddy` proxy. `uninstall.sh` at the repository root still removes that layout and nothing else — it requires Docker, targets the container `circuit-breaker` and the volume `circuit-breaker-data`, and does not know about the systemd units or the `circuitbreaker` compose project described above.

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/uninstall.sh | bash
```

It stops and removes the `circuit-breaker` and `cb-caddy` containers, their network and volumes (with confirmation), the Caddy CA certificate from the system trust store and Firefox NSS databases, and the `~/.circuit-breaker` config directory.

### Removing the CA Certificate

If you used HTTPS with Caddy's self-signed CA, remove the certificate from your trust store:

#### Linux (system store)

```bash
sudo rm /usr/local/share/ca-certificates/circuit-breaker-caddy-ca.crt
sudo update-ca-certificates
```

#### macOS

```bash
sudo security delete-certificate -c "Circuit Breaker Caddy CA"
```

Or open **Keychain Access**, find the Circuit Breaker CA under **System**, and delete it.

#### Windows

Open **Manage Computer Certificates** → **Trusted Root Certification Authorities** → locate the Circuit Breaker CA entry → right-click → **Delete**.

#### Firefox

**Settings → Privacy & Security → Certificates → View Certificates → Authorities** → find the Circuit Breaker CA → **Delete or Distrust**.

---

### Removing Hosts File Entries

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
- [Proxmox LXC Installation](proxmox-lxc.md)
