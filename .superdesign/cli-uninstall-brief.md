# Uninstall process preview — native 0.4.7
Companion to the approved terminal direction, using same palette/fonts/spacing.
One terminal screenshot with a completed, cumulative transcript of the process.
Keep original ASCII art intact at the top as a lifecycle heading, fitting artwork
and transcript together in the viewport. No new mascot. All values are examples.

Command: $ cb uninstall
Heading: UNINSTALL · native / linux-amd64 · v0.4.7
Plan before changing anything:
  Remove  application files, app services, app nginx site
  Keep    /var/lib/circuitbreaker (database, uploads, backups)
  Keep    /etc/circuitbreaker (configuration and vault key)
  Keep    shared nginx and system dependencies
Data choice: Keep configuration and data [default]
Proceed with software removal? [y/N] y

Completed phase ledger, each phase own duration:
✓ Preflight and removal plan       0.4s
✓ Stop app services                2.1s
✓ Remove app files and units       1.2s
✓ Verify removal and retained data 0.3s

Result:
Software removed · configuration and data retained
Application endpoint stopped. Shared nginx remains installed.
Retained: /etc/circuitbreaker · /var/lib/circuitbreaker
npm CLI remains installed; npm package removal is separate.
Log: /var/log/circuitbreaker/uninstall.log

This is the KEEP DATA path. Purge is a separate explicit choice before service stop
and must identify irreversible database, upload and vault-key deletion. A generic
--yes never opts into data deletion. Do not render a false recovery guarantee,
no restore command after purge, and no artificial percentage for unknown steps.
Sample data · design preview appears outside terminal.
