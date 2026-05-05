/**
 * Type definitions for the agent visualization application.
 * Defines all data structures used throughout the application.
 */

/**
 * Represents an AI agent in the system.
 */
export interface Agent {
  /** Unique identifier of the agent */
  id: number;
  /** Display name of the agent */
  name: string;
  /** Optional description of agent's purpose */
  description?: string;
  /** LLM configuration ID used by this agent */
  llm_id?: number;
  /**
   * Minutes of inactivity before chat should start a fresh session for this
   * agent instead of continuing the previous one.
   */
  session_idle_timeout_minutes: number;
  /** Maximum seconds to wait for sandbox-backed tool execution requests. */
  sandbox_timeout_seconds: number;
  /** Context-window percentage that triggers automatic runtime compaction. */
  compact_threshold_percent: number;
  /** Published release used by default for newly created end-user sessions. */
  active_release_id?: number | null;
  /** Version number of the active release, if any. */
  active_release_version?: number | null;
  /** User ID that originally created this agent. */
  created_by_user_id?: number | null;
  /** Whether use access is granted to all users or selected principals. */
  use_scope?: string;
  /** Whether this agent currently accepts end-user traffic. */
  serving_enabled?: boolean;
  /** Deprecated: Name of the LLM model used by this agent */
  model_name?: string;
  /** Whether the agent is currently active */
  is_active: boolean;
  /** Maximum recursion depth allowed for one ReAct task. */
  max_iteration: number;
  /**
   * JSON-encoded list of allowed tool names, e.g. '["add","test_tool"]'.
   * null means no restriction (all tools visible); '[]' means no tools.
   */
  tool_ids?: string | null;
  /**
   * JSON-encoded list of allowed globally unique skill names, for example
   * '["research","writer"]'. null means no restriction (all visible skills);
   * '[]' means no skills.
   */
  skill_ids?: string | null;
  /** UTC timestamp when agent was created */
  created_at: string;
  /** UTC timestamp when agent was last updated */
  updated_at: string;
}

/**
 * Represents an LLM (Large Language Model) configuration.
 */
export interface LLM {
  /** Unique identifier of the LLM */
  id: number;
  /** Unique logical name for the LLM in the platform */
  name: string;
  /** User ID that originally created this LLM config. */
  created_by_user_id?: number | null;
  /** Whether use access is granted to all users or selected principals. */
  use_scope?: 'all' | 'selected';
  /** HTTP API Base URL for the LLM service */
  endpoint: string;
  /** Model identifier passed to the API */
  model: string;
  /** Authentication credential for the LLM */
  api_key: string;
  /** Protocol specification (e.g., 'openai_completion_llm', 'openai_response_llm') */
  protocol: string;
  /** Protocol-specific cache strategy */
  cache_policy: string;
  /** Protocol-specific thinking strategy */
  thinking_policy: string;
  /** Optional effort tier for effort-based thinking strategies */
  thinking_effort?: string | null;
  /** Optional token budget for extended thinking strategies */
  thinking_budget_tokens?: number | null;
  /** Whether the model supports streaming responses */
  streaming: boolean;
  /** Whether the model accepts user-supplied image inputs */
  image_input: boolean;
  /** Whether the model can produce image outputs */
  image_output: boolean;
  /** Maximum context token limit */
  max_context: number;
  /** Extra JSON configuration for LLM API calls */
  extra_config: string;
  /** UTC timestamp when LLM was created */
  created_at: string;
  /** UTC timestamp when LLM was last updated */
  updated_at: string;
}

/**
 * Safe LLM option visible in Studio selectors.
 * This deliberately excludes provider secrets and endpoint configuration.
 */
export interface LLMUsable {
  /** Unique identifier of the LLM */
  id: number;
  /** Unique logical name for the LLM in the platform */
  name: string;
  /** Model identifier passed to the API */
  model: string;
  /** Protocol specification */
  protocol: string;
  /** Whether the model supports streaming responses */
  streaming: boolean;
  /** Whether the model accepts user-supplied image inputs */
  image_input: boolean;
  /** Whether the model can produce image outputs */
  image_output: boolean;
  /** Maximum context token limit */
  max_context: number;
}
