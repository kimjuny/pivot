#!/bin/bash

# Startup script for the Agent Visualization System

echo "========================================"
echo "Agent Visualization System Startup Script"
echo "========================================"

# Default to development environment
ENV=${ENVIRONMENT:-"dev"}

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
    python3 -m uvicorn app.main:app --reload --port 8003 &
    BACKEND_PID=$!
    cd ..
    echo "Backend server started with PID $BACKEND_PID"
    echo "Environment variables: DOUBAO_SEED_API_KEY=${DOUBAO_SEED_API_KEY:+(set)}"
}

# Function to start frontend
start_frontend() {
    echo "Starting frontend development server..."
    cd web
    
    # Kill any process using port 3003
    lsof -ti:3003 | xargs kill -9 2>/dev/null || true
    
    # Start frontend
    npm run dev -- --host 127.0.0.1 --port 3003 &
    FRONTEND_PID=$!
    cd ..
    echo "Frontend server started with PID $FRONTEND_PID"
}

# Function to stop processes
stop_processes() {
    echo "Stopping processes..."
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

# Start both servers
start_backend
start_frontend

echo ""
echo "Servers started successfully!"
echo "Environment: $ENV"
echo "Backend API available at: http://localhost:8003"
echo "Frontend available at: http://localhost:3003"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for processes to complete
wait