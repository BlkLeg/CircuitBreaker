/* eslint-disable security/detect-object-injection -- internal key lookup */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';
import { SkeletonTable } from '../common/SkeletonTable';
import EntityTable from '../EntityTable';
import SearchBox from '../SearchBox';
import TagFilter from '../TagFilter';
import TagsCell from '../TagsCell';
import { hardwareApi, computeUnitsApi, tagsApi } from '../../api/client';
import NetworkDetail from '../details/NetworkDetail';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { useToast } from '../common/Toast';

function NetworksTab({ networks, sites, loading, onCreate, onUpdate, onDelete }) {
  const toast = useToast();
  const [hardware, setHardware] = useState([]);
  const [computeUnits, setComputeUnits] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [vlanFilter, setVlanFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);
  const [allTags, setAllTags] = useState([]);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const fetchHardware = useCallback(async () => {
    try {
      const [hwRes, cuRes] = await Promise.all([hardwareApi.list(), computeUnitsApi.list()]);
      setHardware(hwRes.data);
      setComputeUnits(cuRes.data);
    } catch (err) {
      toast.error(err.message);
    }
  }, [toast]);

  const fetchTags = useCallback(async () => {
    try {
      const res = await tagsApi.list();
      setAllTags(res.data || []);
    } catch {
      setAllTags([]);
    }
  }, []);

  useEffect(() => {
    fetchHardware();
  }, [fetchHardware]);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  const FIELDS = useMemo(
    () => [
      { name: 'name', label: 'Name', required: true },
      { name: 'cidr', label: 'CIDR (e.g. 192.168.10.0/24)' },
      { name: 'vlan_id', label: 'VLAN ID', type: 'number' },
      { name: 'gateway', label: 'Gateway IP (static text, e.g. 10.10.10.1)' },
      {
        name: 'gateway_hardware_id',
        label: 'Gateway Hardware',
        type: 'select',
        options: [
          ...hardware.map((h) => ({
            value: h.id,
            label: `${h.name}${h.ip_address ? ` (${h.ip_address})` : ''}`,
          })),
        ],
      },
      { name: 'description', label: 'Description', type: 'textarea' },
      {
        name: 'site_id',
        label: 'Site',
        type: 'select',
        options: [
          { value: '', label: '— None —' },
          ...sites.map((s) => ({ value: s.id, label: s.name })),
        ],
      },
      { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
    ],
    [hardware, sites]
  );

  const COLUMNS = useMemo(
    () => [
      { key: 'name', label: 'Name' },
      { key: 'cidr', label: 'CIDR' },
      { key: 'vlan_id', label: 'VLAN' },
      { key: 'gateway', label: 'Gateway IP' },
      {
        key: 'utilization',
        label: 'Utilization',
        render: (_, row) => {
          const pct =
            row.total_count > 0
              ? Math.min(100, Math.round(((row.allocated_count ?? 0) / row.total_count) * 100))
              : 0;
          const barColor = pct >= 80 ? '#f87171' : pct >= 60 ? '#facc15' : '#4ade80';
          return (
            <div
              className="h-1.5 rounded-full"
              style={{ minWidth: 80, background: 'rgba(255,255,255,0.1)' }}
            >
              <div
                className="h-full rounded-full"
                style={{ width: `${pct}%`, background: barColor, transition: 'width 0.3s' }}
              />
            </div>
          );
        },
      },
      {
        key: 'ips',
        label: 'IPs',
        render: (_, row) => (
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {row.allocated_count ?? 0} / {row.total_count || '—'}
          </span>
        ),
      },
      {
        key: 'gateway_hardware_id',
        label: 'Gateway Hardware',
        render: (v) => hardware.find((h) => h.id === v)?.name ?? '—',
      },
      {
        key: 'site_id',
        label: 'Site',
        render: (v) => sites.find((s) => s.id === v)?.name ?? '—',
      },
      { key: 'description', label: 'Description' },
      {
        key: 'tags',
        label: 'Tags',
        render: (v, row) => (
          <TagsCell
            tags={v || []}
            allTags={allTags}
            onTagsChange={async (names) => {
              await onUpdate(row.id, { tags: names });
            }}
            onTagColorChange={async (id, color) => {
              await tagsApi.update(id, { color });
              fetchTags();
            }}
          />
        ),
      },
    ],
    [hardware, sites, allTags, onUpdate, fetchTags]
  );

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      const payload = { [columnKey]: value };
      if (columnKey === 'vlan_id') payload[columnKey] = value === '' ? null : Number(value);
      await onUpdate(row.id, payload);
    },
    [onUpdate]
  );

  const bulkActions = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} network(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await onDelete(id);
              setSelectedIds([]);
            },
          });
        },
      },
    ],
    [onDelete]
  );

  const displayItems = useMemo(() => {
    let filtered = networks;
    if (q) {
      const lq = q.toLowerCase();
      filtered = filtered.filter(
        (n) => n.name.toLowerCase().includes(lq) || (n.description ?? '').toLowerCase().includes(lq)
      );
    }
    if (vlanFilter) {
      filtered = filtered.filter((n) => String(n.vlan_id) === String(vlanFilter));
    }
    if (tagFilter) {
      filtered = filtered.filter((n) => n.tags?.includes(tagFilter));
    }
    return filtered;
  }, [networks, q, tagFilter, vlanFilter]);

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await onUpdate(editTarget.id, values);
      } else {
        await onCreate(values);
      }
      setShowForm(false);
      setEditTarget(null);
      setFormApiErrors({});
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const handleDelete = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this network?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await onDelete(id);
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginBottom: 12,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} tags={allTags} />
        <input
          className="filter-select"
          type="number"
          placeholder="VLAN filter…"
          value={vlanFilter}
          onChange={(e) => setVlanFilter(e.target.value)}
          style={{ width: 120 }}
        />
        <button
          className="btn btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={() => {
            setEditTarget(null);
            setShowForm(true);
          }}
        >
          + Add Network
        </button>
      </div>

      {loading ? (
        <SkeletonTable cols={9} />
      ) : (
        <EntityTable
          columns={COLUMNS}
          data={displayItems}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={(row) => handleDelete(row.id)}
          onRowClick={(row) => setDetailTarget(row)}
          onCellSave={handleCellSave}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          bulkActions={bulkActions}
        />
      )}

      {detailTarget && (
        <NetworkDetail
          network={detailTarget}
          hardware={hardware}
          computeUnits={computeUnits}
          onClose={() => setDetailTarget(null)}
        />
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Network' : 'New Network'}
        fields={FIELDS}
        initialValues={editTarget ?? {}}
        apiErrors={formApiErrors}
        onSubmit={handleSubmit}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
          setFormApiErrors({});
        }}
      />

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

NetworksTab.propTypes = {
  networks: PropTypes.array.isRequired,
  sites: PropTypes.array.isRequired,
  loading: PropTypes.bool.isRequired,
  onCreate: PropTypes.func.isRequired,
  onUpdate: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};

export default NetworksTab;
