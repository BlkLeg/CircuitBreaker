/**
 * The agent capability vocabulary, in the operator's words.
 *
 * One definition, because four places render it: the fleet filter bar, the
 * fleet row's chip list, the capabilities panel's toggles, and the overview
 * tab's "N of M on" count. That last one derives M from `Object.keys().length`,
 * so a capability added to one copy and not the others did not just show the
 * wrong label — it changed the denominator the operator reads as the fleet's
 * capability coverage.
 *
 * Keys are the API's capability names (see `api/agents.normalizeCapability`).
 */
export const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};
