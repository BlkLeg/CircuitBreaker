# NPM-1 — npm Product and Namespace Decision

**Requirements:** NPM-01, NPM-02
**Depends on:** RC scope and API stability

## Objective

Choose exactly one coherent npm product—administration/installer CLI or API SDK—and isolate it from
the private application-repository root package.

## Build sequence

1. Document user jobs, alternatives, maintenance/security burden, platform needs, offline/proxy use,
   support ownership, and relationship to native/container artifacts for CLI and SDK options.
2. For CLI, define commands and explicit artifact download/install boundary. For SDK, define public API
   stability, generated contract, runtime targets, and separate semantic versioning.
3. Choose scoped name and verify registry, trademark/project identity, repository mapping, and recovery
   ownership before announcing it.
4. Define a dedicated workspace/package directory with independent manifest, lock/build/test/release.
   Keep root `private: true` and add a CI assertion that root packing/publishing is rejected.
5. Record the decision/rejected alternative in an ADR and update RC-01 scope.

## Verification and done

Review with product, API, packaging, security, and support owners. Done means one purpose/name/support
matrix is approved, namespace control is verified, and no hybrid or root publication path remains.
