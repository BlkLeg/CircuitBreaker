// @vitest-environment node
/**
 * Every `tw:` class the app uses must compile to CSS.
 *
 * Tailwind drops a class it cannot generate without a word, so a typo is not
 * an error — the element just loses that style. That is how the map's menus
 * and create-node dialog went unstyled: the content globs stopped covering
 * src/features/ (so nothing there compiled), variants were written with the
 * prefix in the wrong place, opacity modifiers were used on `var()` colours
 * Tailwind 3 could not split, and two colour names did not exist in the theme.
 * A class left in Tailwind 3's `tw-x` form fails the same way: under
 * Tailwind 4 the prefix is a variant, `tw:x`, and comes first (`tw:hover:x`).
 *
 * This compiles the real stylesheet (src/styles/tailwind.css, which holds the
 * theme) over the real sources and fails on any class with no rule, naming
 * the class and the file it is in.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';
import tailwindcss from '@tailwindcss/postcss';
import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, '../..');
const src = path.join(frontend, 'src');
const stylesheet = path.join(src, 'styles', 'tailwind.css');

// Marker classes: they exist for their descendants' variants and emit nothing.
const MARKERS = new Set(['tw:group', 'tw:peer']);

function sourceFiles(dir) {
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- walks this repo's src/
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(full);
    return /\.(js|jsx)$/.test(entry.name) ? [full] : [];
  });
}

const CLASS = /(?<![\w-])(tw:[\w./[\]%#(),:-]+)/g;
// Tailwind 3's form, which Tailwind 4 silently ignores.
// eslint-disable-next-line security/detect-unsafe-regex -- bounded input: the repo's own source files
const LEGACY_CLASS = /(?<![\w-])((?:[a-z-]+:)*-?tw-[a-z[][\w./[\]%#(),:-]*)/g;
const escape = (name) => name.replace(/([^a-zA-Z0-9_-])/g, '\\$1');

describe('Tailwind classes', () => {
  it('every tw: class used in src compiles to a CSS rule', async () => {
    const input = fs.readFileSync(stylesheet, 'utf8');
    const result = await postcss([tailwindcss()]).process(input, { from: stylesheet });
    const css = result.css;

    const unresolved = new Map();
    for (const file of sourceFiles(src)) {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- a path sourceFiles() found
      const text = fs.readFileSync(file, 'utf8');
      for (const [, raw] of text.matchAll(CLASS)) {
        const name = raw.replace(/[:,.]+$/, '');
        if (name.endsWith('-') || name.endsWith(':') || MARKERS.has(name)) continue;
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
    expect(css.length, 'the stylesheet compiled to almost nothing').toBeGreaterThan(2000);
  }, 60_000);

  // The check above compiles the stylesheet directly. The app is built by Vite,
  // which inlines @import before PostCSS plugins run and drops the prefix(tw)
  // and source(none) options: wired through PostCSS, the build succeeded and
  // shipped no tw: utility at all. Only Tailwind's Vite plugin handles them.
  it('the build compiles Tailwind through its Vite plugin, not PostCSS', () => {
    const viteConfig = fs.readFileSync(path.join(frontend, 'vite.config.ts'), 'utf8');
    expect(viteConfig).toMatch(/from '@tailwindcss\/vite'/);
    expect(viteConfig).toMatch(/\btailwindcss\(\)/);
    for (const name of ['postcss.config.mjs', 'postcss.config.js', 'postcss.config.cjs']) {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- fixed names in this repo
      expect(
        fs.existsSync(path.join(frontend, name)),
        `${name} would route Tailwind through PostCSS`
      ).toBe(false);
    }
  });

  it('no class is left in the Tailwind 3 tw- form', () => {
    const legacy = [];
    for (const file of sourceFiles(src)) {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- a path sourceFiles() found
      const text = fs.readFileSync(file, 'utf8');
      for (const [, raw] of text.matchAll(LEGACY_CLASS))
        legacy.push(`${raw}  (${path.relative(src, file)})`);
    }
    expect(legacy, 'write these as tw:variant:utility').toEqual([]);
  });
});
