import React from 'react';
import PropTypes from 'prop-types';
import { Loader2, CheckCircle2, XCircle, MinusCircle, Clock, PauseCircle } from 'lucide-react';

const BADGE_CONFIG = {
  queued: {
    label: 'Queued',
    color: '#6b7280',
    bg: 'rgba(107,114,128,0.15)',
    Icon: Clock,
    pulse: false,
  },
  running: {
    label: 'Scanning',
    color: '#22c55e',
    bg: 'rgba(34,197,94,0.15)',
    Icon: Loader2,
    pulse: true,
  },
  scanning: {
    label: 'Scanning',
    color: '#22c55e',
    bg: 'rgba(34,197,94,0.15)',
    Icon: Loader2,
    pulse: true,
  },
  completed: {
    label: 'Completed',
    color: '#22c55e',
    bg: 'rgba(34,197,94,0.15)',
    Icon: CheckCircle2,
    pulse: false,
  },
  done: {
    label: 'Completed',
    color: '#22c55e',
    bg: 'rgba(34,197,94,0.15)',
    Icon: CheckCircle2,
    pulse: false,
  },
  paused: {
    label: 'Paused',
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.15)',
    Icon: PauseCircle,
    pulse: false,
  },
  failed: {
    label: 'Failed',
    color: '#ef4444',
    bg: 'rgba(239,68,68,0.15)',
    Icon: XCircle,
    pulse: false,
  },
  cancelled: {
    label: 'Cancelled',
    color: '#6b7280',
    bg: 'rgba(107,114,128,0.15)',
    Icon: MinusCircle,
    pulse: false,
  },
};

export default function JobStatusBadge({ status, pill }) {
  const cfg = BADGE_CONFIG[status] ?? BADGE_CONFIG.queued;
  const { label, color, bg, Icon, pulse } = cfg;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: pill ? '3px 10px' : '2px 8px',
        borderRadius: pill ? 999 : 4,
        fontSize: 11,
        fontWeight: 600,
        background: bg,
        color,
        border: `1px solid ${color}33`,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
      }}
    >
      <Icon
        size={12}
        strokeWidth={2}
        style={pulse ? { animation: 'spin 1.2s linear infinite' } : undefined}
      />
      {label}
    </span>
  );
}

JobStatusBadge.propTypes = {
  status: PropTypes.oneOf([
    'queued',
    'running',
    'scanning',
    'completed',
    'done',
    'paused',
    'failed',
    'cancelled',
  ]),
  pill: PropTypes.bool,
};
