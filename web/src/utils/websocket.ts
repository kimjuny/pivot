/* eslint-disable no-undef */

type WebSocketEvent = 'connected' | 'disconnected' | 'error' | 'message' | 'maxReconnectAttemptsReached';
type EventCallback = (data?: unknown) => void;

interface WebSocketClient {
  ws: WebSocket | null;
  isConnected: boolean;
  reconnectAttempts: number;
  maxReconnectAttempts: number;
  reconnectInterval: number;
  listeners: Record<string, EventCallback[]>;
  connect(): void;
  attemptReconnect(): void;
  sendMessage(message: unknown): void;
  disconnect(): void;
  on(event: WebSocketEvent, callback: EventCallback): void;
  off(event: WebSocketEvent, callback: EventCallback): void;
  emit(event: WebSocketEvent, data?: unknown): void;
}

class WebSocketClientImpl implements WebSocketClient {
  ws: WebSocket | null = null;
  isConnected: boolean = false;
  reconnectAttempts: number = 0;
  maxReconnectAttempts: number = 5;
  reconnectInterval: number = 3000;
  listeners: Record<string, EventCallback[]> = {};

  connect(): void {
    if (this.ws) {
      this.ws.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.hostname}:8003/ws`;
    
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

  sendMessage(message: unknown): void {
    if (this.isConnected && this.ws) {
      this.ws.send(JSON.stringify(message));
    }
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close();
    }
  }

  on(event: WebSocketEvent, callback: EventCallback): void {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }

  off(event: WebSocketEvent, callback: EventCallback): void {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }
  }

  emit(event: WebSocketEvent, data?: unknown): void {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => callback(data));
    }
  }
}

const wsClient = new WebSocketClientImpl();
export default wsClient as WebSocketClient;
