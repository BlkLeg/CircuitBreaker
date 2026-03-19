# Authentication & Access

Circuit Breaker supports local auth, OAuth/OIDC sign-in, MFA, user invites, and recovery flows.

---

## First Admin Bootstrap

During OOBE, you can create the first admin account via:

- Local email/password
- OAuth sign-up (GitHub, Google, or OIDC)

Both paths finish in the same setup flow and keep all later OOBE steps (theme, regional, SMTP, vault key ceremony).

---

## Sign-In Methods

| Method | Description |
|---|---|
| **Local login** | Email + password, managed entirely within Circuit Breaker |
| **GitHub OAuth** | Sign in with your GitHub account |
| **Google OAuth** | Sign in with your Google account |
| **OIDC** | Generic OpenID Connect — works with Authentik, Keycloak, and others |
| **MFA step-up** | TOTP code required after password if enabled on your account |

---

## OAuth / OIDC Setup

### Before you begin — set your Application Base URL

OAuth providers send users back to a **redirect URI** after authentication. Circuit Breaker builds this URI from the **Application Base URL** setting.

**Set this first:**

1. Go to **Settings → Application**
2. Set **Application Base URL** to the URL you use to access the app:
   - Local access: `https://localhost`
   - LAN hostname: `https://circuitbreaker.local`
   - Cloudflare Tunnel / public domain: `https://cb.yourdomain.com`

If this is blank, the app falls back to the request host header — which breaks OAuth when accessed from a different address than what the provider has registered.

---

### GitHub OAuth

**1. Create a GitHub OAuth App**

1. Go to [GitHub → Settings → Developer settings → OAuth Apps](https://github.com/settings/developers)
2. Click **New OAuth App**
3. Fill in:
   - **Homepage URL**: your app URL (e.g. `https://cb.yourdomain.com`)
   - **Authorization callback URL**:
     ```
     https://cb.yourdomain.com/api/v1/auth/oauth/github/callback
     ```
     Replace the hostname with your actual Application Base URL.
4. Click **Register application**
5. Copy the **Client ID** and generate a **Client Secret**

**2. Configure in Circuit Breaker**

1. Go to **Settings → Security → OAuth/OIDC**
2. Expand **GitHub** and toggle it **on**
3. Paste the **Client ID** and **Client Secret**
4. The exact redirect URI is shown under the fields — confirm it matches what you registered on GitHub
5. Click **Save OAuth Settings**

!!! tip "Redirect URI format"
    The redirect URI is always:
    `{Application Base URL}/api/v1/auth/oauth/github/callback`

---

### Google OAuth

**1. Create a Google OAuth Client**

1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials → OAuth 2.0 Client ID**
3. Select **Web application**
4. Under **Authorized redirect URIs**, add:
   ```
   https://cb.yourdomain.com/api/v1/auth/oauth/google/callback
   ```
5. Click **Create** and copy the **Client ID** and **Client Secret**

!!! warning "Google does not allow raw IP addresses"
    Google blocks OAuth callbacks to private IP ranges (10.x, 192.168.x, etc.).
    You must use either `https://localhost` (development exemption) or a real domain.
    A [Cloudflare Tunnel](remote-access.md) is the easiest way to get a trusted public URL for a homelab.

**2. Configure in Circuit Breaker**

1. Go to **Settings → Security → OAuth/OIDC**
2. Expand **Google** and toggle it **on**
3. Paste the **Client ID** and **Client Secret**
4. Click **Save OAuth Settings**

---

### OIDC (Authentik, Keycloak, etc.)

OIDC is the recommended option for homelabs — self-hosted providers like [Authentik](https://goauthentik.io) impose no domain restrictions and work with local IPs and private hostnames.

**1. Create an OIDC application in your provider**

In Authentik (example):

1. Go to **Applications → Providers → Create → OAuth2/OpenID Provider**
2. Set the **Redirect URI** to:
   ```
   https://your-cb-url/api/v1/auth/oauth/oidc/my-provider/callback
   ```
   Replace `my-provider` with the slug you'll use in Circuit Breaker.
3. Note the **Client ID**, **Client Secret**, and **Discovery URL**
   - Discovery URL format: `https://authentik.local/application/o/my-app/.well-known/openid-configuration`

**2. Configure in Circuit Breaker**

1. Go to **Settings → Security → OAuth/OIDC**
2. Expand **OIDC** and toggle it **on**
3. Enter the **Client ID**, **Client Secret**, and **Discovery URL**
4. Click **Save OAuth Settings**

---

## Common OAuth Errors

| Error | Cause | Fix |
|---|---|---|
| `redirect_uri_mismatch` | The callback URL registered with the provider doesn't match | Copy the exact URI shown under the provider's Configure panel in Settings |
| `device_id and device_name are required for private IP` | Google received a private IP as the redirect URI | Set Application Base URL to `https://localhost` or a real domain |
| `404 Not Found` on callback | Wrong callback URL format registered (e.g. NextAuth format) | Use `/api/v1/auth/oauth/github/callback`, not `/api/auth/callback/github` |
| `Internal server error` at final step | Database schema issue | Run `docker compose up --build -d backend` to apply latest migrations |

---

## Two-Factor Authentication (TOTP)

Circuit Breaker supports TOTP-based MFA using any standard authenticator app (Google Authenticator, Authy, Bitwarden Authenticator, etc.).

### Enabling TOTP MFA

1. Go to **Settings → Account → Security**.
2. Click **Enable Two-Factor Authentication**.
3. Scan the QR code with your authenticator app.
4. Enter the 6-digit code from your app to confirm enrollment.
5. **Save your recovery codes** — they are shown once. Treat them like your vault key: store them somewhere safe offline.

### Signing In with TOTP

Once enrolled, the sign-in flow becomes:

1. Enter email and password as usual.
2. A second prompt appears — enter the 6-digit code from your authenticator app.

Recovery codes can be used in place of the TOTP code if you lose access to your authenticator app. Each recovery code is single-use.

### Admin Reset (Lost Device)

If a user loses access to their authenticator app and has no recovery codes:

1. Go to **Admin → Users**.
2. Select the user.
3. Click **Reset MFA**.

The user's TOTP enrollment is cleared. They will be prompted to re-enroll on their next login.

### Disabling TOTP

1. Go to **Settings → Account → Security**.
2. Click **Disable Two-Factor Authentication**.
3. Confirm by entering your current TOTP code (or a recovery code).

---

## User & Invite Lifecycle

- Admins can invite users from **Admin → Users**.
- Invite acceptance supports initial password set and role assignment.
- Users can be force-prompted to change their password at next login.
- OAuth users are created with the `viewer` role; an admin must elevate them.

---

## Password Recovery

- **Email reset** (recommended): available when SMTP is configured in Settings.
- **Vault key reset** (offline fallback): recover access using your backed-up vault key.

If SMTP is unavailable, vault-key recovery remains the fallback path. See [Deployment & Security](deployment-security.md#secrets-management--vault).

---

## Security Notes

- Keep OAuth client secrets and vault key protected.
- Enable MFA for admin accounts.
- Tune session timeout and lockout settings for your environment under **Settings → Security**.
- Review [Deployment & Security](deployment-security.md) for hardening steps.
- Review the [Audit Log](audit-log.md) for unexpected sign-in activity.
