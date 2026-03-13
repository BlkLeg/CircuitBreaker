import React from 'react';
import PropTypes from 'prop-types';

export default function FutureFeatureBanner({
  title = 'Future Feature',
  message = 'This area is actively evolving. Expect rapid enhancements and layout updates in upcoming releases.',
}) {
  return (
    <div
      role="note"
      aria-live="polite"
      style={{
        marginBottom: 12,
        padding: '10px 12px',
        borderRadius: 8,
        border: '1px solid color-mix(in srgb, var(--color-primary) 50%, var(--color-border))',
        background: 'color-mix(in srgb, var(--color-primary) 10%, transparent)',
        color: 'var(--color-text)',
        fontSize: 13,
      }}
    >
      <strong>{title}:</strong> {message}
    </div>
  );
}

FutureFeatureBanner.propTypes = {
  title: PropTypes.string,
  message: PropTypes.string,
};
