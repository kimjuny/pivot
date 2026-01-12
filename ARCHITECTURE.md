# Agent Visualization System Architecture

## Overview
This system provides a graphical interface for visualizing and interacting with agent systems, specifically demonstrating the sleep companion example. It features a FastAPI backend and a React frontend with real-time visualization capabilities.

## System Components

### 1. Core Agent Framework (Existing)
Located in `/core`, this contains the base agent framework with:
- Agent management (`agent.py`)
- Scene graph modeling (`plan/` directory with scenes, subscenes, and connections)
- LLM integration (`llm/` directory)

### 2. Example Implementation (Existing)
Located in `/example`, this contains sample agent scenarios:
- Sleep companion example (`sleep_companion_example.py`)

### 3. Backend (FastAPI Server)
Located in `/server`, this provides REST API and WebSocket endpoints:

#### Key Files:
- `main.py`: Application entry point with CORS configuration
- `api.py`: REST API endpoints for agent interaction
- `websocket.py`: WebSocket support for real-time updates
- `requirements.txt`: Python dependencies

#### API Endpoints:
- `POST /api/initialize`: Initialize the sleep companion agent
- `POST /api/chat`: Chat with the agent
- `GET /api/state`: Get current agent state
- `GET /api/scene-graph`: Get current scene graph
- `POST /api/reset`: Reset the agent
- `WebSocket /ws`: Real-time updates of agent state changes

### 4. Frontend (React + Vite)
Located in `/web`, this provides the graphical interface:

#### Key Features:
- React Flow integration for visualizing agent scene graphs
- Zustand for state management
- TailwindCSS for styling
- Real-time updates via WebSocket

#### Key Files:
- `src/App.jsx`: Main application component
- `src/components/AgentVisualization.jsx`: React Flow visualization
- `src/components/ChatInterface.jsx`: Chat interface
- `src/store/agentStore.js`: Zustand store for state management
- `src/utils/api.js`: REST API client
- `src/utils/websocket.js`: WebSocket client

#### UI Components:
- Scene graph visualization with React Flow
- Interactive chat interface
- Real-time updates of agent state transitions
- Responsive design

## Data Flow

1. **Initialization**: Frontend initializes agent via REST API
2. **Interaction**: User chats with agent through frontend interface
3. **Processing**: Backend processes chat and updates agent state
4. **Visualization**: State changes are broadcast via WebSocket to frontend
5. **Rendering**: React Flow updates visualization in real-time

## Technologies Used

### Backend:
- FastAPI (Python web framework)
- Uvicorn (ASGI server)
- WebSockets (real-time communication)

### Frontend:
- React 18 (UI framework)
- Vite (build tool)
- React Flow (XYFlow) (graph visualization)
- Zustand (state management)
- TailwindCSS (styling)

## Deployment

### Backend:
```bash
cd server
pip install -r requirements.txt
export DOUBAO_SEED_API_KEY=your_api_key_here
uvicorn server.main:app --reload
```

### Frontend:
```bash
cd web
npm install
npm run dev
```

## URLs
- Backend API: http://localhost:8000
- Frontend: http://localhost:3000
- WebSocket: ws://localhost:8000/ws