import React, { useState } from 'react';
import PropTypes from 'prop-types';
import EntityPicker from '../common/EntityPicker';
import {
  canSyncSource,
  describeContainerList,
  describeSourceStatus,
  parentAssignmentNote,
} from '../../lib/dockerSource';
import '../../styles/docker-sources.css';

function formatStamp(iso) {
  if (!iso) return 'Never';
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? 'Unknown' : parsed.toLocaleString();
}

/**
 * One Docker source: what it is, what the last sync established, and what is
 * still unresolved about it (plan 03, D3/D6/D7).
 *
 * Last attempt and last success are deliberately two separate rows. Collapsing
 * them into one "last synced" value is what let a daemon fail quietly for days
 * while the page still looked current.
 */
function DockerSourceCard({ source, run, containers, onSync, onAssignParent, busy }) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const status = describeSourceStatus(source, run);
  const list = describeContainerList(source, run, containers.length);
  const sync = canSyncSource(source, run);
  const parentNote = parentAssignmentNote(source);
  const hasParent = Boolean(source.parent_type && source.parent_id);

  const handlePick = (option) => {
    setPickerOpen(false);
    const ref = option?.ref;
    if (!ref) return;
    onAssignParent(source.id, {
      parent_type: ref.entity_type,
      parent_id: ref.entity_id,
      // The revision we rendered. If the source moved since, the server answers
      // 409 rather than letting this land on top of someone else's correction.
      expected_revision: source.revision,
    });
  };

  return (
    <section className={`docker-source docker-source--${status.state}`}>
      <header className="docker-source__head">
        <div>
          <h4 className="docker-source__name">{source.name}</h4>
          <p className="docker-source__endpoint">
            {source.connection_kind} · {source.endpoint_hint}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => onSync(source.id)}
          disabled={!sync.allowed || busy}
        >
          Sync
        </button>
      </header>

      <p className="docker-source__status" role="status">
        <span className="docker-source__state">{status.title}</span> {status.detail}
      </p>
      {!sync.allowed && sync.reason && <p className="docker-source__note">{sync.reason}</p>}

      <dl className="docker-source__stamps">
        <div>
          <dt>Last attempt</dt>
          <dd>{formatStamp(status.lastAttemptAt)}</dd>
        </div>
        <div>
          <dt>Last success</dt>
          <dd>{formatStamp(status.lastSuccessAt)}</dd>
        </div>
      </dl>

      {status.showsStaleInventory && (
        <p className="docker-source__warning">
          The latest attempt did not succeed. What follows is the last good picture, not the current
          one.
        </p>
      )}

      <div className="docker-source__parent">
        <p className="docker-source__note">{parentNote}</p>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => setPickerOpen(true)}
        >
          {hasParent ? 'Change host' : 'Assign host'}
        </button>
      </div>

      {list.note && <p className="docker-source__warning">{list.note}</p>}

      {containers.length === 0 ? (
        <p className="docker-source__empty">{list.emptyReason}</p>
      ) : (
        <ul className="docker-source__containers">
          {containers.map((container) => (
            <li key={container.id}>
              <span className="docker-source__container-name">{container.name}</span>
              <span className="docker-source__container-meta">
                {container.image || 'unknown image'} · {container.status || 'unknown'}
              </span>
            </li>
          ))}
        </ul>
      )}

      <EntityPicker
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title={`Host for ${source.name}`}
        action="docker_parent"
        types={['hardware', 'compute_unit']}
        onSelect={handlePick}
      />
    </section>
  );
}

DockerSourceCard.propTypes = {
  source: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
    connection_kind: PropTypes.string,
    endpoint_hint: PropTypes.string,
    enabled: PropTypes.bool,
    revision: PropTypes.number.isRequired,
    parent_type: PropTypes.string,
    parent_id: PropTypes.number,
    parent_provenance: PropTypes.string,
    last_attempt_at: PropTypes.string,
    last_success_at: PropTypes.string,
  }).isRequired,
  /** The most recent run for this source, if one is known. */
  run: PropTypes.object,
  containers: PropTypes.arrayOf(PropTypes.object),
  onSync: PropTypes.func.isRequired,
  onAssignParent: PropTypes.func.isRequired,
  busy: PropTypes.bool,
};

DockerSourceCard.defaultProps = {
  run: null,
  containers: [],
  busy: false,
};

export default DockerSourceCard;
