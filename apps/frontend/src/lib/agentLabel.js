/**
 * The one answer to "what do we call this agent in front of an operator?".
 *
 * `agents.name` is nullable and enrollment never writes it — only an operator
 * `PATCH /agents/{id}` does — so a null name is the common case, not the
 * exception. Resolved at display time rather than defaulted at enrollment: a
 * stored guess cannot later be told apart from a deliberate name, so a renamed
 * host would keep the stale label forever.
 *
 * One exported function rather than an inline `a.name || a.hostname || ...` at
 * each of its call sites, which is how a dropdown ends up reading
 * `branch-office-01` while the refusal underneath it reads `Agent 8`.
 *
 * Accepts either id spelling: the fleet list keys on `id`, the eligibility
 * listings on `agent_id` (there the row is a verdict about an agent, not the
 * agent). A caller holding only an id passes `fallbackId` and still gets a
 * label. Lowercase "agent 7" matches how the backend spells it in refusals.
 *
 * @param {{name?: string|null, hostname?: string|null, id?: number, agent_id?: number}|null|undefined} agent
 * @param {number|string|null} [fallbackId] Id to name when `agent` is absent.
 * @returns {string|null} A label, or `null` when there is not even an id.
 */
export function agentDisplayName(agent, fallbackId = null) {
  const id = agent?.agent_id ?? agent?.id ?? fallbackId;
  return agent?.name || agent?.hostname || (id == null ? null : `agent ${id}`);
}

export default agentDisplayName;
