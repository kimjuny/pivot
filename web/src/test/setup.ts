import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import React from 'react'

afterEach(() => {
  cleanup()
})

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  MiniMap: () => React.createElement('div', { 'data-testid': 'minimap' }),
  Controls: () => React.createElement('div', { 'data-testid': 'controls' }),
  Background: () => React.createElement('div', { 'data-testid': 'background' }),
  useNodesState: (initial: unknown[]) => [initial, vi.fn(), vi.fn()],
  useEdgesState: (initial: unknown[]) => [initial, vi.fn(), vi.fn()],
  addEdge: vi.fn(),
  MarkerType: { ArrowClosed: 'arrowclosed' },
  Handle: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  BezierEdge: () => React.createElement('div', { 'data-testid': 'bezier-edge' }),
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  Node: {},
  Edge: {},
  Connection: {},
  ReactFlowInstance: {},
}))
