import type { Agent, Scene, SceneGraph, SceneNode } from '../types'

export const mockAgent: Agent = {
  id: 1,
  name: 'Test Agent',
  description: 'Test agent description',
  model_name: 'gpt-4',
  is_active: true,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

export const mockScenes: Scene[] = [
  {
    id: 1,
    name: 'Test Scene 1',
    description: 'First test scene',
    agent_id: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 2,
    name: 'Test Scene 2',
    description: 'Second test scene',
    agent_id: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
]

export const mockSceneGraph: SceneGraph = {
  subscenes: [
    {
      id: 'subscene-Start',
      type: 'start',
      position: { x: 100, y: 100 },
      data: {
        label: 'Start',
        description: 'Start node',
        type: 'start',
        state: 'active',
        mandatory: false,
        objective: 'Begin workflow',
      },
      connections: [],
    },
  ],
  current_scene: 'Test Scene 1',
}

export const mockNewScene: Scene = {
  id: 3,
  name: 'New Test Scene',
  description: 'Newly created scene',
  agent_id: 1,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}
