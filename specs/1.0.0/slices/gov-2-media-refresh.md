# GOV-2 — Screenshot and Media Refresh

**Requirements:** GOV-01, GOV-02, GOV-03, GOV-04
**Depends on:** Stable RC UI for final capture

## Primary touchpoints

- `docs/assets/screenshots/`, README/gallery references, `docs/screenshots.md`
- Browser E2E deterministic fixtures and visual-regression infrastructure

## Build sequence

1. Create a media manifest for all 16 restored assets and new requirements: source version/commit,
   page/state, viewport, fixture, capture command, format/dimensions, alt text, privacy review, owner.
2. Inspect originals at full resolution for names, IP/MAC, hostnames, tokens, email, filesystem paths,
   browser/profile metadata, and obsolete UI. Mark replace, approve, or remove with rationale.
3. Build deterministic anonymized fixture data and capture scripts where practical. Disable animations,
   stabilize fonts/time/network, and never post-process sensitive pixels as the only anonymization.
4. Capture install/OOBE, agent enrollment/fleet, discovery review/import, agent monitor, backup/restore,
   mobile, empty/error/loading, focus/accessibility, architecture, and deployment comparison media.
5. Record a 2–3 minute physical remote-site agent demo proving outbound-only operation; show firewall
   evidence without exposing credentials or real private infrastructure.
6. Optimize assets without destroying legibility, add meaningful alt text/captions, and link-check.

## Verification and done

Two reviewers approve privacy and RC accuracy; automated docs build resolves every target. Done means
all published media has provenance and no historical image is assumed current merely because it exists.
