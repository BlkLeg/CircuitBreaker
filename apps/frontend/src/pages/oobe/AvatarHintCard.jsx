import React from 'react';
import { UserCircle2 } from 'lucide-react';
/**
 * The aside beside step 3, explaining where the avatar comes from.
 *
 * Static markup with no wizard state of its own, so it takes neither props
 * nor the context — it was only ever inline because the page it belonged to
 * had nowhere else to put it.
 */
export default function AvatarHintCard() {
  return (
    <div className="oobe-hint-card">
      <div className="oobe-hint-header">
        <UserCircle2 size={16} className="oobe-hint-icon" />
        <span>Profile Photo</span>
      </div>
      <p className="oobe-hint-body">
        Your avatar is pulled automatically from <strong>Gravatar</strong> using your email address
        — no upload needed.
      </p>
      <ul className="oobe-hint-combos">
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-primary)' }} />
          Type your email and the preview updates live
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-text-muted)' }} />
          No Gravatar? Click the photo to upload your own JPEG or PNG
        </li>
        <li>
          <span className="oobe-hint-swatch" style={{ background: 'var(--color-online)' }} />
          Custom upload always takes priority over Gravatar
        </li>
      </ul>
      <p className="oobe-hint-tip">
        💡 You can update your photo any time from your profile in the header. Max size: 10 MB.
      </p>
    </div>
  );
}
