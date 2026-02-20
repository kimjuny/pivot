# =============================================================================
# Pivot — Production Fat Image
# Strategy: Build frontend → copy static into backend → single-process serve
# Usage:    podman build -t pivot .
#           podman run -p 80:80 pivot
# =============================================================================

# ---- Stage 1: Build frontend ------------------------------------------------
FROM docker.io/library/node:20-alpine AS frontend-build

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --legacy-peer-deps --ignore-scripts

COPY web/ ./
# Production build — VITE_API_BASE_URL=/api so requests go to the same origin
ENV VITE_API_BASE_URL=/api
RUN npm run build


# ---- Stage 2: Production runtime --------------------------------------------
FROM docker.io/library/python:3.10-slim AS runtime

# System deps needed by some Python packages (bcrypt, cryptography)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry into a known location
ENV POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1
RUN python -m pip install --no-cache-dir poetry==1.8.5
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Copy dependency manifests first (for layer caching)
COPY pyproject.toml poetry.lock ./

# Install only production dependencies
RUN poetry install --no-root --only main && \
    rm -rf /root/.cache

# Copy application code
COPY server/ ./server/

# Copy built frontend into a directory the backend will serve
COPY --from=frontend-build /build/web/dist ./server/static

# Environment
ENV DATABASE_URL="sqlite:///./server/pivot.db" \
    ENV="production" \
    PYTHONUNBUFFERED=1

EXPOSE 80

# Single-process launch — Uvicorn serves both API and static files
CMD ["poetry", "run", "python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "80", "--workers", "4", \
     "--app-dir", "server"]
