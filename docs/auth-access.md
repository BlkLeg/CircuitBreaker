# Authentication & Access

Circuit Breaker supports local auth, OAuth/OIDC sign-in, MFA, user invites, and recovery flows.

## First Admin Bootstrap

During OOBE, you can create the first admin account via:

- Local email/password
- OAuth sign-up (GitHub, Google, or OIDC)

Both paths finish in the same setup flow and keep all later OOBE steps (theme, regional, SMTP, vault key ceremony).

## Sign-In Methods

- **Local login**: email + password
- **OAuth/OIDC**: provider buttons on login page
- **MFA step-up**: if enabled on your account, login redirects to code verification

## User & Invite Lifecycle

- Admins can invite users from the admin users area.
- Invite acceptance supports initial password set and role assignment.
- Users can be force-prompted to change password at next login.

## Password Recovery

- **Email reset** (recommended): available when SMTP is configured.
- **Vault key reset** (offline fallback): recover access using your backed-up vault key.

If SMTP is unavailable, vault-key recovery remains the fallback path.

## OAuth/OIDC Setup Checklist

1. Open **Settings → OAuth/OIDC**.
2. Enable provider and enter client credentials.
3. Copy callback URL exactly as shown and register it in provider config.
4. Save and run a login test.

## Security Notes

- Keep OAuth client secrets and vault key protected.
- Enable MFA for admin accounts.
- Tune session timeout and lockout settings for your environment.
- Review [Deployment & Security](deployment-security.md) for hardening steps.
