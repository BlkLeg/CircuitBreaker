import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import Drawer from './Drawer';
import { inventoryApi } from '../../api/client';
import { toOptionRef } from '../../lib/inventoryList';

const SEARCH_DEBOUNCE_MS = 200;
const EMPTY_SELECTED = [];

/**
 * Bounded inventory option picker backed by GET /inventory/options.
 * Search is independent of any table page currently on screen.
 */
export default function EntityPicker({
  isOpen,
  onClose,
  title = 'Find an inventory asset',
  action = 'view',
  types = undefined,
  selected = EMPTY_SELECTED,
  onSelect,
}) {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState([]);
  const [selectedLabels, setSelectedLabels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const requestSeq = useRef(0);

  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (!isOpen) return undefined;

    const seq = ++requestSeq.current;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const params = {
          action,
          limit: 25,
          q: query || undefined,
        };
        if (types?.length) params.types = types;
        if (selected.length) {
          params.selected = selected.map((ref) =>
            typeof ref === 'string' ? ref : toOptionRef(ref.entity_type, ref.entity_id)
          );
        }
        const res = await inventoryApi.options(params);
        if (seq !== requestSeq.current) return;
        setItems(res.data.items || []);
        setSelectedLabels(res.data.selected || []);
        setHasMore(Boolean(res.data.has_more));
      } catch (err) {
        if (seq !== requestSeq.current) return;
        setError(err.message || 'Could not load inventory options.');
        setItems([]);
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    }, SEARCH_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [isOpen, query, action, types, selected]);

  useEffect(() => {
    if (wasOpenRef.current && !isOpen) {
      setQuery('');
      setItems([]);
      setError(null);
      setSelectedLabels([]);
      setHasMore(false);
    }
    wasOpenRef.current = isOpen;
  }, [isOpen]);

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={title} width="440px">
      <div className="tw-flex tw-flex-col tw-gap-3">
        <label className="tw-text-xs tw-text-cb-text-muted" htmlFor="entity-picker-search">
          Search every page
        </label>
        <input
          id="entity-picker-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Name, address, or label"
          className="tw-w-full tw-h-9 tw-rounded tw-border tw-border-cb-border tw-bg-cb-bg tw-text-cb-text tw-px-3 tw-text-sm focus:tw-outline-none focus:tw-ring-1 focus:tw-ring-cb-primary"
          autoFocus
        />
        {selectedLabels.length > 0 && (
          <div className="tw-text-xs tw-text-cb-text-muted">
            Selected:{' '}
            {selectedLabels.map((opt) => (
              <span key={opt.ref?.key || opt.label} className="tw-mr-2">
                {opt.label}
                {!opt.available ? ` (${opt.unavailable_reason || 'unavailable'})` : ''}
              </span>
            ))}
          </div>
        )}
        {loading && <p className="tw-text-sm tw-text-cb-text-muted">Searching…</p>}
        {error && (
          <p className="tw-text-sm tw-text-cb-danger" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && items.length === 0 && (
          <p className="tw-text-sm tw-text-cb-text-muted">No matching assets.</p>
        )}
        <ul className="tw-list-none tw-m-0 tw-p-0 tw-flex tw-flex-col">
          {items.map((opt) => (
            <li key={opt.ref?.key || `${opt.ref?.entity_type}:${opt.ref?.entity_id}`}>
              <button
                type="button"
                className="tw-w-full tw-text-left tw-border-0 tw-border-b tw-border-cb-border tw-bg-transparent tw-text-cb-text tw-px-0 tw-py-3 hover:tw-bg-cb-surface-raised"
                onClick={() => {
                  onSelect?.(opt);
                  onClose();
                }}
                disabled={!opt.available}
              >
                <strong className="tw-font-medium">{opt.label}</strong>
                {opt.description && (
                  <span className="tw-block tw-text-xs tw-text-cb-text-muted tw-mt-1">
                    {opt.description}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
        {hasMore && (
          <p className="tw-text-xs tw-text-cb-text-muted">
            More matches exist — refine the search to narrow results.
          </p>
        )}
        <p className="tw-text-xs tw-text-cb-text-muted">
          Results are independent of the current table page and filters.
        </p>
      </div>
    </Drawer>
  );
}

EntityPicker.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  title: PropTypes.string,
  action: PropTypes.oneOf(['view', 'relate', 'monitor', 'docker_parent']),
  types: PropTypes.arrayOf(PropTypes.string),
  selected: PropTypes.arrayOf(
    PropTypes.oneOfType([
      PropTypes.string,
      PropTypes.shape({
        entity_type: PropTypes.string.isRequired,
        entity_id: PropTypes.number.isRequired,
      }),
    ])
  ),
  onSelect: PropTypes.func,
};
