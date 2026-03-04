import { useEffect } from 'react';
import { FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../lib/fonts';

/**
 * Applies the user's chosen font family and base font size to the document
 * via CSS custom properties.  Injects a Google Fonts <link> when needed and
 * removes it when the user switches to a font that doesn't require one.
 *
 * Wired in SettingsContext so it re-runs whenever settings.ui_font or
 * settings.ui_font_size changes.
 */
export function useAppFont(fontId, fontSizeId) {
  useEffect(() => {
    const font = FONT_OPTIONS.find((f) => f.id === fontId) ?? FONT_OPTIONS.find((f) => f.id === 'inter') ?? FONT_OPTIONS[0];
    const size = FONT_SIZE_OPTIONS.find((s) => s.id === fontSizeId) ?? FONT_SIZE_OPTIONS.find((s) => s.id === 'medium') ?? FONT_SIZE_OPTIONS[0];

    // Inject or update Google Fonts <link> for hosted fonts; remove it for system fonts
    const existingLink = document.getElementById('cb-font-link');
    if (font.googleUrl) {
      const link = existingLink ?? document.createElement('link');
      link.id = 'cb-font-link';
      link.rel = 'stylesheet';
      link.href = font.googleUrl;
      if (!existingLink) document.head.appendChild(link);
      else link.href = font.googleUrl;
    } else {
      existingLink?.remove();
    }

    // Apply CSS custom properties — body uses var(--font), html uses var(--font-size-base)
    document.documentElement.style.setProperty('--font', font.stack);
    document.documentElement.style.setProperty('--font-size-base', `${size.rootPx}px`);
    document.documentElement.style.fontSize = `${size.rootPx}px`;
  }, [fontId, fontSizeId]);
}
