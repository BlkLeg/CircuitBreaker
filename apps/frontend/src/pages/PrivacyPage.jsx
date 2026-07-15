import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ExternalLink,
  Info,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  X,
} from 'lucide-react';
import { windscribeApi, hardwareApi } from '../api/client';
import { getRemediationGuide } from '../data/remediationGuides';
import { PRIVACY_REFRESH_INTERVAL_MS } from '../lib/constants';

const SEVERITY_ORDER = ['critical', 'warning', 'info'];
const SEVERITY_COLORS = {
  critical: 'var(--color-danger, #ef4444)',
  warning: 'var(--color-warning, #eab308)',
  info: 'var(--color-info, #3b82f6)',
};
const CHECK_STATUS_COLORS = {
  ok: 'var(--color-success, #22c55e)',
  info: 'var(--color-info, #3b82f6)',
  warning: 'var(--color-warning, #eab308)',
  critical: 'var(--color-danger, #ef4444)',
  unknown: 'var(--color-text-muted)',
};
const CHECK_LABELS = {
  captive_portal: 'Captive portal',
  dns_tamper: 'DNS integrity',
  dns_filtering_absent: 'DNS filtering',
};

function gradeColor(grade) {
  if (grade === 'A' || grade === 'B') return 'var(--color-success, #22c55e)';
  if (grade === 'C' || grade === 'D') return 'var(--color-warning, #eab308)';
  return 'var(--color-danger, #ef4444)';
}

function ScoreCard({ data }) {
  const history = data.history || [];
  const previous = history.length > 1 ? history[1].score : null;
  const delta = previous === null ? null : data.score - previous;
  return (
    <div className="card" style={{ padding: 20, display: 'flex', alignItems: 'center', gap: 20 }}>
      <div
        style={{
          fontSize: 44,
          fontWeight: 700,
          color: gradeColor(data.grade),
          lineHeight: 1,
          minWidth: 90,
          textAlign: 'center',
        }}
      >
        {data.score}
        <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>Grade {data.grade}</div>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Network Privacy Score</div>
        <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
          Last evaluated {data.checked_at ? new Date(data.checked_at).toLocaleString() : 'never'}
          {delta !== null && (
            <span
              style={{
                marginLeft: 8,
                color: delta >= 0 ? 'var(--color-success)' : 'var(--color-danger)',
              }}
            >
              {delta >= 0 ? '▲' : '▼'} {Math.abs(delta)} since previous evaluation
            </span>
          )}
        </div>
        <ScoreTrend history={history} />
      </div>
    </div>
  );
}

function ScoreTrend({ history }) {
  if (!history || history.length < 2) return null;
  const points = [...history].reverse();
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 36, marginTop: 10 }}>
      {points.map((p, i) => (
        <div
          key={i}
          title={`${p.score} — ${p.at ? new Date(p.at).toLocaleString() : ''}`}
          style={{
            width: 8,
            height: Math.max(3, (p.score / 100) * 36),
            borderRadius: 2,
            background: gradeColor(p.score >= 80 ? 'A' : p.score >= 60 ? 'C' : 'F'),
            opacity: i === points.length - 1 ? 1 : 0.45,
          }}
        />
      ))}
    </div>
  );
}

function CheckStrip({ checks }) {
  if (!checks?.length) return null;
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      {checks.map((check) => (
        <div
          key={check.check_id}
          title={check.evidence}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 12px',
            borderRadius: 8,
            border: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
            fontSize: 13,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: CHECK_STATUS_COLORS[check.status] || CHECK_STATUS_COLORS.unknown,
            }}
          />
          {CHECK_LABELS[check.check_id] || check.check_id}
          <span style={{ color: 'var(--color-text-muted)' }}>{check.status}</span>
        </div>
      ))}
    </div>
  );
}

function RemediationDrawer({ deduction, onClose }) {
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
        boxShadow: '-8px 0 24px rgba(0,0,0,0.25)',
        zIndex: 200,
        padding: 20,
        overflowY: 'auto',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>{guide?.title || deduction.title}</h3>
        <button className="btn btn-sm" onClick={onClose} aria-label="Close remediation guide">
          <X size={16} />
        </button>
      </div>
      <div style={{ fontSize: 13, color: SEVERITY_COLORS[deduction.severity], marginTop: 6 }}>
        {deduction.severity} · −{deduction.points} points
      </div>
      {guide ? (
        <>
          <ol style={{ fontSize: 14, lineHeight: 1.6, paddingLeft: 18, marginTop: 16 }}>
            {guide.steps.map((step, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                {step}
              </li>
            ))}
          </ol>
          {guide.links.length > 0 && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {guide.links.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  <ExternalLink size={13} /> {link.label}
                </a>
              ))}
            </div>
          )}
        </>
      ) : (
        <p style={{ fontSize: 14, marginTop: 16 }}>No guide available for this finding.</p>
      )}
    </div>
  );
}

function DeductionList({ deductions, onSelect }) {
  const grouped = useMemo(() => {
    const groups = { critical: [], warning: [], info: [] };
    for (const d of deductions) (groups[d.severity] || groups.info).push(d);
    return groups;
  }, [deductions]);

  if (!deductions.length) {
    return (
      <p style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
        No findings — nothing to remediate.
      </p>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {SEVERITY_ORDER.filter((severity) => grouped[severity].length).map((severity) => (
        <div key={severity}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: SEVERITY_COLORS[severity],
              marginBottom: 6,
            }}
          >
            {severity} ({grouped[severity].length})
          </div>
          {grouped[severity].map((deduction, i) => (
            <button
              key={`${deduction.rule_id}-${deduction.hardware_id ?? 'net'}-${i}`}
              onClick={() => onSelect(deduction)}
              className="btn"
              style={{
                display: 'flex',
                width: '100%',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 14px',
                marginBottom: 6,
                textAlign: 'left',
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                background: 'var(--color-surface)',
              }}
            >
              <span style={{ fontSize: 14 }}>{deduction.title}</span>
              <span style={{ fontSize: 13, color: SEVERITY_COLORS[severity] }}>
                −{deduction.points}
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

function FlaggedDevicesTable({ deductions, hardwareNames }) {
  const navigate = useNavigate();
  const byDevice = useMemo(() => {
    const map = new Map();
    for (const d of deductions) {
      if (d.hardware_id == null) continue;
      if (!map.has(d.hardware_id)) map.set(d.hardware_id, []);
      map.get(d.hardware_id).push(d);
    }
    return [...map.entries()];
  }, [deductions]);

  if (!byDevice.length) return null;
  return (
    <table className="entity-table" style={{ width: '100%', fontSize: 14 }}>
      <thead>
        <tr>
          <th style={{ textAlign: 'left' }}>Device</th>
          <th style={{ textAlign: 'left' }}>Findings</th>
          <th style={{ textAlign: 'right' }}>Points</th>
        </tr>
      </thead>
      <tbody>
        {byDevice.map(([hardwareId, items]) => (
          <tr
            key={hardwareId}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hardware')}
            title="Open Hardware page"
          >
            <td>{hardwareNames.get(hardwareId) || `Hardware #${hardwareId}`}</td>
            <td>{items.map((d) => d.title).join(', ')}</td>
            <td style={{ textAlign: 'right' }}>−{items.reduce((sum, d) => sum + d.points, 0)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function PrivacyPage() {
  const [scoreData, setScoreData] = useState(null);
  const [hardwareNames, setHardwareNames] = useState(new Map());
  const [selectedDeduction, setSelectedDeduction] = useState(null);
  const [loadError, setLoadError] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [scoreRes, hardwareRes] = await Promise.all([
        windscribeApi.getNetworkPrivacyScore(),
        hardwareApi.list().catch(() => null),
      ]);
      setScoreData(scoreRes.data);
      if (hardwareRes?.data) {
        setHardwareNames(new Map(hardwareRes.data.map((h) => [h.id, h.name])));
      }
      setLoadError(false);
    } catch (err) {
      console.error('Privacy data load failed:', err);
      setLoadError(true);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, PRIVACY_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const latestChecks = useMemo(() => {
    if (!scoreData) return [];
    // deductions carry the findings; checks live alongside in the snapshot
    return scoreData.checks || [];
  }, [scoreData]);

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <ShieldCheck className="tw-text-cb-primary" size={24} />
          <h2>Privacy</h2>
        </div>
      </div>

      {loadError && (
        <div
          className="card"
          style={{ padding: 16, display: 'flex', gap: 8, alignItems: 'center' }}
        >
          <AlertTriangle size={16} color="var(--color-warning)" /> Could not load privacy data.
        </div>
      )}

      {scoreData && scoreData.enabled === false && (
        <div
          className="card"
          style={{ padding: 20, display: 'flex', gap: 10, alignItems: 'center' }}
        >
          <ShieldQuestion size={20} color="var(--color-text-muted)" />
          <div>
            Privacy scoring is disabled. Enable it in{' '}
            <a href="/settings">Settings → Security → Privacy &amp; Threat Intelligence</a>.
          </div>
        </div>
      )}

      {scoreData && scoreData.enabled !== false && scoreData.score === null && (
        <div
          className="card"
          style={{ padding: 20, display: 'flex', gap: 10, alignItems: 'center' }}
        >
          <Info size={20} color="var(--color-text-muted)" />
          Not evaluated yet — the score is computed after the next discovery scan or periodic check.
        </div>
      )}

      {scoreData && scoreData.score !== null && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <ScoreCard data={scoreData} />
          <CheckStrip checks={latestChecks} />
          <div className="card" style={{ padding: 20 }}>
            <h3 style={{ marginTop: 0, fontSize: 15 }}>
              <ShieldAlert size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
              Findings
            </h3>
            <DeductionList
              deductions={scoreData.deductions || []}
              onSelect={setSelectedDeduction}
            />
          </div>
          <div className="card" style={{ padding: 20 }}>
            <h3 style={{ marginTop: 0, fontSize: 15 }}>Flagged devices</h3>
            <FlaggedDevicesTable
              deductions={scoreData.deductions || []}
              hardwareNames={hardwareNames}
            />
            {!(scoreData.deductions || []).some((d) => d.hardware_id != null) && (
              <p style={{ fontSize: 14, color: 'var(--color-text-muted)', margin: 0 }}>
                No devices are currently flagged.
              </p>
            )}
          </div>
        </div>
      )}

      {selectedDeduction && (
        <RemediationDrawer
          deduction={selectedDeduction}
          onClose={() => setSelectedDeduction(null)}
        />
      )}
    </div>
  );
}
