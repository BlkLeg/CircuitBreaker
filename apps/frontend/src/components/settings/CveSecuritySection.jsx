import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { cveApi } from '../../api/client';
import SettingField from './SettingField';
import SettingSection from './SettingSection';

function CveSecuritySection({ form, set }) {
  const [cveStatus, setCveStatus] = useState(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    cveApi
      .status()
      .then((r) => setCveStatus(r.data))
      .catch((err) => {
        console.error('CVE status load failed:', err);
      });
  }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await cveApi.triggerSync();
      setTimeout(() => {
        cveApi
          .status()
          .then((r) => setCveStatus(r.data))
          .catch((err) => {
            console.error('CVE status refresh failed:', err);
          });
        setSyncing(false);
      }, 2000);
    } catch (err) {
      console.error('CVE sync trigger failed:', err);
      setSyncing(false);
    }
  };

  return (
    <SettingSection title="CVE Feed Sync">
      <SettingField
        label="Enable CVE Feed Sync"
        hint="Periodically fetch vulnerability data from the NVD to surface known CVEs on entity detail pages."
      >
        <label className="toggle-switch">
          <span className="sr-only">Enable CVE Feed Sync</span>
          <input
            type="checkbox"
            checked={form.cve_sync_enabled ?? false}
            onChange={(e) => set('cve_sync_enabled', e.target.checked)}
          />
          <span className="toggle-switch-track" />
        </label>
      </SettingField>

      {form.cve_sync_enabled && (
        <>
          <SettingField
            label="Sync Interval (hours)"
            hint="How often to fetch the latest CVE data (1-168)."
          >
            <input
              className="form-control"
              type="number"
              min={1}
              max={168}
              value={form.cve_sync_interval_hours ?? 24}
              onChange={(e) =>
                set('cve_sync_interval_hours', Number.parseInt(e.target.value, 10) || 24)
              }
              style={{ width: 100 }}
            />
          </SettingField>

          <SettingField label="Manual Sync" hint="Trigger an immediate NVD feed sync.">
            <button
              className="btn btn-sm"
              onClick={handleSync}
              disabled={syncing}
              style={{ fontSize: 12 }}
            >
              {syncing ? 'Syncing...' : 'Sync Now'}
            </button>
          </SettingField>

          {cveStatus && (
            <div
              style={{
                fontSize: 12,
                color: 'var(--color-text-muted)',
                marginTop: 8,
                padding: '8px 12px',
                background: 'var(--color-surface)',
                borderRadius: 6,
                border: '1px solid var(--color-border)',
              }}
            >
              <div>
                <strong>Total CVE entries:</strong> {cveStatus.total_entries?.toLocaleString() ?? 0}
              </div>
              <div>
                <strong>Last sync:</strong> {cveStatus.last_sync_at || 'Never'}
              </div>
            </div>
          )}
        </>
      )}
    </SettingSection>
  );
}

CveSecuritySection.propTypes = {
  form: PropTypes.object.isRequired,
  set: PropTypes.func.isRequired,
};

export default CveSecuritySection;
