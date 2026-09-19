/**
 * Presentation for Docker sources, runs, and their containers (plan 03).
 *
 * The rule this module exists to hold: an empty result and a failed one are not
 * the same thing. The old sync path returned a bare empty list for both, so a
 * daemon that had fallen over was indistinguishable from a host that genuinely
 * ran nothing — and reconciliation happily stopped every container on the
 * strength of it. The backend now reports outcome and completeness separately;
 * this module makes sure the UI never flattens them back together.
 *
 * Nothing here infers absence. "Not observed" is only ever reported as
 * not observed, never as gone.
 */

export const RUN_ACTIVE_STATES = ['queued', 'running'];

const PROVENANCE_MANUAL = 'manual';
const PROVENANCE_AUTOMATIC = 'automatic';

function isActive(run) {
  return Boolean(run) && RUN_ACTIVE_STATES.includes(run.status);
}

/**
 * Summarise a source and the most recent run against it.
 *
 * `showsStaleInventory` is the flag the card uses to say "what you are looking
 * at is the last good picture, not the current one" — it is true exactly when
 * we hold a prior success and the latest attempt did not produce a new one.
 */
export function describeSourceStatus(source, run) {
  const lastAttemptAt = source?.last_attempt_at ?? null;
  const lastSuccessAt = source?.last_success_at ?? null;
  const hasPriorSuccess = Boolean(lastSuccessAt);

  if (isActive(run)) {
    return {
      state: 'running',
      title: run.status === 'queued' ? 'Sync queued' : 'Sync running',
      detail: 'A sync is in progress. Nothing is concluded until it finishes.',
      lastAttemptAt,
      lastSuccessAt,
      showsStaleInventory: false,
    };
  }

  if (!run && !lastAttemptAt) {
    return {
      state: 'never-run',
      title: 'Never synced',
      detail: 'This source has not been synced yet, so nothing is known about it.',
      lastAttemptAt,
      lastSuccessAt,
      showsStaleInventory: false,
    };
  }

  // Attempted, but we hold no run to say how it went. Older servers do not
  // return `last_run` on a source, and a run row can be pruned. Saying
  // "Synced" here is exactly the failure this module exists to prevent, so
  // report the gap instead and keep any prior success visibly prior.
  if (!run) {
    return {
      state: 'unknown',
      title: 'Outcome unknown',
      detail:
        'This source was attempted, but its result is not available, so nothing is concluded from it.',
      lastAttemptAt,
      lastSuccessAt,
      showsStaleInventory: hasPriorSuccess,
    };
  }

  if (run?.status === 'failed' || run?.status === 'interrupted') {
    return {
      state: 'failed',
      title: run.status === 'interrupted' ? 'Sync interrupted' : 'Sync failed',
      detail: run.safe_message || 'The daemon could not be enumerated.',
      lastAttemptAt,
      lastSuccessAt,
      showsStaleInventory: hasPriorSuccess,
    };
  }

  if (run?.status === 'partial' || (run && run.containers_complete === false)) {
    return {
      state: 'partial',
      title: 'Partial sync',
      detail:
        run?.safe_message ||
        'Coverage was incomplete, so containers that were not seen are left alone.',
      lastAttemptAt,
      lastSuccessAt,
      showsStaleInventory: false,
    };
  }

  return {
    state: 'ok',
    title: 'Synced',
    detail:
      run?.safe_message ||
      `The daemon was reachable and reported ${run?.containers_observed ?? 0} container(s).`,
    lastAttemptAt,
    lastSuccessAt,
    showsStaleInventory: false,
  };
}

/**
 * How to render the container list, including *why* it is empty when it is.
 *
 * `unreadable` is the case where we could not load the list at all. An empty
 * array is the answer to "what is running here"; a failed request is the
 * absence of an answer, and rendering the two the same way is the mistake this
 * module exists to prevent — one level further down than the run outcome.
 *
 * @param {object} source
 * @param {object|null} run - most recent run for this source.
 * @param {number} count - containers currently held for the source.
 * @param {boolean} [unreadable] - the container list could not be fetched.
 */
export function describeContainerList(source, run, count, unreadable = false) {
  const failed = run?.status === 'failed' || run?.status === 'interrupted';
  const incomplete = run?.status === 'partial' || run?.containers_complete === false;

  let emptyReason = null;
  if (unreadable) {
    emptyReason =
      'The container list could not be loaded, so what this source holds is unknown right now.';
  } else if (count === 0) {
    if (failed) {
      emptyReason = source?.last_success_at
        ? 'The daemon could not be read. This is the last successful picture, not the current one.'
        : 'The daemon could not be read, so no containers have ever been observed.';
    } else if (isActive(run)) {
      emptyReason = 'The sync is still running.';
    } else if (!run && !source?.last_attempt_at) {
      emptyReason = 'This source has not been synced yet.';
    } else if (!run) {
      emptyReason =
        'This source was attempted, but its run is unknown, so nothing can be concluded about it.';
    } else {
      emptyReason = 'The daemon was reachable and reported no containers.';
    }
  }

  return {
    emptyReason,
    unreadable: Boolean(unreadable),
    provisional: Boolean(incomplete),
    note: incomplete
      ? 'Coverage was incomplete, so this list may be missing containers that are still running.'
      : null,
  };
}

/**
 * Whether a sync may be started, and if not, what to tell the operator.
 *
 * A failed run never blocks a retry — the plan is explicit that retry must stay
 * available without discarding the data already held.
 */
export function canSyncSource(source, run) {
  if (source && source.enabled === false) {
    return { allowed: false, reason: 'This source is disabled. Enable it before syncing.' };
  }
  if (isActive(run)) {
    return { allowed: false, reason: 'A sync is already running for this source.' };
  }
  return { allowed: true, reason: null };
}

/**
 * Explain what will happen to the current parent association on the next sync.
 * Plan 03 asks for this explicitly: a user who corrected a parent needs to know
 * whether rediscovery is about to undo them.
 */
export function parentAssignmentNote(source) {
  const provenance = source?.parent_provenance;
  const assigned = Boolean(source?.parent_type && source?.parent_id);

  if (!assigned) {
    return 'This source is not yet assigned to a host. Until it is, its containers have no parent.';
  }
  if (provenance === PROVENANCE_MANUAL) {
    return 'You set this parent, so it is kept as-is and rediscovery will not overwrite it.';
  }
  if (provenance === PROVENANCE_AUTOMATIC) {
    return 'This parent was resolved automatically and a later sync may replace it. Set it yourself to pin it.';
  }
  return 'This parent has no recorded provenance, so a later sync may replace it.';
}
