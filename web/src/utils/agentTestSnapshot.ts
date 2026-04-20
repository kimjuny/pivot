import type { Agent } from "@/types";

/**
 * Session namespaces supported by the shared chat surface.
 */
export type ChatSessionType = "consumer" | "studio_test";

/**
 * Runtime-facing agent payload frozen into a Studio test snapshot.
 */
export interface StudioTestSnapshotAgent {
  /** User-facing agent name. */
  name: string;
  /** Optional agent description. */
  description?: string | null;
  /** Primary LLM identifier. */
  llm_id?: number | null;
  /** Idle timeout used by the chat shell. */
  session_idle_timeout_minutes: number;
  /** Sandbox timeout used for tool execution. */
  sandbox_timeout_seconds: number;
  /** Context usage threshold used for compaction. */
  compact_threshold_percent: number;
  /** Whether the agent is active in Studio. */
  is_active: boolean;
  /** Maximum recursion depth. */
  max_iteration: number;
  /** Normalized tool allowlist or null for unrestricted access. */
  tool_ids: string[] | null;
  /** Normalized skill allowlist or null for unrestricted access. */
  skill_ids: string[] | null;
}

/**
 * Minimal working-copy snapshot passed from Studio into the shared chat core.
 */
export interface StudioTestSnapshotPayload {
  /** Snapshot schema version. */
  schema_version: 1;
  /** Runtime-facing agent settings. */
  agent: StudioTestSnapshotAgent;
}

function normalizeAllowlist(rawValue: string | null | undefined): string[] | null {
  if (rawValue == null) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }

    return [
      ...new Set(
        parsed
          .filter((item): item is string => typeof item === "string")
          .map((item) => item.trim())
          .filter((item) => item.length > 0),
      ),
    ].sort();
  } catch {
    return [];
  }
}

function toCanonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map((item) => toCanonicalJson(item)).join(",")}]`;
  }

  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey));

  return `{${entries
    .map(([key, item]) => `${JSON.stringify(key)}:${toCanonicalJson(item)}`)
    .join(",")}}`;
}

/**
 * Build a normalized Studio working-copy snapshot from the current editor state.
 */
export function buildStudioTestSnapshotPayload(
  agent: Agent,
): StudioTestSnapshotPayload {
  return {
    schema_version: 1,
    agent: {
      name: agent.name,
      description: agent.description ?? null,
      llm_id: agent.llm_id ?? null,
      session_idle_timeout_minutes: agent.session_idle_timeout_minutes,
      sandbox_timeout_seconds: agent.sandbox_timeout_seconds,
      compact_threshold_percent: agent.compact_threshold_percent,
      is_active: agent.is_active,
      max_iteration: agent.max_iteration,
      tool_ids: normalizeAllowlist(agent.tool_ids),
      skill_ids: normalizeAllowlist(agent.skill_ids),
    },
  };
}

/**
 * Compute the Studio working-copy hash used to auto-restore matching test sessions.
 */
export async function computeStudioTestWorkspaceHash(
  payload: StudioTestSnapshotPayload,
): Promise<string> {
  const data = new TextEncoder().encode(toCanonicalJson(payload));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((item) => item.toString(16).padStart(2, "0"))
    .join("");
}
