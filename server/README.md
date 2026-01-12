# Agent Visualization Server

This directory contains the FastAPI backend for the agent visualization system.

## Structure

- `main.py`: Entry point for the FastAPI application
- `api.py`: API endpoints for interacting with the agent
- `websocket.py`: WebSocket support for real-time updates
- `requirements.txt`: Python dependencies

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your DOUBAO_SEED_API_KEY environment variable:
   ```bash
   export DOUBAO_SEED_API_KEY=your_api_key_here
   ```

3. Run the server:
   ```bash
   uvicorn server.main:app --reload
   ```

The API will be available at http://localhost:8000
WebSocket connections can be made to ws://localhost:8000/ws