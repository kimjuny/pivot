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
  /** Optional LLM configuration ID for skill resolution only */
  skill_resolution_llm_id?: number | null;
  /** Deprecated: Name of the LLM model used by this agent */
  model_name?: string;
  /** Whether the agent is currently active */
  is_active: boolean;
  /**
   * JSON-encoded list of allowed tool names, e.g. '["add","test_tool"]'.
   * null means no restriction (all tools visible); '[]' means no tools.
   */
  tool_ids?: string | null;
  /**
   * JSON-encoded list of allowed skill names, e.g. '["research","writer"]'.
   * null means no restriction (all skills visible); '[]' means no skills.
   */
  skill_ids?: string | null;
  /** UTC timestamp when agent was created */
  created_at: string;
  /** UTC timestamp when agent was last updated */
  updated_at: string;
  /** List of scenes with their full graph data */
  scenes?: SceneGraph[];
}

/**
 * Represents a scene in the agent system.
 * A scene is a collection of subscenes that define a workflow.
 */
export interface Scene {
  /** Unique identifier of the scene */
  id: number;
  /** Display name of the scene */
  name: string;
  /** Optional description of the scene's purpose */
  description?: string;
  /** ID of the agent that owns this scene */
  agent_id?: number;
  /** UTC timestamp when scene was created */
  created_at: string;
  /** UTC timestamp when scene was last updated */
  updated_at: string;
  /** Optional graph data for local/unsaved scenes */
  graph?: SceneGraph;
}

/**
 * Represents a subscene within a scene.
 * Subscenes are individual steps or states in a workflow.
 */
export interface Subscene {
  /** Unique identifier of the subscene */
  id: number;
  /** Display name of the subscene */
  name: string;
  /** Type of subscene (e.g., 'decision', 'action') */
  type: string;
  /** Current state of the subscene */
  state: string;
  /** Optional description of the subscene's purpose */
  description?: string;
  /** Whether this subscene is mandatory in the workflow */
  mandatory: boolean;
  /** Objective or goal of this subscene */
  objective?: string;
  /** ID of the parent scene */
  scene_id?: number;
  /** UTC timestamp when subscene was created */
  created_at: string;
  /** UTC timestamp when subscene was last updated */
  updated_at: string;
}

/**
 * Represents a connection between subscenes.
 * Defines transitions or relationships in the workflow.
 */
export interface Connection {
  /** Unique identifier of the connection */
  id: number;
  /** Display name of the connection */
  name: string;
  /** Optional condition for following this connection */
  condition?: string;
  /** ID of the source subscene */
  from_subscene: string;
  /** ID of the target subscene */
  to_subscene: string;
  /** Numeric ID of the source subscene */
  from_subscene_id?: number;
  /** Numeric ID of the target subscene */
  to_subscene_id?: number;
  /** ID of the scene this connection belongs to */
  scene_id?: number;
  /** UTC timestamp when connection was created */
  created_at: string;
  /** UTC timestamp when connection was last updated */
  updated_at: string;
}

/**
 * Represents the complete scene graph structure.
 * Used for visualizing and managing agent workflows.
 */
export interface SceneGraph {
  /** ID of the scene */
  id?: number;
  /** Name of the scene */
  name?: string;
  /** Description of the scene */
  description?: string;
  /** Agent ID */
  agent_id?: number;
  /** Creation timestamp */
  created_at?: string;
  /** Update timestamp */
  updated_at?: string;

  /** Array of scene nodes in the graph */
  subscenes: SceneNode[];
  /** ID of the currently active scene */
  current_scene?: string;
  /** ID of the currently active subscene */
  current_subscene?: string;
}

/**
 * Represents a node in the scene graph visualization.
 * Can be a scene, subscene, or connection point.
 */
export interface SceneNode {
  /** Unique identifier of the node */
  id: string;
  /** Type of the node */
  type: string;
  /** Position coordinates in the visualization */
  position: { x: number; y: number };
  /** Data associated with this node */
  data: {
    /** Display label for the node */
    label: string;
    /** Optional description of the node */
    description?: string;
    /** Optional type classification */
    type?: string;
    /** Current state of the node */
    state?: string;
    /** Whether this node is mandatory */
    mandatory?: boolean;
    /** Objective of this node */
    objective?: string;
  };
  /** Optional connections from this node */
  connections?: Connection[];
  /** Optional name field */
  name?: string;
  /** Optional state field */
  state?: string;
  /** Optional mandatory field */
  mandatory?: boolean;
  /** Optional objective field */
  objective?: string;
  /** Optional nested subscenes */
  subscenes?: SceneNode[];
}

/**
 * Represents an LLM (Large Language Model) configuration.
 */
export interface LLM {
  /** Unique identifier of the LLM */
  id: number;
  /** Unique logical name for the LLM in the platform */
  name: string;
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
  /** Whether the model supports multi-turn conversation with message roles */
  chat: boolean;
  /** Whether the model truly distinguishes system role with higher priority */
  system_role: boolean;
  /** Tool calling support level ('native', 'prompt', 'none') */
  tool_calling: string;
  /** JSON output reliability ('strong', 'weak', 'none') */
  json_schema: string;
  /** Thinking mode control ('auto', 'enabled', 'disabled') */
  thinking: string;
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
