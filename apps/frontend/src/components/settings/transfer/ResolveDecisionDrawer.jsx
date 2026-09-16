import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../../common/Drawer';
import {
  clustersApi,
  computeUnitsApi,
  docsApi,
  externalNodesApi,
  hardwareApi,
  miscApi,
  networksApi,
  servicesApi,
  storageApi,
  tagsApi,
} from '../../../api/client.jsx';
import {
  UNIQUE_FIELDS,
  defaultDecisionFor,
  isRelationKind,
  proposedRenameValue,
  referenceTargetKind,
} from '../../../lib/inventoryTransfer';

const TARGET_FETCHERS = {
  hardware: { fetch: () => hardwareApi.list(), label: (row) => row.name },
  compute_units: { fetch: () => computeUnitsApi.list(), label: (row) => row.name },
  services: { fetch: () => servicesApi.list(), label: (row) => row.name },
  storage: { fetch: () => storageApi.list(), label: (row) => row.name },
  networks: { fetch: () => networksApi.list(), label: (row) => row.name },
  misc_items: { fetch: () => miscApi.list(), label: (row) => row.name },
  docs: { fetch: () => docsApi.list(), label: (row) => row.title ?? row.name },
  tags: { fetch: () => tagsApi.list(), label: (row) => row.name },
  hardware_clusters: { fetch: () => clustersApi.list(), label: (row) => row.name },
  external_nodes: { fetch: () => externalNodesApi.list(), label: (row) => row.name },
};

/** Pick one existing local record of a portable kind. */
function LocalTargetPicker({ kind, value, onChange }) {
  const [options, setOptions] = useState(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    let cancelled = false;
    setOptions(null);
    setFailed(false);
    const fetcher = TARGET_FETCHERS[kind];
    if (!fetcher) {
      setFailed(true);
      return undefined;
    }
    fetcher
      .fetch()
      .then((res) => {
        if (cancelled) return;
        const data = res?.data;
        setOptions(Array.isArray(data) ? data : (data?.items ?? []));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [kind]);

  if (failed) {
    return <p className="inv-picker__note">Local {kind} records could not be loaded.</p>;
  }
  if (options === null) return <p className="inv-picker__note">Loading local records…</p>;

  const labelOf = TARGET_FETCHERS[kind]?.label ?? ((row) => row?.name ?? `#${row?.id}`);
  const filtered = filter
    ? options.filter((row) =>
        String(labelOf(row) ?? '')
          .toLowerCase()
          .includes(filter.toLowerCase())
      )
    : options;

  return (
    <div className="inv-picker">
      <input
        type="search"
        className="inv-picker__filter"
        placeholder={`Filter local ${kind}`}
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        aria-label={`Filter local ${kind} records`}
      />
      <select
        className="inv-picker__select"
        value={value ?? ''}
        onChange={(event) => {
          const id = event.target.value ? Number(event.target.value) : null;
          const row = options.find((item) => item.id === id) ?? null;
          onChange(id, row ? String(labelOf(row)) : null);
        }}
      >
        <option value="">Choose an existing record…</option>
        {filtered.map((row) => (
          <option key={row.id} value={row.id}>
            {labelOf(row)} · #{row.id}
          </option>
        ))}
      </select>
      {filtered.length === 0 ? (
        <p className="inv-picker__note">No local {kind} records match.</p>
      ) : null}
    </div>
  );
}

/**
 * The per-conflict decision drawer (plan 02): keep-both rename, explicit match,
 * or reassign a broken reference to an existing local record. The preview must
 * accept a decision before it is saved, so a bad rename never sticks.
 */
export default function ResolveDecisionDrawer({
  open,
  conflict,
  existingDecision,
  document: portableDocument,
  busy,
  error,
  onSave,
  onClose,
}) {
  const [action, setAction] = useState(null);
  const [renameValue, setRenameValue] = useState('');
  const [targetId, setTargetId] = useState(null);
  const [targetLabel, setTargetLabel] = useState(null);

  const setTargetIdWithLabel = (id, label) => {
    setTargetId(id);
    setTargetLabel(label);
  };

  useEffect(() => {
    if (!open || !conflict) return;
    const base = existingDecision ?? defaultDecisionFor(conflict, portableDocument);
    setAction(base?.action ?? null);
    setRenameValue(
      base?.newValue ??
        proposedRenameValue(conflict.row, conflict.field ?? UNIQUE_FIELDS[conflict.entity_type])
    );
    setTargetId(base?.targetId ?? null);
    setTargetLabel(base?.targetLabel ?? null);
  }, [open, conflict, existingDecision, portableDocument]);

  if (!conflict) return null;

  const uniqueField = UNIQUE_FIELDS[conflict.entity_type];
  const isReferenceIssue = conflict.reason_code === 'missing_reference';
  const canRename = Boolean(uniqueField) && !isRelationKind(conflict.entity_type);
  const canMatch = !isRelationKind(conflict.entity_type) && !isReferenceIssue;
  const canReassign = isReferenceIssue;
  const targetKind = canReassign
    ? referenceTargetKind(conflict.entity_type, conflict.field, conflict.row)
    : conflict.entity_type;

  const saveReady =
    (action === 'rename' && renameValue.trim().length > 0) ||
    ((action === 'match' || action === 'reassign') && targetId != null);

  const handleSave = async () => {
    if (!saveReady) return;
    const decision =
      action === 'rename'
        ? { action: 'rename', newValue: renameValue.trim() }
        : { action, field: isReferenceIssue ? conflict.field : null, targetId, targetLabel };
    const body = await onSave(decision);
    if (body) onClose();
  };

  return (
    <Drawer
      isOpen={open}
      onClose={onClose}
      title={`Resolve ${conflict.row?.name ?? conflict.entity_type}`}
    >
      <div className="inv-resolve">
        <p className="inv-resolve__message" role="status">
          {conflict.message}
        </p>
        {canReassign ? null : (
          <p className="inv-resolve__hint">
            Existing relationships are preserved and incoming references are remapped.
          </p>
        )}
        <fieldset className="inv-resolve__options">
          <legend>Proposed decision</legend>
          {canRename ? (
            <label className="inv-resolve__option">
              <input
                type="radio"
                name="transfer-decision"
                checked={action === 'rename'}
                onChange={() => setAction('rename')}
              />
              <span>
                Keep both — rename the incoming record
                {action === 'rename' ? (
                  <input
                    type="text"
                    className="inv-resolve__input"
                    value={renameValue}
                    maxLength={200}
                    aria-label={`New ${conflict.field ?? uniqueField} for the incoming record`}
                    onChange={(event) => setRenameValue(event.target.value)}
                  />
                ) : null}
              </span>
            </label>
          ) : null}
          {canMatch ? (
            <label className="inv-resolve__option">
              <input
                type="radio"
                name="transfer-decision"
                checked={action === 'match'}
                onChange={() => setAction('match')}
              />
              <span>
                Match an existing record
                {action === 'match' ? (
                  <LocalTargetPicker
                    kind={conflict.entity_type}
                    value={targetId}
                    onChange={setTargetIdWithLabel}
                  />
                ) : null}
              </span>
            </label>
          ) : null}
          {canReassign ? (
            <label className="inv-resolve__option">
              <input
                type="radio"
                name="transfer-decision"
                checked={action === 'reassign'}
                onChange={() => setAction('reassign')}
              />
              <span>
                Assign {conflict.field} to an existing local record
                {action === 'reassign' && targetKind ? (
                  <LocalTargetPicker
                    kind={targetKind}
                    value={targetId}
                    onChange={setTargetIdWithLabel}
                  />
                ) : null}
              </span>
            </label>
          ) : null}
        </fieldset>
        {error ? (
          <p className="inv-resolve__error" role="alert">
            {error.message}
          </p>
        ) : null}
        <div className="inv-resolve__actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!saveReady || busy}
            onClick={handleSave}
          >
            {busy ? 'Saving…' : 'Save decision'}
          </button>
        </div>
        <p className="inv-resolve__note">No changes have been applied.</p>
      </div>
    </Drawer>
  );
}

const conflictShape = PropTypes.shape({
  entity_type: PropTypes.string.isRequired,
  source_id: PropTypes.number.isRequired,
  reason_code: PropTypes.string.isRequired,
  message: PropTypes.string.isRequired,
  field: PropTypes.string,
  candidates: PropTypes.arrayOf(PropTypes.number),
  candidate_labels: PropTypes.arrayOf(PropTypes.string),
  row: PropTypes.object,
});

ResolveDecisionDrawer.propTypes = {
  open: PropTypes.bool.isRequired,
  conflict: conflictShape,
  existingDecision: PropTypes.shape({
    action: PropTypes.string,
    newValue: PropTypes.string,
    targetId: PropTypes.number,
    targetLabel: PropTypes.string,
  }),
  document: PropTypes.object,
  busy: PropTypes.bool,
  error: PropTypes.shape({ message: PropTypes.string }),
  onSave: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};
