import logging
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add server directory and parent directory to the Python path BEFORE importing other modules
server_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(server_dir)
sys.path.append(str(Path(server_dir).parent))

# Configure logging before importing other modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler()]
)

# Set core module loggers to DEBUG level for development
logging.getLogger('core').setLevel(logging.DEBUG)
logging.getLogger('core.agent').setLevel(logging.DEBUG)
logging.getLogger('core.llm').setLevel(logging.DEBUG)

# Import logging config to ensure core modules use of same logging setup
from core.utils.logging_config import get_logger

# Initialize logger for server
logger = get_logger('server')

# Import database session and models
# Import WebSocket manager
# Import API routers
from app.api.agents import router as agents_router
from app.db.session import init_db
from server.websocket import websocket_endpoint

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

# WebSocket endpoint
app.websocket("/ws")(websocket_endpoint)

# Startup event to initialize database
@app.on_event("startup")
async def startup_event():
    logger.info("Starting up application...")
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully")
    logger.info("Application startup complete")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down application...")

# Global exception handler for better error logging
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc!s}")
    logger.error(f"Exception traceback:\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal server error: {exc!s}",
            "type": type(exc).__name__,
            "path": str(request.url)
        }
    )

# Health check endpoints
@app.get("/")
async def root():
    logger.info("Root endpoint accessed")
    return {"message": "Agent Visualization API"}

@app.get("/health")
async def health_check():
    logger.info("Health check endpoint accessed")
    return {"status": "healthy"}
