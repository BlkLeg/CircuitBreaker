/* eslint-disable security/detect-object-injection -- internal role/column keys */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import { createApiCache } from '../utils/apiCache';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import TagsCell from '../components/TagsCell';
import { hardwareApi, clustersApi, computeUnitsApi, tagsApi } from '../api/client';
import HardwareDetail from '../components/details/HardwareDetail';

// 15-second TTL cache for the cluster list — refreshed on tab switch, invalidated after mutations
const cachedClusterList = createApiCache(() => clustersApi.list(), 15_000);
import ClusterDetail from '../components/details/ClusterDetail';
import { VENDORS } from '../config/vendors';
import { useHardwareRoles } from '../hooks/useHardwareRoles';
import { CPU_BRANDS, CPU_BRAND_MAP } from '../config/cpuBrands';
import { getVendorIcon } from '../icons/vendorIcons';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import IconPickerModal, { IconImg } from '../components/common/IconPickerModal';
import IpConflictAlert from '../components/common/IpConflictAlert';
import EntityPicker from '../components/common/EntityPicker';
import { useSettings } from '../context/SettingsContext';
import { useToast } from '../components/common/Toast';
import { validateIpAddress, validateDuplicateName } from '../utils/validation';
import { useTargetMonitors } from '../hooks/useTargetMonitors';
import MonitorCell, { MonitorStatusCell } from '../components/monitors/MonitorCell';
import { useEntityDeepLink } from '../hooks/useEntityDeepLink';
import {
  DEFAULT_PAGE_LIMIT,
  SELECTION_MODE_ALL_MATCHING,
  SELECTION_MODE_IDS,
  buildPageParams,
  clearSelection,
  emptySelection,
  isRowSelected,
  selectAllMatching,
  selectionAfterFilterChange,
  selectionCount,
  selectionScopeLabel,
} from '../lib/inventoryList';

const TAIL_COLUMNS = [
  {
    key: 'ip_address',
    label: 'IP Address',
    render: (v, row) =>
      v ? (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span
            style={{
              color: row.ip_conflict ? '#f59e0b' : undefined,
              fontFamily: 'monospace',
              fontSize: 12,
            }}
          >
            {v}
          </span>
          {row.ip_conflict && (
            <span
              title="IP conflict: this IP is already assigned to another entity"
              style={{
                width: 14,
                height: 14,
                borderRadius: '50%',
                background: '#f59e0b',
                color: '#111',
                fontSize: 9,
                fontWeight: 800,
                flexShrink: 0,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              !
            </span>
          )}
        </span>
      ) : (
        '—'
      ),
  },
  { key: 'wan_uplink', label: 'WAN / Uplink' },
  {
    key: 'cpu_brand',
    label: 'CPU Brand',
    render: (v) => {
      if (!v) return null;
      const brand = CPU_BRAND_MAP[v];
      if (!brand) return <span>{v}</span>;
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <img
            src={brand.icon}
            alt={brand.label}
            width={14}
            height={14}
            style={{ objectFit: 'contain' }}
            onError={(e) => {
              e.target.style.display = 'none';
            }}
          />
          {brand.label}
        </span>
      );
    },
  },
  { key: 'model', label: 'Model' },
  { key: 'cpu', label: 'CPU' },
  { key: 'memory_gb', label: 'Memory (GB)' },
  { key: 'location', label: 'Location' },
];

const CLUSTER_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'environment', label: 'Environment' },
  { key: 'location', label: 'Location' },
  { key: 'member_count', label: 'Members' },
  {
    key: 'updated_at',
    label: 'Last Updated',
    render: (v) => (v ? new Date(v).toLocaleDateString() : '—'),
  },
];

const CLUSTER_FIELDS = (environments) => [
  { name: 'name', label: 'Name', required: true },
  environments?.length
    ? {
        name: 'environment',
        label: 'Environment',
        type: 'select',
        options: environments.map((e) => ({ value: e, label: e })),
      }
    : { name: 'environment', label: 'Environment' },
  { name: 'location', label: 'Location' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

function HardwarePage() {
  const { options: HARDWARE_ROLES, labels: HARDWARE_ROLE_LABELS } = useHardwareRoles();
  const { settings } = useSettings();
  const toast = useToast();
  const vendorIconMode = settings?.vendor_icon_mode ?? 'custom_files';
  const locations = settings?.locations ?? [];
  const environments = settings?.environments ?? [];

  const [activeTab, setActiveTab] = useState('hardware');

  // Icon picker state (for vendor_icon_slug)
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [pendingIconSlug, setPendingIconSlug] = useState(null);
  const [iconPickerCallback, setIconPickerCallback] = useState(null);

  // Confirm dialog state
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const [selection, setSelection] = useState(() => emptySelection());
  const [clusterSelectedIds, setClusterSelectedIds] = useState([]);
  const [allTags, setAllTags] = useState([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [formConflict, setFormConflict] = useState(null);

  const buildFields = (currentIconSlug) => [
    {
      name: 'name',
      label: 'Name / Device Lookup',
      required: true,
      type: 'catalog-search',
      placeholder: 'Search catalog or type a custom name…',
      onSelect: (result, updateValues) => {
        if (result._freeform) {
          updateValues({ name: result.device_label });
        } else {
          updateValues({
            name: result.device_label,
            vendor: result.vendor_key ?? null,
            model: result.device_label,
            vendor_catalog_key: result.vendor_key ?? null,
            model_catalog_key: result.model_key ?? null,
            role: result.role ?? null,
          });
        }
      },
    },
    { name: 'role', label: 'Role', type: 'select', options: HARDWARE_ROLES },
    { name: 'vendor', label: 'Vendor', type: 'select', options: VENDORS },
    {
      name: 'vendor_icon_slug',
      label: 'Vendor Icon',
      type: 'icon-picker',
      currentSlug: currentIconSlug,
      onOpenPicker: (slug, onSelect) => {
        setPendingIconSlug(slug);
        setIconPickerCallback(() => onSelect);
        setIconPickerOpen(true);
      },
    },
    {
      name: 'custom_icon',
      label: 'Custom Icon',
      type: 'image-upload',
      hint: 'Upload PNG/JPEG/SVG (max 2MB). Stored at /user-icons/... and rendered on the map.',
      onUpload: async (file) => {
        const res = await computeUnitsApi.uploadIcon(file);
        return res.data.path;
      },
    },
    { name: 'model', label: 'Model' },
    { name: 'ip_address', label: 'IP Address', type: 'ip-address-input' },
    {
      name: 'wan_uplink',
      label: 'WAN / Uplink',
      hint: 'e.g. ISP — 1Gbps fiber, or upstream interface name',
    },
    {
      name: 'upload_speed_mbps',
      label: 'Upload speed (Mbps)',
      type: 'number',
      hint: 'Used for map link bandwidth and telemetry (e.g. 1000 for 1 Gbps).',
    },
    {
      name: 'download_speed_mbps',
      label: 'Download speed (Mbps)',
      type: 'number',
      hint: 'Used for map link bandwidth and telemetry (e.g. 1000 for 1 Gbps).',
    },
    { name: 'cpu_brand', label: 'CPU Brand', type: 'cpu-select', options: CPU_BRANDS },
    { name: 'cpu', label: 'CPU' },
    { name: 'memory_gb', label: 'Memory (GB)', type: 'number' },
    locations.length
      ? {
          name: 'location',
          label: 'Location',
          type: 'select',
          options: locations.map((l) => ({ value: l, label: l })),
        }
      : { name: 'location', label: 'Location' },
    { name: 'environment_id', label: 'Environment', type: 'environment-combobox' },
    {
      name: 'status_override',
      label: 'Status Override',
      type: 'select',
      options: [
        { value: '', label: '— Auto (derived) —' },
        { value: 'online', label: 'Online' },
        { value: 'offline', label: 'Offline' },
        { value: 'degraded', label: 'Degraded' },
        { value: 'maintenance', label: 'Maintenance' },
      ],
    },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ];

  // ── Hardware state ──────────────────────────────────────────────────────
  const [items, setItems] = useState([]);
  const [listTotal, setListTotal] = useState(0);
  const [listOffset, setListOffset] = useState(0);
  const [listLimit, setListLimit] = useState(DEFAULT_PAGE_LIMIT);
  const [listSort, setListSort] = useState('name');
  const [listDirection] = useState('asc');
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});
  const fetchSeq = useRef(0);

  const listFilter = useMemo(
    () => ({
      q,
      role: roleFilter,
      tag: tagFilter,
      sort: listSort,
      direction: listDirection,
    }),
    [q, roleFilter, tagFilter, listSort, listDirection]
  );

  const loadDeepLinkedEntity = useCallback(async (id) => (await hardwareApi.get(id)).data, []);
  const selectHardwareDetail = useCallback((entity) => {
    if (entity) setActiveTab('hardware');
    setDetailTarget(entity);
  }, []);
  const reportDeepLinkError = useCallback((message) => toast.error(message), [toast]);
  const { openEntity, closeEntity } = useEntityDeepLink({
    loadEntity: loadDeepLinkedEntity,
    selectedId: detailTarget?.id,
    onSelect: selectHardwareDetail,
    onError: reportDeepLinkError,
  });

  // ── Cluster state ───────────────────────────────────────────────────────
  const [clusters, setClusters] = useState([]);
  const [clustersLoading, setClustersLoading] = useState(false);
  const [clusterDetail, setClusterDetail] = useState(null);
  const [showClusterForm, setShowClusterForm] = useState(false);
  const [editCluster, setEditCluster] = useState(null);
  const [clusterFormErrors, setClusterFormErrors] = useState({});

  const fetchData = useCallback(async () => {
    const seq = ++fetchSeq.current;
    setLoading(true);
    setListError(null);
    try {
      const params = buildPageParams({
        limit: listLimit,
        offset: listOffset,
        sort: listSort,
        direction: listDirection,
        q,
        role: roleFilter,
        tag: tagFilter,
      });
      const res = await hardwareApi.page(params);
      if (seq !== fetchSeq.current) return;
      const page = res.data || {};
      setItems(page.items || []);
      setListTotal(page.total || 0);
    } catch (err) {
      if (seq !== fetchSeq.current) return;
      setListError(err.message || 'Could not load hardware.');
      toast.error(err.message);
    } finally {
      if (seq === fetchSeq.current) setLoading(false);
    }
  }, [listLimit, listOffset, listSort, listDirection, q, tagFilter, roleFilter, toast]);

  const fetchClusters = useCallback(async () => {
    setClustersLoading(true);
    try {
      const res = await cachedClusterList();
      setClusters(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setClustersLoading(false);
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
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  useEffect(() => {
    if (activeTab === 'clusters') fetchClusters();
  }, [activeTab, fetchClusters]);

  useEffect(() => {
    if (selection.mode === SELECTION_MODE_ALL_MATCHING) {
      setSelection((prev) =>
        prev.mode === SELECTION_MODE_ALL_MATCHING && prev.totalMatching !== listTotal
          ? { ...prev, totalMatching: listTotal }
          : prev
      );
    }
  }, [listTotal, selection.mode]);

  const hardwarePickerTypes = useMemo(() => ['hardware'], []);

  const applyListFilter = useCallback((patch) => {
    setListOffset(0);
    setQ((q0) => ('q' in patch ? patch.q : q0));
    setTagFilter((t0) => ('tag' in patch ? patch.tag : t0));
    setRoleFilter((r0) => ('role' in patch ? patch.role : r0));
    setListSort((s0) => ('sort' in patch ? patch.sort : s0));
    setSelection((prev) =>
      selectionAfterFilterChange({
        q: 'q' in patch ? patch.q : prev.filter?.q || '',
        role: 'role' in patch ? patch.role : prev.filter?.role || '',
        tag: 'tag' in patch ? patch.tag : prev.filter?.tag || '',
        sort: 'sort' in patch ? patch.sort : prev.filter?.sort || 'name',
        direction: prev.filter?.direction || 'asc',
      })
    );
  }, []);

  const monitorTargetIds = useMemo(() => items.map((i) => i.id), [items]);
  const monitors = useTargetMonitors('hardware', monitorTargetIds);

  const selectedIds = selection.mode === SELECTION_MODE_ALL_MATCHING ? [] : selection.ids;
  const selectedCount = selectionCount(selection);

  const COLUMNS = useMemo(
    () => [
      { key: 'id', label: 'ID' },
      { key: 'name', label: 'Name' },
      { key: 'role', label: 'Role', render: (v) => HARDWARE_ROLE_LABELS[v] ?? v ?? '—' },
      {
        key: 'vendor',
        label: 'Vendor',
        render: (v, row) => {
          if (!v && !row?.vendor_icon_slug) return null;
          if (vendorIconMode === 'none' && !row?.vendor_icon_slug) return <span>{v}</span>;
          if (row?.vendor_icon_slug) {
            return (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <IconImg slug={row.vendor_icon_slug} size={16} />
                {v ? (getVendorIcon(v)?.label ?? v) : ''}
              </span>
            );
          }
          const info = getVendorIcon(v);
          return (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <img src={info.path} alt={info.label} style={{ width: 16, height: 16 }} />
              {info.label}
            </span>
          );
        },
      },
      ...TAIL_COLUMNS,
      {
        key: 'monitor',
        label: 'Monitor',
        render: (_, row) => <MonitorStatusCell state={monitors.byId[row.id]} />,
      },
      {
        key: 'tags',
        label: 'Tags',
        render: (v, row) => (
          <TagsCell
            tags={v || []}
            allTags={allTags}
            onTagsChange={async (names) => {
              await hardwareApi.update(row.id, { tags: names });
              fetchData();
            }}
            onTagColorChange={async (id, color) => {
              await tagsApi.update(id, { color });
              fetchTags();
            }}
          />
        ),
      },
    ],
    [vendorIconMode, allTags, fetchData, fetchTags, HARDWARE_ROLE_LABELS, monitors.byId]
  );

  const HARDWARE_EDITABLE = [
    'name',
    'location',
    'model',
    'cpu',
    'memory_gb',
    'ip_address',
    'wan_uplink',
  ];
  const HARDWARE_BULK_ACTIONS = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          if (selection.mode === SELECTION_MODE_ALL_MATCHING) {
            toast.warn(
              'All-matching delete is not available yet. Select specific rows on this page, or narrow the filter.'
            );
            return;
          }
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} hardware node(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await hardwareApi.delete(id);
              toast.success('Deleted.');
              setSelection(clearSelection(selection));
              fetchData();
            },
          });
        },
      },
    ],
    [toast, fetchData, selection]
  );
  const CLUSTER_BULK_ACTIONS = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} cluster(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await clustersApi.delete(id);
              toast.success('Deleted.');
              setClusterSelectedIds([]);
              cachedClusterList.invalidate();
              fetchClusters();
            },
          });
        },
      },
    ],
    [toast, fetchClusters]
  );

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      const payload = {};
      if (columnKey === 'memory_gb') {
        payload[columnKey] = value === '' ? null : Number(value);
      } else {
        payload[columnKey] = value;
      }
      await hardwareApi.update(row.id, payload);
      toast.success('Saved.');
      fetchData();
    },
    [toast, fetchData]
  );

  const handleSubmit = async (values) => {
    try {
      let saved;
      if (editTarget) {
        const res = await hardwareApi.update(editTarget.id, values);
        saved = res.data;
        toast.success('Hardware updated.');
      } else {
        const res = await hardwareApi.create(values);
        saved = res.data;
        toast.success('Hardware node created.');
      }
      setShowForm(false);
      setEditTarget(null);
      setFormApiErrors({});
      setFormConflict(null);
      if (saved && detailTarget?.id === saved.id) {
        setDetailTarget(saved);
      }
      fetchData();
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
      if (err.errorCode === 'ip_conflict') {
        setFormConflict(err.conflictContext || null);
      }
    }
  };

  const handleDelete = async (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this hardware node?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await hardwareApi.delete(id);
          toast.success('Hardware node deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  const monitorAction = useCallback(
    async (fn, successMsg) => {
      try {
        await fn();
        toast.success(successMsg);
      } catch (err) {
        const status = err?.response?.status;
        toast.error(
          status === 404
            ? 'No address to probe — add an IP address or hostname first.'
            : err?.response?.data?.detail || err.message || 'Failed to update monitoring.'
        );
      }
    },
    [toast]
  );

  const handleClusterSubmit = async (values) => {
    try {
      if (editCluster) {
        await clustersApi.update(editCluster.id, values);
        toast.success('Cluster updated.');
      } else {
        await clustersApi.create(values);
        toast.success('Cluster created.');
      }
      setShowClusterForm(false);
      setEditCluster(null);
      setClusterFormErrors({});
      cachedClusterList.invalidate();
      fetchClusters();
    } catch (err) {
      if (err.fieldErrors) {
        setClusterFormErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const handleClusterDelete = async (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this cluster? All member assignments will also be removed.',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await clustersApi.delete(id);
          toast.success('Cluster deleted.');
          cachedClusterList.invalidate();
          fetchClusters();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{activeTab === 'hardware' ? 'Hardware' : 'Hardware Clusters'}</h2>
        {activeTab === 'hardware' ? (
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditTarget(null);
              setShowForm(true);
            }}
          >
            + Add Hardware
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditCluster(null);
              setShowClusterForm(true);
            }}
          >
            + Add Cluster
          </button>
        )}
      </div>

      <div className="tab-bar" style={{ marginBottom: 16 }}>
        <button
          className={`tab-btn${activeTab === 'hardware' ? ' active' : ''}`}
          onClick={() => setActiveTab('hardware')}
        >
          Hardware
        </button>
        <button
          className={`tab-btn${activeTab === 'clusters' ? ' active' : ''}`}
          onClick={() => {
            if (detailTarget) closeEntity();
            setActiveTab('clusters');
          }}
        >
          Clusters {clusters.length > 0 && <span className="tab-badge">{clusters.length}</span>}
        </button>
      </div>

      {activeTab === 'hardware' && (
        <>
          <div className="filter-bar">
            <SearchBox value={q} onChange={(value) => applyListFilter({ q: value })} />
            <TagFilter value={tagFilter} onChange={(value) => applyListFilter({ tag: value })} />
            <select
              className="filter-select"
              aria-label="Filter by roles"
              value={roleFilter}
              onChange={(e) => applyListFilter({ role: e.target.value })}
              title="Filter by role"
            >
              <option value="">All roles</option>
              {HARDWARE_ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
            <select
              className="filter-select"
              aria-label="Sort hardware"
              value={listSort}
              onChange={(e) => applyListFilter({ sort: e.target.value })}
            >
              <option value="name">Name A–Z</option>
              <option value="role">Role</option>
              <option value="status">Status</option>
              <option value="updated_at">Updated</option>
            </select>
            <button type="button" className="btn btn-sm" onClick={() => setPickerOpen(true)}>
              Find asset
            </button>
          </div>

          {!loading && items.length === 0 && !listError && settings?.show_page_hints && (
            <div className="info-tip" style={{ marginBottom: 12 }}>
              💡 <strong>Tip:</strong> Start by adding hardware nodes — these represent physical
              machines and are required before creating compute units or services.
            </div>
          )}

          {listError && !loading && (
            <div className="info-tip" style={{ marginBottom: 12 }} role="alert">
              {listError}{' '}
              <button type="button" className="text-btn" onClick={fetchData}>
                Retry
              </button>
            </div>
          )}

          {loading ? (
            <SkeletonTable cols={7} />
          ) : (
            <EntityTable
              columns={COLUMNS}
              data={items}
              onEdit={(row) => {
                setEditTarget(row);
                setFormConflict(null);
                setShowForm(true);
              }}
              onDelete={handleDelete}
              renderMonitorAction={(row) => (
                <MonitorCell
                  state={monitors.byId[row.id]}
                  onEnable={() =>
                    monitorAction(() => monitors.enable(row.id), 'Monitoring enabled.')
                  }
                  onPause={() => monitorAction(() => monitors.pause(row.id), 'Monitoring paused.')}
                  onResume={() =>
                    monitorAction(() => monitors.resume(row.id), 'Monitoring resumed.')
                  }
                  onCheckNow={() =>
                    monitorAction(() => monitors.checkNow(row.id), 'Probe triggered.')
                  }
                />
              )}
              onRowClick={openEntity}
              editableColumns={HARDWARE_EDITABLE}
              onCellSave={handleCellSave}
              selectable
              selectedIds={selectedIds}
              rowIsSelected={(id) => isRowSelected(selection, id)}
              onSelectionChange={(ids) => {
                setSelection({
                  ...emptySelection(listFilter),
                  mode: SELECTION_MODE_IDS,
                  ids,
                });
              }}
              bulkActions={HARDWARE_BULK_ACTIONS}
              serverPaging={{
                total: listTotal,
                limit: listLimit,
                offset: listOffset,
                onPageChange: setListOffset,
                onLimitChange: (next) => {
                  setListLimit(next);
                  setListOffset(0);
                },
              }}
              selectionToolbar={
                selectedCount > 0 ? (
                  <div className="tw-flex tw-items-center tw-justify-between tw-gap-3 tw-mb-2 tw-px-3 tw-py-2 tw-rounded tw-border tw-border-cb-border tw-bg-cb-surface-raised/40">
                    <span className="tw-text-sm tw-text-cb-text">
                      <strong>{selectedCount}</strong> {selectionScopeLabel(selection)}
                    </span>
                    <div className="tw-flex tw-items-center tw-gap-3">
                      {selection.mode !== SELECTION_MODE_ALL_MATCHING &&
                        listTotal > items.length && (
                          <button
                            type="button"
                            className="text-btn"
                            onClick={() =>
                              setSelection(
                                selectAllMatching({ ...selection, filter: listFilter }, listTotal)
                              )
                            }
                          >
                            Select all {listTotal} matching
                          </button>
                        )}
                      <button
                        type="button"
                        className="text-btn tw-text-cb-text-muted"
                        onClick={() => setSelection(clearSelection(selection))}
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                ) : null
              }
            />
          )}
        </>
      )}

      {activeTab === 'clusters' && (
        <>
          {!clustersLoading && clusters.length === 0 && settings?.show_page_hints && (
            <div className="info-tip" style={{ marginBottom: 12 }}>
              💡 <strong>Tip:</strong> Clusters group related hardware into logical units (e.g. a
              rack or HA pair). Add hardware nodes first, then assign them to a cluster from the
              cluster’s detail panel.
            </div>
          )}
          {clustersLoading ? (
            <SkeletonTable cols={4} />
          ) : (
            <EntityTable
              columns={CLUSTER_COLUMNS}
              data={clusters}
              onEdit={(row) => {
                setEditCluster(row);
                setShowClusterForm(true);
              }}
              onDelete={(id) => handleClusterDelete(id)}
              onRowClick={(row) => setClusterDetail(row)}
              editableColumns={['name', 'location']}
              onCellSave={async (row, columnKey, value) => {
                if (value == null) return;
                await clustersApi.update(row.id, { [columnKey]: value });
                toast.success('Saved.');
                cachedClusterList.invalidate();
                fetchClusters();
              }}
              selectable
              selectedIds={clusterSelectedIds}
              onSelectionChange={setClusterSelectedIds}
              bulkActions={CLUSTER_BULK_ACTIONS}
            />
          )}
        </>
      )}

      <HardwareDetail hardware={detailTarget} isOpen={!!detailTarget} onClose={closeEntity} />

      <ClusterDetail
        cluster={clusterDetail}
        isOpen={!!clusterDetail}
        onClose={() => setClusterDetail(null)}
        onUpdate={fetchClusters}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Hardware' : 'New Hardware'}
        fields={buildFields(editTarget?.vendor_icon_slug ?? null)}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onValidate={(values) => {
          const errors = {};
          const nameErr = validateDuplicateName(values.name, items, editTarget?.id);
          if (nameErr) errors.name = nameErr;
          const ipErr = validateIpAddress(values.ip_address);
          if (ipErr) errors.ip_address = ipErr;
          return errors;
        }}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
          setFormApiErrors({});
          setFormConflict(null);
        }}
        apiErrors={formApiErrors}
        entityType="hardware"
        entityId={editTarget?.id}
      />

      {showForm && formConflict && (
        <div
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            zIndex: 120,
            maxWidth: 420,
          }}
        >
          <IpConflictAlert
            conflictContext={formConflict}
            onInspect={async (conflict) => {
              if (!conflict?.entity_id) return;
              try {
                if (conflict.entity_type === 'hardware') {
                  const res = await hardwareApi.get(conflict.entity_id);
                  openEntity(res.data);
                } else {
                  toast.info('Open the conflicting asset from Inventory to inspect it.');
                }
              } catch (err) {
                toast.error(err.message || 'Could not open the conflicting asset.');
              }
            }}
          />
        </div>
      )}

      <EntityPicker
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        types={hardwarePickerTypes}
        action="view"
        onSelect={(opt) => {
          const id = opt?.ref?.entity_id;
          if (!id) return;
          hardwareApi
            .get(id)
            .then((res) => openEntity(res.data))
            .catch((err) => toast.error(err.message));
        }}
      />

      <FormModal
        open={showClusterForm}
        title={editCluster ? 'Edit Cluster' : 'New Cluster'}
        fields={CLUSTER_FIELDS(environments)}
        initialValues={editCluster || {}}
        onSubmit={handleClusterSubmit}
        onClose={() => {
          setShowClusterForm(false);
          setEditCluster(null);
          setClusterFormErrors({});
        }}
        apiErrors={clusterFormErrors}
      />

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />

      {iconPickerOpen && (
        <IconPickerModal
          currentSlug={pendingIconSlug}
          onSelect={(slug) => {
            iconPickerCallback?.(slug);
            setIconPickerOpen(false);
          }}
          onClose={() => setIconPickerOpen(false)}
        />
      )}
    </div>
  );
}

export default HardwarePage;
