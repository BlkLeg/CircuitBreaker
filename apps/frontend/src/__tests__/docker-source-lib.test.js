import { describe, it, expect } from 'vitest';
import {
  canSyncSource,
  describeContainerList,
  describeSourceStatus,
  parentAssignmentNote,
} from '../lib/dockerSource';

const source = (over = {}) => ({
  id: 1,
  name: 'Local daemon',
  connection_kind: 'socket',
  endpoint_hint: '/var/run/docker.sock',
  enabled: true,
  revision: 3,
  parent_type: null,
  parent_id: null,
  parent_provenance: 'unresolved',
  last_attempt_at: null,
  last_success_at: null,
  ...over,
});

const run = (over = {}) => ({
  id: 'run-1',
  source_id: 1,
  source_revision: 3,
  status: 'succeeded',
  containers_complete: true,
  networks_complete: true,
  containers_observed: 4,
  networks_observed: 2,
  containers_stopped: 0,
  conflict_count: 0,
  reason_code: null,
  safe_message: null,
  ...over,
});

describe('describeSourceStatus', () => {
  it('does not infer anything from a source that has never run', () => {
    const view = describeSourceStatus(source(), null);

    expect(view.state).toBe('never-run');
    expect(view.detail).toMatch(/has not been synced/i);
    expect(view.showsStaleInventory).toBe(false);
  });

  it('keeps last attempt and last success as separate facts', () => {
    const view = describeSourceStatus(
      source({
        last_attempt_at: '2026-09-15T10:00:00Z',
        last_success_at: '2026-09-14T09:00:00Z',
      }),
      run({ status: 'failed', containers_complete: false, safe_message: 'Daemon unreachable.' })
    );

    expect(view.lastAttemptAt).toBe('2026-09-15T10:00:00Z');
    expect(view.lastSuccessAt).toBe('2026-09-14T09:00:00Z');
    // The whole point: a failed attempt must not erase the earlier success.
    expect(view.state).toBe('failed');
    expect(view.showsStaleInventory).toBe(true);
  });

  it('reports a running attempt without claiming an outcome', () => {
    const view = describeSourceStatus(source(), run({ status: 'running' }));

    expect(view.state).toBe('running');
    expect(view.detail).toMatch(/in progress/i);
    expect(view.showsStaleInventory).toBe(false);
  });

  it('qualifies a partial enumeration as incomplete coverage', () => {
    const view = describeSourceStatus(
      source({ last_success_at: '2026-09-14T09:00:00Z' }),
      run({ status: 'partial', containers_complete: false, containers_observed: 2 })
    );

    expect(view.state).toBe('partial');
    expect(view.detail).toMatch(/incomplete/i);
  });

  it('prefers the server reason over invented wording when one is given', () => {
    const view = describeSourceStatus(
      source(),
      run({ status: 'failed', containers_complete: false, safe_message: 'Daemon unreachable.' })
    );

    expect(view.detail).toBe('Daemon unreachable.');
  });
});

describe('describeContainerList', () => {
  it('distinguishes a reachable daemon with no containers from a failed enumeration', () => {
    const reachable = describeContainerList(source(), run({ containers_observed: 0 }), 0);
    const broken = describeContainerList(
      source({ last_success_at: '2026-09-14T09:00:00Z' }),
      run({ status: 'failed', containers_complete: false }),
      0
    );

    expect(reachable.emptyReason).toMatch(/no containers/i);
    expect(broken.emptyReason).toMatch(/could not be read|last successful/i);
    // The bug the plan names: empty and failed must not look identical.
    expect(reachable.emptyReason).not.toBe(broken.emptyReason);
  });

  it('marks a list as provisional when coverage was incomplete', () => {
    const view = describeContainerList(
      source(),
      run({ status: 'partial', containers_complete: false }),
      2
    );

    expect(view.provisional).toBe(true);
    expect(view.note).toMatch(/incomplete/i);
  });

  it('does not mark a complete enumeration provisional', () => {
    const view = describeContainerList(source(), run(), 4);
    expect(view.provisional).toBe(false);
  });
});

describe('canSyncSource', () => {
  it('refuses a second sync while one is already running', () => {
    expect(canSyncSource(source(), run({ status: 'running' })).allowed).toBe(false);
    expect(canSyncSource(source(), run({ status: 'queued' })).allowed).toBe(false);
  });

  it('allows a retry after a failure without discarding what is already there', () => {
    const decision = canSyncSource(
      source({ last_success_at: '2026-09-14T09:00:00Z' }),
      run({ status: 'failed' })
    );
    expect(decision.allowed).toBe(true);
  });

  it('refuses a disabled source and says why', () => {
    const decision = canSyncSource(source({ enabled: false }), null);
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toMatch(/disabled/i);
  });
});

describe('parentAssignmentNote', () => {
  it('explains that a manual assignment survives rediscovery', () => {
    const note = parentAssignmentNote(
      source({ parent_provenance: 'manual', parent_type: 'hardware', parent_id: 2 })
    );
    expect(note).toMatch(/kept|retained/i);
    expect(note).toMatch(/rediscover/i);
  });

  it('says an automatic association may be replaced', () => {
    const note = parentAssignmentNote(
      source({ parent_provenance: 'automatic', parent_type: 'hardware', parent_id: 2 })
    );
    expect(note).toMatch(/automatic/i);
  });

  it('names an unresolved parent as needing a decision', () => {
    const note = parentAssignmentNote(source());
    expect(note).toMatch(/not .*assigned|unresolved/i);
  });
});

describe('a source whose run is unknown', () => {
  it('is never described as synced just because it was attempted', () => {
    const status = describeSourceStatus(source({ last_attempt_at: '2026-09-17T10:00:00Z' }), null);

    expect(status.state).toBe('unknown');
    expect(status.title).toBe('Outcome unknown');
    expect(status.detail).not.toMatch(/reachable/i);
  });

  it('keeps a prior success visibly prior rather than presenting it as current', () => {
    const status = describeSourceStatus(
      source({ last_attempt_at: '2026-09-17T10:00:00Z', last_success_at: '2026-09-14T09:00:00Z' }),
      null
    );

    expect(status.showsStaleInventory).toBe(true);
  });

  it('still reports a source that has never been attempted as never synced', () => {
    expect(describeSourceStatus(source(), null).state).toBe('never-run');
  });

  it('does not explain an empty list as a reachable daemon reporting nothing', () => {
    const list = describeContainerList(
      source({ last_attempt_at: '2026-09-17T10:00:00Z' }),
      null,
      0
    );

    expect(list.emptyReason).toMatch(/run is unknown/i);
    expect(list.emptyReason).not.toMatch(/reachable/i);
  });
});

describe('an unreadable container list', () => {
  it('is reported as unknown rather than as empty', () => {
    const list = describeContainerList(source(), run(), 0, true);

    expect(list.unreadable).toBe(true);
    expect(list.emptyReason).toMatch(/could not be loaded/i);
  });

  it('takes precedence over a successful run that observed containers', () => {
    const list = describeContainerList(source(), run({ containers_observed: 5 }), 0, true);

    expect(list.emptyReason).not.toMatch(/reported no containers/i);
  });

  it('leaves a readable empty list alone', () => {
    const list = describeContainerList(
      source({ last_attempt_at: '2026-09-17T10:00:00Z' }),
      run({ containers_observed: 0 }),
      0,
      false
    );

    expect(list.unreadable).toBe(false);
    expect(list.emptyReason).toMatch(/reachable and reported no containers/i);
  });
});
