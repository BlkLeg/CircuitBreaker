# REL-3 — Process, Proxy, and Recovery Faults

**Requirements:** REL-09, REL-10
**Depends on:** SRV-3, SRV-7

## Build sequence

1. Build supported direct, mono proxy, split Caddy/reverse proxy, and trusted external proxy fixtures.
2. Verify forwarded client/proto/host only from trusted hops; secure cookies, redirects, absolute and
   WebSocket URLs, CSRF/CORS, audit actor IP, and rate-limit identity must agree.
3. Add process control for graceful SIGTERM, forced SIGKILL, rolling restart, lease-holder death,
   database failover/restart where supported, Redis/NATS outage, and mass agent reconnect.
4. Capture pre-fault durable counters and IDs; after recovery reconcile notification sends, monitor
   runs/results, telemetry samples, discovery jobs, audit entries, queue acks/dead letters, and agents.
5. Assert readiness transitions, drain deadline, retry jitter, resource ceilings, alerts, and recovery
   time. A process returning does not prove work recovery.

## Verification and done

Run through production systemd/Compose and real proxy headers/TLS. Done means spoofed headers cannot
alter identity, every topology builds correct secure URLs/cookies, and lifecycle faults meet RC SLOs
without unexplained duplicate or lost effects.
