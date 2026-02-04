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

    # Start backend with proper output prefix
    poetry run python -m uvicorn app.main:app --reload --port 8003 2>&1 | sed 's/^/[BACKEND] /' &
    BACKEND_PID=$!
    cd ..
    echo "Backend server started with PID $BACKEND_PID"
}

# Function to start frontend
start_frontend() {
    echo "Starting frontend development server..."
    cd web
    
    # Kill any process using port 3000
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    
    # Start frontend with proper output prefix
    npm run dev 2>&1 | sed 's/^/[FRONTEND] /' &
    FRONTEND_PID=$!
    cd ..
    echo "Frontend server started with PID $FRONTEND_PID"
}

# Function to start tests
start_tests() {
    echo "Starting test watcher..."
    cd web
    
    # Start test watcher with proper output prefix
    npm run test:watch 2>&1 | sed 's/^/[TEST] /' &
    TEST_PID=$!
    cd ..
    echo "Test watcher started with PID $TEST_PID"
}

# Function to stop processes
stop_processes() {
    echo ""
    echo "Stopping processes..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo "Backend stopped"
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
        echo "Frontend stopped"
    fi
    if [ ! -z "$TEST_PID" ]; then
        kill $TEST_PID 2>/dev/null
        echo "Test watcher stopped"
    fi
    exit 0
}

# Trap Ctrl+C to stop processes
trap stop_processes INT TERM

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
    echo ""
    echo "Starting development services..."
    echo ""
    
    # Start all services separately with output prefixes
    start_backend
    sleep 1
    start_frontend
    sleep 1
    start_tests
else
    # For production, start backend and frontend separately
    start_backend
    start_frontend
fi

echo ""
echo "========================================="
echo "Servers started successfully!"
echo "========================================="
echo "Environment: $ENV"
echo "Backend API: http://localhost:8003"
echo "Frontend:    http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop all servers"
echo "========================================="
echo ""

# Wait for processes to complete
wait
