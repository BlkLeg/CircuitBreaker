/**
 * Font catalogue for Circuit Breaker UI font controls.
 *
 * Every family here is self-hosted — the faces are declared in
 * `styles/fonts.css` and served from /fonts — so an entry is just a name and a
 * CSS stack. Entries used to carry a `googleUrl` that three different call
 * sites injected as a <link>, which made the UI's typography depend on
 * reaching fonts.googleapis.com. Adding a family means adding its woff2 files
 * and an @font-face block, not a URL: see scripts/fetch-ui-fonts.py.
 */
export const FONT_OPTIONS = [
  {
    id: 'inter',
    label: 'Inter',
    stack: "'Inter', system-ui, sans-serif",
  },
  {
    id: 'system',
    label: 'System Default',
    stack: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  {
    id: 'jetbrains',
    label: 'JetBrains Mono',
    stack: "'JetBrains Mono', 'Fira Code', monospace",
  },
  {
    id: 'fira',
    label: 'Fira Sans',
    stack: "'Fira Sans', sans-serif",
  },
  {
    id: 'ibm-plex',
    label: 'IBM Plex Sans',
    stack: "'IBM Plex Sans', system-ui, sans-serif",
  },
  {
    id: 'nunito',
    label: 'Nunito',
    stack: "'Nunito', system-ui, sans-serif",
  },
  {
    id: 'roboto',
    label: 'Roboto',
    stack: "'Roboto', system-ui, sans-serif",
  },
  {
    id: 'mono',
    label: 'Source Code Pro',
    stack: "'Source Code Pro', 'Courier New', monospace",
  },
];

export const FONT_SIZE_OPTIONS = [
  { id: 'x-small', label: 'XS', rootPx: 11 },
  { id: 'small', label: 'S', rootPx: 13 },
  { id: 'medium', label: 'M', rootPx: 16 },
  { id: 'large', label: 'L', rootPx: 19 },
  { id: 'x-large', label: 'XL', rootPx: 22 },
];
