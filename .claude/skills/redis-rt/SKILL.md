# SKILL.md
## When to Use
Performance/RT (polling → push).

## Instructions
1. Embedded Redis (`CB_REDIS_URL`).
2. Workers: APScheduler → `aioredis.publish`.
3. WS: `/ws/notifications` (JWT).
4. Frontend: `useRealtime.ts`.
5. Output: `redis.py`, `websocket.py`, hook.

## Channels
telemetry:{entity_id}, notifications:user:{id}
Files: SKILL.md, template-redis.py, template-websocket.py, template-rt-hook.py