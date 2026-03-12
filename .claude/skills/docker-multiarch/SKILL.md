# SKILL.md
## When to Use
Docker changes (libs/volumes/env/entrypoint).

## Instructions
1. Multi-stage Alpine.
2. Non-root `breaker:1000`, chown entrypoint.
3. Volumes `/data/*`.
4. HEALTHCHECK + multi-arch (amd64/arm64/armv7).
5. Output: Full `Dockerfile` + `entrypoint.sh`.

## Example
```
FROM python:3.12-alpine AS runtime
RUN apk add redis
USER breaker:1000

```
Files: SKILL.md, template-Dockerfile, template-entrypoint.sh
