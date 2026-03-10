# Settings

The Settings area lets you control how Circuit Breaker looks, behaves, and protects your environment.

---

## What You Can Configure

### General preferences

- Language
- Timezone
- Default environment
- Helpful interface hints

### Appearance and layout

- Theme and branding
- Icon behavior
- Dock and quick-navigation options
- Map display defaults and visibility options

### Inventory helpers

- Environment list management
- Category list management
- Location list management

### Access and session behavior

- Authentication on/off
- Session timeout
- Concurrent sessions
- Login lockout thresholds / durations
- Password Resets (available when SMTP is enabled)
- OAuth/OIDC provider configuration
- MFA enrollment and recovery workflows

### Email Notifications & SMTP

- Outbound Email Server Configuration (Host, Port, User, TLS/SSL)
- Enables password reset flows for users locked out of their accounts.

### Integrations

- Discovery-specific options from the Discovery settings area
- Webhooks (event routing + test delivery)
- Notification sinks and routing rules
- OAuth/OIDC provider credentials and callback URLs

### System actions

- Export backup
- Import backup
- Reset settings
- Clear lab data

---

## Most Common Tasks

### Change timezone or language

1. Open **Settings**.
2. Update timezone and/or language.
3. Save changes.

### Set your default environment

Use a default environment (for example, `prod`, `staging`, or `dev`) to speed up data entry.

### Update branding

Use branding options to apply your preferred app name and visual identity.

### Enable authentication

Turn on authentication when you want login protection and controlled sessions.

### Configure OAuth / OIDC sign-in

1. Open **Settings → Security / OAuth**.
2. Enable a provider (GitHub, Google, or OIDC).
3. Enter client credentials and copy the shown callback URL into your provider app.
4. Save settings and test login from the login page.

### Configure webhooks and notifications

1. Open **Settings → Webhooks** (or **Notifications**).
2. Add a webhook endpoint label + URL, then choose per-group event toggles (Proxmox, Telemetry, Discovery, and more).
3. Use **Enable all critical** for fast onboarding, or toggle each event independently per webhook card.
4. Run **Test webhook** (`test.ping`) and review per-webhook delivery history (status + response time + retries).

### Adjust session timeout

Set session duration to match your environment’s security needs.

---

## Destructive Actions (Use Carefully)

### Reset settings

Resets configuration values to defaults.

### Clear lab data

Removes inventory data from the environment. Confirm this action carefully before proceeding.

### Import backup with wipe option

If you import with wipe enabled, existing data is removed before restore.

---

## Related Guides

- [Backup & Restore](backup-restore.md)
- [Deployment & Security](deployment-security.md)
- [Auto-Discovery (Beta)](discovery.md)
