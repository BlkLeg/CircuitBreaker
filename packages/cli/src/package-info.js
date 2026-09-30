import { readFileSync } from 'node:fs';

const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));

// Lockstep with VERSION (scripts/check_version_parity.py registers package.json).
export const CLI_VERSION = manifest.version;
