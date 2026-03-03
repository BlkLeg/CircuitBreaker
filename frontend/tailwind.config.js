/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/components/discovery/**/*.{js,jsx}'],
  // Restrict Tailwind to discovery bulk-actions components only.
  // This prevents Tailwind's reset/base from affecting existing CSS.
  prefix: 'tw-',
  important: false,
  corePlugins: {
    preflight: false,   // Don't inject Tailwind resets — preserves existing styles
  },
  theme: {
    extend: {
      colors: {
        // Map to CSS custom properties from main.css
        'cb-bg':          'var(--color-bg)',
        'cb-surface':     'var(--color-surface)',
        'cb-secondary':   'var(--color-secondary)',
        'cb-border':      'var(--color-border)',
        'cb-primary':     'var(--color-primary)',
        'cb-primary-h':   'var(--color-primary-hover)',
        'cb-danger':      'var(--color-danger)',
        'cb-text':        'var(--color-text)',
        'cb-muted':       'var(--color-text-muted)',
        'cb-online':      'var(--color-online)',
      },
      fontFamily: {
        cb: 'var(--font)',
      },
      borderRadius: {
        cb: 'var(--radius)',
      },
      backdropBlur: {
        md: '12px',
      },
    },
  },
  plugins: [],
}
