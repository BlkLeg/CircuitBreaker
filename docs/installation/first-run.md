# First-Run Setup

After installing Circuit Breaker with any method, navigate to the app URL in your browser. On a fresh install with no existing data, the **first-run setup wizard** (OOBE) launches automatically.

The wizard runs once to create your admin account and configure core settings. Subsequent users who sign in will skip straight to the login screen.

---

## The Setup Wizard

The wizard walks you through 7 steps, followed by the vault key screen:

### Step 1 — Welcome

An introduction screen. Click **Get Started** to begin.

---

### Step 2 — Domain

Optional. Enter a fully qualified domain name (for example `circuitbreaker.example.com`) and click **Apply**, and Circuit Breaker generates a matching self-signed certificate and reconfigures nginx for it. The wizard then offers a link to continue at the new HTTPS address.

Click **Skip** to stay on IP-based access — access by IP keeps working either way.

---

### Step 3 — Create Account

Create the first admin account for this installation. You can use a **local email and password** or sign up with an **OAuth provider** (GitHub, Google, or OIDC/SSO).

#### Setup Token

Before creating the first admin, enter the one-time setup token from the server. This prevents another browser on the network from racing you to create the first admin account.

Circuit Breaker accepts the token from one of two places:

- `CB_SETUP_TOKEN` — set this environment variable before first start for unattended or production installs.
- `CB_DATA_DIR/bootstrap-setup-token` — if `CB_SETUP_TOKEN` is not set, the backend generates a token and writes it to this file with `0600` permissions.
  The wizard prints the resolved path for your deployment, so you can copy the `sudo cat …` command straight off the setup screen.

The token is never returned by the public status API or shown in the browser. It expires after 24 hours by default. To change the lifetime before setup, set `CB_SETUP_TOKEN_TTL_HOURS` to a value from `1` to `168`.

If the generated token expires or is lost before setup completes, restart the backend or reload the setup status page to generate a fresh private token file. After bootstrap succeeds, the token is consumed and cannot be replayed.

#### Local Account

Fill in:
- **Setup token** — from `CB_SETUP_TOKEN` or the generated `bootstrap-setup-token` file
- **Email** — used as your login identifier
- **Display Name** (optional) — shown in the UI header
- **Password** — must be at least 8 characters with uppercase, lowercase, a digit, and a special character
- **Confirm Password**

Your **profile photo** is pulled from [Gravatar](https://gravatar.com) automatically based on your email. Click the avatar preview to upload a custom JPEG or PNG. The upload form says 10 MB, but the server rejects anything over **5 MB** — keep it under 5 MB.

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

### Step 4 — Choose Your Theme

Pick a colour palette and light/dark mode. You can also set your preferred font family and size. All of these can be changed later in **Settings → Appearance**.

---

### Step 5 — Regional Preferences

Configure:
- **Location** — search for your city to auto-set the weather widget and clock in the header
- **Timezone** — set manually or filled automatically from your location choice
- **Language** — UI display language (English, Spanish, French, German, Chinese, Japanese)

All of these can be changed later in **Settings → General**.

---

### Step 6 — Email Recovery Setup (Optional)

Configure **SMTP** so Circuit Breaker can send password reset emails and user invite links. This step is optional — you can skip it and rely on your vault key as an offline recovery path.

Settings to fill in if you enable SMTP:
- **SMTP Host** and **Port** (default 587)
- **Username** and **Password** (if your server requires auth)
- **From Email** and **From Name**
- **Use TLS** checkbox (default on)

Also set your **External App URL** — the public HTTPS address where users reach Circuit Breaker. This is used in email links so remote users get the right URL instead of a local address.

If Caddy HTTPS is detected, the wizard offers to auto-fill the HTTPS URL and lets you download the CA certificate.

---

### Step 7 — Confirmation

Review your choices. Click **Create account and enter Circuit Breaker** to finish setup.

---

## Vault Key Ceremony (Step 8)

If `CB_VAULT_KEY` was not pre-set in your environment, Circuit Breaker generates a Fernet encryption key during bootstrap and writes it into the data directory — `/data/.env` in container installs, `/etc/circuitbreaker/.env` on native installs, where the installer generates one for you up front.

**This key is shown only once.** A "Critical: Back Up Your Vault Key" screen appears before you enter the app.

The vault key protects:
- SMTP credentials
- Proxmox API tokens
- SNMP community strings and iDRAC/iLO passwords

**Back it up now.** Recommended locations:
- Your password manager
- An offline secure note
- The data directory itself (already written to `.env` there)

If you lose the vault key, you will need to re-enter every encrypted credential afterwards.

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
- If you lost your credentials, restore a backup. See [Backup & Restore](../backup-restore.md).

---

## Related

- [Configuration Reference](configuration.md) — environment variables and vault key setup
- [Authentication & Access](../auth-access.md) — OAuth/OIDC configuration for ongoing use
- [Backup & Restore](../backup-restore.md)
- [cb CLI Tool](../cb-cli.md)
