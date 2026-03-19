import React from 'react';
import PropTypes from 'prop-types';

const S = {
  section: {
    marginBottom: 32,
    padding: '24px',
    borderRadius: 12,
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.15)',
  },
  title: {
    fontSize: 14,
    fontWeight: 700,
    letterSpacing: '0.05em',
    textTransform: 'uppercase',
    color: 'var(--color-primary)',
    marginBottom: 20,
    paddingBottom: 10,
    borderBottom: '1px solid var(--color-border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  description: {
    fontSize: 13,
    color: 'var(--color-text-muted)',
    marginBottom: 24,
    lineHeight: 1.6,
  },
};

export default function SettingSection({
  title = null,
  description = null,
  children = null,
  action = null,
  className = '',
}) {
  const sectionClassName = className ? `setting-section ${className}` : 'setting-section';

  return (
    <section className={sectionClassName} style={S.section}>
      {title && (
        <div style={S.title}>
          {title}
          {action && <div>{action}</div>}
        </div>
      )}
      {description && <p style={S.description}>{description}</p>}
      <div>{children}</div>
    </section>
  );
}

SettingSection.propTypes = {
  title: PropTypes.node,
  description: PropTypes.node,
  children: PropTypes.node,
  action: PropTypes.node,
  className: PropTypes.string,
};
