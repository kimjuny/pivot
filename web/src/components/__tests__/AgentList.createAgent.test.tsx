import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import AgentList from '../AgentList'
import * as api from '../../utils/api'
import { mockAgent, mockScenes, mockSceneGraph } from '../../test/mocks'

vi.mock('../../utils/api', () => ({
  getAgents: vi.fn(),
  createAgent: vi.fn(),
  getAgentById: vi.fn(),
  getScenes: vi.fn(),
}))

vi.mock('../../store/sceneGraphStore', () => ({
  useSceneGraphStore: vi.fn(() => ({
    refreshSceneGraph: vi.fn(),
  })),
}))

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }: { children: React.ReactNode }) => React.createElement('div', { 'data-testid': 'react-flow' }, children),
  MiniMap: () => React.createElement('div', { 'data-testid': 'minimap' }),
  Controls: () => React.createElement('div', { 'data-testid': 'controls' }),
  Background: () => React.createElement('div', { 'data-testid': 'background' }),
  MarkerType: { ArrowClosed: 'arrowclosed' },
}))

function LocationDisplay() {
  const location = useLocation()
  return <div data-testid="location-display">{location.pathname}</div>
}

function renderWithRouter(component: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={component} />
        <Route path="/agent/:agentId" element={<div data-testid="agent-detail">Agent Detail</div>} />
      </Routes>
      <LocationDisplay />
    </MemoryRouter>
  )
}

describe('AgentList - Create Agent Flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.location.pathname = '/'
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should open create agent modal when Create Agent button is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getAgents).mockResolvedValue([])

    renderWithRouter(<AgentList />)

    await waitFor(() => {
      expect(screen.getByText('Agent List')).toBeInTheDocument()
    })

    const createButton = screen.getByRole('button', { name: /Create Agent/i })
    await user.click(createButton)

    await waitFor(() => {
      expect(screen.getByText('Create New Agent')).toBeInTheDocument()
    })
  })

  it('should display error message when agent creation fails', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getAgents).mockResolvedValue([])
    const errorMessage = 'Failed to create agent: Agent name already exists'
    vi.mocked(api.createAgent).mockRejectedValue(new Error(errorMessage))

    renderWithRouter(<AgentList />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create Agent/i })).toBeInTheDocument()
    })

    const createButton = screen.getByRole('button', { name: /Create Agent/i })
    await user.click(createButton)

    await waitFor(() => {
      expect(screen.getByText('Create New Agent')).toBeInTheDocument()
    })

    const nameInput = screen.getByPlaceholderText('Enter agent name')
    await user.type(nameInput, 'Test Agent')

    const createModalButton = screen.getByRole('button', { name: 'Create' })
    await user.click(createModalButton)

    await waitFor(() => {
      expect(screen.getByText(errorMessage)).toBeInTheDocument()
    })

    expect(screen.getByText('Create New Agent')).toBeInTheDocument()
  })

  it('should navigate to agent detail page and show empty scene list and graph when agent creation succeeds', async () => {
    const user = userEvent.setup()
    const newAgent = { ...mockAgent, id: 123, name: 'New Test Agent' }
    
    vi.mocked(api.getAgents).mockResolvedValue([])
    vi.mocked(api.createAgent).mockResolvedValue(newAgent)
    vi.mocked(api.getAgentById).mockResolvedValue(newAgent)
    vi.mocked(api.getScenes).mockResolvedValue([])

    renderWithRouter(<AgentList />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create Agent/i })).toBeInTheDocument()
    })

    const createButton = screen.getByRole('button', { name: /Create Agent/i })
    await user.click(createButton)

    await waitFor(() => {
      expect(screen.getByText('Create New Agent')).toBeInTheDocument()
    })

    const nameInput = screen.getByPlaceholderText('Enter agent name')
    const descriptionInput = screen.getByPlaceholderText('Enter agent description (optional)')
    const modelInput = screen.getByPlaceholderText(/e\.g\., gpt-4/)

    await user.type(nameInput, 'New Test Agent')
    await user.type(descriptionInput, 'Test agent description')
    await user.type(modelInput, 'gpt-4')

    const createModalButton = screen.getByRole('button', { name: 'Create' })
    await user.click(createModalButton)

    await waitFor(() => {
      expect(api.createAgent).toHaveBeenCalledWith({
        name: 'New Test Agent',
        description: 'Test agent description',
        model_name: 'gpt-4',
        is_active: true,
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId('location-display')).toHaveTextContent('/agent/123')
    })

    expect(screen.getByText('Agent Detail')).toBeInTheDocument()
  })

  it('should show validation error when creating agent without name', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getAgents).mockResolvedValue([])

    renderWithRouter(<AgentList />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create Agent/i })).toBeInTheDocument()
    })

    const createButton = screen.getByRole('button', { name: /Create Agent/i })
    await user.click(createButton)

    await waitFor(() => {
      expect(screen.getByText('Create New Agent')).toBeInTheDocument()
    })

    const nameInput = screen.getByPlaceholderText('Enter agent name')
    const createModalButton = screen.getByRole('button', { name: 'Create' })

    expect(createModalButton).toBeDisabled()

    await user.type(nameInput, 'Test Agent')
    await user.clear(nameInput)

    expect(createModalButton).toBeDisabled()

    await user.type(nameInput, 'Test Agent')
    expect(createModalButton).not.toBeDisabled()
  })

  it('should close modal when clicking cancel button', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getAgents).mockResolvedValue([])

    renderWithRouter(<AgentList />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create Agent/i })).toBeInTheDocument()
    })

    const createButton = screen.getByRole('button', { name: /Create Agent/i })
    await user.click(createButton)

    await waitFor(() => {
      expect(screen.getByText('Create New Agent')).toBeInTheDocument()
    })

    const cancelButton = screen.getByRole('button', { name: 'Cancel' })
    await user.click(cancelButton)

    await waitFor(() => {
      expect(screen.queryByText('Create New Agent')).not.toBeInTheDocument()
    })
  })

  it('should close modal when clicking X button', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getAgents).mockResolvedValue([])

    renderWithRouter(<AgentList />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create Agent/i })).toBeInTheDocument()
    })

    const createButton = screen.getByRole('button', { name: /Create Agent/i })
    await user.click(createButton)

    await waitFor(() => {
      expect(screen.getByText('Create New Agent')).toBeInTheDocument()
    })

    const closeButton = screen.getByRole('button', { name: '' })
    await user.click(closeButton)

    await waitFor(() => {
      expect(screen.queryByText('Create New Agent')).not.toBeInTheDocument()
    })
  })
})
