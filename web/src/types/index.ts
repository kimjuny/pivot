export interface Agent {
  id: number;
  name: string;
  description?: string;
  model_name?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Scene {
  id: number;
  name: string;
  description?: string;
  agent_id?: number;
  created_at: string;
  updated_at: string;
}

export interface Subscene {
  id: number;
  name: string;
  type: string;
  state: string;
  description?: string;
  mandatory: boolean;
  objective?: string;
  scene_id?: number;
  created_at: string;
  updated_at: string;
}

export interface Connection {
  id: number;
  name: string;
  condition?: string;
  from_subscene: string;
  to_subscene: string;
  from_subscene_id?: number;
  to_subscene_id?: number;
  scene_id?: number;
  created_at: string;
  updated_at: string;
}

export interface ChatHistory {
  id: number;
  agent_id: number;
  user: string;
  role: 'user' | 'agent';
  message: string;
  reason?: string;
  update_scene?: string;
  create_time: string;
  graph?: SceneGraph;
}

export interface SceneGraph {
  scenes: SceneNode[];
  current_scene?: string;
  current_subscene?: string;
}

export interface SceneNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label: string;
    description?: string;
    type?: string;
    state?: string;
    mandatory?: boolean;
    objective?: string;
  };
}

export interface ChatRequest {
  message: string;
  user?: string;
}

export interface ChatResponse {
  response: string;
  reason?: string;
  graph?: SceneGraph;
  create_time?: string;
}

export interface ChatHistoryResponse {
  history: ChatHistory[];
  latest_graph?: SceneGraph;
}
