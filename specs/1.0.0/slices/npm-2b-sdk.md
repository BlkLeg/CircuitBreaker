# NPM-2B — API Client/SDK

**Requirement:** NPM-04
**Run only if:** NPM-1 selects the SDK

## Build sequence

1. Define supported server API versions, Node/browser runtimes, module formats, authentication models,
   pagination/streaming, error/retry/timeout/cancellation semantics, and SDK semver policy.
2. Generate types/client primitives from the accepted OpenAPI contract where possible. Keep a reviewed
   customization layer; fail generation drift in CI.
3. Prevent secret-bearing server tokens from unsafe browser use; document CORS/CSRF/session versus API
   token constraints and default no retry for non-idempotent actions.
4. Export a minimal typed surface with source maps only if intentional and no internal server code.
5. Test compile/runtime against each supported server version, ESM/CJS policy, Node versions, browser
   bundling if claimed, network errors, cancellation, pagination, streams, and machine errors.
6. Publish migration notes for breaking SDK/API changes and reject incompatible server versions clearly.

## Verification and done

Contract tests run against real supported server artifacts, not only mocked HTTP. Done means declarations,
runtime, exports, docs, and compatibility table agree and the SDK has independent release ownership.
