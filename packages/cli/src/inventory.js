import { readFileSync } from 'node:fs';

const document = JSON.parse(
  readFileSync(new URL('../schemas/native-commands.json', import.meta.url), 'utf8'),
);

// Every command the native cb dispatches. tests/build/test_cli_package.py fails when
// this list and deploy/cli/cb's dispatcher disagree.
export const NATIVE_COMMANDS = Object.freeze(document.commands.map((c) => Object.freeze({ ...c })));

export function findNativeCommand(name) {
  return NATIVE_COMMANDS.find((c) => c.name === name) ?? null;
}
