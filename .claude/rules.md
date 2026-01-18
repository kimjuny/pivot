# Claude Development Rules for Pivot

This document outlines the rules and guidelines that Claude must follow when working on the Pivot project - an Agent development framework with visualization capabilities.

## Project Overview

**Pivot** is an open-source Agent development framework consisting of three main components:

- **core**: Pure Python framework core library (agent, llm, utils modules)
- **server**: FastAPI backend providing orchestration and conversation APIs
- **web**: React + TypeScript frontend for visual agent orchestration and chat

## General Principles

### Language Standards
- **ENGLISH FIRST**: All code comments, documentation, frontend UI text, and commit messages MUST be in English
- This is an international open-source project - ensure accessibility for global contributors

### Configuration Immutability
- **NEVER modify** `pyproject.toml`, `web/tsconfig.json`, or `web/eslint.config.js`
- These configurations are carefully tuned - relaxations are intentional, strict rules are mandatory
- Do not attempt to bypass or lower any code quality standards

### Code Quality Workflow
- **For Python changes**: Must run `server/lint.sh` and fix ALL reported errors before completion
- **For web changes**: Must run `npm run check-all` (lint + type-check) and fix ALL errors before completion
- Fix all reported issues, not just those directly related to your changes

## Python Development Rules (core & server)

### Code Quality Standards

**Configuration Source**: `pyproject.toml` at project root

#### Ruff Configuration Requirements
- **Line Length**: 88 characters (hard limit)
- **Target Version**: Python 3.10 (for maximum compatibility)
- **Rule Sets**: E, F, I, B, UP, N, C4, PTH, RUF, SIM, TCH
- **Formatting**: Double quotes, 4-space indentation

#### Pyright Configuration Requirements
- **Type Checking Mode**: `standard`
- **Python Version**: 3.10
- **Strict Enforcement**:
  - `reportOptionalMemberAccess`: Error level (mandatory None-checks)
  - `reportGeneralTypeIssues`: Error level
  - `reportUnusedImport`: Warning level
  - `reportUnusedVariable`: Warning level

### Pre-Commit Workflow (MANDATORY)

Before completing any task involving Python code, you MUST:

1. Run `ruff check . --fix` from `server/` directory (checks both server and core)
2. Run `ruff format .` to ensure consistent styling
3. Run `pyright .` to verify type integrity
4. Fix all reported issues before considering the task complete

### Strategic Coding Requirements

#### Type Safety
- **Type Hints**: Mandatory for all function signatures and class members
- **Union Types**: Use `T | None` syntax (Python 3.10+), NOT `Optional[T]`
- **None-Safety**: Explicit guards required before accessing Optional types
  ```python
  if agent is not None:
      agent.execute()
  ```

#### Code Style
- **Naming**: `snake_case` for variables/functions, `PascalCase` for classes
- **Path Handling**: Always use `pathlib.Path`, NEVER `os.path`
- **Import Organization**: Automatic via Ruff (stdlib → third-party → first-party)

#### Module Integration
- Multi-module structure: `./core/` and `./server/`
- Access shared logic via `import core.xxx`
- The `extraPaths = ["../"]` in pyproject.toml enables cross-module type resolution
- **DO NOT break this resolution path**

#### Import Management
- `core` and `server` are recognized as first-party local modules
- Use `if TYPE_CHECKING:` blocks for imports used only in type annotations
- Avoid circular dependencies

### Documentation Standards

#### Docstring Format (Google Style)
All public functions, classes, and methods MUST have Google-style docstrings:

```python
def get_agent_status(agent_id: str, verbose: bool = False) -> dict | None:
    """Fetches the current status of a specific agent.

    Args:
        agent_id: The unique identifier of the agent.
        verbose: If True, returns detailed metadata.

    Returns:
        A dictionary containing status info, or None if agent doesn't exist.

    Raises:
        ConnectionError: If the core database is unreachable.
    """
```

#### Commentary Rules
- **NO redundant comments**: Don't state the obvious (e.g., `# Increment i`)
- **Explain "WHY", not "WHAT"**: Document business logic, technical constraints, design decisions
- **Side effects**: Clearly document if functions modify global state or write to files
- **TODO format**: Use `TODO(username): description` for temporary hacks or planned features
- **Complex logic**: If a method contains unique designs that may confuse readers, explain the principles and design rationale clearly

### Testing Requirements
- New features should include unit tests
- Ensure existing tests pass before completing any task
- Follow established testing patterns in the project

## TypeScript & React Development Rules (web)

### Configuration Standards

**Configuration Sources**:
- `web/tsconfig.json`: TypeScript compiler settings
- `web/eslint.config.js`: Linting rules
- `web/tailwind.config.js`: Styling theme configuration
- `web/vite.config.ts`: Build configuration

**Prohibited Actions**:
- **NEVER** modify `tsconfig.json`, `eslint.config.js`, or `tailwind.config.js`
- **NEVER** use `/* eslint-disable ... */` to bypass rules
- **NEVER** use `// @ts-ignore`, `// @ts-nocheck`, or `/* @ts-expect-error */`
- For global variables, declare them in `web/src/global.d.ts`

### Type Safety Standards

#### TypeScript Compiler Options
- **Strict Mode**: Enabled (`"strict": true`)
- **Implicit Any**: Prohibited (`"noImplicitAny": true`)
- **Module Detection**: Force isolation to prevent variable name conflicts
- Unused locals/parameters: Allowed (IDE will gray them out, don't hard-block AI)

#### ESLint Rules
- **No unused vars**: OFF (let IDE handle via graying out)
- **Explicit any**: WARN (allowed as escape hatch when needed)
- **React Hooks deps**: ERROR (strict dependency checking is mandatory)
- **No console/debugger**: WARN (remove before committing)
- **React Refresh**: Enabled for HMR optimization

### Pre-Commit Workflow (MANDATORY)

Before completing any task involving web code, you MUST:

1. Run `npm run check-all` from `web/` directory
   - This runs both `eslint` and `tsc` checks
2. Fix ALL reported errors, not just those directly related to your changes
3. Ensure the build succeeds

### Code Style Requirements

#### JSDoc Comments
- All exported components, functions, interfaces MUST use `/** ... */` format
- Must include descriptions
- Complex Props MUST be documented in interfaces with inline comments
- Component tops must summarize functionality
- Special Hook logic (e.g., complex `useEffect`) must explain trigger conditions

#### Color System
- **CRITICAL**: Follow `tailwind.config.js` theme colors strictly
- Use defined color tokens: `primary`, `dark.bg`, `dark.border`, `dark.text`, etc.
- **NEVER** create arbitrary color values inline
- Prevent color inconsistency across the UI

#### Timestamp Handling (CRITICAL)

**Backend (server)**:
- All timestamp fields MUST use `datetime.now(timezone.utc)` as `default_factory`
- When returning timestamps via API, ALWAYS use `.replace(tzinfo=timezone.utc).isoformat()`
- This ensures ISO 8601 format with explicit UTC timezone

**Frontend (web)**:
- Use `web/src/utils/timestamp.ts` conversion functions
  - `formatTimestamp()`: Full datetime in user's local timezone
  - `formatDate()`: Date only in user's local timezone
  - `formatTime()`: Time only in user's local timezone
- Frontend renders UTC timestamps converted to user's local time
- Example: `formatTimestamp(message.create_time)`

**Key Principles**:
1. Backend generates and returns UTC timestamps only (no timezone conversion)
2. Frontend converts UTC to local time for display
3. API layer must explicitly tag UTC timezone to prevent serialization loss

### React Best Practices

#### Component Structure
- Functional components with hooks (no class components)
- Use `@xyflow/react` for graph visualization
- Use Zustand for state management
- Use React Router for navigation

#### Hook Rules
- **CRITICAL**: Follow exhaustive-deps rule (enforced as ERROR)
- Don't omit dependencies from useEffect/useCallback/useMemo
- Use ESLint auto-fix suggestions for deps arrays

#### Import Organization
- Follow ESLint auto-sorting
- Group: React imports → Third-party → First-party → Types → Styles

## Project Architecture

### Directory Structure

```
pivot/
├── core/                      # Pure Python framework core
│   ├── agent/                # Agent framework logic
│   ├── llm/                  # LLM integration
│   └── utils/                # Utility functions
│
├── server/                   # FastAPI backend
│   ├── app/
│   │   ├── api/             # REST API endpoints
│   │   ├── models/          # SQLModel database models
│   │   ├── db/              # Database session/engine
│   │   └── main.py          # FastAPI app entry point
│   └── lint.sh              # Linting script (MUST run before commits)
│
├── web/                      # React + TypeScript frontend
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── utils/           # Utilities (api.js, timestamp.ts)
│   │   └── global.d.ts      # Global type declarations
│   ├── tailwind.config.js   # Theme configuration (DO NOT MODIFY)
│   ├── tsconfig.json        # TypeScript config (DO NOT MODIFY)
│   └── eslint.config.js     # ESLint config (DO NOT MODIFY)
│
└── pyproject.toml           # Python project config (DO NOT MODIFY)
```

### Technology Stack

**Backend (server)**:
- FastAPI: Web framework
- SQLModel: ORM + Pydantic validation (unified model system)
- SQLAlchemy: Database toolkit
- Alembic: Database migrations
- Uvicorn: ASGI server
- WebSockets: Real-time communication

**Frontend (web)**:
- React 18: UI framework
- TypeScript: Type-safe JavaScript
- Vite: Build tool and dev server
- Tailwind CSS: Utility-first styling
- @xyflow/react: Graph visualization
- Zustand: State management
- React Router: Navigation

**Development Tools**:
- Ruff: Python linting and formatting
- Pyright: Python type checking
- ESLint: JavaScript/TypeScript linting
- TypeScript: Type checking

## Universal Development Rules

### Open Source Best Practices
- All configurations must be **generic and reusable**
- **NO** local-specific settings that would break for other developers
- Ensure first-time contributors can easily start and debug the project
- Documentation must be clear for external contributors

### Cross-Module Data Flow
- Clearly document data flow between `core` and `server` modules
- Ensure type hints enable cross-module IDE autocomplete
- Maintain the `extraPaths` configuration for type resolution

### Error Handling
- Explicit None-checks mandatory for Optional types (Python)
- No error suppression via linting disables (TypeScript/Python)
- Proper exception handling with specific exception types
- User-friendly error messages in API responses

### Performance Considerations
- Use `pathlib.Path` for efficient path operations
- Leverage SQLModel's unified ORM/Pydantic approach to reduce code duplication
- Optimize database queries with proper indexing
- Use React.memo and useMemo for expensive computations

## Mandatory Pre-Completion Checklist

Before marking any task as complete, verify:

### For Python Changes:
- [ ] Ran `ruff check . --fix` from server/ directory
- [ ] Ran `ruff format .` from server/ directory
- [ ] Ran `pyright .` from server/ directory
- [ ] All reported errors are fixed
- [ ] Type hints present on all functions/classes
- [ ] Google-style docstrings on public APIs
- [ ] No `# @ts-ignore` or similar bypasses

### For Web Changes:
- [ ] Ran `npm run check-all` from web/ directory
- [ ] All ESLint and TypeScript errors fixed
- [ ] No `// @ts-ignore` or `/* eslint-disable */` present
- [ ] Colors use `tailwind.config.js` tokens only
- [ ] Timestamps use `timestamp.ts` utility functions
- [ ] JSDoc comments on all exports
- [ ] React Hooks dependencies are complete

### For All Changes:
- [ ] All text/comments in English
- [ ] No configuration files modified (pyproject.toml, tsconfig.json, eslint.config.js)
- [ ] Code follows project architecture patterns
- [ ] Tests pass (if applicable)
- [ ] Documentation updated (if needed)

## Code Review Principles

When reviewing code or generating PRs:
1. **Type Safety**: No `any` types without clear justification
2. **None Handling**: Explicit guards for all Optionals
3. **Documentation**: Why, not what - explain business logic
4. **Testing**: New features have test coverage
5. **Style**: Consistent with project patterns
6. **Performance**: No obvious anti-patterns
7. **Security**: No injection vulnerabilities, proper input validation

## Key Architectural Constraints

### Module Boundaries
- `core` MUST remain usable standalone (without server/web)
- Server orchestrates core logic for API access
- Web provides visualization layer only
- No circular dependencies between modules

### Database Design
- Use SQLModel for unified ORM/Pydantic models
- Alembic handles all migrations automatically
- Timestamps in UTC timezone only
- Proper foreign key relationships

### API Design
- RESTful endpoints with consistent response format
- Proper HTTP status codes
- Request/response validation via Pydantic/SQLModel
- WebSocket support for real-time updates

### Frontend Architecture
- Component-based React architecture
- Zustand for global state
- Local state for component-specific data
- Proper separation: UI (components) → State (store) → API (utils/api.js)

---

**Remember**: These rules exist to ensure code quality, maintainability, and collaboration in an open-source environment. Following them strictly prevents bugs, reduces review cycles, and makes the project accessible to all contributors.

**When in doubt**: err on the side of stricter standards, clearer documentation, and more comprehensive testing.
