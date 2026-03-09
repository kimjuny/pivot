import sys
import time
import traceback
from asyncio import Task, create_task, sleep
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Add server directory and parent directory to Python path BEFORE importing other modules
server_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(server_dir)
sys.path.append(str(Path(server_dir).parent))

# Import core modules after path is set up (noqa: E402 - must be after sys.path setup)
# Import server modules (noqa: E402 - must be after sys.path setup)
from app.api.agents import router as agents_router  # noqa: E402
from app.api.auth import init_default_user, router as auth_router  # noqa: E402
from app.api.build import router as build_router  # noqa: E402
from app.api.files import router as files_router  # noqa: E402
from app.api.llms import router as llms_router  # noqa: E402
from app.api.models import router as models_router  # noqa: E402
from app.api.react import router as react_router  # noqa: E402
from app.api.scenes import router as scenes_router  # noqa: E402
from app.api.session import router as session_router  # noqa: E402
from app.api.skills import router as skills_router  # noqa: E402
from app.api.tools import router as tools_router  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import (  # noqa: E402
    ensure_file_schema_compatibility,
    ensure_llm_schema_compatibility,
    ensure_react_schema_compatibility,
    get_engine,
    get_session,
)
from app.orchestration.tool import get_tool_manager  # noqa: E402
from app.services.file_service import FileService  # noqa: E402
from app.utils.logging_config import get_logger, setup_logging  # noqa: E402
from sqlmodel import Session as DBSession  # noqa: E402

# Set up logging at startup
setup_logging()

# Initialize logger for server
logger = get_logger("server")

app = FastAPI(title="Agent Visualization API", version="1.0.0")


class TimingMiddleware(BaseHTTPMiddleware):
    """Middleware to log request with processing time appended.

    Replaces uvicorn's default access log with a single line that includes
    the processing time in milliseconds at the end.
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time_ms = (time.time() - start_time) * 1000

        # Log in uvicorn-like format with timing appended: client - "method path" status - Xms
        client = (
            f"{request.client.host}:{request.client.port}" if request.client else "-"
        )
        logger.info(
            f'{client} - "{request.method} {request.url.path} HTTP/{request.scope.get("http_version", "1.1")}" '
            f"{response.status_code} - {process_time_ms:.0f}ms"
        )

        return response


# Add CORS middleware to allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add timing middleware
app.add_middleware(TimingMiddleware)

# Include API routes
app.include_router(agents_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(build_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(llms_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(react_router, prefix="/api")
app.include_router(session_router, prefix="/api")
app.include_router(tools_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(auth_router, prefix="/api")

# ---------- Production: serve frontend static files ----------
# In the production fat image the built React SPA is copied to ./static/.
# Mount it so the backend serves both the API and the UI from a single process.
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.is_dir() and (_static_dir / "index.html").exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Serve assets (JS, CSS, images) before the catch-all
    app.mount(
        "/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets"
    )

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        """Catch-all: return index.html for client-side routing."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_static_dir / "index.html"))


async def _prune_unused_files_loop() -> None:
    """Periodically delete uploaded files that were never used in chat."""
    interval_seconds = int(get_settings().FILE_PRUNE_INTERVAL_MINUTES) * 60
    while True:
        try:
            with DBSession(get_engine()) as session:
                deleted_count = FileService(session).prune_expired_unused_files()
            if deleted_count > 0:
                logger.info("Pruned %d expired unused files", deleted_count)
        except Exception as exc:
            logger.error("Failed to prune expired files: %s", exc)
        await sleep(interval_seconds)


# Startup event to initialize database
@app.on_event("startup")
async def startup_event():
    """Handle application startup events.

    Initializes the database and logs startup completion.
    """
    logger.info("=" * 50)
    logger.info("Starting Pivot Agent Framework...")
    logger.info("=" * 50)

    logger.info("Initializing database...")
    from sqlmodel import SQLModel

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    ensure_llm_schema_compatibility()
    ensure_react_schema_compatibility()
    ensure_file_schema_compatibility()

    logger.info("Database initialized successfully")

    # Initialize default user
    logger.info("Initializing default user...")
    try:
        with next(get_session()) as session:
            init_default_user(session)
    except Exception as e:
        logger.error(f"Failed to initialize default user: {e}")

    # Initialize tool system
    logger.info("Initializing tool system...")
    try:
        tool_manager = get_tool_manager()
        builtin_tools_dir = Path(__file__).parent / "orchestration" / "tool" / "builtin"
        tool_manager.refresh(builtin_tools_dir)
        tool_count = len(tool_manager.list_tools())
        logger.info(f"Tool system initialized with {tool_count} built-in tools")
    except Exception as e:
        logger.error(f"Failed to initialize tool system: {e}")

    app.state.file_prune_task = create_task(_prune_unused_files_loop())

    logger.info("=" * 50)
    logger.info("Application startup complete")
    logger.info("=" * 50)


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown events.

    Logs shutdown notification.
    """
    logger.info("=" * 50)
    logger.info("Shutting down application...")
    logger.info("=" * 50)
    prune_task: Task[None] | None = getattr(app.state, "file_prune_task", None)
    if prune_task is not None:
        prune_task.cancel()


# Global exception handler for better error logging
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions globally.

    Logs the exception details and returns a standardized error response.

    Args:
        request: The incoming request that caused the exception.
        exc: The exception that was raised.

    Returns:
        A JSON response with error details and HTTP 500 status.
    """
    logger.error(f"Unhandled exception on {request.url}: {exc!s}")
    logger.error(f"Exception traceback:\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal server error: {exc!s}",
            "type": type(exc).__name__,
            "path": str(request.url),
        },
    )


# Health check endpoints
@app.get("/")
async def root():
    """Root endpoint returning API information.

    Returns:
        A welcome message for the API.
    """
    logger.info("Root endpoint accessed")
    return {"message": "Agent Visualization API"}


@app.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        A status indicating the API is healthy.
    """
    logger.info("Health check endpoint accessed")
    return {"status": "healthy"}
