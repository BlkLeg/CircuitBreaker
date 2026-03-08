/**
 * Font catalogue for Circuit Breaker UI font controls.
 * Each entry describes a font family available to the user.
 * googleUrl is null for fonts that don't need a network request.
 */
export const FONT_OPTIONS = [
  {
    id: 'inter',
    label: 'Inter',
    stack: "'Inter', system-ui, sans-serif",
    googleUrl: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap',
  },
  {
    id: 'system',
    label: 'System Default',
    stack: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    googleUrl: null,
  },
  {
    id: 'jetbrains',
    label: 'JetBrains Mono',
    stack: "'JetBrains Mono', 'Fira Code', monospace",
    googleUrl: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap',
  },
  {
    id: 'fira',
    label: 'Fira Sans',
    stack: "'Fira Sans', sans-serif",
    googleUrl: 'https://fonts.googleapis.com/css2?family=Fira+Sans:wght@400;500;600&display=swap',
  },
  {
    id: 'ibm-plex',
    label: 'IBM Plex Sans',
    stack: "'IBM Plex Sans', system-ui, sans-serif",
    googleUrl:
      'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap',
  },
  {
    id: 'nunito',
    label: 'Nunito',
    stack: "'Nunito', system-ui, sans-serif",
    googleUrl: 'https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap',
  },
  {
    id: 'roboto',
    label: 'Roboto',
    stack: "'Roboto', system-ui, sans-serif",
    googleUrl: 'https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap',
  },
  {
    id: 'mono',
    label: 'Source Code Pro',
    stack: "'Source Code Pro', 'Courier New', monospace",
    googleUrl: 'https://fonts.googleapis.com/css2?family=Source+Code+Pro:wght@400;500&display=swap',
  },
];

export const FONT_SIZE_OPTIONS = [
  { id: 'x-small', label: 'XS', rootPx: 11 },
  { id: 'small', label: 'S', rootPx: 13 },
  { id: 'medium', label: 'M', rootPx: 16 },
  { id: 'large', label: 'L', rootPx: 19 },
  { id: 'x-large', label: 'XL', rootPx: 22 },
];
