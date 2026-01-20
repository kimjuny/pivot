import type { SceneGraph, SceneNode, Connection, Scene, Agent } from '../types';

/**
 * Compares two Agent objects deeply to detect any differences.
 * Checks basic info and all scenes/graphs.
 */
export function compareAgents(agentA: Agent | null, agentB: Agent | null): boolean {
  if (agentA === agentB) return false;
  if (!agentA || !agentB) return true;

  // Compare basic fields
  if (
    agentA.name !== agentB.name ||
    agentA.description !== agentB.description ||
    agentA.model_name !== agentB.model_name ||
    agentA.is_active !== agentB.is_active
  ) {
    return true;
  }

  // Compare scenes
  const scenesA = agentA.scenes || [];
  const scenesB = agentB.scenes || [];

  if (scenesA.length !== scenesB.length) return true;

  // Map by name for comparison
  const mapA = new Map(scenesA.map(s => [s.name || '', s]));

  for (const sceneB of scenesB) {
    const sceneA = mapA.get(sceneB.name || '');
    if (!sceneA) return true; // New scene added

    // Compare scene details using compareSceneGraphs
    // compareSceneGraphs checks the 'scenes' array (subscenes) and other props
    if (compareSceneGraphs(sceneA, sceneB)) return true;
  }

  return false;
}

/**
 * Deep copies an Agent object.
 */
export function deepCopyAgent(agent: Agent | null): Agent | null {
  if (!agent) return null;
  return JSON.parse(JSON.stringify(agent)) as Agent;
}

/**
 * Compares two lists of Scenes to detect any differences.
 * Checks name and description.
 * 
 * @param scenesA - The original scene list
 * @param scenesB - The working scene list
 * @returns True if there are differences
 */
export function compareScenesList(scenesA: Scene[], scenesB: Scene[]): boolean {
  if (scenesA.length !== scenesB.length) {
    return true;
  }

  // Sort by ID to ensure order doesn't affect comparison (unless ID is missing for new scenes)
  // New scenes might have negative IDs or be at the end. 
  // For simplicity, we assume order matters or we compare by finding match.
  // Given the UI list is ordered, let's compare by index for now, or better:
  // Convert to map by ID (for existing) or Name (if unique).
  
  // Simple check: iterate and compare.
  for (let i = 0; i < scenesA.length; i++) {
    const sceneA = scenesA[i];
    const sceneB = scenesB[i];

    if (sceneA.name !== sceneB.name || sceneA.description !== sceneB.description) {
      return true;
    }
  }

  return false;
}

/**
 * Creates a deep copy of a Scene list.
 */
export function deepCopyScenes(scenes: Scene[]): Scene[] {
  return JSON.parse(JSON.stringify(scenes)) as Scene[];
}

/**
 * Compares two SceneGraph objects deeply to detect any differences.
 * This function checks for differences in scenes structure, including
 * subscenes and their connections.
 *
 * @param graphA - The original SceneGraph (A data)
 * @param graphB - The working SceneGraph (B data)
 * @returns True if there are differences, false if they are identical
 */
export function compareSceneGraphs(graphA: SceneGraph | null, graphB: SceneGraph | null): boolean {
  if (graphA === graphB) {
    return false;
  }

  if (!graphA || !graphB) {
    return true;
  }

  if (graphA.subscenes.length !== graphB.subscenes.length) {
    return true;
  }

  for (let i = 0; i < graphA.subscenes.length; i++) {
    const sceneA = graphA.subscenes[i];
    const sceneB = graphB.subscenes[i];

    if (!compareSceneNodes(sceneA, sceneB)) {
      return true;
    }
  }

  return false;
}

/**
 * Compares two scene nodes deeply including their subscenes and connections.
 *
 * @param nodeA - The first scene node
 * @param nodeB - The second scene node
 * @returns True if the nodes are equal, false otherwise
 */
function compareSceneNodes(nodeA: SceneNode, nodeB: SceneNode): boolean {
  if (nodeA === nodeB) {
    return true;
  }

  if (!nodeA || !nodeB) {
    return false;
  }

  if (nodeA.id !== nodeB.id) {
    return false;
  }

  if (nodeA.name !== nodeB.name) {
    return false;
  }

  if (nodeA.type !== nodeB.type) {
    return false;
  }

  if (nodeA.data?.description !== nodeB.data?.description) {
    return false;
  }

  if (nodeA.state !== nodeB.state) {
    return false;
  }

  if (nodeA.mandatory !== nodeB.mandatory) {
    return false;
  }

  if (nodeA.objective !== nodeB.objective) {
    return false;
  }

  const subscenesA = nodeA.subscenes || [];
  const subscenesB = nodeB.subscenes || [];

  if (subscenesA.length !== subscenesB.length) {
    return false;
  }

  for (let i = 0; i < subscenesA.length; i++) {
    if (!compareSceneNodes(subscenesA[i], subscenesB[i])) {
      return false;
    }
  }

  const connectionsA = nodeA.connections || [];
  const connectionsB = nodeB.connections || [];

  if (connectionsA.length !== connectionsB.length) {
    return false;
  }

  for (let i = 0; i < connectionsA.length; i++) {
    if (!compareConnections(connectionsA[i], connectionsB[i])) {
      return false;
    }
  }

  return true;
}

/**
 * Compares two connection objects.
 *
 * @param connA - The first connection
 * @param connB - The second connection
 * @returns True if the connections are equal, false otherwise
 */
function compareConnections(connA: Connection, connB: Connection): boolean {
  if (connA === connB) {
    return true;
  }

  if (!connA || !connB) {
    return false;
  }

  return (
    connA.id === connB.id &&
    connA.name === connB.name &&
    connA.condition === connB.condition &&
    connA.from_subscene === connB.from_subscene &&
    connA.to_subscene === connB.to_subscene
  );
}

/**
 * Creates a deep copy of a SceneGraph object.
 * This is used to initialize the working data (B) from the server data (A).
 *
 * @param graph - The SceneGraph to copy
 * @returns A deep copy of the SceneGraph
 */
export function deepCopySceneGraph(graph: SceneGraph | null): SceneGraph | null {
  if (!graph) {
    return null;
  }

  return JSON.parse(JSON.stringify(graph)) as SceneGraph;
}
