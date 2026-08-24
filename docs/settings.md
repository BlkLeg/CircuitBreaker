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

### The dock

Choose which pages appear in the dock and the order they appear in. The list is grouped
the same way the route menu is — Acquire, Inventory, Observe, Govern, System — and offers
every destination your role can reach. The dock renders them left to right in the order
shown, and the up/down controls beside a checked item change that order.

A fresh install starts with nine items: Discovery, Agents, Hardware, Compute, Services,
Map, Monitors, Logs, and Settings. An installation upgraded from a release before this
setting existed keeps the dock it already had, including anything it had hidden.

Preferences are stored per-installation in the `dock_order` setting.

### Inventory helpers (Resources tab)

- Location list management
- Environment list management
- Icon library management

Categories are not managed here — they are created inline while editing hardware and services.

### Device Roles

- The device role catalog (labels and topology ranking) used by hardware and discovery.

### Access and session behavior (Security tab)

- Open registration on/off
- Rate limit profile
- Session duration
- Concurrent sessions
- Login lockout thresholds / durations
- Invite expiry (days)
- Allow masquerade
- Audit log retention
- Vault encryption status
- Password Resets (available when SMTP is enabled)
- OAuth / SSO provider configuration
- MFA enrollment and backup-code workflows (per user, from Profile → Security)

### Users (admins only)

- Accounts, roles, invites, and active sessions.

### Connectivity

- Auto-Discovery settings (the same panel as Discovery → Scan Settings)
- Discovery Engine v2 (always-on mDNS/SSDP listener)
- External Access — the App URL used in invite links

### Email Notifications & SMTP

- Outbound Email Server Configuration (Host, Port, User, TLS/SSL)
- Enables password reset flows for users locked out of their accounts.

### Integrations

- NATS message bus
- Network threat intelligence
- Docker integration (container discovery)
- Privacy & threat intelligence
- CVE feed sync
- Notification sinks and routing rules
- Proxmox VE and OPNsense (both configured from the Discovery page)
- Service integrations (for example Uptime Kuma)

### Monitoring

- Auto-monitor hardware accepted from a discovery scan (General tab).

### System actions

- Full backup (Download Backup)
- Clear lab data
- Database and host diagnostics (admins only)
- Backup & Recovery — S3 target configuration and test upload (admins only)
- Experimental features toggle
- Factory reset (Reset to Defaults)

Restoring a backup is an API operation, not a Settings control. See [Backup & Restore](backup-restore.md).

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

### Open or close registration

Use **Open Registration** under **Settings → Security → Authentication** to decide whether anyone can create
an account, or whether new users must be invited.

### Configure OAuth / OIDC sign-in

1. Open **Settings → Security → OAuth / SSO Providers**.
2. Enable a provider (GitHub, Google, or OIDC).
3. Enter client credentials and copy the shown callback URL into your provider app.
4. Save settings and test login from the login page.

### Adjust session timeout

Set session duration to match your environment’s security needs.

---

## Destructive Actions (Use Carefully)

### Factory reset

**Settings → System → Advanced → Reset to Defaults** resets all application settings to their defaults.

### Clear lab data

Removes inventory data from the environment. Confirm this action carefully before proceeding.

### Restore from a backup

Restore is an API operation: `POST /api/v1/admin/import`. If you send it with `wipe_before_import`, existing
data is removed before the restore runs, and the request must carry the destructive-action confirmation
headers. See [Backup & Restore](backup-restore.md).

---

## Related Guides

- [Backup & Restore](backup-restore.md)
- [Deployment & Security](deployment-security.md)
- [Auto-Discovery (Beta)](discovery.md)
