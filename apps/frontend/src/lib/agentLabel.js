/**
 * The one answer to "what do we call this agent in front of an operator?".
 *
 * `agents.name` is nullable (`db/models.py`'s `Agent.name`) and **enrollment
 * never writes it**: `ws_agents.enroll_stream` builds the row through
 * `agent_registry.create_pending_agent` with hostname/os/arch and no name, and
 * the only writer is an explicit operator `PATCH /agents/{id}`. So `name ==
 * null` is not the exceptional case — it is every agent nobody has renamed,
 * which is most of them, and any surface reading `name` alone labels the common
 * case "agent 7" and the rare one properly.
 *
 * Rejected alternative: default `Agent.name` to the hostname at enrollment.
 * That fixes nothing for the rows that already exist, and it conflates "an
 * operator chose this" with "we guessed" — once a guess is stored, a host that
 * is later renamed keeps the stale label forever, because nothing can tell the
 * guess apart from a deliberate name. Resolving at display time fixes old and
 * new rows alike and leaves `name` meaning exactly what it means.
 *
 * One exported function rather than an inline `a.name || a.hostname || ...` at
 * each call site: there are four of them across the discovery pages and the
 * "Scan from" selector, and four copies is how the dropdown ends up reading
 * `branch-office-01` while the refusal underneath it reads `Agent 8`.
 *
 * Accepts either id spelling on purpose. The fleet list (`AgentOut`) keys on
 * `id`; the eligibility listings (`EligibleDiscoveryAgent`) key on `agent_id`,
 * because there the row is a verdict *about* an agent rather than the agent.
 * A caller holding only an id — a history row whose agent has since been
 * deleted, an `?agent=` deep link naming an agent that no longer exists —
 * passes it as `fallbackId` and still gets a label instead of an empty string.
 *
 * Lowercase "agent 7" matches how the backend already spells an unnamed agent
 * in its refusals ("agent 7 may not run this discovery request") and how
 * `ScanDetailPanel`'s "Ran on" spells it, so the id form reads the same
 * wherever it surfaces.
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
