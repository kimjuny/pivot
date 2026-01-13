/**
 * WebSocket client for real-time communication with backend server.
 * Provides event-driven interface for WebSocket connections with automatic reconnection.
 */

/** WebSocket event types for connection lifecycle */
type WebSocketEvent = 'connected' | 'disconnected' | 'error' | 'message' | 'maxReconnectAttemptsReached';

/** Callback function type for event handlers */
type EventCallback = (data?: unknown) => void;

/**
 * Interface defining WebSocket client operations.
 */
interface WebSocketClient {
  /** WebSocket connection instance */
  ws: WebSocket | null;
  /** Whether connection is currently active */
  isConnected: boolean;
  /** Number of reconnection attempts made */
  reconnectAttempts: number;
  /** Maximum number of reconnection attempts before giving up */
  maxReconnectAttempts: number;
  /** Delay between reconnection attempts in milliseconds */
  reconnectInterval: number;
  /** Event listeners registered for each event type */
  listeners: Record<string, EventCallback[]>;
  /** Establish WebSocket connection */
  connect(): void;
  /** Attempt to reconnect to WebSocket server */
  attemptReconnect(): void;
  /** Send message through WebSocket connection */
  sendMessage(message: unknown): void;
  /** Close WebSocket connection */
  disconnect(): void;
  /** Register event listener */
  on(event: WebSocketEvent, callback: EventCallback): void;
  /** Unregister event listener */
  off(event: WebSocketEvent, callback: EventCallback): void;
  /** Trigger event with optional data */
  emit(event: WebSocketEvent, data?: unknown): void;
}

/**
 * Implementation of WebSocket client with automatic reconnection.
 * Handles connection lifecycle, message parsing, and event emission.
 */
class WebSocketClientImpl implements WebSocketClient {
  ws: WebSocket | null = null;
  isConnected: boolean = false;
  reconnectAttempts: number = 0;
  maxReconnectAttempts: number = 5;
  reconnectInterval: number = 3000;
  listeners: Record<string, EventCallback[]> = {};

  /**
   * Establish WebSocket connection to server.
   * Closes existing connection if present, then creates new connection.
   * Uses environment variable for WebSocket URL in development.
   */
  connect(): void {
    if (this.ws) {
      this.ws.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace('/api', '') || 'http://localhost:8003';
    const wsUrl = `${wsBaseUrl}/ws`;
    
    try {
      this.ws = new WebSocket(wsUrl);
      
      this.ws.onopen = () => {
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.emit('connected');
      };

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string) as Record<string, unknown>;
          this.emit('message', data);
        } catch (error) {
          void error;
        }
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        this.emit('disconnected');
        this.attemptReconnect();
      };

      this.ws.onerror = (error: Event) => {
        this.emit('error', error);
      };
    } catch (error) {
      console.error('Failed to establish WebSocket connection:', error);
      this.emit('error', error);
      this.attemptReconnect();
    }
  }

  /**
   * Attempt to reconnect to WebSocket server.
   * Uses exponential backoff with maximum retry limit.
   */
  attemptReconnect(): void {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      
      setTimeout(() => {
        this.connect();
      }, this.reconnectInterval);
    } else {
      this.emit('maxReconnectAttemptsReached');
    }
  }

  /**
   * Send message through WebSocket connection.
   * Only sends if connection is active.
   * 
   * @param message - Message data to send (will be JSON stringified)
   */
  sendMessage(message: unknown): void {
    if (this.isConnected && this.ws) {
      this.ws.send(JSON.stringify(message));
    }
  }

  /**
   * Close WebSocket connection.
   */
  disconnect(): void {
    if (this.ws) {
      this.ws.close();
    }
  }

  /**
   * Register event listener for specific event type.
   * 
   * @param event - Event type to listen for
   * @param callback - Function to call when event occurs
   */
  on(event: WebSocketEvent, callback: EventCallback): void {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }

  /**
   * Unregister event listener for specific event type.
   * 
   * @param event - Event type to stop listening for
   * @param callback - Function to remove from listeners
   */
  off(event: WebSocketEvent, callback: EventCallback): void {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }
  }

  /**
   * Trigger event and call all registered listeners.
   * 
   * @param event - Event type to trigger
   * @param data - Optional data to pass to listeners
   */
  emit(event: WebSocketEvent, data?: unknown): void {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => callback(data));
    }
  }
}

/** Global WebSocket client instance */
const wsClient = new WebSocketClientImpl();
export default wsClient as WebSocketClient;
