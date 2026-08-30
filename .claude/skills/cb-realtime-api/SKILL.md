---
name: cb-realtime-api
description: How Circuit Breaker moves data between backend and frontend — the NATS internal bus, Redis pub/sub, the WebSocket stream endpoints and their first-message JWT handshake, SSE log/event streams, and the axios API client. Use this whenever adding or changing a WebSocket or SSE endpoint, publishing or subscribing to a NATS subject, wiring a React hook to live data, adding or renaming a REST endpoint or response field, debugging a stream that will not connect or reconnect, or auditing whether the frontend and backend still agree on an API contract.
---

# Circuit Breaker — Realtime & API Contract

## The transports, and which one to reach for

Three mechanisms, each with a job. Picking the wrong one is the most common
mistake here, so start from the question "who needs this, and when?"

| Transport | Use it for | Where |
|---|---|---|
| **NATS** | Backend-internal fan-out between API, workers, and agents | `core/nats_client.py`, subjects in `core/subjects.py` |
| **Redis pub/sub** | Backing store for WS push; last-value cache | `core/redis.py` |
| **WebSocket** | Bidirectional browser streams where the client subscribes | `api/ws_*.py` |
| **SSE** | One-way server→browser append streams (logs, events) | `api/events.py`, `api/logs.py` |
| **REST** | Everything else | `api/*.py` ↔ `apps/frontend/src/api/*.js` |

NATS is the internal bus and never reaches the browser directly. A worker
publishes to a subject; the API process subscribes and relays to connected
sockets. Authentication is `NATS_AUTH_TOKEN`, which `docker-compose.yml`
requires with `:?` — there is no unauthenticated bus.

## NATS subjects are constants, not strings

Every subject lives in `app/core/subjects.py` under `<domain>.<entity>.<event>`:

```python
from app.core.subjects import DISCOVERY_SCAN_PROGRESS, TELEMETRY_INGEST

await nats.publish(DISCOVERY_SCAN_PROGRESS, {"scan_id": scan_id, "pct": 42})
await nats.publish(TELEMETRY_INGEST.format(hardware_id=hw.id), payload)
```

Import the constant rather than typing the string. A hard-coded subject is
invisible to the subscriber side when someone renames an event, and the failure
mode is silent: the publish succeeds, nobody is listening, and the feature just
stops updating. Subjects with `{...}` placeholders are formatted at publish
time and have a matching `.>` wildcard for subscribers.

`NatsClient.publish` buffers on failure and resubscribes registered subjects
after a reconnect, so a dropped bus recovers on its own. Do not add retry loops
around it.

## WebSocket endpoints share one auth handshake

Five streams, all mounted at `/stream` under their router prefix:

```
WS /api/v1/discovery/stream   ws_discovery.py
WS /api/v1/telemetry/stream   ws_telemetry.py
WS /api/v1/topology/stream    ws_topology.py
WS /api/v1/monitors/stream    ws_monitors.py
WS /api/v1/agents/stream      ws_agents.py
```

All five are mounted with `Depends(require_auth)` in `main.py`. The agent
`/enroll` and `/link` sockets are the one router mounted without it, because
their Noise IK handshake is the authentication — that exception is deliberate
and documented at the mount site.

The handshake is identical everywhere, and new streams must match it:

1. Client connects.
2. Client sends the JWT as the **first text message**, raw — not a header, not JSON.
3. Server validates, checks session revocation, and replies `{"status": "connected"}`.
4. Only then do events flow.

Server-side that means `token_from_websocket_scope`, `decode_token`,
`is_session_revoked`, and `ws_require_wss` from `core/auth_cookie.py` and
`core/security.py`. There is no anonymous path — see the `cb-security-hardening`
skill, which treats a WS handler without JWT validation as a security defect.

Policy rejections close with **1008** and an `{"error": "..."}` frame
(`unauthorized`, `auth_timeout`, `subscription_limit_exceeded`). This matters
because the client uses the code to decide whether to retry: **1008 must not
trigger reconnection**, or a revoked session becomes a reconnect storm.

Subscription frames follow the `ws_telemetry.py` shape:

```json
{"subscribe": [5, 12, 34]}    {"unsubscribe": [12]}    {"type": "ping"}
```

Cap total distinct channels per connection and reject overflow rather than
letting one socket subscribe to everything.

## Frontend stream hooks

Hooks live in `apps/frontend/src/hooks/*.js` — `useDiscoveryStream`,
`useTelemetryStream`, `useAgentLive`, `useConnectionState`. Read
`useDiscoveryStream.js` before writing a new one; its header documents the
contract and it is the reference implementation.

Established behavior worth preserving:

- **One connection, mounted once at the app root** (`App.jsx`), not per page —
  it must survive navigation, and per-component sockets multiply silently.
- **Exponential backoff** starting at 2s, capped at 30s.
- **Never reconnect after 1008 / `auth_timeout`** — the credential is the
  problem, and retrying only burns the server.
- **Application-level ping/pong both directions**, so either side detects a
  half-open link that TCP still believes is alive.

Redis being unavailable degrades a stream to "connected but silent"; the client
falls back to REST polling. Keep that path working rather than failing the
socket outright.

## REST contract between the two halves

```
Backend  : apps/backend/src/app/api/*.py
Frontend : apps/frontend/src/api/*.js     (axios, via client.jsx)
```

The frontend never calls `fetch` inline. `api/client.jsx` is the single axios
instance and it already handles 401 session expiry, 422 field-error extraction
into `{field: message}`, 5xx user-facing messages, and server clock recording.
A new endpoint gets a function in the matching `api/*.js` module so every caller
inherits that behavior.

API conventions: snake_case JSON both directions, errors as
`{"detail": "message"}`, and 422 validation errors as the FastAPI array shape
that `extractFieldErrors` already understands.

### Auditing for drift

When OOBE breaks or a page renders empty fields, the usual cause is a schema
that moved without its caller. Compare the two sides directly:

```bash
grep -rhoE "'/[a-z0-9/_{}-]+'" apps/frontend/src/api/*.js | sort -u
grep -rhoE '@router\.(get|post|put|patch|delete)\("[^"]+"' apps/backend/src/app/api/*.py | sort -u
```

Report gaps as a table, then fix backend-first — schema, then service, then
route, then the frontend module — so the frontend is never written against an
endpoint that does not exist yet:

| Frontend call | Backend endpoint | Gap | Fix |
|---|---|---|---|

Changing a response field is a breaking change. Add the new field alongside the
old one and migrate callers rather than renaming in place; self-hosted users
upgrade on their own schedule and a half-updated deployment should still work.
