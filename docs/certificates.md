# Certificates

The Certificates page gives you visibility into the TLS/SSL certificates across your homelab.

Use it to track expiry dates, spot certificates that are about to expire, and keep a central record of what is protected and by whom.

---

## What You Can Track

- **Self-signed certificates** you manage directly
- **Let's Encrypt certificates** issued through Caddy or other ACME clients
- Certificates with **pasted PEM content** (for externally issued certs)

Certificates managed automatically by Caddy (the built-in reverse proxy) are tracked here automatically. You can also add records for external certificates you want to monitor.

---

## Status Indicators

Each certificate row shows a shield icon reflecting its current health:

| Icon | Meaning |
|---|---|
| 🟢 Green shield (check) | Valid — more than 30 days remaining |
| 🟡 Amber shield (alert) | Expiring soon — fewer than 30 days remaining |
| 🔴 Red shield (alert) | Expired |
| ⚪ Grey shield (off) | Expiry date unknown |

---

## Adding a Certificate

1. Open **Certificates**.
2. Click **+ Add Certificate**.
3. Fill in:
   - **Domain Name** — the CN or primary domain (e.g. `git.local`, `*.homelab.local`)
   - **Type** — `Self-Signed` or `Let's Encrypt`
   - **Auto Renew** — toggle on if the certificate is managed automatically
   - **Certificate PEM** (optional) — paste the full certificate chain if you want expiry parsed from real data
   - **Private Key PEM** (optional) — paste if you want Circuit Breaker to store the key for reference
4. Click **Save**.

If you leave PEM fields blank, Circuit Breaker creates a tracking record without stored key material.

---

## Certificate Detail

Click any row to open the detail drawer. It shows:

- Subject / CN
- SANs (Subject Alternative Names)
- Issuer
- Valid from / expires at dates
- Days remaining

---

## Bulk Delete

Select multiple certificates using the checkbox column, then choose **Delete Selected** from the bulk-actions bar.

---

## Related Guides

- [Deployment & Security](deployment-security.md) — Caddy automatic HTTPS setup
- [Settings](settings.md) — SMTP and system configuration
