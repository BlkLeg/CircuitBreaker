import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { Play, Edit2, Trash2, Zap, Search, Shield, Clock, Calendar } from 'lucide-react';
import { getProfiles, deleteProfile, runProfile } from '../../api/discovery.js';
import { useToast } from '../common/Toast';
import ConfirmDialog from '../common/ConfirmDialog.jsx';
import ScanProfileForm from './ScanProfileForm.jsx';

const TYPE_STYLES = {
  quick: { label: 'Quick', Icon: Zap, cls: 'profile-badge-blue' },
  standard: { label: 'Standard', Icon: Search, cls: 'profile-badge-orange' },
  deep: { label: 'Deep', Icon: Shield, cls: 'profile-badge-purple' },
};

function inferType(profile) {
  const name = (profile.name || '').toLowerCase();
  if (name.includes('quick') || name.includes('fast')) return 'quick';
  if (name.includes('deep') || name.includes('full') || name.includes('audit')) return 'deep';
  return 'standard';
}

function TypeBadge({ type }) {
  const cfg = TYPE_STYLES[type] || TYPE_STYLES.standard;
  const { Icon } = cfg;
  return (
    <span className={`profile-card-badge ${cfg.cls}`}>
      <Icon size={10} />
      {cfg.label}
    </span>
  );
}
TypeBadge.propTypes = { type: PropTypes.string.isRequired };

export default function ScanProfilesPanel({ onSaved }) {
  const toast = useToast();
  const [profiles, setProfiles] = useState([]);
  const [editProfile, setEditProfile] = useState(undefined);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = useCallback(() => {
    getProfiles()
      .then((r) => setProfiles(r.data || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRun = async (id) => {
    try {
      await runProfile(id);
      toast.success('Profile scan started');
    } catch (err) {
      toast.error(err?.message || 'Failed to start scan');
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await deleteProfile(confirmDelete);
      toast.success('Profile deleted');
      load();
      onSaved?.();
    } catch (err) {
      toast.error(err?.message || 'Failed to delete profile');
    } finally {
      setConfirmDelete(null);
    }
  };

  const handleSaved = () => {
    setEditProfile(undefined);
    load();
    onSaved?.();
  };

  return (
    <div className="profiles-panel">
      <div className="profiles-header">
        <div>
          <h2 className="profiles-title">Scan Profiles</h2>
          <p className="profiles-subtitle">
            Manage automated discovery schedules and configurations
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary profiles-create-btn"
          onClick={() => setEditProfile(null)}
        >
          <Edit2 size={12} /> Create Profile
        </button>
      </div>

      <div className="profiles-grid">
        {profiles.map((p) => {
          const type = inferType(p);
          const scanTypes = (() => {
            try {
              return JSON.parse(p.scan_types || '[]');
            } catch {
              return [];
            }
          })();
          return (
            <div key={p.id} className="profile-card">
              <div className="profile-card-top">
                <TypeBadge type={type} />
                <div className="profile-card-actions">
                  <button
                    type="button"
                    className="profile-action-btn"
                    title="Run Now"
                    onClick={() => handleRun(p.id)}
                  >
                    <Play size={12} />
                  </button>
                  <button
                    type="button"
                    className="profile-action-btn"
                    title="Edit"
                    onClick={() => setEditProfile(p)}
                  >
                    <Edit2 size={12} />
                  </button>
                  <button
                    type="button"
                    className="profile-action-btn profile-action-danger"
                    title="Delete"
                    onClick={() => setConfirmDelete(p.id)}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>

              <h3 className="profile-card-name">{p.name}</h3>
              <div className="profile-card-cidr">{p.cidr}</div>
              <div className="profile-card-probes">
                {scanTypes.map((t) => (
                  <span key={t} className="profile-probe-tag">
                    {t.toUpperCase()}
                  </span>
                ))}
              </div>

              <div className="profile-card-meta">
                {p.schedule_cron && (
                  <div className="profile-meta-row">
                    <span className="profile-meta-label">
                      <Calendar size={10} /> Schedule
                    </span>
                    <span className="profile-meta-value">{p.schedule_cron}</span>
                  </div>
                )}
                <div className="profile-meta-row">
                  <span className="profile-meta-label">
                    <Clock size={10} /> Last Run
                  </span>
                  <span className="profile-meta-value">{p.last_run_at || 'Never'}</span>
                </div>
              </div>
            </div>
          );
        })}

        <button
          type="button"
          className="profile-card profile-card-placeholder"
          onClick={() => setEditProfile(null)}
        >
          <div className="profile-placeholder-icon">
            <Edit2 size={16} />
          </div>
          <span className="profile-placeholder-label">Create New Profile</span>
        </button>
      </div>

      {editProfile !== undefined && (
        <ScanProfileForm
          profile={editProfile}
          onClose={() => setEditProfile(undefined)}
          onSaved={handleSaved}
        />
      )}

      {confirmDelete && (
        <ConfirmDialog
          title="Delete Profile"
          message="Are you sure you want to delete this scan profile? This action cannot be undone."
          onConfirm={handleDelete}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

ScanProfilesPanel.propTypes = {
  onSaved: PropTypes.func,
};
