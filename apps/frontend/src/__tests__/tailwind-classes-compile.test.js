// @vitest-environment node
/**
 * Every `tw-` class the app uses must compile to CSS.
 *
 * Tailwind drops a class it cannot generate without a word, so a typo is not
 * an error — the element just loses that style. That is how the map's menus
 * and create-node dialog went unstyled: the content globs stopped covering
 * src/features/ (so nothing there compiled), variants were written with the
 * prefix in the wrong place (`tw-hover:tw-x` instead of `hover:tw-x`),
 * opacity modifiers were used on `var()` colours Tailwind could not split, and
 * two colour names did not exist in the config.
 *
 * This compiles the real config over the real sources and fails on any class
 * with no rule, naming the class and the file it is in.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';
import tailwindcss from 'tailwindcss';
import { describe, expect, it } from 'vitest';
import config from '../../tailwind.config.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, '../..');
const src = path.join(frontend, 'src');

// Marker classes: they exist for their descendants' variants and emit nothing.
const MARKERS = new Set(['tw-group', 'tw-peer']);

function sourceFiles(dir) {
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- walks this repo's src/
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(full);
    return /\.(js|jsx)$/.test(entry.name) ? [full] : [];
  });
}

// eslint-disable-next-line security/detect-unsafe-regex -- bounded input: the repo's own source files
const CLASS = /(?<![\w-])((?:[a-z-]+:)*-?tw-[\w./[\]%#(),:-]+)/g;
const escape = (name) => name.replace(/([^a-zA-Z0-9_-])/g, '\\$1');

describe('Tailwind classes', () => {
  it('every tw- class used in src compiles to a CSS rule', async () => {
    const result = await postcss([
      tailwindcss({ ...config, content: [`${src}/**/*.{js,jsx}`, `!${src}/__tests__/**`] }),
    ]).process('@tailwind utilities;', { from: undefined });
    const css = result.css;

    const unresolved = new Map();
    for (const file of sourceFiles(src)) {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- a path sourceFiles() found
      const text = fs.readFileSync(file, 'utf8');
      for (const [, raw] of text.matchAll(CLASS)) {
        const name = raw.replace(/[:,.]+$/, '');
        if (name.endsWith('-') || MARKERS.has(name)) continue;
        if (!css.includes(`.${escape(name)}`)) {
          const files = unresolved.get(name) ?? new Set();
          files.add(path.relative(src, file));
          unresolved.set(name, files);
        }
      }
    }

    const report = [...unresolved].map(([name, files]) => `${name}  (${[...files].join(', ')})`);
    expect(
      report,
      'classes that generate no CSS — check the variant order and colour names'
    ).toEqual([]);
  }, 60_000);
});
