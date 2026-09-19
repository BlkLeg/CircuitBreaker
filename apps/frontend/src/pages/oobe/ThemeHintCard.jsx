import React from 'react';
import { Sparkles } from 'lucide-react';
/**
 * The aside beside step 4, explaining that the theme is changeable later.
 *
 * Static markup with no wizard state of its own, so it takes neither props
 * nor the context — it was only ever inline because the page it belonged to
 * had nowhere else to put it.
 */
export default function ThemeHintCard() {
  return (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <Sparkles size={16} className="oobe-hint-icon" />
        <span>Mix &amp; Match</span>
      </div>
      <p className="oobe-hint-body">
        Every theme has both a <strong>dark</strong> and <strong>light</strong> variant. Use the
        toggle above to flip modes as you try presets — your perfect combination is out there.
      </p>
      <ul className="oobe-hint-combos">
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#00f5ff' }} />
          Cyberpunk Neon + Dark — high-contrast night
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#8be9fd' }} />
          Dracula + Light — soft pastel daytime
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#a9dc76' }} />
          Monokai + Dark — warm retro terminal
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: '#b48ead' }} />
          Nord + Light — calm Nordic workspace
        </li>
      </ul>
      <p className="oobe-hint-tip">
        💡 You can change your theme and mode any time from the header or{' '}
        <em>Settings → Appearance</em>.
      </p>
    </div>
  );
}
