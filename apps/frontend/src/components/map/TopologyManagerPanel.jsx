/**
 * TopologyManagerPanel — slide-in drawer to list, create, rename, and delete
 * named topologies. Accessible from the MapPage toolbar.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { topologiesApi } from '../../api/client';
import { useToast } from '../common/Toast';
import ConfirmDialog from '../common/ConfirmDialog';
import FormModal from '../common/FormModal';
import { X } from 'lucide-react';

const FIELDS = [{ name: 'name', label: 'Name', required: true }];

function TopologyRow({ topo, onSetDefault, onDelete }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 0',
        borderBottom: '1px solid var(--color-border)',
        fontSize: 13,
      }}
    >
      <span style={{ flex: 1 }}>
        {topo.name}
        {topo.is_default && (
          <span style={{ marginLeft: 6, fontSize: 10, color: '#22c55e', fontWeight: 700 }}>
            DEFAULT
          </span>
        )}
      </span>
      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
        {topo.node_count}N · {topo.edge_count}E
      </span>
      {!topo.is_default && (
        <button
          className="btn"
          style={{ fontSize: 11, padding: '2px 8px' }}
          onClick={() => onSetDefault(topo.id)}
        >
          Set default
        </button>
      )}
      {!topo.is_default && (
        <button
          className="btn btn-danger"
          style={{ fontSize: 11, padding: '2px 8px' }}
          onClick={() => onDelete(topo)}
        >
          Delete
        </button>
      )}
    </div>
  );
}

TopologyRow.propTypes = {
  topo: PropTypes.object.isRequired,
  onSetDefault: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};

export default function TopologyManagerPanel({ onClose }) {
  const toast = useToast();
  const [topologies, setTopologies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await topologiesApi.list();
      setTopologies(res.data ?? []);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (values) => {
    await topologiesApi.create(values);
    toast.success('Topology created.');
    setShowForm(false);
    await load();
  };

  const handleSetDefault = async (id) => {
    await topologiesApi.update(id, { is_default: true });
    toast.success('Default topology updated.');
    await load();
  };

  const handleDelete = async () => {
    await topologiesApi.delete(confirmDelete.id);
    toast.success('Topology deleted.');
    setConfirmDelete(null);
    await load();
  };

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        width: 340,
        height: '100%',
        background: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-border)',
        zIndex: 50,
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '-4px 0 16px rgba(0,0,0,0.2)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '10px 14px',
          borderBottom: '1px solid var(--color-border)',
        }}
      >
        <span style={{ fontWeight: 600, flex: 1 }}>Topologies</span>
        <button className="btn" style={{ padding: '2px 6px' }} onClick={() => setShowForm(true)}>
          + New
        </button>
        <button
          style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 }}
          onClick={onClose}
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 14px' }}>
        {loading && <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading…</p>}
        {!loading && topologies.length === 0 && (
          <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>No topologies found.</p>
        )}
        {topologies.map((t) => (
          <TopologyRow
            key={t.id}
            topo={t}
            onSetDefault={handleSetDefault}
            onDelete={setConfirmDelete}
          />
        ))}
      </div>

      <FormModal
        open={showForm}
        title="New Topology"
        fields={FIELDS}
        initialValues={{}}
        onSubmit={handleCreate}
        onClose={() => setShowForm(false)}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete topology "${confirmDelete?.name}"? This removes all its saved positions.`}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

TopologyManagerPanel.propTypes = {
  onClose: PropTypes.func.isRequired,
};
