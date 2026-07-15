import React from 'react';
import { AlertTriangle, ExternalLink, X } from 'lucide-react';
import { getRemediationGuide } from '../../data/remediationGuides';

const SEVERITY_COLORS = {
  critical: 'var(--color-danger, #ef4444)',
  warning: 'var(--color-warning, #eab308)',
  info: 'var(--color-info, #3b82f6)',
};

export default function RemediationDrawer({ deduction, onClose }) {
  const guide = getRemediationGuide(deduction?.remediation_id);
  if (!deduction) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: 380,
        maxWidth: '90vw',
        background: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-border)',
        boxShadow: '-8px 0 24px rgba(0,0,0,0.35)',
        zIndex: 200,
        padding: 24,
        overflowY: 'auto',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
          {guide?.title || deduction.title}
        </h3>
        <button
          className="btn btn-sm"
          onClick={onClose}
          aria-label="Close remediation guide"
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}
        >
          <X size={18} color="var(--color-text-muted)" />
        </button>
      </div>
      <div
        style={{
          fontSize: 13,
          color: SEVERITY_COLORS[deduction.severity],
          marginTop: 8,
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <AlertTriangle size={14} />
        {deduction.severity} · −{deduction.points} points
      </div>
      {guide ? (
        <>
          <ol
            style={{
              fontSize: 14,
              lineHeight: 1.7,
              paddingLeft: 20,
              marginTop: 20,
              color: 'var(--color-text)',
            }}
          >
            {guide.steps.map((step, i) => (
              <li key={i} style={{ marginBottom: 10 }}>
                {step}
              </li>
            ))}
          </ol>
          {guide.links.length > 0 && (
            <div
              style={{
                marginTop: 16,
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                borderTop: '1px solid var(--color-border)',
                paddingTop: 16,
              }}
            >
              {guide.links.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    fontSize: 13,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    color: 'var(--color-primary)',
                  }}
                >
                  <ExternalLink size={13} /> {link.label}
                </a>
              ))}
            </div>
          )}
        </>
      ) : (
        <p style={{ fontSize: 14, marginTop: 20, color: 'var(--color-text-muted)' }}>
          No guide available for this finding.
        </p>
      )}
    </div>
  );
}
