# SKILL.md
## When to Use
Integrations/scans (secrets/airgap).

## Instructions
1. `integration_configs.creds_json` (Fernet `CB_VAULT_KEY`).
2. Air-gap: `CB_AIRGAP=true`, CIDR ACL.
3. Audit logs.
4. Output: Schema/service/API + tests.

## Validate
No plaintext logs; `CB_AIRGAP` blocks external.

Files: SKILL.md, vault-template.py, vault-test.py