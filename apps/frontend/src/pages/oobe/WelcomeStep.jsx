import React from 'react';
import { useOOBE } from './OOBEContext';

/**
 * Step 1 — the welcome panel, and the only step with nothing to fill in.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function WelcomeStep() {
  const { goNext } = useOOBE();

  return (
    <>
      {/* Card title removed - logo and context are sufficient */}
      <p className="login-card-subtitle">
        Let’s create your first admin account and personalize your dashboard.
      </p>
      <div className="oobe-actions">
        <button type="button" className="btn btn-primary login-btn-submit" onClick={goNext}>
          Get Started
        </button>
      </div>
    </>
  );
}
