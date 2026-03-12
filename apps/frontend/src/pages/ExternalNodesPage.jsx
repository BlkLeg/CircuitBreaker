import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import IconPickerModal, { IconImg } from '../components/common/IconPickerModal';
import TagsCell from '../components/TagsCell';
import { externalNodesApi, networksApi, tagsApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Drawer from '../components/common/Drawer';
import { useToast } from '../components/common/Toast';
import { useSettings } from '../context/SettingsContext';
import { validateDuplicateName } from '../utils/validation';

const PROVIDER_OPTIONS = [
  'AWS',
  'Azure',
  'Google Cloud',
  'Hetzner',
  'DigitalOcean',
  'Linode',
  'Vultr',
  'OVHcloud',
  'Cloudflare',
  'Oracle Cloud',
  'DreamHost',
  'Contabo',
  'Other',
];
const KIND_OPTIONS = [
  'vps',
  'managed_db',
  'saas',
  'vpn_gateway',
  'cdn',
  'dns',
  'object_storage',
  'serverless',
  'container_registry',
  'load_balancer',
  'other',
];
const LINK_TYPE_OPTIONS = ['vpn', 'wan', 'wireguard', 'reverse_proxy', 'direct', 'other'];

function ExternalNodesPage() {
  const toast = useToast();
  const { settings } = useSettings();
  const [items, setItems] = useState([]);
  const [networks, setNetworks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [nodeNetworks, setNodeNetworks] = useState([]);
  const [nodeServices, setNodeServices] = useState([]);
  const [showLinkNetworkForm, setShowLinkNetworkForm] = useState(false);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [envFilter, setEnvFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);
  const [allTags, setAllTags] = useState([]);
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [pendingIconSlug, setPendingIconSlug] = useState(null);
  const [iconPickerCallback, setIconPickerCallback] = useState(null);

  const envOptions = useMemo(
    () => settings?.environments || ['prod', 'staging', 'dev'],
    [settings]
  );

  const COLUMNS = useMemo(
    () => [
      { key: 'id', label: 'ID' },
      {
        key: 'icon_slug',
        label: '',
        render: (v) => (v ? <IconImg slug={v} size={20} /> : null),
      },
      { key: 'name', label: 'Name' },
      { key: 'provider', label: 'Provider' },
      { key: 'kind', label: 'Kind' },
      { key: 'region', label: 'Region' },
      { key: 'ip_address', label: 'IP Address' },
      { key: 'environment', label: 'Environment' },
      { key: 'networks_count', label: 'Networks' },
      { key: 'services_count', label: 'Services' },
    ],
    []
  );

  const buildFields = useCallback(
    (currentIcon) => [
      { name: 'name', label: 'Name', required: true },
      {
        name: 'icon_slug',
        label: 'Icon',
        type: 'icon-picker',
        value: currentIcon,
        onOpenPicker: (slug, onSelect) => {
          setPendingIconSlug(slug);
          setIconPickerCallback(() => onSelect);
          setIconPickerOpen(true);
        },
      },
      {
        name: 'provider',
        label: 'Provider',
        type: 'select',
        options: PROVIDER_OPTIONS.map((p) => ({ value: p, label: p })),
      },
      {
        name: 'kind',
        label: 'Kind',
        type: 'select',
        options: KIND_OPTIONS.map((k) => ({ value: k, label: k })),
      },
      { name: 'region', label: 'Region' },
      { name: 'ip_address', label: 'IP Address / Hostname' },
      {
        name: 'environment',
        label: 'Environment',
        type: 'select',
        options: envOptions.map((e) => ({ value: e, label: e })),
      },
      { name: 'notes', label: 'Notes', type: 'textarea' },
      { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
    ],
    [envOptions]
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (providerFilter) params.provider = providerFilter;
      if (kindFilter) params.kind = kindFilter;
      if (envFilter) params.environment = envFilter;
      const [extRes, netRes] = await Promise.all([
        externalNodesApi.list(params),
        networksApi.list(),
      ]);
      setItems(extRes.data);
      setNetworks(netRes.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, providerFilter, kindFilter, envFilter, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchTags = useCallback(async () => {
    try {
      const res = await tagsApi.list();
      setAllTags(res.data || []);
    } catch {
      setAllTags([]);
    }
  }, []);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  const COLUMNS_WITH_TAGS = useMemo(
    () => [
      ...COLUMNS,
      {
        key: 'tags',
        label: 'Tags',
        render: (v, row) => (
          <TagsCell
            tags={v || []}
            allTags={allTags}
            onTagsChange={async (names) => {
              await externalNodesApi.update(row.id, { tags: names });
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
    [allTags, fetchData, fetchTags, COLUMNS]
  );

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      await externalNodesApi.update(row.id, { [columnKey]: value });
      toast.success('Saved.');
      fetchData();
    },
    [toast, fetchData]
  );

  const bulkActions = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} external node(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await externalNodesApi.delete(id);
              toast.success('Deleted.');
              setSelectedIds([]);
              fetchData();
            },
          });
        },
      },
    ],
    [toast, fetchData]
  );

  const fetchDetail = useCallback(
    async (node) => {
      try {
        const [netRes, svcRes] = await Promise.all([
          externalNodesApi.getNetworks(node.id),
          externalNodesApi.getServices(node.id),
        ]);
        setNodeNetworks(netRes.data);
        setNodeServices(svcRes.data);
      } catch (err) {
        toast.error(err.message);
      }
    },
    [toast]
  );

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await externalNodesApi.update(editTarget.id, values);
        toast.success('External node updated.');
      } else {
        await externalNodesApi.create(values);
        toast.success('External node created.');
      }
      setShowForm(false);
      setEditTarget(null);
      setFormApiErrors({});
      fetchData();
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleDelete = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this external node? All linked relationships will also be removed.',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await externalNodesApi.delete(id);
          toast.success('External node deleted.');
          if (detailTarget?.id === id) setDetailTarget(null);
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  const handleLinkNetwork = async (values) => {
    try {
      await externalNodesApi.addNetwork(detailTarget.id, values);
      toast.success('Network linked.');
      setShowLinkNetworkForm(false);
      fetchDetail(detailTarget);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleUnlinkNetwork = async (relId) => {
    try {
      await externalNodesApi.removeNetwork(relId);
      toast.success('Network unlinked.');
      fetchDetail(detailTarget);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const openDetail = (row) => {
    setDetailTarget(row);
    fetchDetail(row);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>External / Cloud Nodes</h2>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditTarget(null);
            setShowForm(true);
          }}
        >
          + Add External Node
        </button>
      </div>

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <select
          className="filter-select"
          value={providerFilter}
          onChange={(e) => setProviderFilter(e.target.value)}
        >
          <option value="">All Providers</option>
          {PROVIDER_OPTIONS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select
          className="filter-select"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
        >
          <option value="">All Kinds</option>
          {KIND_OPTIONS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <select
          className="filter-select"
          value={envFilter}
          onChange={(e) => setEnvFilter(e.target.value)}
        >
          <option value="">All Environments</option>
          {envOptions.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </select>
      </div>

      {!loading && items.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 8 }}>
          💡 <strong>Tip:</strong> Add external/cloud nodes (VPS, managed databases, SaaS
          dependencies) here. You can link them to your local networks and services.
        </div>
      )}

      {loading ? (
        <SkeletonTable cols={6} />
      ) : (
        <EntityTable
          columns={COLUMNS_WITH_TAGS}
          data={items}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={handleDelete}
          onRowClick={openDetail}
          editableColumns={['name', 'provider', 'kind', 'region', 'ip_address', 'environment']}
          onCellSave={handleCellSave}
          selectable
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          bulkActions={bulkActions}
        />
      )}

      {/* Detail Panel */}
      <Drawer
        isOpen={!!detailTarget}
        onClose={() => {
          setDetailTarget(null);
          setNodeNetworks([]);
          setNodeServices([]);
        }}
        title={detailTarget?.name || ''}
      >
        {detailTarget && (
          <div className="detail-content">
            <div className="detail-section">
              <h4>Info</h4>
              {detailTarget.icon_slug && (
                <p>
                  <IconImg slug={detailTarget.icon_slug} size={28} />{' '}
                  <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                    {detailTarget.icon_slug}
                  </span>
                </p>
              )}
              <p>
                <strong>Provider:</strong> {detailTarget.provider || '—'}
              </p>
              <p>
                <strong>Kind:</strong> {detailTarget.kind || '—'}
              </p>
              <p>
                <strong>Region:</strong> {detailTarget.region || '—'}
              </p>
              <p>
                <strong>IP:</strong> {detailTarget.ip_address || '—'}
              </p>
              <p>
                <strong>Environment:</strong> {detailTarget.environment || '—'}
              </p>
              <p>
                <strong>Tags:</strong> {(detailTarget.tags || []).join(', ') || '—'}
              </p>
              {detailTarget.notes && (
                <p>
                  <strong>Notes:</strong> {detailTarget.notes}
                </p>
              )}
            </div>

            <div className="detail-section">
              <div
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <h4>Connected Networks ({nodeNetworks.length})</h4>
                <button className="btn btn-sm" onClick={() => setShowLinkNetworkForm(true)}>
                  + Link Network
                </button>
              </div>
              {nodeNetworks.length === 0 ? (
                <p className="text-muted">No networks linked.</p>
              ) : (
                <ul className="link-list">
                  {nodeNetworks.map((link) => (
                    <li key={link.id}>
                      <span>{link.network_name || `Network #${link.network_id}`}</span>
                      {link.link_type && <span className="badge">{link.link_type}</span>}
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleUnlinkNetwork(link.id)}
                        title="Unlink"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="detail-section">
              <h4>Dependent Services ({nodeServices.length})</h4>
              {nodeServices.length === 0 ? (
                <p className="text-muted">No services depend on this node.</p>
              ) : (
                <ul className="link-list">
                  {nodeServices.map((link) => (
                    <li key={link.id}>
                      <span>{link.service_name || `Service #${link.service_id}`}</span>
                      {link.purpose && <span className="badge">{link.purpose}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit External Node' : 'New External Node'}
        fields={buildFields(editTarget?.icon_slug ?? null)}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onValidate={(values) => {
          const errors = {};
          const nameErr = validateDuplicateName(values.name, items, editTarget?.id);
          if (nameErr) errors.name = nameErr;
          return errors;
        }}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
          setFormApiErrors({});
        }}
        apiErrors={formApiErrors}
      />

      {/* Link network modal */}
      <FormModal
        open={showLinkNetworkForm}
        title="Link Network to External Node"
        fields={[
          {
            name: 'network_id',
            label: 'Network',
            type: 'select',
            required: true,
            options: networks.map((n) => ({
              value: n.id,
              label: `${n.name}${n.cidr ? ` (${n.cidr})` : ''}`,
            })),
          },
          {
            name: 'link_type',
            label: 'Link Type',
            type: 'select',
            options: LINK_TYPE_OPTIONS.map((t) => ({ value: t, label: t })),
          },
          { name: 'notes', label: 'Notes', type: 'textarea' },
        ]}
        initialValues={{}}
        onSubmit={handleLinkNetwork}
        onClose={() => setShowLinkNetworkForm(false)}
      />

      {iconPickerOpen && (
        <IconPickerModal
          currentSlug={pendingIconSlug}
          onSelect={(slug) => {
            if (iconPickerCallback) iconPickerCallback(slug);
          }}
          onClose={() => setIconPickerOpen(false)}
        />
      )}

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default ExternalNodesPage;
