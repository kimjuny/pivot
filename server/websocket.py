import json

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """Manages active WebSocket connections.

    This class provides methods to connect, disconnect, and broadcast
    messages to all connected WebSocket clients. It's used to
    push real-time updates (e.g., scene graph changes) to frontend clients.
    """

    def __init__(self):
        """Initialize the connection manager with an empty list of connections."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and add it to active connections.

        Args:
            websocket: The WebSocket connection to accept and track.
        """
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from active connections.

        Args:
            websocket: The WebSocket connection to remove.
        """
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Send a message to a specific WebSocket connection.

        Args:
            message: The message content to send.
            websocket: The WebSocket connection to send the message to.
        """
        await websocket.send_text(message)

    async def broadcast(self, message: dict):
        """Broadcast a message to all active WebSocket connections.

        This is used to send real-time updates to all connected clients,
        such as scene graph updates during agent conversations.

        Args:
            message: The message dictionary to broadcast (will be JSON serialized).
        """
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))


manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication.

    This endpoint handles WebSocket connections, allowing clients to
    receive real-time updates from the server. Currently, it echoes
    messages back to the sender but can be extended to handle
    bidirectional communication.

    Args:
        websocket: The WebSocket connection object.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo the message back
            await manager.send_personal_message(f"You sent: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)