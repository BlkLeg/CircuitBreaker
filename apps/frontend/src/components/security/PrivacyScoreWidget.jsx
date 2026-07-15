import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-react';
import { windscribeApi } from '../../api/client';
import { discoveryEmitter } from '../../hooks/useDiscoveryStream';

const GOOD_SCORE_MIN = 80;
const FAIR_SCORE_MIN = 60;

/**
 * Compact Map overlay pill: score + grade, click-through to /privacy.
 * Refetches on scan completion (job:update) — scores recompute post-scan.
 */
export default function PrivacyScoreWidget() {
  const [data, setData] = useState(null);
  const navigate = useNavigate();

  const fetchScore = useCallback(() => {
    windscribeApi
      .getNetworkPrivacyScore()
      .then((res) => setData(res.data))
      .catch((err) => console.error('Privacy score fetch failed:', err));
  }, []);

  useEffect(() => {
    fetchScore();
    const onJobUpdate = (job) => {
      if (job?.status === 'completed') fetchScore();
    };
    discoveryEmitter.on('job:update', onJobUpdate);
    return () => discoveryEmitter.off('job:update', onJobUpdate);
  }, [fetchScore]);

  if (!data || data.enabled === false || data.score === null) return null;

  const { score, grade } = data;
  const color =
    score >= GOOD_SCORE_MIN
      ? 'var(--color-success, #22c55e)'
      : score >= FAIR_SCORE_MIN
        ? 'var(--color-warning, #eab308)'
        : 'var(--color-danger, #ef4444)';
  const Icon =
    score >= GOOD_SCORE_MIN ? ShieldCheck : score >= FAIR_SCORE_MIN ? Shield : ShieldAlert;

  return (
    <button
      onClick={() => navigate('/privacy')}
      title="Network privacy score — open Privacy page"
      style={{
        position: 'absolute',
        top: 16,
        right: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 999,
        border: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
        color: 'var(--color-text)',
        cursor: 'pointer',
        zIndex: 100,
        fontSize: 14,
        fontWeight: 600,
        boxShadow: '0 2px 6px rgba(0, 0, 0, 0.15)',
      }}
    >
      <Icon size={16} color={color} />
      {score}
      <span style={{ color, fontWeight: 700 }}>{grade}</span>
    </button>
  );
}
