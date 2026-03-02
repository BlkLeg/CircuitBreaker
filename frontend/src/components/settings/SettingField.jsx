import React from 'react';

const S = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    marginBottom: 20,
  },
  labelRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text)',
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  hint: {
    display: 'block',
    fontSize: 11,
    color: 'var(--color-text-muted)',
    lineHeight: 1.5,
  },
  content: {
    marginTop: 2,
  },
};

export default function SettingField({ label, hint, children, action }) {
  return (
    <div style={S.container}>
      <div style={S.labelRow}>
        <div style={{ flex: 1 }}>
          <label style={S.label}>{label}</label>
          {hint && <span style={S.hint}>{hint}</span>}
        </div>
        {action && <div style={{ flexShrink: 0 }}>{action}</div>}
      </div>
      <div style={S.content}>
        {children}
      </div>
    </div>
  );
}
