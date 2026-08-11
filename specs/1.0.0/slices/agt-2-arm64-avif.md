# AGT-2 — ARM64 AVIF Release Defect

**Requirement:** AGT-10
**Priority:** P0
**Issue:** #101

## Primary files

- `scripts/build_native_release.py`, `.github/workflows/release.yml`
- Python/Pillow dependency manifests and native package definitions
- `packaging/`, `deploy/systemd/`, image upload/processing services and tests

## Build sequence

1. Install the exact current ARM64 package on a clean Raspberry Pi 5-class host; retain package
   digest, architecture, OS image, journal, loader output, and PyInstaller extraction diagnostics.
2. Trace whether `_avif` is imported directly, through Pillow feature discovery, or a hidden import.
   Decide from the support contract whether AVIF must work or must be excluded cleanly.
3. For supported AVIF, pin/build a compatible wheel/native library and add a real decode/encode smoke.
   For unsupported AVIF, exclude the extension and return an explicit unsupported-format response.
4. Update PyInstaller hidden-import/exclusion configuration deterministically. Prove x86_64 parity.
5. Add an ARM64 artifact job that installs, starts every service, exercises supported image handling,
   restarts repeatedly, and uploads journal/build diagnostics on failure.

## Verification and rollback

Run backend image tests from source, then the packaged ARM64 service test; source import success is
not sufficient. Rollback reverts the dependency/build change and package together. Do not ship a
package that starts only because image processing was silently disabled.

## Definition of done

The signed ARM64 candidate repeatedly starts and processes every documented image format without
`_avif` loader failure; package contents and diagnostics prove the tested binary is the published one.
