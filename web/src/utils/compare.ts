import type { Agent } from '../types';

/**
 * Compares two Agent objects deeply to detect any differences.
 * Checks only persisted agent-level draft fields.
 */
export function compareAgents(agentA: Agent | null, agentB: Agent | null): boolean {
  if (agentA === agentB) return false;
  if (!agentA || !agentB) return true;

  return (
    agentA.name !== agentB.name ||
    agentA.description !== agentB.description ||
    agentA.llm_id !== agentB.llm_id ||
    agentA.session_idle_timeout_minutes !== agentB.session_idle_timeout_minutes ||
    agentA.sandbox_timeout_seconds !== agentB.sandbox_timeout_seconds ||
    agentA.compact_threshold_percent !== agentB.compact_threshold_percent ||
    agentA.max_iteration !== agentB.max_iteration ||
    agentA.tool_ids !== agentB.tool_ids ||
    agentA.skill_ids !== agentB.skill_ids ||
    agentA.model_name !== agentB.model_name ||
    agentA.is_active !== agentB.is_active
  );
}

/**
 * Deep copies an Agent object.
 */
export function deepCopyAgent(agent: Agent | null): Agent | null {
  if (!agent) return null;
  return JSON.parse(JSON.stringify(agent)) as Agent;
}
