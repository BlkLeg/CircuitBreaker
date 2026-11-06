#!/usr/bin/env node
import { unsupportedRuntime } from '../src/runtime.js';
import { EXIT } from '../src/exit-codes.js';
import { spawnSync } from 'node:child_process';
import { proxyReexec } from '../src/proxy.js';

const problem = unsupportedRuntime();
if (problem) {
  process.stderr.write(`circuitbreaker: ${problem}\n`);
  process.exit(EXIT.UNSUPPORTED);
}

const reexec = proxyReexec(process.env, process.execPath, process.argv);
if (reexec) {
  const child = spawnSync(reexec.command, reexec.args, { stdio: 'inherit', env: reexec.env });
  process.exit(child.status ?? 128 + (child.signal ? 15 : 1));
}

// Imported only after the runtime check so nothing newer than the floor is parsed first.
const { run } = await import('../src/main.js');
process.exitCode = await run(process.argv.slice(2));
