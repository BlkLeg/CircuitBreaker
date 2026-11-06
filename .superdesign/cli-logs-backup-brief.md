# cb logs and backup — companion previews
Same existing terminal style: monospace, orange headings, purple active accents,
muted timestamps/metadata, readable labels for levels/status. No installer artwork
for routine commands. Sample messages and sizes, not actual logs or backup files.

## Logs — append-only follow stream
$ cb logs -f
Circuit Breaker 0.4.7  LOGS  native / linux-amd64
Following native journal · last 100 lines · circuitbreaker-*
Local time (America/Phoenix) · Ctrl-C stops following

TIME          LEVEL  COMPONENT                 MESSAGE
13:32:01.124   INFO   backend                   Startup complete
13:32:02.201   INFO   worker: discovery          Scan queued: homelab
13:32:02.842   INFO   worker: monitor_poll       Probe complete: gateway.local up
13:32:03.109   WARN   storage                   Data filesystem: 512 MiB free
13:32:03.110   WARN   storage                   Minimum free space: 1 GiB
13:32:03.481   INFO   worker: telemetry          Host sample received
13:32:04.005   ERROR  worker: integration        Proxmox sync timed out
                                           Retry scheduled in 30s (attempt 1/3)
13:32:04.212   INFO   worker: notification       Alert queued: low disk space
13:32:05.006   INFO   backend                   GET /api/v1/readyz 200
13:32:05.820   INFO   worker: monitor_scheduler  12 monitors dispatched

Following… [small restrained purple activity marker]
No made-up q/pause/filter keys or CLI flags; only Ctrl-C. Log lines append and
remain in scrollback; don't clear/redraw the log history. The continuation message
stays associated with its error. On a narrow terminal wrap message continuation,
not metadata columns. Printed severity words, not color alone. Use danger for
ERROR, orange for WARN, muted INFO; do not make routine info a warning color.
There are no actual credentials in the sample. Structured formatting/redaction
is proposed for interactive 0.4.7 output; preserving source order and original
unstructured lines is required. Plain redirected output keeps its stream contract.
Sample data · design preview outside terminal.

## Backup — completed process transcript
$ cb backup
Circuit Breaker 0.4.7  BACKUP  native / linux-amd64
Full-state snapshot · local copy · online
Includes database, uploads, native config, and vault key

✓ Preflight: permissions and free space       0.2s
✓ Stream database dump                       3.8s
✓ Capture uploads, config and vault key      0.6s
✓ Write manifest and pack archive            4.1s
✓ Verify structure and database checksum     1.1s
✓ Publish protected snapshot                 0.1s

BACKUP SAVED
cb-snapshot-20260930-203200.tar.gz
/var/lib/circuitbreaker/backups/cb-snapshot-20260930-203200.tar.gz
Size 186.4 MiB · Duration 9.9s · Mode 0600
Snapshot verified; restore rehearsal has not been performed.

LOCAL COPY
Contains the vault key in plaintext. Keep this archive private.
Off-host copy: cb backup --encrypt-to <age-recipient>
Encryption creates an additional .age file; local plaintext remains.

RESTORE
cb restore /var/lib/circuitbreaker/backups/cb-snapshot-20260930-203200.tar.gz
Restore replaces current data and requires confirmation.

Don't imply a release-code rollback bundle: this is application state, not server
binaries. Don't show a completed backup with a still-running phase, fake percent
or retry/confidence claims. No actual dump is taken for this design task.
The full-state native adapter, richer events and post-build verification are
proposed 0.4.7 work. Current cmd_backup has docker/compose and package/binary
branches; native support must be wired to the same builder before claiming it
ships. Preserve the builder's checksum/manifest and atomic/0600 output contract.
Sample data · proposed 0.4.7 flow outside terminal.
