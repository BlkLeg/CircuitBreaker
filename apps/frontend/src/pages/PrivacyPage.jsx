import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Info, RefreshCw, ShieldCheck, ShieldQuestion } from 'lucide-react';
import { windscribeApi, hardwareApi } from '../api/client';
import { startAdHocScan } from '../api/discovery';
import { PRIVACY_REFRESH_INTERVAL_MS } from '../lib/constants';
import PrivacyScoreCard from '../components/privacy/PrivacyScoreCard';
import NetworkStatusCheck from '../components/privacy/NetworkStatusCheck';
import FindingsOverviewChart from '../components/privacy/FindingsOverviewChart';
import FindingsByCategoryChart from '../components/privacy/FindingsByCategoryChart';
import KeyFindingsList from '../components/privacy/KeyFindingsList';
import FlaggedDevicesTable from '../components/privacy/FlaggedDevicesTable';
import RemediationDrawer from '../components/privacy/RemediationDrawer';
import AttackSurfaceTable from '../components/privacy/AttackSurfaceTable';

/* ── Main Page ──────────────────────────────────────────────────────────── */

export default function PrivacyPage() {
  const navigate = useNavigate();
  const [scoreData, setScoreData] = useState(null);
  const [historyDays, setHistoryDays] = useState([]);
  const [hardwareMap, setHardwareMap] = useState(new Map());
  const [attackSurfaceData, setAttackSurfaceData] = useState(null);
  const [selectedDeduction, setSelectedDeduction] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [scanLaunching, setScanLaunching] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [scoreRes, hardwareRes, attackSurfaceRes, historyRes] = await Promise.all([
        windscribeApi.getNetworkPrivacyScore(),
        hardwareApi.list().catch(() => null),
        windscribeApi.getAttackSurface().catch(() => null),
        windscribeApi.getNetworkPrivacyScoreHistory(30).catch(() => null),
      ]);
      setScoreData(scoreRes.data);
      setHistoryDays(historyRes?.data?.days || []);
      if (attackSurfaceRes?.data) {
        setAttackSurfaceData(attackSurfaceRes.data.attack_surface);
      }
      if (hardwareRes?.data) {
        setHardwareMap(
          new Map(
            hardwareRes.data.map((h) => [
              h.id,
              { name: h.name, os: h.os || null, icon_slug: h.icon_slug || null },
            ])
          )
        );
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

  const checks = useMemo(() => scoreData?.checks || [], [scoreData]);
  const deductions = useMemo(() => scoreData?.deductions || [], [scoreData]);

  const handleRerunScan = async () => {
    setScanLaunching(true);
    try {
      await startAdHocScan({});
    } catch (err) {
      console.error('Failed to launch scan:', err);
    } finally {
      setScanLaunching(false);
    }
  };

  const handleViewDetails = (deduction) => {
    if (deduction.hardware_id != null) {
      navigate('/hardware');
    }
  };

  /* ── Empty states ───────────────────────────────────────────────── */

  if (loadError) {
    return (
      <div className="page">
        <PageHeader />
        <div
          className="card"
          style={{ padding: 20, display: 'flex', gap: 10, alignItems: 'center' }}
        >
          <AlertTriangle size={18} color="var(--color-warning)" />
          Could not load privacy data. Check your connection and try again.
        </div>
      </div>
    );
  }

  if (scoreData && scoreData.enabled === false) {
    return (
      <div className="page">
        <PageHeader />
        <div
          className="card"
          style={{ padding: 24, display: 'flex', gap: 12, alignItems: 'center' }}
        >
          <ShieldQuestion size={22} color="var(--color-text-muted)" />
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Privacy scoring is disabled</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              Enable it in{' '}
              <a href="/settings" style={{ color: 'var(--color-primary)' }}>
                Settings → Security → Privacy &amp; Threat Intelligence
              </a>
              .
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (scoreData && scoreData.score === null) {
    return (
      <div className="page">
        <PageHeader />
        <div
          className="card"
          style={{ padding: 24, display: 'flex', gap: 12, alignItems: 'center' }}
        >
          <Info size={22} color="var(--color-text-muted)" />
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Not evaluated yet</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              The privacy score is computed after the next discovery scan or periodic check.
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!scoreData) {
    return (
      <div className="page">
        <PageHeader />
        <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)' }}>
          Loading…
        </div>
      </div>
    );
  }

  /* ── Dashboard grid ─────────────────────────────────────────────── */

  return (
    <div className="page">
      <PageHeader />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 16,
        }}
      >
        {/* Row 1 */}
        <PrivacyScoreCard data={scoreData} />
        <NetworkStatusCheck checks={checks} />

        {/* Row 2 */}
        <FindingsOverviewChart days={historyDays} />
        <FindingsByCategoryChart deductions={deductions} />

        {/* Row 3 */}
        <KeyFindingsList
          deductions={deductions}
          onRemediate={setSelectedDeduction}
          onViewDetails={handleViewDetails}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FlaggedDevicesTable
            deductions={deductions}
            hardwareMap={hardwareMap}
            onRemediate={setSelectedDeduction}
          />
          <button
            onClick={handleRerunScan}
            disabled={scanLaunching}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 10,
              padding: '14px 24px',
              borderRadius: 10,
              border: 'none',
              background: 'var(--color-primary, #00f5ff)',
              color: 'var(--color-bg, #020617)',
              fontSize: 15,
              fontWeight: 700,
              cursor: scanLaunching ? 'wait' : 'pointer',
              opacity: scanLaunching ? 0.6 : 1,
              letterSpacing: '0.02em',
              textTransform: 'uppercase',
              transition: 'opacity 0.15s ease, transform 0.1s ease',
              boxShadow: '0 4px 14px rgba(0, 245, 255, 0.2)',
            }}
          >
            <RefreshCw size={18} className={scanLaunching ? 'spin' : ''} />
            {scanLaunching ? 'Launching…' : 'Re-run Discovery Scan'}
          </button>
        </div>

        {/* Row 4 */}
        <div style={{ gridColumn: '1 / -1' }}>
          <AttackSurfaceTable attackSurface={attackSurfaceData} />
        </div>
      </div>

      {/* Responsive: collapse to single column on small screens */}
      <style>{`
        @media (max-width: 900px) {
          .page > div[style*="grid-template-columns"] {
            grid-template-columns: 1fr !important;
          }
        }
        .privacy-card {
          border-radius: 12px;
          border: 1px solid var(--color-border, #333);
          background: var(--color-surface, #1e1e1e);
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .spin {
          animation: spin 1s linear infinite;
        }
      `}</style>

      {selectedDeduction && (
        <RemediationDrawer
          deduction={selectedDeduction}
          onClose={() => setSelectedDeduction(null)}
        />
      )}
    </div>
  );
}

function PageHeader() {
  return (
    <div className="page-header">
      <div className="tw-flex tw-items-center tw-gap-3">
        <ShieldCheck className="tw-text-cb-primary" size={24} />
        <h2>Privacy</h2>
      </div>
    </div>
  );
}
