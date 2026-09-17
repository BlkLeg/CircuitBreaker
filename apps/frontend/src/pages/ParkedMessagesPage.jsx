import React, { useCallback, useEffect, useState } from 'react';
import Banner from '../components/common/Banner';
import ConfirmDialog from '../components/common/ConfirmDialog';
import EmptyState from '../components/common/EmptyState';
import { SkeletonTable } from '../components/common/SkeletonTable';
import { failedMessagesApi } from '../api/client';
import '../styles/monitors.css';

/** Matches `failed_message_service.DEFAULT_PARKED_PAGE`. */
const PAGE_SIZE = 100;

function formatStamp(iso) {
  if (!iso) return null;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : at.toLocaleString();
}

function resolutionOf(row) {
  if (row.requeued_at) return `Requeued ${formatStamp(row.requeued_at)}`;
  if (row.discarded_at) return `Discarded ${formatStamp(row.discarded_at)}`;
  return null;
}

/**
 * Parked JetStream work: messages that exhausted their delivery budget.
 *
 * Route F14's objective is "0 silent poison-message loops: every JetStream
 * max-deliver exhaustion produces an operator-visible record". The table and
 * the three admin routes shipped; this is the half that makes a parked row
 * something a person can actually see and act on.
 *
 * Paging is component state rather than query params on purpose. Nobody
 * deep-links to page three of a dead-letter queue, and `/logs` next door owns
 * `limit` and `offset` for its own list.
 */
function ParkedMessagesPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [includeResolved, setIncludeResolved] = useState(false);
  const [offset, setOffset] = useState(0);
  const [busyId, setBusyId] = useState(null);
  const [confirming, setConfirming] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await failedMessagesApi.list({
        include_resolved: includeResolved,
        limit: PAGE_SIZE,
        offset,
      });
      setRows(response.data || []);
      setError(null);
    } catch (err) {
      setRows([]);
      setError(err?.userMessage || 'The parked messages could not be read.');
    } finally {
      setLoading(false);
    }
  }, [includeResolved, offset]);

  useEffect(() => {
    load();
  }, [load]);

  /**
   * Three failures that mean three different things.
   *
   * 502 is the service refusing to stamp a row while the bus is disconnected —
   * `nats_client.publish` buffers rather than raising, so without that refusal a
   * requeue during an outage would report success and send nothing. The message
   * is intact; reporting it as unrecoverable would be a lie.
   */
  const actOn = async (row, action, verb) => {
    setBusyId(row.id);
    setNotice(null);
    try {
      await action(row.id);
      setNotice({ tone: 'ok', text: `${row.subject} ${verb}.` });
      await load();
    } catch (err) {
      if (err?.statusCode === 502) {
        setNotice({
          tone: 'warn',
          text: `The message bus is not connected, so ${row.subject} is still parked. Try again once it reconnects — nothing was sent and nothing was lost.`,
        });
      } else if (err?.statusCode === 409) {
        setNotice({
          tone: 'info',
          text: `${row.subject} was already acted on by someone else. Refreshed to show where it stands.`,
        });
        await load();
      } else if (err?.statusCode === 404) {
        setNotice({
          tone: 'info',
          text: `${row.subject} is no longer parked. Refreshed the list.`,
        });
        await load();
      } else {
        setNotice({
          tone: 'danger',
          text: err?.userMessage || `${row.subject} could not be ${verb}.`,
        });
      }
    } finally {
      setBusyId(null);
    }
  };

  if (loading && rows.length === 0 && !error) {
    return (
      <div className="page" data-testid="parked-loading">
        <SkeletonTable rows={5} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <h2>Parked Messages</h2>
      </div>

      <p className="form-hint">
        Work that exhausted its delivery budget on the message bus and was set aside instead of
        retried forever. Requeue puts a message back on its stream; discard abandons it. Both keep
        the row, because &ldquo;this failed and was retried&rdquo; is a different fact from
        &ldquo;this never happened&rdquo;.
      </p>

      {notice && (
        <div role="alert">
          <Banner
            tone={notice.tone === 'ok' ? 'ok' : notice.tone === 'danger' ? 'danger' : notice.tone}
            title="Parked message"
            body={notice.text}
          />
        </div>
      )}

      {error ? (
        <div role="alert">
          <Banner
            tone="danger"
            title="The parked messages could not be read"
            body={error}
            actions={
              <button type="button" className="btn btn-sm" onClick={load}>
                Retry
              </button>
            }
          />
        </div>
      ) : (
        <>
          <div className="intel-filters">
            <label htmlFor="parked-resolved">
              <input
                id="parked-resolved"
                type="checkbox"
                checked={includeResolved}
                onChange={(event) => {
                  setOffset(0);
                  setIncludeResolved(event.target.checked);
                }}
              />{' '}
              Show resolved
            </label>
          </div>

          {rows.length === 0 ? (
            <EmptyState
              message="No parked messages."
              hint="A message lands here only after the bus has retried it to exhaustion. An empty queue is the healthy state."
            />
          ) : (
            <table className="entity-table rule-table">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Consumer</th>
                  <th>Error</th>
                  <th>Attempts</th>
                  <th>Parked</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const resolution = resolutionOf(row);
                  return (
                    <tr
                      key={row.id}
                      data-testid={`parked-row-${row.id}`}
                      data-resolved={String(Boolean(resolution))}
                    >
                      <td>
                        <strong>{row.subject}</strong>
                        <span className="rule-incident">{row.stream}</span>
                      </td>
                      <td>{row.consumer}</td>
                      <td className="rule-reason">{row.error}</td>
                      <td>{row.delivered_count}</td>
                      <td>
                        {formatStamp(row.parked_at)}
                        {resolution && <span className="rule-reason">{resolution}</span>}
                      </td>
                      <td>
                        {!resolution && (
                          <>
                            <button
                              type="button"
                              className="btn btn-sm"
                              disabled={busyId === row.id}
                              onClick={() => actOn(row, failedMessagesApi.requeue, 'requeued')}
                            >
                              Requeue
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm"
                              disabled={busyId === row.id}
                              onClick={() => setConfirming(row)}
                            >
                              Discard
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          <div className="rule-list__header">
            <button
              type="button"
              className="btn btn-sm"
              disabled={offset === 0}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              Newer
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={rows.length < PAGE_SIZE}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Older
            </button>
          </div>
        </>
      )}

      <ConfirmDialog
        open={Boolean(confirming)}
        message={
          confirming
            ? `Discard the parked message ${confirming.subject}? Its payload stops being recoverable, and the row stays as a record that it happened.`
            : ''
        }
        onConfirm={async () => {
          const target = confirming;
          setConfirming(null);
          if (target) await actOn(target, failedMessagesApi.discard, 'discarded');
        }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

export default ParkedMessagesPage;
