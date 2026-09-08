import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { AlertTriangle, Clock, Loader2, Pin, Search } from 'lucide-react';
import NavigatorResultRow from './NavigatorResultRow.jsx';
import { NAV_GROUPS, canSeeNavItem } from '../../data/navigation';
import { buildLocalIndex } from '../../lib/navigationSearch';
import {
  namespaceFor,
  readPins,
  readRecents,
  togglePin as togglePinStored,
} from '../../lib/navigatorPrefs';
import { useNavigatorSearch } from '../../hooks/useNavigatorSearch';
import { useAuth } from '../../context/AuthContext.jsx';
import { useIsMobile } from '../../hooks/useIsMobile';
import '../../styles/navigator.css';

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '');

// A search keystroke re-renders every visible row otherwise; the browse list is
// ~21 rows and the rows are pure in their props.
const NavigatorResultRowMemo = React.memo(NavigatorResultRow);

/**
 * The one navigation overlay.
 *
 * Replaces both Header's Routes dropdown and CommandPalette. Plan 01: "Never
 * have two active keyboard listeners toggling separate overlays" — this
 * component owns no global shortcut at all; App.jsx owns the single one and
 * passes `isOpen` down.
 */
function GlobalNavigator({ isOpen, onClose, onNavigate }) {
  const { user, isMasquerade } = useAuth();
  const isMobile = useIsMobile();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [pins, setPins] = useState([]);
  const [recents, setRecents] = useState([]);

  const inputRef = useRef(null);
  const panelRef = useRef(null);
  const activeRowRef = useRef(null);
  // The element that had focus when the navigator opened, so Escape can put it
  // back. Plan 01: "Escape closes and restores the actual opener" — restoring
  // to document.body, which is what happens if nothing is captured, strands
  // keyboard users at the top of the page.
  const openerRef = useRef(null);

  const namespace = useMemo(() => namespaceFor({ user, isMasquerade }), [user, isMasquerade]);

  const { localResults, assetResults, assetsLoading, assetsError, hasMore, retryAssets } =
    useNavigatorSearch({ query, user, enabled: isOpen });

  const index = useMemo(() => buildLocalIndex(user), [user]);
  const byId = useMemo(() => new Map(index.map((entry) => [entry.id, entry])), [index]);

  useEffect(() => {
    if (!isOpen) return undefined;
    openerRef.current = document.activeElement;
    setQuery('');
    setActiveIndex(0);
    setPins(readPins(namespace));
    setRecents(readRecents(namespace));
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [isOpen, namespace]);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const close = useCallback(() => {
    onClose();
    // Focus goes back before the caller can move it somewhere better; an
    // action that opens a modal overrides this deliberately in handleActivate.
    const opener = openerRef.current;
    if (opener && typeof opener.focus === 'function' && document.contains(opener)) {
      opener.focus();
    }
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const onPointerDown = (event) => {
      if (panelRef.current && !panelRef.current.contains(event.target)) close();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [isOpen, close]);

  const searching = query.trim().length > 0;

  /** Browse mode: the grouped default, with counts derived from what is visible. */
  const browseGroups = useMemo(() => {
    if (searching) return [];
    const groups = NAV_GROUPS.map((group) => ({
      id: group.id,
      label: group.label,
      entries: group.items
        .filter((item) => canSeeNavItem(item, group, user))
        .map((item) => byId.get(`page:${item.path}`))
        .filter(Boolean),
    })).filter((group) => group.entries.length > 0);

    const pinned = pins.map((id) => byId.get(id)).filter(Boolean);
    const recent = recents.map((id) => byId.get(id)).filter(Boolean);

    return [
      ...(pinned.length ? [{ id: 'pinned', label: 'Pinned', entries: pinned }] : []),
      ...(recent.length ? [{ id: 'recent', label: 'Recent', entries: recent }] : []),
      ...groups,
    ];
  }, [searching, user, byId, pins, recents]);

  /** Search mode: three labelled groups in a fixed order. */
  const resultGroups = useMemo(() => {
    if (!searching) return [];
    const pagesAndSettings = localResults.filter((entry) => entry.kind !== 'action');
    const actions = localResults.filter((entry) => entry.kind === 'action');
    return [
      ...(pagesAndSettings.length
        ? [{ id: 'local', label: 'Pages & Settings', entries: pagesAndSettings }]
        : []),
      ...(assetResults.length ? [{ id: 'assets', label: 'Assets', entries: assetResults }] : []),
      ...(actions.length ? [{ id: 'actions', label: 'Actions', entries: actions }] : []),
    ];
  }, [searching, localResults, assetResults]);

  const groups = searching ? resultGroups : browseGroups;
  const flat = useMemo(() => groups.flatMap((group) => group.entries), [groups]);

  useEffect(() => {
    setActiveIndex((current) => (current < flat.length ? current : 0));
  }, [flat.length]);

  const handleActivate = useCallback(
    (entry) => {
      if (!entry) return;
      // Close first, then hand over: an action opens a modal that wants focus,
      // and restoring focus to the opener afterwards would steal it back.
      onClose();
      onNavigate(entry);
    },
    [onClose, onNavigate]
  );

  const handleTogglePin = useCallback(
    (entry) => setPins(togglePinStored(namespace, entry.id)),
    [namespace]
  );

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    // Composition: a Japanese or Chinese IME uses Enter to commit a candidate.
    // Navigating on that keystroke would discard what the user was typing.
    if (event.nativeEvent?.isComposing) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((i) => (flat.length ? Math.min(i + 1, flat.length - 1) : 0));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      handleActivate(flat[activeIndex]);
    } else if (event.key === 'Tab') {
      // A one-field dialog: keep Tab inside it rather than walking the page
      // behind the overlay.
      event.preventDefault();
    }
  };

  if (!isOpen) return null;

  const pinSet = new Set(pins);
  let cursor = -1;

  return (
    <div className="navigator-overlay">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigate"
        className={`navigator-panel${isMobile ? ' navigator-panel--mobile' : ''}`}
      >
        <div className="navigator-search-row">
          <Search size={15} aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            role="searchbox"
            className="navigator-input"
            placeholder="Search pages, settings and assets…"
            aria-label="Search pages, settings and assets"
            aria-controls="navigator-results"
            aria-activedescendant={flat.length ? `navigator-option-${activeIndex}` : undefined}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="navigator-hint">{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd>
        </div>

        <div className="navigator-status" role="status" aria-live="polite">
          {assetsLoading
            ? 'Searching assets…'
            : `${flat.length} result${flat.length === 1 ? '' : 's'}`}
        </div>

        {assetsError ? (
          <div className="navigator-banner navigator-banner--error">
            <AlertTriangle size={14} aria-hidden="true" />
            <span>Assets could not be searched.</span>
            <button type="button" className="navigator-retry" onClick={retryAssets}>
              Retry
            </button>
          </div>
        ) : null}

        <div
          id="navigator-results"
          role="listbox"
          aria-label="Results"
          className="navigator-results"
        >
          {groups.map((group) => (
            <div key={group.id} className="navigator-group">
              <div className="navigator-group-label">
                {group.id === 'pinned' ? <Pin size={12} aria-hidden="true" /> : null}
                {group.id === 'recent' ? <Clock size={12} aria-hidden="true" /> : null}
                <span>{group.label}</span>
                <span
                  className="navigator-group-count"
                  data-testid={`navigator-group-count-${group.id}`}
                >
                  {group.entries.length}
                </span>
              </div>
              {group.entries.map((entry) => {
                cursor += 1;
                const active = cursor === activeIndex;
                return (
                  <div key={entry.id} ref={active ? activeRowRef : null}>
                    <NavigatorResultRowMemo
                      entry={entry}
                      active={active}
                      index={cursor}
                      onActivate={handleActivate}
                      onTogglePin={namespace ? handleTogglePin : null}
                      pinned={pinSet.has(entry.id)}
                    />
                  </div>
                );
              })}
            </div>
          ))}

          {assetsLoading && !flat.length ? (
            <div className="navigator-empty">
              <Loader2 size={14} className="navigator-spin" aria-hidden="true" />
              <span>Searching…</span>
            </div>
          ) : null}

          {!assetsLoading && searching && !flat.length && !assetsError ? (
            <div className="navigator-empty">No results for “{query.trim()}”</div>
          ) : null}

          {hasMore ? (
            <div className="navigator-footnote">
              More assets match than are shown. Refine the search to narrow it.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

GlobalNavigator.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onNavigate: PropTypes.func.isRequired,
};

export default GlobalNavigator;
