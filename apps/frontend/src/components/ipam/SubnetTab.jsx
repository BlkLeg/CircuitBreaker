/**
 * SubnetTab — subnet calculator, utilization, heatmap, and split/merge tools.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { ipamApi } from '../../api/client';
import SubnetHeatmap from './SubnetHeatmap';
import NetworkUtilizationBar from './NetworkUtilizationBar';

export default function SubnetTab({ networks }) {
  const [cidr, setCidr] = useState('');
  const [calcResult, setCalcResult] = useState(null);
  const [calcError, setCalcError] = useState('');
  const [selectedNetId, setSelectedNetId] = useState('');
  const [utilization, setUtilization] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [splitPrefix, setSplitPrefix] = useState('');
  const [splitResult, setSplitResult] = useState(null);

  const handleCalc = async () => {
    setCalcError('');
    setCalcResult(null);
    try {
      const res = await ipamApi.calculateSubnet(cidr);
      setCalcResult(res.data);
    } catch (err) {
      setCalcError(err.response?.data?.detail || err.message);
    }
  };

  const handleLoadNetwork = async () => {
    if (!selectedNetId) return;
    try {
      const [uRes, hRes] = await Promise.all([
        ipamApi.networkUtilization(Number(selectedNetId)),
        ipamApi.networkHeatmap(Number(selectedNetId)),
      ]);
      setUtilization(uRes.data);
      setHeatmap(hRes.data);
    } catch {
      /* ignore */
    }
  };

  const handleSplit = async () => {
    if (!cidr || !splitPrefix) return;
    setSplitResult(null);
    try {
      const res = await ipamApi.subnetSplit({ cidr, new_prefix: Number(splitPrefix) });
      setSplitResult(res.data.subnets);
    } catch {
      /* ignore */
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Calculator */}
      <section>
        <h4 style={{ margin: '0 0 8px' }}>Subnet Calculator</h4>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <input
            type="text"
            placeholder="e.g. 10.0.1.0/24"
            value={cidr}
            onChange={(e) => setCidr(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCalc()}
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 6,
              padding: '6px 10px',
              color: 'var(--color-text)',
              fontSize: 13,
              width: 220,
            }}
          />
          <button className="btn btn-primary" onClick={handleCalc}>
            Calculate
          </button>
        </div>
        {calcError && <p style={{ color: '#ef4444', fontSize: 13 }}>{calcError}</p>}
        {calcResult && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
              gap: 8,
              padding: 12,
              background: 'var(--color-bg)',
              borderRadius: 6,
              border: '1px solid var(--color-border)',
              fontSize: 13,
            }}
          >
            {Object.entries(calcResult).map(([k, v]) => (
              <div key={k}>
                <span style={{ color: 'var(--color-text-muted)' }}>{k.replace(/_/g, ' ')}:</span>{' '}
                <strong>{String(v ?? '—')}</strong>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Split Preview */}
      <section>
        <h4 style={{ margin: '0 0 8px' }}>Split Preview</h4>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <input
            type="text"
            placeholder="CIDR to split"
            value={cidr}
            onChange={(e) => setCidr(e.target.value)}
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 6,
              padding: '6px 10px',
              color: 'var(--color-text)',
              fontSize: 13,
              width: 180,
            }}
          />
          <input
            type="number"
            placeholder="New prefix (e.g. 25)"
            value={splitPrefix}
            onChange={(e) => setSplitPrefix(e.target.value)}
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 6,
              padding: '6px 10px',
              color: 'var(--color-text)',
              fontSize: 13,
              width: 160,
            }}
          />
          <button className="btn" onClick={handleSplit}>
            Preview Split
          </button>
        </div>
        {splitResult && (
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 6,
              fontSize: 13,
            }}
          >
            {splitResult.map((s) => (
              <span
                key={s}
                style={{
                  padding: '3px 10px',
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 4,
                }}
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Network Utilization + Heatmap */}
      <section>
        <h4 style={{ margin: '0 0 8px' }}>Network Visualization</h4>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <select
            className="filter-select"
            value={selectedNetId}
            onChange={(e) => setSelectedNetId(e.target.value)}
          >
            <option value="">Select network…</option>
            {networks
              .filter((n) => n.cidr)
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name} ({n.cidr})
                </option>
              ))}
          </select>
          <button className="btn btn-primary" onClick={handleLoadNetwork} disabled={!selectedNetId}>
            Load
          </button>
        </div>
        {utilization && <NetworkUtilizationBar data={utilization} />}
        {heatmap && <SubnetHeatmap data={heatmap} />}
      </section>
    </div>
  );
}

SubnetTab.propTypes = {
  networks: PropTypes.array.isRequired,
};
