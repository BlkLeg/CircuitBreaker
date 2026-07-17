import React, { useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client';

const STYLES = [
  {
    key: 'scanline',
    name: 'Scanline Sweep',
    description: 'Gradient fill with a moving light sweep.',
  },
  {
    key: 'segmented',
    name: 'Segmented Pulse',
    description: 'LED-equalizer-style blocks light up left to right.',
  },
  {
    key: 'circuit',
    name: 'Circuit Trace',
    description: 'A glowing signal node travels along a PCB-style trace.',
  },
  {
    key: 'minimal',
    name: 'Minimal Gradient Glow',
    description: 'A slim gradient bar with a soft breathing glow.',
  },
];

const S = {
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    gap: 10,
  },
  card: (active) => ({
    padding: '12px 14px',
    borderRadius: 8,
    background: 'var(--color-bg)',
    border: `2px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
    cursor: 'pointer',
    transition: 'border-color 0.15s ease',
    boxShadow: active ? '0 0 8px var(--color-glow)' : 'none',
    textAlign: 'left',
  }),
  name: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text)',
    marginBottom: 4,
  },
  description: {
    fontSize: 11,
    color: 'var(--color-text-muted)',
    marginBottom: 10,
  },
  demoWrap: {
    height: 24,
    display: 'flex',
    alignItems: 'center',
  },
};

export default function ScanProgressStyleSettings() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const active = settings?.scan_progress_style ?? 'circuit';

  const handleSelect = async (key) => {
    if (key === active || saving) return;
    setSaving(true);
    try {
      await settingsApi.update({ scan_progress_style: key });
      await reloadSettings();
    } catch (err) {
      toast.error(`Failed to save scan progress style: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div style={S.grid}>
        {STYLES.map(({ key, name, description }) => (
          <button
            key={key}
            type="button"
            style={S.card(active === key)}
            onClick={() => handleSelect(key)}
            disabled={saving}
            aria-pressed={active === key}
          >
            <div style={S.name}>{name}</div>
            <div style={S.description}>{description}</div>
            <div style={S.demoWrap}>
              {key === 'scanline' && (
                <div className="sps-demo-scanline-track">
                  <div className="sps-demo-scanline-fill" />
                </div>
              )}
              {key === 'segmented' && (
                <div className="sps-demo-segmented">
                  {Array.from({ length: 20 }, (_, i) => (
                    <span key={i} style={{ animationDelay: `${i * 0.05}s` }} />
                  ))}
                </div>
              )}
              {key === 'circuit' && (
                <div className="sps-demo-circuit">
                  <div className="sps-demo-circuit-track" />
                  <div className="sps-demo-circuit-fill" />
                  <div className="sps-demo-circuit-node" />
                </div>
              )}
              {key === 'minimal' && (
                <div className="sps-demo-minimal-track">
                  <div className="sps-demo-minimal-fill" />
                </div>
              )}
            </div>
          </button>
        ))}
      </div>

      <style>{`
        .sps-demo-scanline-track {
          position: relative;
          width: 100%;
          height: 8px;
          border-radius: 5px;
          background: var(--color-border, #2a2a2a);
          overflow: hidden;
        }
        .sps-demo-scanline-fill {
          position: relative;
          height: 100%;
          border-radius: 5px;
          background: linear-gradient(90deg, color-mix(in srgb, var(--color-primary, #fe8019) 65%, black), var(--color-primary, #fe8019));
          box-shadow: 0 0 8px color-mix(in srgb, var(--color-primary, #fe8019) 60%, transparent);
          overflow: hidden;
          animation: spsDemoFill 3.2s ease-in-out infinite;
        }
        .sps-demo-scanline-fill::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(115deg, transparent 30%, rgba(255,255,255,0.55) 48%, transparent 66%);
          background-size: 200% 100%;
          animation: spsDemoSweep 1.4s linear infinite;
        }

        .sps-demo-segmented {
          display: flex;
          gap: 2px;
          width: 100%;
          height: 10px;
        }
        .sps-demo-segmented span {
          flex: 1;
          border-radius: 2px;
          background: var(--color-border, #2a2a2a);
          animation: spsDemoSegment 3.2s ease-in-out infinite;
        }

        .sps-demo-circuit {
          position: relative;
          width: 100%;
          height: 12px;
        }
        .sps-demo-circuit-track {
          position: absolute;
          top: 50%;
          left: 0;
          right: 0;
          height: 2px;
          background: var(--color-border, #2a2a2a);
          transform: translateY(-50%);
        }
        .sps-demo-circuit-fill {
          position: absolute;
          top: 50%;
          left: 0;
          height: 2px;
          background: var(--color-primary, #fe8019);
          transform: translateY(-50%);
          box-shadow: 0 0 6px color-mix(in srgb, var(--color-primary, #fe8019) 70%, transparent);
          animation: spsDemoFill 3.2s ease-in-out infinite;
        }
        .sps-demo-circuit-node {
          position: absolute;
          top: 50%;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #fff8f0;
          box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary, #fe8019) 35%, transparent), 0 0 10px color-mix(in srgb, var(--color-primary, #fe8019) 90%, transparent);
          transform: translate(-50%, -50%);
          animation: spsDemoNode 3.2s ease-in-out infinite;
        }

        .sps-demo-minimal-track {
          width: 100%;
          height: 6px;
          border-radius: 3px;
          background: var(--color-border, #2a2a2a);
        }
        .sps-demo-minimal-fill {
          height: 100%;
          border-radius: 3px;
          background: linear-gradient(90deg, var(--color-primary, #fe8019), color-mix(in srgb, var(--color-primary, #fe8019) 60%, white));
          animation: spsDemoFill 3.2s ease-in-out infinite, spsDemoGlow 1.6s ease-in-out infinite;
        }

        @keyframes spsDemoFill {
          0%, 8% { width: 18%; }
          50% { width: 72%; }
          92%, 100% { width: 18%; }
        }
        @keyframes spsDemoSweep {
          0% { background-position: 150% 0; }
          100% { background-position: -50% 0; }
        }
        @keyframes spsDemoSegment {
          0%, 100% { background: var(--color-border, #2a2a2a); }
          45%, 55% { background: var(--color-primary, #fe8019); box-shadow: 0 0 8px color-mix(in srgb, var(--color-primary, #fe8019) 70%, transparent); }
        }
        @keyframes spsDemoNode {
          0%, 8% { left: 18%; }
          50% { left: 72%; }
          92%, 100% { left: 18%; }
        }
        @keyframes spsDemoGlow {
          0%, 100% { box-shadow: 0 0 4px color-mix(in srgb, var(--color-primary, #fe8019) 40%, transparent); }
          50% { box-shadow: 0 0 14px color-mix(in srgb, var(--color-primary, #fe8019) 90%, transparent); }
        }
      `}</style>
    </div>
  );
}
