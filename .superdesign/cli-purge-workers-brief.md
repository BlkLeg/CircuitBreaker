# Two requested companion previews: purge and expanded workers
Preserve established terminal design; illustrative data, no runtime mutation.

## Purge confirmation — pending, before mutation
Source is existing uninstall preview. Keep exact ASCII artwork. Use compact
plan and danger emphasis, no decorative web alert cards or new palette.
$ cb uninstall --purge
PURGE · native / linux-amd64 · v0.4.7
Permanently remove Circuit Breaker and its local data.
DELETE /opt/circuitbreaker — application files
DELETE /var/lib/circuitbreaker — database, uploads, local backups
DELETE /etc/circuitbreaker — configuration, credentials, vault key
REMOVE app services, app nginx site
KEEP shared nginx, system dependencies, npm CLI

Deleting the vault key prevents decrypting retained encrypted data unless an
independent copy of the key exists. This operation cannot be rolled back from
backups inside the directory being deleted. External backups are not deleted.

Services are still running. No changes made.
Type DELETE circuitbreaker to confirm:
> [empty caret, never prefilled]
Enter exact phrase to continue · Ctrl-C cancels

No completed phase ledger or success message before confirmation. A generic --yes
never authorizes data deletion. This is the proposed npm CLI confirmation; the
current shell --purge behavior is separate and not changed by this mockup.
Sample data · design preview outside terminal.

## Expanded resources
Source is resources preview. Keep totals and metrics identical to previous sample.
$ cb resources --watch
Sample window 2.0s · refresh 2s · sorted by CPU · workers expanded
CPU 0.72 cores / 9.0% of 8 CPUs; memory 1.84 GiB / 11.5% of 16 GiB;
cache256MiB swap24MiB; read128KiB/s write1.20MiB/s. Network unavailable.
Real seven worker role names from deploy/cli/cb_resources.py:31:39.
CPU-descending component table, global ordering with all services and workers:
API                        0.18 420MiB 0       0       active
PostgreSQL                 0.17 520MiB 112KiB  960KiB  active
worker: telemetry          0.10 160MiB 8KiB    96KiB   active
worker: discovery          0.07 140MiB 4KiB    64KiB   active
worker: monitor_poll       0.05 110MiB 2KiB    48KiB   active
worker: integration        0.04 100MiB 2KiB    32KiB   active
worker: monitor_probe_dispatch 0.03 80MiB 0    8KiB    active
Redis                      0.02 120MiB 0       0       active
NATS                       0.02 80MiB  0       13KiB   active
worker: monitor_scheduler  0.01 50MiB  0       4KiB    active
worker: notification       0.01 40MiB  0       4KiB    active
PgBouncer                  0.01 32MiB  0       0       active
Helper                     0.01 32MiB  0       0       active
Seven worker rows sum to 0.31 cores,680MiB,16KiB/s read,256KiB/s write.
All components sum0.72cores,1884MiB (~1.84GiB). Do not include Workers aggregate
as another component row when expanded. A compact note may show its subtotal
explicitly as explanatory only. Keep same limits/sharing/throttling notices:
slice1.30/3GiB with PG/helper outside; shared nginx0.03cores/46MiB excluded;
telemetry throttled18%ofperiods. Highlight telemetry worker label using danger
color without replacing active service state with a fake failed state.
Use CPU cores,Memory,Read/s,Write/s,State columns, aligned, no clipped worker names.
Footer [q]quit [c]CPU [m]memory [e]collapse workers [j/k]scroll.
No invented --expand CLI flag; expansion is existing e watch control.
Keep all content readable, reduce empty margins before reducing legibility.
