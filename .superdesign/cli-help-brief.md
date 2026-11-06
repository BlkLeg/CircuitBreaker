# cb — command overview preview
Requested: show output of `cb` with no arguments, in the new 0.4.7 design.
A compact, polished one-column terminal help screen using the existing terminal
palette, orange section headings, purple command names, muted descriptions, and
monospace aligned columns. No full installer mascot; help should be usable in a
normal terminal. Keep all commands from native cb plus proposed npm lifecycle.
Data is illustrative and command additions are proposed, not implemented.

$ cb
Circuit Breaker 0.4.7
CLI 0.4.7 · Server 0.4.7 · native / linux-amd64
Usage: cb <command> [options]

OBSERVE
 info             Install identity, paths and endpoint
 status           Service and container state
 resources        App resource usage; --watch for live view
 logs             Application logs; -f to follow
 doctor           Health checks and diagnosis
 diag bundle      Write a redacted support archive

LIFECYCLE
 install          Install a verified release
 update           Update server; --check only checks
 downgrade        Select an older compatible release
 rollback         Restore a recorded recovery point
 recover          Recover an interrupted operation
 history          Operations and recovery points
 restart          Restart app services
 uninstall        Remove software; data choice is explicit

DATA & SETUP
 backup           Full-state snapshot; encryption available
 restore          Restore a snapshot; replaces data
 setup            First-run setup status
 setup-token      Print one-time token; keep out of logs
 config validate  Validate configuration
 migrate status   Show database schema revision
 migrate upgrade  Apply pending migrations
 vault-recover    Recover an uninitialized vault

ACCESS & FLEET
 token            Create, list, rotate and revoke API tokens
 user             Manage local accounts and roles
 agent            List, approve and revoke agents

CLI
 cli update       Update npm CLI only
 version          CLI and installed server versions
 help             Show command help

More: cb <command> --help
Try: cb resources --watch · cb update --check
No blanket claim of global --json support; command-specific help exposes flags.
Help reads only install identity, no network checks, no token print or mutation.
Sample data · proposed 0.4.7 commands outside terminal.
Fit readable full overview on one screen with compact margins; no two-column
marketing layout, browser UI controls, or extra graphics.
