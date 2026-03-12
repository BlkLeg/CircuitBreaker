# SKILL.md
## When to Use
OOBE broken, API drifts.

## Instructions
1. Scan `frontend/src/lib/api/*.ts` vs `backend/app/api/*.py`.
2. Table gaps (missing fields/endpoints).
3. Fix: Schemas/services first.
4. Output: Markdown table + fixes.

## Template Table
| Frontend Call | Backend Endpoint | Gap | Fix |
|---|---|---|---|
Files: SKILL.md, api-audit-template.md
