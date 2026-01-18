# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Pivot** is an Agent Developing Framework - a full-stack web application for creating and visualizing AI agent workflows through scene graphs. Users can build complex conversational agents with structured dialogue flows using a visual node-based interface.

### Module Structure

The project consists of three main modules:
- **core/**: Pure Python framework containing agent logic, LLM integration, and scene planning
- **server/**: FastAPI backend providing REST API and WebSocket endpoints
- **web/**: React + TypeScript frontend for visual agent orchestration and chat

## Development Commands

### Starting the Application

```bash
# Development (default) - SQLite with hot reload
./start.sh --dev

# Production - PostgreSQL
./start.sh --prod
```

**Individual services:**

```bash
# Backend (port 8003)
cd server && poetry run python -m uvicorn app.main:app --reload --port 8003

# Frontend (port 3003)
cd web && npm run dev -- --host 127.0.0.1 --port 3003
```

The startup script automatically kills processes using ports 8003 and 3003 before starting services.

### Backend Code Quality (Python/TypeScript)

**Before completing any task with Python changes in `server/` or `core/`, you MUST run:**

```bash
cd server && ./lint.sh
```

This runs both Ruff (linting + formatting) and Pyright (type checking) across `server/` and `core/` directories.

**Manual commands:**
```bash
cd server
poetry run ruff check . ../core --fix      # Fix linting issues
poetry run ruff format .                   # Format code
poetry run pyright . ../core               # Type checking
```

### Frontend Code Quality (TypeScript/React)

**Before completing any task with web changes, you MUST run:**

```bash
cd web && npm run check-all
```

This runs both ESLint and TypeScript type checking.

**Individual commands:**
```bash
cd web
npm run type-check             # TypeScript type checking
npm run lint:fix               # Fix ESLint issues
npm run build                  # Production build
```

### Database

The database auto-initializes on startup via `server/app/db/session.py:init_db()`. SQLModel automatically creates tables.

**Development (SQLite):**
- Database file: `server/pivot.db` (auto-created)
- Environment: `DATABASE_URL=sqlite:///./pivot.db`

**Production (PostgreSQL):**
- Environment: `DATABASE_URL=postgresql://user:password@localhost:5432/pivot`

### Environment Variables

Required in `server/.env`:

```bash
DATABASE_URL=sqlite:///./pivot.db  # or postgresql://...
DOUBAO_SEED_API_KEY=your_api_key_here
```

## Architecture

### High-Level Data Flow

1. User creates/edits scene graph through React Flow UI (`web/src/components/AgentVisualization.tsx`)
2. Frontend sends changes via REST API (`web/src/utils/api.ts`) to backend
3. Backend stores in SQLite/PostgreSQL via SQLModel models
4. Agent processes chat messages and updates state
5. WebSocket (`ws://localhost:8003/ws`) broadcasts state changes
6. React Flow updates visualization in real-time via Zustand store

### Key Architecture Patterns

**SQLModel Usage:** Models in `server/app/models/` serve as both database tables AND API validation schemas. This eliminates the need for separate Pydantic schemas in most cases. SQLModel unifies ORM and validation.

**Multi-Module Type Resolution:** The project uses `extraPaths = ["./server", "./core"]` in `pyproject.toml` for cross-module type hints. When importing from core, use `import core.xxx`. This enables IDE autocomplete across modules.

**React Flow Integration:** `@xyflow/react` (v12) visualizes scene graphs as nodes and edges. State flows: React Flow UI → Zustand store → REST API → Backend → WebSocket → Frontend update.

**Timestamp Handling:** Backend uses `datetime.now(timezone.utc)` for all timestamps. API returns use `.replace(tzinfo=timezone.utc).isoformat()`. Frontend converts UTC to local time via `web/src/utils/timestamp.ts` utilities.

### Core Entities

- **Agent**: AI agent configuration (model_name, api_key, is_active)
- **Scene**: Workflow container belonging to an Agent
- **Subscene**: Individual workflow nodes with type (start/normal/end), state, objective
- **Connection**: Transitions between subscenes with conditions
- **ChatHistory**: Agent conversation logs with reasoning

### API Endpoints

- **Agents:** `POST/GET/PUT/DELETE /api/v1/agents`
- **Scenes:** `POST/GET/PUT/DELETE /api/v1/scenes`
- **Subscenes:** `POST/PUT/DELETE /api/v1/scenes/{scene_id}/subscenes`
- **Connections:** `POST/PUT/DELETE /api/v1/subscenes/{subscene_id}/connections`
- **WebSocket:** `ws://localhost:8003/ws` for real-time updates

## Critical Development Rules

### Python (server/core)

**Mandatory standards from `.cursorrules`:**
- Type hints required on all functions/classes (use `T | None` not `Optional[T]`)
- Use `pathlib.Path` instead of `os.path`
- Use Google Style docstrings for public functions
- Enforce None-checks for Optional types (pyright enforces as error)
- Double quotes, 4-space indentation
- Target Python 3.10 for compatibility

### TypeScript/React (web)

**Mandatory standards from `.cursorrules`:**
- NO `// @ts-ignore`, `/* @ts-expect-error */`, or `/* eslint-disable */`
- Colors MUST use `tailwind.config.js` theme tokens (primary, dark.bg, etc.)
- Timestamps MUST use `web/src/utils/timestamp.ts` conversion functions
- JSDoc (`/** */`) on all exports
- React Hooks deps must be complete (enforced as ERROR)

### Configuration Immutability

**NEVER modify these files:**
- `pyproject.toml` - Python linting/formatting config
- `web/tsconfig.json` - TypeScript compiler settings
- `web/eslint.config.js` - ESLint rules

### Language Standards

All code comments, documentation, frontend UI text, and commit messages MUST be in English. This is an international open-source project.

## Technology Stack

**Backend:**
- FastAPI (Python 3.10) with SQLModel for unified ORM/Pydantic
- SQLAlchemy with Alembic for migrations
- WebSocket for real-time agent communication
- Poetry for dependency management

**Frontend:**
- React 18 with TypeScript
- @xyflow/react (React Flow v12) for node-based graph visualization
- Zustand for state management
- Vite for build tooling
- Tailwind CSS for styling

**Dev Tools:**
- Ruff for Python linting/formatting
- Pyright for Python type checking
- ESLint + TypeScript for frontend quality

## URLs

- Backend API: http://localhost:8003
- Frontend: http://localhost:3003
- WebSocket: ws://localhost:8003/ws