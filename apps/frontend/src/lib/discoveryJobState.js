/* eslint-disable security/detect-object-injection -- controlled job field maps */
const JOB_VISUAL_FIELDS = Object.freeze([
  'id',
  'status',
  'target_cidr',
  'label',
  'source_type',
  'scan_types_json',
  'vlan_ids',
  'profile_id',
  'created_at',
  'started_at',
  'finished_at',
  'hosts_found',
  'hosts_new',
  'hosts_conflict',
  'progress_percent',
  'eta_seconds',
  'current_phase',
  'current_message',
  'last_log_message',
  'last_log_phase',
  'last_log_level',
  'last_log_ts',
  'error_text',
]);

function stableList(value) {
  return Array.isArray(value) ? value : [];
}

export function hasJobVisualDiff(previousJob, nextJob, fields = JOB_VISUAL_FIELDS) {
  if (previousJob === nextJob) return false;
  if (!previousJob || !nextJob) return true;
  for (const field of fields) {
    if (previousJob[field] !== nextJob[field]) {
      return true;
    }
  }
  return false;
}

export function mergeJobPatch(currentJob, patch) {
  if (!currentJob) return patch;
  if (!patch) return currentJob;

  let changed = false;
  const nextJob = { ...currentJob };
  for (const [field, value] of Object.entries(patch)) {
    if (value === undefined || currentJob[field] === value) continue;
    nextJob[field] = value;
    changed = true;
  }
  return changed ? nextJob : currentJob;
}

export function mergeJobsById(currentJobs, incomingJobs) {
  const current = stableList(currentJobs);
  const incoming = stableList(incomingJobs);
  if (current.length === 0) return incoming;

  const currentById = new Map(current.map((job) => [job.id, job]));
  const merged = incoming.map((incomingJob) => {
    const existing = currentById.get(incomingJob.id);
    if (!existing) return incomingJob;
    if (!hasJobVisualDiff(existing, incomingJob)) return existing;
    return mergeJobPatch(existing, incomingJob);
  });

  if (merged.length !== current.length) {
    return merged;
  }
  for (let index = 0; index < merged.length; index += 1) {
    if (merged[index] !== current[index]) {
      return merged;
    }
  }
  return current;
}
