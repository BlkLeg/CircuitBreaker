import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
  assignDockerSourceParent,
  getDockerRun,
  getDockerSourceContainers,
  listDockerSources,
  syncDocker,
} from '../../api/discovery';
import { useToast } from '../common/Toast';
import DockerSourceCard from './DockerSourceCard';
import '../../styles/docker-sources.css';

/**
 * The source-oriented Docker surface (plan 03).
 *
 * Progress arrives through the discovery stream rather than a poll loop: the
 * sync path already broadcasts `docker_sync_completed`, so the page that owns
 * the stream bumps `reloadToken` and this panel refetches. Adding a timer here
 * would be a second, worse copy of a mechanism that already exists.
 *
 * A queued sync is reported as queued and nothing more. The run ID it returns
 * is what makes the eventual outcome knowable at all — the older Integrations
 * button threw it away and said "Docker scan started", which was the last word
 * the user ever got.
 */
function DockerSourcesPanel({ reloadToken }) {
  const toast = useToast();
  const [sources, setSources] = useState([]);
  const [containersBySource, setContainersBySource] = useState({});
  const [runsBySource, setRunsBySource] = useState({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [busySourceId, setBusySourceId] = useState(null);
  const fetchSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++fetchSeq.current;
    setLoading(true);
    setLoadError(null);
    try {
      const res = await listDockerSources();
      if (seq !== fetchSeq.current) return;
      const rows = res.data || [];
      setSources(rows);

      const containerEntries = await Promise.all(
        rows.map(async (row) => {
          try {
            const containers = await getDockerSourceContainers(row.id);
            return [row.id, containers.data || []];
          } catch {
            // One unreadable source must not blank the whole panel; the card
            // still renders and explains its own state.
            return [row.id, []];
          }
        })
      );
      if (seq !== fetchSeq.current) return;
      setContainersBySource(Object.fromEntries(containerEntries));
    } catch (err) {
      if (seq !== fetchSeq.current) return;
      setLoadError(err.message || 'Docker sources could not be loaded.');
    } finally {
      if (seq === fetchSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, reloadToken]);

  const handleSync = async (sourceId) => {
    if (busySourceId !== null) return;
    setBusySourceId(sourceId);
    try {
      const res = await syncDocker();
      const { run_id: runId, source_id: acceptedId } = res.data || {};
      toast.info('Sync queued. The result will appear when it finishes.');
      if (runId) {
        try {
          const run = await getDockerRun(runId);
          setRunsBySource((prev) => ({ ...prev, [acceptedId ?? sourceId]: run.data }));
        } catch {
          // The run exists -- we just cannot describe it yet. The stream will
          // bring the outcome; saying nothing beats inventing a status.
        }
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message || 'The sync could not be started.');
    } finally {
      setBusySourceId(null);
    }
  };

  const handleAssignParent = async (sourceId, assignment) => {
    try {
      const res = await assignDockerSourceParent(sourceId, assignment);
      setSources((prev) => prev.map((row) => (row.id === sourceId ? res.data : row)));
      toast.success('Host assigned. It will be kept through future syncs.');
    } catch (err) {
      if (err?.response?.status === 409) {
        toast.error('This source changed since it was loaded. Reloading before you try again.');
        load();
        return;
      }
      toast.error(err?.response?.data?.detail || err.message || 'The host could not be assigned.');
    }
  };

  if (loading) {
    return (
      <div className="docker-sources" role="status">
        Loading Docker sources…
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="docker-sources docker-sources__error" role="alert">
        <p>{loadError}</p>
        <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <div className="docker-sources">
        <p className="docker-source__empty">
          No Docker source is configured. Configure one in Settings → Integrations.
        </p>
      </div>
    );
  }

  return (
    <div className="docker-sources">
      {sources.map((row) => (
        <DockerSourceCard
          key={row.id}
          source={row}
          run={runsBySource[row.id] || null}
          containers={containersBySource[row.id] || []}
          onSync={handleSync}
          onAssignParent={handleAssignParent}
          busy={busySourceId === row.id}
        />
      ))}
    </div>
  );
}

DockerSourcesPanel.propTypes = {
  /** Bumped by the owning page when the discovery stream reports a finished run. */
  reloadToken: PropTypes.number,
};

DockerSourcesPanel.defaultProps = {
  reloadToken: 0,
};

export default DockerSourcesPanel;
