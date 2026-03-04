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

## 3) Practical Security Habits

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
