# Project Rules & Guidelines

## Project Overview

**Name**: pivot

## Directory Structure

### Core Module
- **Purpose**: Agent development framework core library
- **Design Principle**: Can be used standalone (without `server` or `web`) to create working examples

```
core/
├── agent/      # Core framework for agent development
├── llm/         # LLM integration for the agent framework
└── utils/       # Utility classes for the agent framework
```

### Server Module
- **Purpose**: Backend service providing agent orchestration and conversational agent instances
- **Key Features**:
  - Agent orchestration capabilities
  - Conversational agent instances (users can interact directly with agents)

```
server/
└── app/api/     # All core server API endpoints
```

### Web Module
- **Purpose**: Frontend user interface for agent development
- **Key Features**:
  - Visual agent orchestration capabilities
  - Visual agent conversation interface

```
web/
├── src/                    # All core frontend application source code
│   ├── components/        # Core UI logic and components
│   └── utils/            # Utility functions
│       ├── api.js         # Server communication API
│       └── timestamp.js   # Timestamp rendering standardization
└── tailwind.config.js      # Tailwind CSS core configuration
```

## Technology Stack

### Core
- **Language**: Pure Python

### Server
- **Framework**: FastAPI
- **Server**: Uvicorn
- **Database**: 
  - Development: SQLite
  - Production: PostgreSQL (configurable)
- **ORM**: SQLModel
- **Migration**: Alembic

### Web
- **Language**: TypeScript
- **Framework**: React
- **Build Tool**: Vite
- **Styling**: Tailwind CSS
- **Graph Visualization**: XyFlow

---

## TypeScript & React Code Standards

### 1. JSDoc Priority

- **Requirement**: All exported components, functions, and interfaces MUST use JSDoc format (`/** ... */`)
- **Content**: MUST include descriptions
- **Complex Props**: MUST document purposes through comments within interfaces

### 2. "Why" Over "What"

- **Prohibited**: Comments stating the obvious (e.g., `// Increment counter`)
- **Required**: Comments explaining the **business reason** or **technical limitation** behind logic
- **Example**: `// This delay avoids third-party API rate limits`

### 3. Type Annotation Comments

- **Complex Generics/Type Guards**: MUST explain derivation logic
- **Prohibited**: `// @ts-ignore`
- **Exception Handling**: If bypassing type checking is necessary, use `// @ts-expect-error` with specific reasoning

### 4. React Component Standards

- **Component Documentation**: MUST include brief functionality description at the top
- **Complex Hook Logic**: MUST explain trigger timing (especially for complex `useEffect`)

### 5. TODO Markers

- **Format**: `// TODO: [name/AI] description of pending task`
- **Usage**: For incomplete edge cases or planned features

---

## Python Development Rules

### Code Quality Standards

**Requirement**: All Python code MUST strictly adhere to `pyproject.toml` configuration

### Ruff Configuration

| Setting | Value | Description |
|----------|---------|-------------|
| **Line Length** | 88 characters | Maximum line length |
| **Target Version** | Python 3.10 | For maximum open-source compatibility |
| **Formatting** | Double quotes, 4-space indentation | Code style |

**Enabled Rule Sets**:
- `E`, `F`: Basic errors and standard lints
- `I`: Automated import sorting
- `B`: Bugbear (detects common design flaws)
- `UP`: Pyupgrade (ensures modern 3.10 syntax)
- `N`: Naming conventions (enforces `snake_case` for functions/variables)
- `C4`: Comprehensions (optimizes list/dict/set creation)
- `PTH`: Pathlib (mandates `pathlib.Path` over `os.path`)
- `SIM`: Simplify (suggests simpler code structures)
- `TCH`: Type-checking blocks (manages imports used only for types)

### Pyright Configuration

| Setting | Value | Description |
|----------|---------|-------------|
| **Type Checking Mode** | `standard` | Type checking strictness |
| **Python Version** | 3.10 | Target Python version |
| **reportOptionalMemberAccess** | **Error** | Explicit None-checks mandatory |
| **reportGeneralTypeIssues** | **Error** | Catch general type issues |
| **reportUnusedImport** | **Warning** | Flag unused imports |
| **reportUnusedVariable** | **Warning** | Flag unused variables |

### Development Workflow

**Required Before Committing**: Execute these commands in the `server` directory:

1. `ruff check . --fix` - Resolve linting and import issues
2. `ruff format .` - Ensure consistent code styling
3. `pyright .` - Verify type integrity

### Strategic Coding Requirements

| Requirement | Details |
|-------------|---------|
| **Type Hints** | Mandatory for all function signatures and class members |
| **None-Safety** | Handle `Optional` types explicitly. Never access attributes of potentially `None` objects without guards (e.g., `if object is not None:`) |
| **Modern Syntax** | Prefer `T \| None` over `Optional[T]` for Union types (Python 3.10 style) |
| **Naming Convention** | `snake_case` for variables/functions, `PascalCase` for classes |
| **Path Handling** | Always use `pathlib.Path`. String-based path manipulation is discouraged |

### Import Organization

| Rule | Details |
|-------|---------|
| **Order** | Follow `isort` rules: Standard library → Third-party → First-party |
| **First-party** | `core` and `server` are recognized as local modules |
| **Circular Dependencies** | Use `if TYPE_CHECKING:` blocks for imports required only for type annotations |

### Core Module Integration

- **Structure**: Multi-module structure with `./core/` and `./server/`
- **Shared Logic Access**: Use `import core.xxx`
- **Type Resolution**: The `extraPaths = ["../"]` setting in `pyproject.toml` enables `server` to resolve types from `core`
- **Important**: Do not break this type resolution

### Testing

- **Requirement**: New features should include unit tests
- **Verification**: Ensure existing tests pass before completing tasks

### Documentation & Style

#### Docstring Standards

- **Format**: Follow **Google Style Docstrings** for all public functions, classes, and methods
- **Mandatory Fields**:
  - `Args`: List all parameters with their purposes
  - `Returns`: Describe return value and its type
  - `Raises`: Document all explicitly raised exceptions

**Example Pattern**:
```python
def get_agent_status(agent_id: str, verbose: bool = False) -> dict | None:
    """Fetches the current status of a specific agent.

    Args:
        agent_id: The unique identifier of the agent.
        verbose: If True, returns detailed metadata.

    Returns:
        A dictionary containing status info, or None if the agent doesn't exist.

    Raises:
        ConnectionError: If the core database is unreachable.
    """
```

#### AI Commentary Rules

| Rule | Description |
|-------|-------------|
| **No Redundancy** | Don't write comments stating the obvious (e.g., `# Increment i by 1`) |
| **Explain "Why", Not "What"** | Use comments to explain complex logic, business rules, or "hacks" not immediately clear from code |
| **Side Effects** | Clearly document any side effects (e.g., modifying global state, writing to files) |
| **TODO Management** | Use `TODO(username): description` for temporary hacks or planned features |
| **Unique Design Logic** | If a method contains unique design principles (especially those that may confuse readers), clearly explain the rationale and logic, including original design intent |

#### Project Context

- **Language**: All documentation must be in **English** (international open-source project)
- **Clarity**: Ensure `core` module integration descriptions are clear enough for external contributors to understand data flow

---

## Other Rules

### Language Requirements

- **Primary**: English first for all code comments and frontend elements with text
- **Documentation**: Use English for all project documentation

### Frontend Configuration Rules

| Rule | Details |
|-------|---------|
| **TSConfig & ESLint** | Strictly follow configurations in `web/tsconfig.json` and `web/eslint.config.js` |
| **Prohibited** | Never modify these configuration files under any circumstances |
| **Compliance** | Strictly adhere to rules where not relaxed; relaxed areas are explicitly marked |

### Backend & Core Configuration Rules

| Rule | Details |
|-------|---------|
| **Pyproject.toml** | Strictly follow all configuration and code style requirements |
| **Prohibited** | Never modify `pyproject.toml` under any circumstances |

### TypeScript Error Handling

**Prohibited Commands**:
- `/* eslint-disable ... */`
- `// @ts-ignore`
- `// @ts-nocheck`
- `/* @ts-expect-error */`

**Global Variables**: Declare in `web/src/global.d.ts` instead of using eslint-disable

### Frontend Color Usage

**Rule**: To avoid color inconsistency, follow the color scheme in `tailwind.config.js` theme configuration

**Best Practice**: Reference colors from the Tailwind config rather than creating custom colors in the UI

### Timestamp Handling Rules

**Backend Responsibility**:

| Layer | Requirement |
|--------|-------------|
| **Model Layer** | All timestamp fields MUST use `datetime.now(timezone.utc)` as `default_factory`. Deprecated: `datetime.utcnow` |
| **API Layer** | Return timestamps MUST explicitly use `.replace(tzinfo=timezone.utc).isoformat()` to ensure ISO 8601 UTC format |
| **Example** | See `chat.py`: `get_chat_history` and `chat_with_agent_by_id` correctly use `.replace(tzinfo=timezone.utc).isoformat()` |

**Frontend Responsibility**:

| Requirement | Details |
|-------------|---------|
| **Timestamp Conversion** | Use `formatTimestamp()` function in `web/src/utils/timestamp.js` to convert UTC timestamps to user's local timezone |
| **Rendering** | Example: In ChatInterface, use `formatTimestamp(message.create_time)` for message timestamps |
| **No Timezone Logic** | Frontend should not handle timezone conversion; only display converted time |

**Key Principles**:

1. **Backend**: Generates and returns UTC timestamps only, performs no timezone conversion
2. **Frontend**: Converts UTC timestamps to local time for display only
3. **API Layer**: Must explicitly annotate UTC timezone to prevent information loss during serialization

### Quality Assurance Checks

**Web Frontend**:
- Run `npm run check-all` after every code modification
- This command performs both linting and type checking (see `package.json`)
- **Requirement**: Fix all reported issues, regardless of direct relation to current changes

**Server & Core**:
- Run `server/lint.sh` after every code modification
- **Requirement**: Fix all ruff and pyright errors, regardless of direct relation to current changes

### Open Source Project Guidelines

**Principle**: This is an open-source project

**Configuration Requirements**:
- Do not include any local-specific configurations
- Configure in a generic, universally applicable manner
- Enable first-time contributors to easily start and debug the project
