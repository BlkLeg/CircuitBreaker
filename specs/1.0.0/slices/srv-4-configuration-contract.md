# SRV-4 — Configuration Contract

**Requirement:** SRV-05
**Depends on:** SRV-1

## Primary files

- `apps/backend/src/app/core/config.py`, `config_toml.py`, settings models/services
- `packaging/config.toml.default`, deploy env/templates and setup scripts
- `deploy/cli/cb`, installation configuration documentation

## Build sequence

1. Generate an inventory of setting name, type, default, secret status, valid range, sources,
   restart/reload need, and owning process. Resolve aliases such as historical pool names explicitly.
2. Define precedence across CLI, environment, file, database, and defaults, including empty values and
   secret indirection. Reject conflicting or process-inapplicable options.
3. Implement one typed loader/validation path shared by API, workers, CLI, installer preflight, and
   diagnostics. Do not duplicate parsing in shell templates.
4. Add `cb config validate` with human and JSON output, source attribution, warnings/errors, and
   fully redacted effective configuration.
5. Validate checked-in samples and test every source, precedence conflict, invalid bound, missing
   secret, unknown key, and upgrade alias.

## Verification and rollout

Run config unit/contract tests, installer dry runs, and headless artifact smoke. Introduce strict
unknown-key failure with an upgrade preflight and compatibility aliases where justified. Done means
all processes interpret the same configuration identically and diagnostics cannot leak secrets.
