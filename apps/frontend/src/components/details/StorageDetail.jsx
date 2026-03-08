import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import { hardwareApi } from '../../api/client';
import { Database, Server } from 'lucide-react';
import logger from '../../utils/logger';

const KIND_LABELS = {
  disk: 'Disk',
  pool: 'Pool',
  dataset: 'Dataset',
  share: 'Share',
};

function formatCapacity(gb) {
  if (!gb) return '—';
  if (gb >= 1024) return `${(gb / 1024).toFixed(1)} TB`;
  return `${gb} GB`;
}

function StorageDetail({ storage, isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [hardwareName, setHardwareName] = useState(null);

  const fetchData = useCallback(async () => {
    if (!storage?.hardware_id) return;
    try {
      const res = await hardwareApi.get(storage.hardware_id);
      setHardwareName(res.data?.name ?? null);
    } catch (err) {
      logger.error(err);
    }
  }, [storage]);

  useEffect(() => {
    if (isOpen) {
      setActiveTab('overview');
      fetchData();
    }
  }, [isOpen, fetchData]);

  if (!storage) return null;

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Storage: ${storage.name}`}>
      <div className="tabs">
        <button
          className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          Overview
        </button>
        <button
          className={`tab ${activeTab === 'docs' ? 'active' : ''}`}
          onClick={() => setActiveTab('docs')}
        >
          Docs
        </button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group">
              <span className="field-label">Name</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Database size={14} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                {storage.name}
              </div>
            </div>

            <div className="field-group">
              <span className="field-label">Kind</span>
              <div>{KIND_LABELS[storage.kind] ?? storage.kind ?? '—'}</div>
            </div>

            <div className="field-group">
              <span className="field-label">Capacity</span>
              <div>{formatCapacity(storage.capacity_gb)}</div>
            </div>

            {storage.used_gb != null && (
              <div className="field-group">
                <span className="field-label">Used</span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span>{formatCapacity(storage.used_gb)}</span>
                    {storage.capacity_gb > 0 && (
                      <span style={{ color: 'var(--color-text-muted)' }}>
                        {Math.round((storage.used_gb / storage.capacity_gb) * 100)}% used
                      </span>
                    )}
                  </div>
                  {storage.capacity_gb > 0 &&
                    (() => {
                      const pct = Math.min(
                        100,
                        Math.round((storage.used_gb / storage.capacity_gb) * 100)
                      );
                      const barColor =
                        pct > 85
                          ? 'var(--color-danger)'
                          : pct > 65
                            ? '#f59e0b'
                            : 'var(--color-online)';
                      return (
                        <div
                          style={{
                            height: 6,
                            borderRadius: 3,
                            background: 'var(--color-border)',
                            width: '100%',
                          }}
                        >
                          <div
                            style={{
                              height: '100%',
                              width: `${pct}%`,
                              borderRadius: 3,
                              background: barColor,
                              transition: 'width 0.3s',
                            }}
                          />
                        </div>
                      );
                    })()}
                </div>
              </div>
            )}

            {storage.path && (
              <div className="field-group">
                <span className="field-label">Path</span>
                <div style={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}>
                  {storage.path}
                </div>
              </div>
            )}

            {storage.protocol && (
              <div className="field-group">
                <span className="field-label">Protocol</span>
                <div>{storage.protocol}</div>
              </div>
            )}

            <div className="field-group">
              <span className="field-label">Hardware</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {storage.hardware_id ? (
                  <>
                    <Server size={13} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                    {hardwareName ?? `#${storage.hardware_id}`}
                  </>
                ) : (
                  <span style={{ color: 'var(--color-text-muted)' }}>Not assigned</span>
                )}
              </div>
            </div>

            {storage.notes && (
              <div className="field-group">
                <span className="field-label">Notes</span>
                <div style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                  {storage.notes}
                </div>
              </div>
            )}

            {storage.tags?.length > 0 && (
              <div className="field-group">
                <span className="field-label">Tags</span>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {storage.tags.map((t) => (
                    <span
                      key={t}
                      style={{
                        background: 'var(--color-glow)',
                        color: 'var(--color-primary)',
                        borderRadius: 3,
                        padding: '2px 7px',
                        fontSize: 11,
                      }}
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'docs' && <DocsPanel entityType="storage" entityId={storage.id} />}
      </div>
    </Drawer>
  );
}

StorageDetail.propTypes = {
  storage: PropTypes.object,
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default StorageDetail;
