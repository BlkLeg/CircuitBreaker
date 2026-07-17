import React from 'react';
import PropTypes from 'prop-types';
import { useSettings } from '../../context/SettingsContext';

const CONTAINER_CLASS_NAME = 'scan-progress-animation';
const SEGMENT_COUNT = 20;

function clampPct(pct) {
  if (typeof pct !== 'number' || Number.isNaN(pct)) return 0;
  return Math.max(0, Math.min(100, pct));
}

function ScanlineSweepBar({ pct }) {
  return (
    <div className="spb-scanline-track">
      <div className="spb-scanline-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
ScanlineSweepBar.propTypes = { pct: PropTypes.number.isRequired };

function SegmentedPulseBar({ pct }) {
  const litCount = Math.round((pct / 100) * SEGMENT_COUNT);
  return (
    <div className="spb-segmented">
      {Array.from({ length: SEGMENT_COUNT }, (_, i) => (
        <span key={i} className={i < litCount ? 'spb-segment spb-segment-lit' : 'spb-segment'} />
      ))}
    </div>
  );
}
SegmentedPulseBar.propTypes = { pct: PropTypes.number.isRequired };

function CircuitTraceBar({ pct }) {
  return (
    <div className="spb-circuit">
      <div className="spb-circuit-track" />
      <div className="spb-circuit-fill" style={{ width: `${pct}%` }} />
      <div className="spb-circuit-node" style={{ left: `${pct}%` }} />
    </div>
  );
}
CircuitTraceBar.propTypes = { pct: PropTypes.number.isRequired };

function MinimalGradientGlowBar({ pct }) {
  return (
    <div className="spb-minimal-track">
      <div className="spb-minimal-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
MinimalGradientGlowBar.propTypes = { pct: PropTypes.number.isRequired };

const STYLE_COMPONENTS = {
  scanline: ScanlineSweepBar,
  segmented: SegmentedPulseBar,
  circuit: CircuitTraceBar,
  minimal: MinimalGradientGlowBar,
};

const DEFAULT_STYLE = 'circuit';

export default function ScanProgressAnimation({ className = '', pct = 0, compact = false }) {
  const { settings } = useSettings();
  const styleKey = STYLE_COMPONENTS[settings?.scan_progress_style]
    ? settings.scan_progress_style
    : DEFAULT_STYLE;
  const StyleComponent = STYLE_COMPONENTS[styleKey];
  const containerClassName = [CONTAINER_CLASS_NAME, compact && 'compact', className]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={containerClassName} data-testid="scan-progress-animation" aria-hidden="true">
      <StyleComponent pct={clampPct(pct)} />
    </div>
  );
}

ScanProgressAnimation.propTypes = {
  className: PropTypes.string,
  pct: PropTypes.number,
  compact: PropTypes.bool,
};
