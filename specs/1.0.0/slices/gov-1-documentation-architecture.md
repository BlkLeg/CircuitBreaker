# GOV-1 — Documentation Information Architecture

**Requirements:** GOV-05, GOV-06, GOV-07, GOV-08
**Depends on:** RC support/deployment decisions

## Primary touchpoints

- `README.md`, `mkdocs.yml`, `docs/index.md`, `docs/installation/`
- Feature/operations/security docs, `docs/updates/`, generated OpenAPI/CLI/config references
- Generated `site/` tree and docs build workflow

## Build sequence

1. Inventory every page, inbound/outbound link, navigation entry, duplicate topic, stale release claim,
   missing owner, and generated/source status. Record canonical replacement before moving content.
2. Design task-oriented navigation: evaluate/install, configure/secure, operate/recover, agents and
   features, API/CLI reference, upgrade/compatibility, troubleshoot, contribute/security/release.
3. Consolidate native, mono, split, source, and Proxmox installation names into one decision table with
   support tier, prerequisites, ports, TLS, state, scaling, backup, update, and uninstall.
4. Publish RC-derived platform/browser support, sizing, data paths, backup/rollback, agent security,
   configuration precedence/catalog/examples, threat/privacy/update policies, migration and compatibility.
5. Generate OpenAPI/CLI/config references from production contracts; execute code/command examples in CI.
6. Add Markdown link/image, MkDocs strict build, orphan/nav, duplicate slug, and stale generated-output checks.
7. Remove tracked `site/` or document an atomic reproducible deployment that proves it is required.

## Verification and done

Build docs from a clean checkout with warnings treated as failures, run link/media checks, and conduct
new-user install plus operator recovery walkthroughs. Done means each task has one authoritative page,
all claims match RC-01/RC-02, and generated references cannot drift silently.
