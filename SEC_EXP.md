# SEC_EXPANSION.md: Authentication Expansion Plan

**Author**: CyberSec Student Showcase  
**Goal**: Transform single-user JWT → Production-grade multi-auth (OAuth2 + OIDC + SAML) while maintaining OOBE simplicity. Demonstrate enterprise security patterns: RBAC, MFA, session federation, audit trails.

**Phases**: Progressive hardening. Each phase standalone + testable.

***

## Phase 1: OAuth2 Provider Integration (GitHub + Google)

**Timeline**: 2 days  
**Scope**: Email/password + GitHub/Google OAuth. RBAC auto-assignment.

### Backend Changes

**Auth Router** (`app/api/auth_oauth.py`):
```
POST /api/v1/auth/github
POST /api/v1/auth/google
GET  /api/v1/auth/callback/{provider}
```

**OAuth Config** (`app_settings`):
```yaml
oauth:
  github:
    client_id: ""
    client_secret_enc: ""  # Fernet
    redirect_uri: "https://circuitbreaker.local/api/v1/auth/callback/github"
  google:
    client_id: ""
    client_secret_enc: ""
```

**User Mapping**:
```
External ID → User row (email primary)
New user → Auto-create w/ role="viewer"
Existing → Link accounts (email match)
```

**Scopes**: `openid email profile`

### Frontend

**Login Page**:
```
Sign In
[ Email / Password ]  ← Existing

OAuth:
[ GitHub ] [ Google ]  ← New buttons
```

**Settings → Security**:
```
OAuth Clients
┌─ GitHub ───────┐
│ Client ID: [ ] │
│ Secret:   [Gen]│ [Test]
└───────────────┘
┌─ Google ───────┐
│ Client ID: [ ] │
└───────────────┘
[Save & Restart]
```

### Security

- Client secrets Fernet-encrypted.
- State parameter CSRF protection.
- PKCE for public clients (future mobile).

***

## Phase 2: OIDC Provider Support (Authentik)

**Timeline**: 3 days  
**Scope**: Generic OIDC (Authentik/Keycloak). Client Credentials + Authorization Code flow.

### Backend

**OIDC Client** (`python3-oidc` + `httpx`):
```
POST /api/v1/auth/oidc/{provider}
# provider="authentik", "keycloak"
```

**Dynamic Provider Config**:
```yaml
oidc_providers:
  - name: "Authentik"
    client_id: ""
    client_secret_enc: ""
    issuer_url: "https://authentik.local/application/o/circuit-breaker/"
    redirect_uri: "..."
    role_mapping: "groups"  # Extract admin/editor from claims
```

**Advanced Claims**:
```
User claims → RBAC:
{
  "sub": "abc123",
  "email": "user@local",
  "groups": ["cb-admin", "cb-editor"]
}
→ user.role = "admin" if "cb-admin" in groups
```

### Frontend

**Login Dropdown**:
```
OAuth Providers ▼
├── GitHub
├── Google
└── Authentik (oidc.authentik.local)
```

### Security

- JWKS validation (remote issuer).
- Token introspection endpoint.
- Group-based RBAC (no hardcoding).

***

## Phase 3: SAML 2.0 (Enterprise)

**Timeline**: 2 days  
**Scope**: SAML IdP (Authentik + Azure AD). SP-initiated flow.

### Backend

**SAML Library** (`pysaml2`):
```
POST /api/v1/auth/saml/acs  # Assertion Consumer Service
GET  /api/v1/auth/saml/login
```

**SAML Metadata**:
```
Auto-generate SP metadata XML → User pastes into IdP
IdP metadata XML → Auto-fetch/parse → app_settings.saml_idp_metadata
```

**Attribute Mapping**:
```
SAML Attr → User:
email → user.email
memberOf → user.role (mapped)
```

### Security

- XML signing validation.
- Audience/Issuer restriction.
- Session fixation protection.

***

## Phase 4: MFA (TOTP + WebAuthn)

**Timeline**: 3 days  
**Scope**: 2FA for all auth flows. Enforceable per-role.

### Backend

**TOTP** (`pyotp`):
```
POST /api/v1/auth/mfa/setup     # QR code SVG
POST /api/v1/auth/mfa/verify    # 6-digit code
POST /api/v1/auth/mfa/disable
```

**WebAuthn** (`webauthn` lib):
```
POST /api/v1/auth/webauthn/register
POST /api/v1/auth/webauthn/authenticate
```

**Schema**:
```sql
ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN mfa_secret_enc TEXT;  -- TOTP secret
ALTER TABLE users ADD COLUMN mfa_backup_codes TEXT;  -- JSON array
```

### Frontend

**MFA Flow** (post-login):
```
Enable 2FA
1. Scan QR: [SVG QR]
2. Enter Code: [123456]
3. Backup Codes: [Copy 10x codes]

[ ] Require MFA for all users  ← Admin toggle
```

### Security

- Rate limit TOTP (10/min).
- Backup codes single-use.
- WebAuthn RP ID = domain.

***

## Phase 5: Enterprise Features

**Timeline**: 2 days  
**Scope**: SSO dashboard + compliance.

### RBAC Granularity

```
roles → permissions matrix:
admin:   ["*"]
editor:  ["topology.write", "hardware.write"]
viewer:  ["read"]
```

### Audit Trail

```
Every auth event:
2026-03-07 14:30 | user:alice | auth_oidc_success | {"provider":"authentik","ip":"192.168.1.100"}
2026-03-07 14:31 | user:alice | mfa_verified | {"method":"totp"}
```

### Session Federation

```
SAML/OIDC session → CB JWT
JWT expiry synced with IdP
/api/v1/auth/logout → IdP SLO (Single Logout)
```

***

## Data Model Summary

```sql
-- users
ALTER TABLE users ADD COLUMN provider TEXT;              -- "local", "github", "oidc"
ALTER TABLE users ADD COLUMN provider_id TEXT UNIQUE;    -- External ID
ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN;
ALTER TABLE users ADD COLUMN mfa_secret_enc TEXT;
ALTER TABLE users ADD COLUMN mfa_backup_codes JSON;

-- oauth_tokens (refresh tokens)
CREATE TABLE oauth_tokens (
  user_id INTEGER,
  provider TEXT,
  refresh_token_enc TEXT,
  expires DATETIME
);

-- app_settings (configs)
ALTER TABLE app_settings ADD COLUMN oauth_providers JSON;
ALTER TABLE app_settings ADD COLUMN oidc_providers JSON;
ALTER TABLE app_settings ADD COLUMN saml_metadata TEXT;
```

***

## Migration & Rollout

```
Phase 1: GitHub/Google OAuth + Settings UI
Phase 2: OIDC (Authentik) → Test w/ Authentik dev instance
Phase 3: SAML → Enterprise demo
Phase 4: MFA → Required for admin
Phase 5: Federation + SLO
```

**OOBE Updates**:
```
1. Local admin account
2. OAuth client setup wizard
3. MFA QR code
```

**Security Showcase**:
- **Zero Trust**: Every login audited + MFA enforced.
- **Federation**: Works with any OAuth2/OIDC/SAML IdP.
- **Compliance**: Audit logs exportable (CSV/JSON).

**Estimated Total**: 12 days → v0.3.0 "Enterprise Auth".