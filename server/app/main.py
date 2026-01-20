import logging
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add server directory and parent directory to Python path BEFORE importing other modules
server_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(server_dir)
sys.path.append(str(Path(server_dir).parent))

# Import core modules after path is set up (noqa: E402 - must be after sys.path setup)
# Import server modules (noqa: E402 - must be after sys.path setup)
from app.api.agents import router as agents_router  # noqa: E402
from app.api.build import router as build_router  # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402
from app.api.scenes import router as scenes_router  # noqa: E402
from app.db.session import init_db  # noqa: E402

from core.utils.logging_config import get_logger  # noqa: E402
from server.websocket import websocket_endpoint  # noqa: E402

# Configure logging before importing other modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Set core module loggers to DEBUG level for development
logging.getLogger("core").setLevel(logging.DEBUG)
logging.getLogger("core.agent").setLevel(logging.DEBUG)
logging.getLogger("core.llm").setLevel(logging.DEBUG)

# Initialize logger for server
logger = get_logger("server")

app = FastAPI(title="Agent Visualization API", version="1.0.0")

# Add CORS middleware to allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(agents_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(build_router, prefix="/api")

# WebSocket endpoint
app.websocket("/ws")(websocket_endpoint)


# Startup event to initialize database
@app.on_event("startup")
async def startup_event():
    """Handle application startup events.

    Initializes the database and logs startup completion.
    """
    logger.info("Starting up application...")
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully")
    logger.info("Application startup complete")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown events.

    Logs shutdown notification.
    """
    logger.info("Shutting down application...")


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
