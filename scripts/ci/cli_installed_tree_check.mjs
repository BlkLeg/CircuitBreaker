// NPM-10 on the tree a user actually gets, for the packed-CLI smoke.
//
// Usage: node cli_installed_tree_check.mjs <installed package dir>
// Checks the dependency tree npm installed under the package against the
// npm-shrinkwrap.json the package shipped: every locked package present at its
// locked version, nothing installed that the lock does not list, and no
// installed package declaring preinstall, install or postinstall. Exits 1 with
// one line per problem.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = process.argv[2];
if (!root) {
  console.error('usage: cli_installed_tree_check.mjs <installed package dir>');
  process.exit(2);
}
const INSTALL_HOOKS = ['preinstall', 'install', 'postinstall'];
const lock = JSON.parse(readFileSync(join(root, 'npm-shrinkwrap.json'), 'utf8'));
const locked = Object.entries(lock.packages).filter(([path]) => path !== '');
const problems = [];

// Package roots under a node_modules tree, nested trees included:
// node_modules/<name> and node_modules/@scope/<name>.
function packageRoots(modules) {
  if (!existsSync(modules)) return [];
  const roots = [];
  for (const entry of readdirSync(modules, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    const dirs = entry.name.startsWith('@')
      ? readdirSync(join(modules, entry.name), { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => join(modules, entry.name, d.name))
      : [join(modules, entry.name)];
    for (const dir of dirs) roots.push(dir, ...packageRoots(join(dir, 'node_modules')));
  }
  return roots;
}

for (const [path, entry] of locked) {
  const manifest = join(root, path, 'package.json');
  if (!existsSync(manifest)) { problems.push(`${path}: locked at ${entry.version} but not installed`); continue; }
  const { version } = JSON.parse(readFileSync(manifest, 'utf8'));
  if (version !== entry.version) problems.push(`${path}: installed ${version}, locked ${entry.version}`);
}
const lockedPaths = new Set(locked.map(([path]) => path));
const installed = packageRoots(join(root, 'node_modules'));
for (const dir of installed) {
  const path = relative(root, dir);
  if (!lockedPaths.has(path)) problems.push(`${path}: installed but not in npm-shrinkwrap.json`);
  const { scripts = {} } = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
  const hooks = INSTALL_HOOKS.filter((hook) => hook in scripts);
  if (hooks.length) problems.push(`${path}: declares ${hooks.join(', ')} (NPM-10)`);
}
if (!installed.some((dir) => relative(root, dir) === join('node_modules', 'sigstore'))) problems.push('node_modules/sigstore: not installed');

if (problems.length) {
  for (const problem of problems) console.error(problem);
  process.exit(1);
}
console.log(`installed tree matches npm-shrinkwrap.json: ${installed.length} packages, no install scripts`);
