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
  /** Name of the LLM model used by this agent */
  model_name?: string;
  /** Whether the agent is currently active */
  is_active: boolean;
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
 * Represents a single message in the chat history.
 */
export interface ChatHistory {
  /** Unique identifier of the message */
  id: number;
  /** ID of the agent that sent/received this message */
  agent_id: number;
  /** User identifier who sent the message */
  user: string;
  /** Role of the message sender */
  role: 'user' | 'agent';
  /** Content of the message */
  message: string;
  /** Optional reasoning provided by the agent */
  reason?: string;
  /** Optional scene update triggered by this message */
  update_scene?: string;
  /** UTC timestamp when the message was created */
  create_time: string;
  /** Optional scene graph data associated with this message */
  graph?: SceneGraph;
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
 * Request payload for sending a chat message.
 */
export interface ChatRequest {
  /** Message content to send */
  message: string;
  /** Optional user identifier */
  user?: string;
}

/**
 * Response from the agent after processing a message.
 */
export interface ChatResponse {
  /** Agent's response message */
  response: string;
  /** Optional reasoning behind the response */
  reason: string;
  /** Optional updated scene graph */
  graph?: SceneGraph;
  /** UTC timestamp of the response */
  create_time?: string;
}

/**
 * Response containing chat history and latest graph.
 */
export interface ChatHistoryResponse {
  /** Array of chat messages */
  history: ChatHistory[];
  /** Optional latest scene graph state */
  latest_graph?: SceneGraph;
}

/**
 * Request payload for Build Chat API.
 * Used to send messages to the Build Agent for agent editing assistance.
 */
export interface BuildChatRequest {
  /** User's message to the Build Agent */
  content: string;
  /** Optional session ID for continuing a conversation */
  session_id?: string | null;
  /** Optional agent ID when modifying an existing agent */
  agent_id?: string | null;
}

/**
 * Response from the Build Agent after processing a request.
 */
export interface BuildChatResponse {
  /** Session ID for the conversation */
  session_id: string;
  /** Build Agent's text response */
  response: string;
  /** Reasoning behind the suggested changes */
  reason: string;
  /** Updated agent configuration with scene graph changes */
  updated_agent: {
    /** Agent name */
    name: string;
    /** Agent description */
    description?: string;
    /** Scene data from the agent - List of scenes with their graph data */
    scenes?: Array<{
      name: string;
      description?: string;
      type?: string;
      state?: string;
      mandatory?: boolean;
      objective?: string;
      subscenes?: SceneNode[]; // subscenes list
      connections?: Connection[]; // connections list
    }>;
  };
}

/**
 * Represents a single message in the Build Chat history.
 */
export interface BuildHistory {
  /** Unique identifier of the message */
  id: number;
  /** Session ID for this conversation */
  session_id: string;
  /** Role of the message sender */
  role: 'user' | 'assistant';
  /** Content of the message */
  content: string;
  /** Optional agent snapshot after this message */
  agent_snapshot?: string;
  /** UTC timestamp when the message was created */
  created_at: string;
}

/**
 * Request payload for Preview Chat API.
 */
export interface PreviewChatRequest {
  /** User's message to the Preview Agent */
  message: string;
  /** Full agent detail definition */
  agent_detail: Agent;
  /** Name of the currently active scene */
  current_scene_name?: string | null;
  /** Name of the currently active subscene */
  current_subscene_name?: string | null;
}

/**
 * Response from the Preview Chat API.
 */
export interface PreviewChatResponse {
  /** Agent's response message */
  response: string;
  /** Optional reasoning behind the response */
  reason?: string;
  /** Optional updated scene graph (list of scenes) */
  graph?: SceneGraph[] | null;
  /** Updated active scene */
  current_scene_name?: string | null;
  /** Updated active subscene */
  current_subscene_name?: string | null;
  /** UTC timestamp of the response */
  create_time: string;
}

/**
 * Enum for SSE stream event types.
 */
export enum StreamEventType {
  REASONING = 'reasoning',
  REASON = 'reason',
  RESPONSE = 'response',
  UPDATED_SCENES = 'updated_scenes',
  MATCH_CONNECTION = 'match_connection',
  ERROR = 'error',
}

/**
 * SSE stream event from Preview Chat API.
 */
export interface StreamEvent {
  /** Type of the stream event */
  type: StreamEventType;
  /** Delta content for text-based events */
  delta?: string | null;
  /** Updated scenes for scene update events */
  updated_scenes?: SceneGraph[] | null;
  /** Matched connection for connection match events */
  matched_connection?: Connection | null;
  /** Error message for error events */
  error?: string | null;
  /** UTC timestamp when the event was created */
  create_time: string;
}
