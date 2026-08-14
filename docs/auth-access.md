# Authentication & Access

Circuit Breaker supports local auth, OAuth/OIDC sign-in, MFA, user invites, and recovery flows.

Circuit Breaker 1.0 is single-tenant per deployment. Multiple users and RBAC are supported inside
one trusted deployment, but tenant isolation is not a security boundary. Run separate deployments for
separate households, customers, organizations, or other trust domains.

---

## First Admin Bootstrap

During OOBE, you can create the first admin account via:

- Local email/password
- OAuth sign-up (GitHub, Google, or OIDC)

Both paths finish in the same setup flow and keep all later OOBE steps (theme, regional, SMTP, vault key ceremony).

First run is not an open admin session. Until the first admin exists, only the endpoints the setup wizard itself
needs will answer: `/api/v1/bootstrap`, `/api/v1/auth`, `PATCH /api/v1/settings/oauth`, and `GET /api/v1/settings`.
Every other route returns 401, and the bootstrap routes are additionally gated by the setup token. Even so,
complete OOBE promptly and keep the port off untrusted networks while you do it.

---

## Sign-In Methods

| Method | Description |
|---|---|
| **Local login** | Email + password, managed entirely within Circuit Breaker |
| **GitHub OAuth** | Sign in with your GitHub account |
| **Google OAuth** | Sign in with your Google account |
| **OIDC** | Generic OpenID Connect — works with Authentik, Keycloak, and others |
| **MFA step-up** | TOTP code required after password if enabled on your account |
| **API tokens** | Scoped, non-interactive tokens created by an admin under Profile → API tokens |

### API tokens

Admins can mint scoped API tokens from the **API tokens** tab of the Profile modal (`POST /api/v1/auth/api-token`).
The token value is shown once at creation — copy it then, because it cannot be retrieved later. Existing tokens are
listed and can be revoked individually (`GET /api/v1/auth/api-tokens`, `DELETE /api/v1/auth/api-tokens/{token_id}`). A token carries scopes rather
than a session, so it is the right way to script against the API instead of reusing a user login.

---

## OAuth / OIDC Setup

### Before you begin — set your App URL

OAuth providers send users back to a **redirect URI** after authentication. Circuit Breaker builds this URI from the **App URL** setting.

**Set this first:**

1. Go to **Settings → Connectivity → External Access**
2. Set **App URL (used in invite links)** to the URL you use to access the app:
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
     Replace the hostname with your actual App URL.
4. Click **Register application**
5. Copy the **Client ID** and generate a **Client Secret**

**2. Configure in Circuit Breaker**

1. Go to **Settings → Security → OAuth / SSO Providers**
2. Expand **GitHub** and toggle it **on**
3. Paste the **Client ID** and **Client Secret**
4. The exact redirect URI is shown under the fields — confirm it matches what you registered on GitHub
5. Click **Save OAuth Settings**

!!! tip "Redirect URI format"
    The redirect URI is always:
    `{App URL}/api/v1/auth/oauth/github/callback`

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

1. Go to **Settings → Security → OAuth / SSO Providers**
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
   https://your-cb-url/api/v1/auth/oauth/oidc/oidc/callback
   ```
   Copy the exact value shown under the OIDC **Configure** panel in Circuit Breaker — the UI always uses the
   `oidc` slug, so the segment is repeated.
3. Note the **Client ID**, **Client Secret**, and **Discovery URL**
   - Discovery URL format: `https://authentik.local/application/o/my-app/.well-known/openid-configuration`

**2. Configure in Circuit Breaker**

1. Go to **Settings → Security → OAuth / SSO Providers**
2. Expand **OIDC** and toggle it **on**
3. Enter the **Client ID**, **Client Secret**, and **Discovery URL**
4. Click **Save OAuth Settings**

---

## Common OAuth Errors

| Error | Cause | Fix |
|---|---|---|
| `redirect_uri_mismatch` | The callback URL registered with the provider doesn't match | Copy the exact URI shown under the provider's Configure panel in Settings |
| `device_id and device_name are required for private IP` | Google received a private IP as the redirect URI | Set the App URL to `https://localhost` or a real domain |
| `404 Not Found` on callback | Wrong callback URL format registered (e.g. NextAuth format) | Use `/api/v1/auth/oauth/github/callback`, not `/api/auth/callback/github` |
| `Internal server error` at final step | Database schema issue | Restart the container — migrations run on start (`docker compose up -d --build circuitbreaker`) |

---

## Two-Factor Authentication (TOTP)

Circuit Breaker supports TOTP-based MFA using any standard authenticator app (Google Authenticator, Authy, Bitwarden Authenticator, etc.).

### Enabling TOTP MFA

1. Open the user avatar in the header → **Profile** → **Security** tab.
2. Click **Enable Two-Factor Authentication**.
3. Scan the QR code with your authenticator app.
4. Enter the 6-digit code from your app to confirm enrollment.
5. **Save your backup codes** — they are shown once. Treat them like your vault key: store them somewhere safe offline.

### Signing In with TOTP

Once enrolled, the sign-in flow becomes:

1. Enter email and password as usual.
2. A second prompt appears — enter the 6-digit code from your authenticator app.

Backup codes can be used in place of the TOTP code if you lose access to your authenticator app. Each backup code is single-use. An enrolled user can mint a fresh set with **Regenerate Backup Codes** on the same Profile → Security tab; regenerating invalidates the previous set.

### Lost Device

Backup codes are the recovery path — there is no admin control that clears another user's TOTP enrollment.

If a user loses their authenticator app and has no backup codes left, an admin's only options under
**Admin → Users** are to reset the account's password (which does not clear MFA) or to delete the
account and re-invite the person, who then enrolls again from scratch.

### Disabling TOTP

1. Open the user avatar in the header → **Profile** → **Security** tab.
2. Click **Disable Two-Factor Authentication**.
3. Confirm by entering your current TOTP code (or a backup code).

---

## Roles and Permissions

Every account carries one role. Roles are hierarchical — `viewer` < `editor` < `admin`.

| Role | What it can do |
|---|---|
| **viewer** | Read everything (`read:*`). No writes, no deletes, no admin surfaces. |
| **editor** | Everything viewer can do, plus write access to hardware, services, networks, clusters, external nodes, compute, storage, misc, docs, graph and layout. No deletes and no admin surfaces. |
| **admin** | Full access: read, write, delete, and the admin surfaces (users, invites, audit log, restore, masquerade). |
| **demo** | Read-only, same scopes as viewer, but time-boxed. |

Only `admin`, `editor` and `viewer` can be assigned to an account or carried by an invite. `demo` is not an
assignable account role — it is a one-hour read-only session minted by `POST /api/v1/auth/demo` that expires
on its own.

An account that has tripped the login lockout is refused with `423 Locked` on authenticated requests until
the lockout expires or an admin unlocks it from **Admin → Users**.

---

## User & Invite Lifecycle

- Admins can invite users from **Admin → Users**.
- Invite acceptance supports initial password set and role assignment.
- Users can be force-prompted to change their password at next login.
- OAuth users are created with the `viewer` role and an admin must elevate them — unless the user signs up
  through an invite, in which case they get the role the invite carried.
- When **Allow Masquerade** is enabled under **Settings → Security → Authentication**, an admin can act as
  another user from **Admin → Users**. The masquerade token is short-lived, a banner stays visible for the
  duration, and the action is written to the [Audit Log](audit-log.md).

---

## Password Recovery

- **Email reset** (recommended): available when SMTP is configured in Settings.
- **Vault key reset** (offline fallback): recover access using your backed-up vault key.

If SMTP is unavailable, vault-key recovery remains the fallback path. See [Deployment & Security](deployment-security.md#3-secrets-management-vault).

---

## Security Notes

- Keep OAuth client secrets and vault key protected.
- Enable MFA for admin accounts.
- Tune session timeout and lockout settings for your environment under **Settings → Security**.
- Review [Deployment & Security](deployment-security.md) for hardening steps.
- Review the [Audit Log](audit-log.md) for unexpected sign-in activity.
