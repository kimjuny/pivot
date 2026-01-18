#!/bin/bash

# Startup script for Pivot

echo "========================================"
echo "Pivot Startup Script"
echo "========================================"

# Add Poetry to PATH if not already present
if ! command -v poetry &> /dev/null; then
    if [ -f "$HOME/.local/bin/poetry" ]; then
        export PATH="$HOME/.local/bin:$PATH"
        echo "Added Poetry to PATH"
    else
        echo "Error: Poetry not found. Please install Poetry first."
        echo "Visit: https://python-poetry.org/docs/#installation"
        exit 1
    fi
fi

# Default to development environment
ENV=${ENVIRONMENT:-"dev"}

# Function to initialize Poetry environment if needed
init_poetry() {
    if [ ! -d ".venv" ]; then
        echo "Poetry environment not found. Installing dependencies..."
        poetry install
        echo "Poetry environment initialized successfully!"
    else
        echo "Poetry environment already exists."
    fi
}

# Function to start backend
start_backend() {
    echo "Starting backend server in $ENV environment..."
    cd server

    # Load environment variables from .env file if it exists
    if [ -f .env ]; then
        export $(cat .env | grep -v '^#' | xargs)
        echo "Loaded environment variables from .env"
    fi

    # Kill any process using port 8003
    lsof -ti:8003 | xargs kill -9 2>/dev/null || true

    # Set environment variables
    if [ "$ENV" = "prod" ]; then
        export DATABASE_URL="postgresql://user:password@localhost:5432/pivot"
        echo "Using PostgreSQL database (Production)"
    else
        export DATABASE_URL="sqlite:///./pivot.db"
        echo "Using SQLite database (Development)"
    fi

    # Start backend
    poetry run python -m uvicorn app.main:app --reload --port 8003 &
    BACKEND_PID=$!
    cd ..
    echo "Backend server started with PID $BACKEND_PID"
    echo "Environment variables: DOUBAO_SEED_API_KEY=${DOUBAO_SEED_API_KEY:+(set)}"
}

# Function to start all services using dev:all (frontend + backend + tests)
start_dev_all() {
    echo "Starting all services (frontend, backend, tests) using dev:all..."
    cd web

    # Kill any process using port 3000
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true

    # Kill any process using port 8003
    lsof -ti:8003 | xargs kill -9 2>/dev/null || true

    # Start all services using dev:all
    npm run dev:all &
    DEV_ALL_PID=$!
    cd ..
    echo "All services started with PID $DEV_ALL_PID"
}

# Function to start frontend
start_frontend() {
    echo "Starting frontend development server..."
    cd web
    
    # Kill any process using port 3000
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    
    # Start frontend
    npm run dev -- --host 127.0.0.1 &
    FRONTEND_PID=$!
    cd ..
    echo "Frontend server started with PID $FRONTEND_PID"
}

# Function to stop processes
stop_processes() {
    echo "Stopping processes..."
    if [ ! -z "$DEV_ALL_PID" ]; then
        kill $DEV_ALL_PID 2>/dev/null
        echo "All services stopped"
    fi
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo "Backend stopped"
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
        echo "Frontend stopped"
    fi
}

# Trap Ctrl+C to stop processes
trap stop_processes INT

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            ENV="dev"
            shift
            ;;
        --prod)
            ENV="prod"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--dev|--prod]"
            exit 1
            ;;
    esac
done

# Initialize Poetry for dev environment
if [ "$ENV" = "dev" ]; then
    init_poetry
fi

# Start services based on environment
if [ "$ENV" = "dev" ]; then
    # Use dev:all for development to start frontend, backend, and tests together
    start_dev_all
else
    # For production, start backend and frontend separately
    start_backend
    start_frontend
fi

echo ""
echo "Servers started successfully!"
echo "Environment: $ENV"
echo "Backend API available at: http://localhost:8003"
echo "Frontend available at: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for processes to complete
wait
