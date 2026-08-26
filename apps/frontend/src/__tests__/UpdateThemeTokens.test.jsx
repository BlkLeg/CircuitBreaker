/* eslint-disable security/detect-non-literal-fs-filename -- reads its own repo tree: paths are built from __dirname and this file's own literals, never from input */
/**
 * The one contrast failure jsdom CAN catch: a component referencing a CSS
 * custom property that is defined nowhere.
 *
 * UpdateBanner used `var(--color-info-bg, #1e3a5f)` and UpdateStatusPanel used
 * `var(--color-bg-subtle, #111827)`. Neither variable is defined anywhere in
 * src/styles or set by theme/applyTheme.js, so both ALWAYS resolved to their
 * hardcoded dark-navy fallback. Each paired that with `var(--color-text)`,
 * which IS defined and IS re-set per theme at runtime -- so under any light
 * preset the result was near-black text on a near-black bar. 826 jsdom tests
 * passed the whole time, because jsdom does not render and cannot measure
 * contrast. It can, however, tell that a token has no definition.
 *
 * This test asserts a weaker but checkable property: every `var(--token)` these
 * two components reference is actually defined -- either statically in
 * src/styles/*.css, or at runtime by applyTheme's setProperty calls. A token
 * that is defined in both places is theme-tracked, which is what keeps a
 * background and its foreground a designed pair rather than an accident.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, '..');

const COMPONENTS = {
  UpdateBanner: path.join(SRC, 'components/UpdateBanner.jsx'),
  UpdateStatusPanel: path.join(SRC, 'components/settings/UpdateStatusPanel.jsx'),
};

function referencedTokens(file) {
  const source = fs.readFileSync(file, 'utf8');
  // Ignore the explanatory comments, which name the old broken tokens.
  const code = source.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  return new Set([...code.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]));
}

function staticallyDefinedTokens() {
  const dir = path.join(SRC, 'styles');
  const defined = new Set();
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith('.css')) continue;
    const css = fs.readFileSync(path.join(dir, name), 'utf8');
    for (const m of css.matchAll(/(--[\w-]+)\s*:/g)) defined.add(m[1]);
  }
  return defined;
}

function runtimeDefinedTokens() {
  const js = fs.readFileSync(path.join(SRC, 'theme/applyTheme.js'), 'utf8');
  return new Set([...js.matchAll(/setProperty\(\s*['"](--[\w-]+)['"]/g)].map((m) => m[1]));
}

const STATIC = staticallyDefinedTokens();
const RUNTIME = runtimeDefinedTokens();

describe('the update surfaces only reference CSS variables that exist', () => {
  test('the token scanner finds the known-good tokens (self-check)', () => {
    // Guards against a scanner that silently matches nothing and passes.
    expect(STATIC.has('--color-text')).toBe(true);
    expect(STATIC.has('--color-surface')).toBe(true);
    expect(RUNTIME.has('--color-text')).toBe(true);
    expect(STATIC.has('--color-info-bg')).toBe(false);
    expect(STATIC.has('--color-bg-subtle')).toBe(false);
    expect(RUNTIME.has('--color-info-bg')).toBe(false);
    expect(RUNTIME.has('--color-bg-subtle')).toBe(false);
  });

  for (const [name, file] of Object.entries(COMPONENTS)) {
    test(`${name} references no undefined token`, () => {
      const undefinedTokens = [...referencedTokens(file)].filter(
        (token) => !STATIC.has(token) && !RUNTIME.has(token)
      );
      expect(undefinedTokens).toEqual([]);
    });
  }

  test('the banner draws its background and its text from the same theme pair', () => {
    const source = fs.readFileSync(COMPONENTS.UpdateBanner, 'utf8');
    expect(source).toContain("background: 'var(--color-surface)'");
    expect(source).toContain("color: 'var(--color-text)'");
    // Both must be theme-tracked. A theme-tracked foreground over a static
    // background is exactly the failure this file documents.
    for (const token of ['--color-surface', '--color-text']) {
      expect(RUNTIME.has(token), `${token} must be re-set per theme`).toBe(true);
      expect(STATIC.has(token), `${token} needs a :root default`).toBe(true);
    }
  });

  test("the panel's upgrade command block is theme-tracked too", () => {
    const source = fs.readFileSync(COMPONENTS.UpdateStatusPanel, 'utf8');
    expect(source).toContain("background: 'var(--color-secondary)'");
    expect(source).toContain("color: 'var(--color-text)'");
    for (const token of ['--color-secondary', '--color-text']) {
      expect(RUNTIME.has(token)).toBe(true);
      expect(STATIC.has(token)).toBe(true);
    }
  });
});

describe('the banner survives a narrow viewport', () => {
  test('it wraps and lets the upgrade command shrink', () => {
    const source = fs.readFileSync(COMPONENTS.UpdateBanner, 'utf8');
    // The docker upgrade_command is ~70 characters. A single-line flex with no
    // wrap and no minWidth:0 on the <code> pushes .page-content into
    // horizontal scroll at its mobile breakpoints.
    expect(source).toContain("flexWrap: 'wrap'");
    expect(source).toContain('minWidth: 0');
  });
});
