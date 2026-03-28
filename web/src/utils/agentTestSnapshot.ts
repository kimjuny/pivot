import type { Agent, Scene, SceneGraph } from "@/types";

/**
 * Session namespaces supported by the shared chat surface.
 */
export type ChatSessionType = "consumer" | "studio_test";

/**
 * One normalized connection frozen into a Studio test snapshot.
 */
export interface StudioTestSnapshotConnection {
  /** Stable persisted or temporary identifier. */
  id?: number | string;
  /** User-facing connection label. */
  name: string;
  /** Optional transition condition. */
  condition?: string | null;
  /** Source subscene name. */
  from_subscene: string;
  /** Target subscene name. */
  to_subscene: string;
}

/**
 * One normalized subscene frozen into a Studio test snapshot.
 */
export interface StudioTestSnapshotSubscene {
  /** Stable persisted or temporary identifier. */
  id?: number | string;
  /** User-facing subscene label. */
  name: string;
  /** Runtime subscene type. */
  type: string;
  /** Runtime subscene state. */
  state: string;
  /** Optional human-readable description. */
  description?: string | null;
  /** Whether the subscene is mandatory. */
  mandatory: boolean;
  /** Optional objective shown in Studio. */
  objective?: string | null;
  /** Outgoing transitions frozen for this test. */
  connections: StudioTestSnapshotConnection[];
}

/**
 * One normalized scene frozen into a Studio test snapshot.
 */
export interface StudioTestSnapshotScene {
  /** Stable persisted or temporary identifier. */
  id?: number | string;
  /** User-facing scene label. */
  name: string;
  /** Optional scene description. */
  description?: string | null;
  /** Ordered scene graph content. */
  subscenes: StudioTestSnapshotSubscene[];
}

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
  /** Optional skill-resolution LLM identifier. */
  skill_resolution_llm_id?: number | null;
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
  /** Ordered scene graph state. */
  scenes: StudioTestSnapshotScene[];
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
  scenes: Scene[],
): StudioTestSnapshotPayload {
  return {
    schema_version: 1,
    agent: {
      name: agent.name,
      description: agent.description ?? null,
      llm_id: agent.llm_id ?? null,
      skill_resolution_llm_id: agent.skill_resolution_llm_id ?? null,
      session_idle_timeout_minutes: agent.session_idle_timeout_minutes,
      sandbox_timeout_seconds: agent.sandbox_timeout_seconds,
      compact_threshold_percent: agent.compact_threshold_percent,
      is_active: agent.is_active,
      max_iteration: agent.max_iteration,
      tool_ids: normalizeAllowlist(agent.tool_ids),
      skill_ids: normalizeAllowlist(agent.skill_ids),
    },
    scenes: scenes.map((scene) => {
      const sceneGraph = scene as unknown as SceneGraph;
      return {
        id: sceneGraph.id,
        name: sceneGraph.name ?? scene.name ?? "",
        description: sceneGraph.description ?? scene.description ?? null,
        subscenes: (sceneGraph.subscenes ?? []).map(
          (subscene) => ({
            id: subscene.id,
            name: subscene.name ?? subscene.data?.label ?? "",
            type: subscene.type ?? subscene.data?.type ?? "normal",
            state: subscene.state ?? subscene.data?.state ?? "inactive",
            description: subscene.data?.description ?? null,
            mandatory:
              subscene.mandatory ?? subscene.data?.mandatory ?? false,
            objective: subscene.objective ?? subscene.data?.objective ?? null,
            connections: (subscene.connections ?? []).map((connection) => ({
              id: connection.id,
              name: connection.name,
              condition: connection.condition ?? null,
              from_subscene: connection.from_subscene,
              to_subscene: connection.to_subscene,
            })),
          }),
        ),
      };
    }),
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
