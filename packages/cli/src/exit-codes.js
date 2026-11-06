// Exit codes for failures the CLI itself decides. Forwarded native commands keep
// their own codes; these never overwrite a child's status. Values are the
// design's lifecycle table (docs/design/2026-09-30-v0.4.7-npm-cli-design.md).
export const EXIT = Object.freeze({
  OK: 0,
  USAGE: 2,
  UNSUPPORTED: 3,
  NETWORK: 4,
  TRUST: 5,
  PERMISSION: 6,
  PREFLIGHT: 7,
  RECOVERED: 8,
  MANUAL: 9,
  LOCKED: 10,
  INTERRUPTED: 130,
});
