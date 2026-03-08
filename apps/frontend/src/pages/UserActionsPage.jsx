import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { adminUsersApi } from '../api/client';
import { useToast } from '../components/common/Toast';
import TimestampCell from '../components/TimestampCell';

export default function UserActionsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [logs, setLogs] = useState([]);

  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    start_time: '',
    end_time: '',
    action: '',
  });

  const fetchActions = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const params = {};
      if (filters.start_time) params.start_time = filters.start_time;
      if (filters.end_time) params.end_time = filters.end_time;
      if (filters.action) params.action = filters.action;
      const res = await adminUsersApi.getUserActions(id, params);
      setLogs(res.data?.logs || []);
    } catch (err) {
      toast.error(err?.message || 'Failed to load actions');
    } finally {
      setLoading(false);
    }
  }, [id, filters.start_time, filters.end_time, filters.action, toast]);

  useEffect(() => {
    fetchActions();
  }, [fetchActions]);

  return (
    <div className="page-container" style={{ padding: 24 }}>
      <button
        type="button"
        className="btn-ghost"
        onClick={() => navigate('/admin/users')}
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}
      >
        <ArrowLeft size={18} />
        Back to Users
      </button>

      <h1 style={{ margin: '0 0 24px', fontSize: 24, fontWeight: 600 }}>
        Action History — User #{id}
      </h1>

      <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>Start</label>
          <input
            type="datetime-local"
            value={filters.start_time}
            onChange={(e) => setFilters((p) => ({ ...p, start_time: e.target.value }))}
            style={{ padding: 8, borderRadius: 6, fontSize: 13 }}
          />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>End</label>
          <input
            type="datetime-local"
            value={filters.end_time}
            onChange={(e) => setFilters((p) => ({ ...p, end_time: e.target.value }))}
            style={{ padding: 8, borderRadius: 6, fontSize: 13 }}
          />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>Action</label>
          <input
            type="text"
            placeholder="e.g. login_success"
            value={filters.action}
            onChange={(e) => setFilters((p) => ({ ...p, action: e.target.value }))}
            style={{ padding: 8, borderRadius: 6, fontSize: 13, minWidth: 140 }}
          />
        </div>
      </div>

      {loading ? (
        <p style={{ color: 'var(--color-text-muted)' }}>Loading...</p>
      ) : (
        <div
          style={{
            background: 'var(--color-surface)',
            borderRadius: 8,
            border: '1px solid var(--color-border)',
            overflow: 'hidden',
          }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr
                style={{
                  background: 'var(--color-bg)',
                  borderBottom: '1px solid var(--color-border)',
                }}
              >
                <th style={{ padding: 12, textAlign: 'left', fontWeight: 600 }}>Time</th>
                <th style={{ padding: 12, textAlign: 'left', fontWeight: 600 }}>Action</th>
                <th style={{ padding: 12, textAlign: 'left', fontWeight: 600 }}>Entity</th>
                <th style={{ padding: 12, textAlign: 'left', fontWeight: 600 }}>IP</th>
                <th style={{ padding: 12, textAlign: 'left', fontWeight: 600 }}>Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: 12, fontSize: 13 }}>
                    <TimestampCell value={log.created_at_utc || log.timestamp} />
                  </td>
                  <td style={{ padding: 12, fontSize: 13 }}>{log.action}</td>
                  <td style={{ padding: 12, fontSize: 13 }}>
                    {log.entity_type && log.entity_id
                      ? `${log.entity_type} #${log.entity_id}`
                      : log.entity_name || '—'}
                  </td>
                  <td style={{ padding: 12, fontSize: 13, color: 'var(--color-text-muted)' }}>
                    {log.ip_address || '—'}
                  </td>
                  <td
                    style={{
                      padding: 12,
                      fontSize: 13,
                      color: 'var(--color-text-muted)',
                      maxWidth: 300,
                    }}
                  >
                    {log.details ? String(log.details).slice(0, 80) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {logs.length === 0 && (
            <p style={{ padding: 24, textAlign: 'center', color: 'var(--color-text-muted)' }}>
              No actions found
            </p>
          )}
        </div>
      )}
    </div>
  );
}
