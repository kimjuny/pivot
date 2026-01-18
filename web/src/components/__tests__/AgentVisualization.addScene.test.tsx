import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AgentVisualization from '../AgentVisualization'
import * as api from '../../utils/api'
import { mockAgent, mockScenes, mockSceneGraph, mockNewScene } from '../../test/mocks'

vi.mock('../../utils/api')

describe('AgentVisualization - Add Scene Integration Test', () => {
  const mockOnResetSceneGraph = vi.fn()
  const mockOnSceneSelect = vi.fn()
  const mockOnRefreshScenes = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getSceneGraph).mockResolvedValue(mockSceneGraph)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('should create a new scene and verify it appears in the list and is automatically selected', async () => {
    const user = userEvent.setup()

    render(
      <AgentVisualization
        agent={mockAgent}
        scenes={mockScenes}
        selectedScene={mockScenes[0]}
        agentId={mockAgent.id}
        onResetSceneGraph={mockOnResetSceneGraph}
        onSceneSelect={mockOnSceneSelect}
        onRefreshScenes={mockOnRefreshScenes}
      />
    )

    expect(screen.getByText('Test Scene 1')).toBeInTheDocument()
    expect(screen.getByText('Test Scene 2')).toBeInTheDocument()

    const addSceneButton = screen.getByText('Add Scene')
    expect(addSceneButton).toBeInTheDocument()

    await user.click(addSceneButton)

    expect(screen.getByText('Create New Scene')).toBeInTheDocument()

    const nameInput = screen.getByPlaceholderText('Enter scene name')
    const descriptionTextarea = screen.getByPlaceholderText('Enter scene description (optional)')

    await user.type(nameInput, 'New Test Scene')
    await user.type(descriptionTextarea, 'Newly created scene')

    vi.mocked(api.createScene).mockResolvedValueOnce(mockNewScene)

    const createButton = screen.getByRole('button', { name: 'Create' })
    await user.click(createButton)

    await waitFor(() => {
      expect(api.createScene).toHaveBeenCalledWith({
        name: 'New Test Scene',
        description: 'Newly created scene',
        agent_id: mockAgent.id,
      })
    })

    await waitFor(() => {
      expect(mockOnRefreshScenes).toHaveBeenCalled()
    })

    expect(screen.queryByText('Create New Scene')).not.toBeInTheDocument()

    await waitFor(() => {
      expect(api.getSceneGraph).toHaveBeenCalledWith(mockNewScene.id)
    })
  })

  it('should handle scene creation error', async () => {
    const user = userEvent.setup()
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    vi.mocked(api.createScene).mockRejectedValueOnce(new Error('Failed to create scene'))

    render(
      <AgentVisualization
        agent={mockAgent}
        scenes={mockScenes}
        selectedScene={mockScenes[0]}
        agentId={mockAgent.id}
        onResetSceneGraph={mockOnResetSceneGraph}
        onSceneSelect={mockOnSceneSelect}
        onRefreshScenes={mockOnRefreshScenes}
      />
    )

    const addSceneButton = screen.getByText('Add Scene')
    await user.click(addSceneButton)

    const nameInput = screen.getByPlaceholderText('Enter scene name')
    await user.type(nameInput, 'Error Scene')

    const createButton = screen.getByRole('button', { name: 'Create' })
    await user.click(createButton)

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to create scene:', expect.any(Error))
    })

    expect(mockOnRefreshScenes).not.toHaveBeenCalled()
    expect(mockOnSceneSelect).not.toHaveBeenCalled()

    consoleErrorSpy.mockRestore()
  })

  it('should not create scene without name and keep button disabled', async () => {
    const user = userEvent.setup()

    render(
      <AgentVisualization
        agent={mockAgent}
        scenes={mockScenes}
        selectedScene={mockScenes[0]}
        agentId={mockAgent.id}
        onResetSceneGraph={mockOnResetSceneGraph}
        onSceneSelect={mockOnSceneSelect}
        onRefreshScenes={mockOnRefreshScenes}
      />
    )

    const addSceneButton = screen.getByText('Add Scene')
    await user.click(addSceneButton)

    const createButton = screen.getByRole('button', { name: 'Create' })
    expect(createButton).toBeDisabled()

    expect(api.createScene).not.toHaveBeenCalled()
  })

  it('should close modal when clicking Cancel button', async () => {
    const user = userEvent.setup()

    render(
      <AgentVisualization
        agent={mockAgent}
        scenes={mockScenes}
        selectedScene={mockScenes[0]}
        agentId={mockAgent.id}
        onResetSceneGraph={mockOnResetSceneGraph}
        onSceneSelect={mockOnSceneSelect}
        onRefreshScenes={mockOnRefreshScenes}
      />
    )

    const addSceneButton = screen.getByText('Add Scene')
    await user.click(addSceneButton)

    expect(screen.getByText('Create New Scene')).toBeInTheDocument()

    const cancelButton = screen.getByRole('button', { name: 'Cancel' })
    await user.click(cancelButton)

    await waitFor(() => {
      expect(screen.queryByText('Create New Scene')).not.toBeInTheDocument()
    })
  })
})
