import React, { useState } from 'react';
import { Shield, ShieldAlert, ShieldQuestion, Info, ChevronDown, ChevronUp } from 'lucide-react';
import RemediationDrawer from '../privacy/RemediationDrawer';

const SEVERITY_COLORS = {
  critical: 'var(--color-danger, #ef4444)',
  warning: 'var(--color-warning, #eab308)',
  info: 'var(--color-info, #3b82f6)',
};
const PRIVACY_GOOD_SCORE_MIN = 80;

export default function HardwareThreatProfile({ threatData, windscribeEnabled }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedDeduction, setSelectedDeduction] = useState(null);

  if (windscribeEnabled === false) {
    return (
      <div
        style={{
          marginBottom: 16,
          padding: '16px',
          background: 'var(--color-surface)',
          borderRadius: 8,
          border: '1px solid var(--color-border)',
          display: 'flex',
          gap: 12,
          alignItems: 'center',
        }}
      >
        <ShieldQuestion size={22} color="var(--color-text-muted)" />
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Threat Profile Disabled</div>
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            Privacy scoring is disabled in Settings.
          </div>
        </div>
      </div>
    );
  }

  if (!threatData || threatData.score == null) {
    return (
      <div
        style={{
          marginBottom: 16,
          padding: '16px',
          background: 'var(--color-surface)',
          borderRadius: 8,
          border: '1px solid var(--color-border)',
          display: 'flex',
          gap: 12,
          alignItems: 'center',
        }}
      >
        <Info size={22} color="var(--color-text-muted)" />
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Not evaluated yet</div>
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            Score is computed after the next discovery scan.
          </div>
        </div>
      </div>
    );
  }

  const deductions = threatData.deductions || [];
  const hasFindings = deductions.length > 0;

  return (
    <>
      <div
        style={{
          marginBottom: 16,
          background: 'var(--color-surface)',
          borderRadius: 8,
          border: '1px solid var(--color-border)',
          overflow: 'hidden',
        }}
      >
        {/* Header (always visible) */}
        <div
          onClick={() => setExpanded(!expanded)}
          style={{
            padding: '12px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            cursor: 'pointer',
            background: 'var(--color-surface-alt, rgba(255,255,255,0.02))',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {threatData.score >= PRIVACY_GOOD_SCORE_MIN ? (
              <Shield size={24} color="var(--color-success, #22c55e)" />
            ) : (
              <ShieldAlert size={24} color="var(--color-danger, #ef4444)" />
            )}
            <div>
              <div style={{ fontWeight: 600 }}>Privacy Score: {threatData.score}/100</div>
              <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 2 }}>
                {hasFindings ? `${deductions.length} finding(s)` : 'Clean profile'}
              </div>
            </div>
          </div>
          <button className="btn btn-sm" style={{ background: 'none', border: 'none', padding: 0 }}>
            {expanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
          </button>
        </div>

        {/* Expanded Content */}
        {expanded && (
          <div style={{ padding: '16px', borderTop: '1px solid var(--color-border)' }}>
            {!hasFindings ? (
              <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                No threats or privacy issues found on this device.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {deductions.map((deduction, i) => (
                  <div
                    key={`${deduction.rule_id}-${i}`}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      background: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 6,
                      borderLeft: `3px solid ${SEVERITY_COLORS[deduction.severity]}`,
                    }}
                  >
                    <span style={{ fontSize: 13, color: 'var(--color-text)' }}>
                      {deduction.title}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 700,
                          color: SEVERITY_COLORS[deduction.severity],
                        }}
                      >
                        −{deduction.points}
                      </span>
                      <button
                        className="btn btn-sm"
                        style={{
                          fontSize: 11,
                          padding: '4px 10px',
                          border: '1px solid var(--color-primary)',
                          color: 'var(--color-primary)',
                          background: 'transparent',
                        }}
                        onClick={() => setSelectedDeduction(deduction)}
                      >
                        Remediate
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {selectedDeduction && (
        <RemediationDrawer
          deduction={selectedDeduction}
          onClose={() => setSelectedDeduction(null)}
        />
      )}
    </>
  );
}
