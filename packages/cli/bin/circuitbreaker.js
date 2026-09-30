#!/usr/bin/env node
import { unsupportedRuntime } from '../src/runtime.js';
import { EXIT } from '../src/exit-codes.js';

const problem = unsupportedRuntime();
if (problem) {
  process.stderr.write(`circuitbreaker: ${problem}\n`);
  process.exit(EXIT.UNSUPPORTED);
}

// Imported only after the runtime check so nothing newer than the floor is parsed first.
const { run } = await import('../src/main.js');
process.exitCode = await run(process.argv.slice(2));
