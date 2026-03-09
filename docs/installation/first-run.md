# First-Run Setup

After installing Circuit Breaker with any method, navigate to the app URL in your browser. On a fresh install with no existing data, the **first-run setup wizard** (OOBE) launches automatically.

The wizard runs once to create your admin account and configure core settings. Subsequent users who sign in will skip straight to the login screen.

---

## The Setup Wizard

The wizard walks you through 6 steps:

### Step 1 — Welcome

An introduction screen. Click **Get Started** to begin.

---

### Step 2 — Create Account

Create the first admin account for this installation. You can use a **local email and password** or sign up with an **OAuth provider** (GitHub, Google, or OIDC/SSO).

#### Local Account

Fill in:
- **Email** — used as your login identifier
- **Display Name** (optional) — shown in the UI header
- **Password** — must be at least 8 characters with uppercase, lowercase, a digit, and a special character
- **Confirm Password**

Your **profile photo** is pulled from [Gravatar](https://gravatar.com) automatically based on your email. Click the avatar preview to upload a custom JPEG or PNG (max 10 MB).

#### OAuth / SSO Account

Click **Continue with GitHub**, **Continue with Google**, or **Continue with SSO / OIDC**.

You will be prompted to enter your OAuth app's **Client ID** and **Client Secret** (and a Discovery URL for OIDC). Circuit Breaker saves these settings, then redirects to your chosen provider. After you authorize, you are returned to the wizard to continue.

> **OAuth app callback URL:** When registering your OAuth app with the provider, use this as the authorized redirect URI:
> ```
> https://<your-domain>/api/v1/auth/oauth/<provider>/callback
> ```
> For OIDC: `https://<your-domain>/api/v1/auth/oauth/oidc/oidc/callback`

The provider choice you make here is automatically enabled as a login option for future users.

---

### Step 3 — Choose Your Theme

Pick a colour palette and light/dark mode. You can also set your preferred font family and size. All of these can be changed later in **Settings → Appearance**.

---

### Step 4 — Regional Preferences

Configure:
- **Location** — search for your city to auto-set the weather widget and clock in the header
- **Timezone** — set manually or filled automatically from your location choice
- **Language** — UI display language (English, Spanish, French, German, Chinese, Japanese)

All of these can be changed later in **Settings → General**.

---

### Step 5 — Email Recovery Setup (Optional)

Configure **SMTP** so Circuit Breaker can send password reset emails and user invite links. This step is optional — you can skip it and rely on your vault key as an offline recovery path.

Settings to fill in if you enable SMTP:
- **SMTP Host** and **Port** (default 587)
- **Username** and **Password** (if your server requires auth)
- **From Email** and **From Name**
- **Use TLS** checkbox (default on)

Also set your **External App URL** — the public HTTPS address where users reach Circuit Breaker. This is used in email links so remote users get the right URL instead of a local address.

If Caddy HTTPS is detected, the wizard offers to auto-fill the HTTPS URL and lets you download the CA certificate.

---

### Step 6 — Confirmation

Review your choices. Click **Create account and enter Circuit Breaker** to finish setup.

---

## Vault Key Ceremony (Step 7)

If `CB_VAULT_KEY` was not pre-set in your environment, Circuit Breaker generates a Fernet encryption key during bootstrap and writes it to `/data/.env` (or `/app/data/.env` in Compose installs) inside the data volume.

**This key is shown only once.** A "Critical: Back Up Your Vault Key" screen appears before you enter the app.

The vault key protects:
- SMTP credentials
- Proxmox API tokens
- SNMP community strings and iDRAC/iLO passwords

**Back it up now.** Recommended locations:
- Your password manager
- An offline secure note
- The data volume itself (already written to `/data/.env`)

If you lose the vault key, you will need to re-enter all encrypted credentials after running `cb vault-recover`.

Check the **"I have securely backed up my vault key"** box and click **Continue to Circuit Breaker**.

---

## After Bootstrap

Once the wizard completes:

- You are logged in as admin.
- Authentication is enabled — subsequent visitors see the login screen.
- The OAuth provider you chose (if any) appears as a login button for other users.

### Inviting Other Users

Go to **Admin → Users → Invite User** to send email invitations, or share the login URL for users with OAuth access.

---

## If the Wizard Doesn't Appear

The wizard only appears on a fresh install with no existing data. If you see the login screen instead:

- Bootstrap has already been completed (data volume from a previous install).
- Log in with the credentials you created earlier.
- If you lost your credentials, use `cb vault-recover` or restore a backup. See [Backup & Restore](../backup-restore.md).

---

## Related

- [Configuration Reference](configuration.md) — environment variables and vault key setup
- [Authentication & Access](../auth-access.md) — OAuth/OIDC configuration for ongoing use
- [Backup & Restore](../backup-restore.md)
- [cb CLI Tool](../cb-cli.md#cb-vault-recover) — vault recovery command
