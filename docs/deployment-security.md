# Deployment & Security

This guide helps you choose the setup style that fits your environment.

- **Lab-friendly setup:** quickest path to get running.
- **Hardened setup:** stronger protection for broader access.

---

## 1) Lab-Friendly Setup (Fast Start)

Best for private, trusted networks and quick testing.

Recommended baseline:

- Keep access limited to trusted network segments.
- Use strong local credentials.
- Keep backups current.

---

## 2) Hardened Setup (Recommended for Shared or Exposed Environments)

Use this profile when more users or broader network access are involved.

### Core hardening checklist

- Require authentication for write actions.
- Use an API token for protected operations.
- Keep the app behind trusted network boundaries.
- Limit external exposure to only required ports.
- Use secure secret values for protected data handling.

### Important environment values

- `CB_API_TOKEN`: protects write operations when configured.
- `CB_VAULT_KEY`: secures sensitive stored credentials.

---

## 3) Secrets Management & Vault

Circuit Breaker uses a Fernet-based secure vault to encrypt sensitive credentials at rest — entirely local, no third-party key management required.

The vault protects:

- **SMTP credentials** — used for password reset and invite emails.
- **Proxmox API tokens** — the secret half of the PVEAuditor token used during cluster scans.
- **SNMP community strings** and **iDRAC/iLO credentials**.

### Vault key lifecycle

**You do not need to generate the vault key manually.** During the first-run setup wizard (OOBE), Circuit Breaker automatically generates a cryptographically secure key, writes it to `/data/.env` inside the data volume, and shows it once so you can back it up.

**If the vault ends up uninitialized** (after a crash, accidental volume deletion, or a headless deploy with no OOBE), use the `cb` CLI to recover:

```bash
cb vault-recover
```

See [cb CLI Tool](cb-cli.md#cb-vault-recover) for details.

**Vault best practices:**

- Back up the key shown during OOBE — store it in a password manager or offline secure location.
- Treat the vault key like a master root credential. Anyone with it can decrypt your stored secrets.
- If you lose the key and cannot recover it, you will need to re-enter all encrypted secrets (SMTP, Proxmox tokens, SNMP strings) in **Settings** after running `cb vault-recover`.

---

## 4) Practical Security Habits

- Rotate tokens on a regular schedule.
- Avoid sharing admin credentials.
- Review audit history for unexpected changes.
- Use least-privilege network access where possible.
- Keep your deployment updated.

---

## 4) Before You Go Live

- Confirm authentication behavior matches your policy.
- Confirm token and secret values are set and persisted.
- Confirm backups can be exported and restored.
- Confirm audit history is visible and reviewed.

---

## Related Guides

- [Settings](settings.md)
- [Backup & Restore](backup-restore.md)
- [Audit Log](audit-log.md)
