# Requested previews: progress and cb resources
Two companion screens in the same CLI visual direction. Neither is a new product style. Full art is for lifecycle entry; normal commands use compact text branding. Use existing terminal palette and monospace design system. Show Sample data · design preview unobtrusively outside terminal output.

## Download progress
$ cb update
UPDATE native / linux-amd64
0.4.6 → 0.4.7
Preflight and compatibility completed 0.8s.
Phase 2 / 6 — Download release
52.0 / 84.0 MiB · 62% · 6.5 MiB/s · elapsed 8s
32-character orange filled bar with 20 filled characters and 12 muted empty characters: [████████████████████░░░░░░░░░░░░]. Purple active spinner separate from bar. Unknown verification/backup/apply/health stages are pending; don't claim verification complete before download. Static example bar with subtle active marker animation only, no fake accumulating data.
Expected target v0.4.7; current v0.4.6 still running.
Existing ASCII mascot above active ledger, byte/space faithful.
Log: /var/log/circuitbreaker/install.log

## Resource watch
$ cb resources --watch
Circuit Breaker 0.4.7  RESOURCES  native
Sample window 2.0s · refresh 2s · sorted by CPU
Scope: local app-owned services · shared nginx excluded
CPU: 0.72 cores, 9.0% of 8 visible CPUs (bar 9% full)
Memory: 1.84 GiB, 11.5% of 16 GiB visible RAM (bar 11.5% full)
Memory includes cache; cache 256 MiB; swap 24 MiB
Disk: 128 KiB/s read · 1.20 MiB/s write
Network: unavailable — per-service accounting disabled (not 0)
Component table: CPU cores, Memory, Read/s, Write/s, State. CPU-descending order:
Workers (7) 0.31 680 MiB 16 KiB 256 KiB active
API 0.18 420 MiB 0 0 active
PostgreSQL 0.17 520 MiB 112 KiB 960 KiB active
Redis 0.02 120 MiB 0 0 active
NATS 0.02 80 MiB 0 13 KiB active
PgBouncer 0.01 32 MiB 0 0 active
Helper 0.01 32 MiB 0 0 active
All seven rows sum to 0.72 cores and 1884 MiB (~1.84 GiB). Shared nginx is separately 0.03 cores / 46 MiB; never included in totals.
Shared limits: circuitbreaker.slice 1.30 / 3.00 GiB · PostgreSQL and helper outside slice.
Attention: telemetry worker CPU throttled in 18% of periods.
Visible capacity is not a guaranteed limit for the install.
Footer: [q] quit [c] CPU [m] memory [e] expand workers [j/k] scroll.
No full installer artwork in routine command view. No animated decorative charts. Rates are per sample and unavailable values remain explicit. This is a terminal table, not browser dashboard cards. Match source CLI semantics; no new command flags.
