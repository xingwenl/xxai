import { EventEmitter } from './event-emitter';
import { parseProtocolEvent, SDK_VERSION } from './protocol';
import type {
  ConnectionState,
  OutgoingMessage,
  TokenProviderContext,
  WebSocketMessage,
} from './types';
import type { Transport } from './transport';

interface SocketLike {
  readonly readyState: number;
  onopen: ((event: any) => void) | null;
  onmessage: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onclose: ((event: any) => void) | null;
  send(data: string): void;
  close(code?: number): void;
}
type SocketFactory = (url: string, protocols: string | string[]) => SocketLike;
const OPEN = 1;

export class WebSocketTransport extends EventEmitter implements Transport {
  private _ws: SocketLike | null = null;
  private _state: ConnectionState = 'disconnected';
  private _reconnectAttempts = 0;
  private readonly _maxRetries: number;
  private readonly _reconnectDelay: number;
  private readonly _endpoint: string;
  private readonly _getToken: (
    context: TokenProviderContext,
  ) => Promise<string>;
  private readonly _platformId: string;
  private readonly _agentId: string;
  private readonly _user: TokenProviderContext['user'];
  private readonly _websocketFactory: SocketFactory;
  private readonly _setTimeout: typeof setTimeout;
  private readonly _clearTimeout: typeof clearTimeout;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _messageId = 0;
  private _queue: OutgoingMessage[] = [];
  private _connectResolve: (() => void) | null = null;
  private _connectReject: ((error: Error) => void) | null = null;
  private _explicitDisconnect = false;
  private _lastSequence = 0;
  private _sessionReady = false;
  private _conversationId: string | undefined;
  private _registeredTools = new Map<string, OutgoingMessage>();
  private _serverCapabilities: string[] = [];

  constructor(options: {
    endpoint: string;
    getToken: (context: TokenProviderContext) => Promise<string>;
    platformId: string;
    agentId: string;
    user?: TokenProviderContext['user'];
    reconnect?: { maxRetries?: number; delayMs?: number };
    websocketFactory?: SocketFactory;
    setTimeout?: typeof setTimeout;
    clearTimeout?: typeof clearTimeout;
    conversationId?: string;
  }) {
    super();
    this._endpoint = options.endpoint;
    this._getToken = options.getToken;
    this._platformId = options.platformId;
    this._agentId = options.agentId;
    this._user = options.user;
    this._conversationId = options.conversationId;
    this._maxRetries = options.reconnect?.maxRetries ?? 5;
    this._reconnectDelay = options.reconnect?.delayMs ?? 3000;
    this._websocketFactory =
      options.websocketFactory ??
      ((url, protocols) => new WebSocket(url, protocols));
    this._setTimeout = (options.setTimeout ?? globalThis.setTimeout).bind(
      globalThis,
    );
    this._clearTimeout = (options.clearTimeout ?? globalThis.clearTimeout).bind(
      globalThis,
    );
  }

  get state(): ConnectionState {
    return this._state;
  }
  get lastSequence(): number {
    return this._lastSequence;
  }
  get serverCapabilities(): string[] {
    return [...this._serverCapabilities];
  }

  setConversationId(conversationId?: string): void {
    this._conversationId = conversationId || undefined;
  }

  private setState(state: ConnectionState): void {
    if (this._state !== state) {
      this._state = state;
      this.emit('state', state);
    }
  }

  private generateId(): string {
    return `req_${++this._messageId}_${Date.now()}`;
  }

  async connect(): Promise<void> {
    if (this._sessionReady && this._ws?.readyState === OPEN) return;
    if (this._connectResolve)
      return new Promise((resolve, reject) => {
        const resolvePrevious = this._connectResolve;
        const rejectPrevious = this._connectReject;
        this._connectResolve = () => {
          resolvePrevious?.();
          resolve();
        };
        this._connectReject = (error) => {
          rejectPrevious?.(error);
          reject(error);
        };
      });
    this._explicitDisconnect = false;
    this.setState(this._reconnectAttempts ? 'reconnecting' : 'connecting');
    return new Promise((resolve, reject) => {
      this._connectResolve = resolve;
      this._connectReject = reject;
      this.openSocket();
    });
  }

  private openSocket(): void {
    try {
      const socket = this._websocketFactory(this._endpoint, 'ai-agent.v1');
      this._ws = socket;
      this._sessionReady = false;
      socket.onopen = () => {
        void this.authenticate();
        this.emit('open');
      };
      socket.onmessage = (event) => this.handleMessage(event.data);
      socket.onerror = (error) =>
        this.emit(
          'error',
          error instanceof Error ? error : new Error('WebSocket error'),
        );
      socket.onclose = (event) => this.handleClose(event);
    } catch (error) {
      this.failConnect(error);
    }
  }

  private async authenticate(): Promise<void> {
    try {
      const token = await this._getToken({
        platformId: this._platformId,
        agentId: this._agentId,
        user: this._user,
      });
      if (typeof token !== 'string' || !token.trim()) {
        throw new Error('token provider returned an empty token');
      }
      if (!this._ws || this._ws.readyState !== OPEN) return;
      this._ws.send(
        JSON.stringify({
          id: this.generateId(),
          type: 'auth',
          protocolVersion: 1,
          timestamp: new Date().toISOString(),
          payload: {
            token,
            platformId: this._platformId,
            agentId: this._agentId,
            protocolVersion: 1,
            sdkVersion: SDK_VERSION,
            conversationId: this._conversationId,
            lastSequence: this._lastSequence || undefined,
          },
        }),
      );
    } catch (error) {
      this.failConnect(error);
    }
  }

  private handleMessage(raw: string): void {
    try {
      const event = parseProtocolEvent(JSON.parse(raw));
      if (event.type === 'unknown') return;
      if (event.conversationId) {
        console.info(
          '[xxai-agent][conversation] transport received conversation id',
          {
            eventType: event.type,
            requestId: event.requestId,
            conversationId: event.conversationId,
          },
        );
        this._conversationId = event.conversationId;
      }
      if (event.type === 'session_ready') {
        const sessionId = (event.payload as Record<string, unknown>).sessionId;
        if (typeof sessionId === 'string') this._conversationId = sessionId;
        const capabilities = (event.payload as Record<string, unknown>)
          .capabilities;
        if (Array.isArray(capabilities)) {
          this._serverCapabilities = capabilities.filter(
            (item): item is string => typeof item === 'string',
          );
        }
        if (event.sequence > this._lastSequence)
          this._lastSequence = event.sequence;
        this._sessionReady = true;
        this._reconnectAttempts = 0;
        this.setState('connected');
        this._connectResolve?.();
        this._connectResolve = null;
        this._connectReject = null;
        const queued = this._queue;
        this._queue = [];
        const queuedRegistrations = new Set(
          queued.filter((message) => message.type === 'host_tools_register'),
        );
        for (const registration of this._registeredTools.values()) {
          if (!queuedRegistrations.has(registration)) this.send(registration);
        }
        queued.forEach((message) => this.send(message));
      } else {
        if (event.sequence <= this._lastSequence) return;
        this._lastSequence = event.sequence;
      }
      if (event.type === 'error') {
        const payload = event.payload as Record<string, unknown>;
        const code = payload.code;
        if (
          code === 'unsupported_protocol_version' ||
          code === 'unsupported_sdk_version'
        ) {
          const compatibilityError = {
            code: String(code),
            retryable: payload.retryable === true,
          };
          this.emit('compatibility_error', compatibilityError);
          this.failConnect(new Error(String(code)));
        }
      }
      this.emit('message', event as WebSocketMessage);
    } catch (error) {
      this.emit(
        'error',
        error instanceof Error ? error : new Error('Invalid WebSocket message'),
      );
    }
  }

  registerHostTools(tools: OutgoingMessage): void {
    const definitions = tools.payload.tools;
    if (Array.isArray(definitions)) {
      for (const definition of definitions) {
        if (
          definition &&
          typeof definition === 'object' &&
          'name' in definition &&
          typeof definition.name === 'string'
        ) {
          this._registeredTools.set(definition.name, tools);
        }
      }
    }
    this.send(tools);
  }

  resolveToolCall(callId: string, approved: boolean): void {
    this.send({
      type: 'confirmation_resolve',
      requestId: callId,
      payload: { callId, approved },
    });
  }

  sendHostToolResult(callId: string, result: unknown): void {
    this.send({
      type: 'host_tool_result',
      requestId: callId,
      payload: { callId, result },
    });
  }

  sendHostToolError(callId: string, code: string, message: string): void {
    this.send({
      type: 'host_tool_error',
      requestId: callId,
      payload: { callId, code, message },
    });
  }

  private handleClose(event: { code: number; wasClean: boolean }): void {
    this._ws = null;
    this._sessionReady = false;
    this.emit('close');
    if (this._explicitDisconnect) {
      this.setState('disconnected');
      return;
    }
    if (this._reconnectAttempts >= this._maxRetries) {
      this.setState('error');
      this.failConnect(new Error(`WebSocket closed (${event.code})`));
      return;
    }
    this._reconnectAttempts += 1;
    this.setState('reconnecting');
    const delay = this._reconnectDelay * 2 ** (this._reconnectAttempts - 1);
    this._reconnectTimer = this._setTimeout(() => {
      this._reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private failConnect(error: unknown): void {
    const normalized =
      error instanceof Error ? error : new Error(String(error));
    this._connectReject?.(normalized);
    this._connectResolve = null;
    this._connectReject = null;
    this.setState('error');
    this.emit('error', normalized);
  }

  send(message: OutgoingMessage): void {
    if (!this._sessionReady || !this._ws || this._ws.readyState !== OPEN) {
      this._queue.push(message);
      return;
    }
    if (message.type === 'message_send') {
      console.info('[xxai-agent][conversation] transport sending message', {
        requestId: message.requestId,
        conversationId: this._conversationId,
      });
    }
    this._ws.send(
      JSON.stringify({
        id: message.requestId || this.generateId(),
        type: message.type,
        protocolVersion: 1,
        ...(message.requestId ? { requestId: message.requestId } : {}),
        ...(message.type === 'message_send' && this._conversationId
          ? { conversationId: this._conversationId }
          : {}),
        timestamp: new Date().toISOString(),
        payload: {
          conversationId: this._conversationId,
          ...message.payload,
        },
      }),
    );
  }

  disconnect(): void {
    this._explicitDisconnect = true;
    if (this._reconnectTimer) {
      this._clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._queue = [];
    this._ws?.close(1000);
    this._ws = null;
    this._sessionReady = false;
    this._connectResolve = null;
    this._connectReject = null;
    this.setState('disconnected');
  }

  override on(
    event:
      | 'message'
      | 'open'
      | 'close'
      | 'error'
      | 'state'
      | 'compatibility_error',
    handler: (...args: any[]) => void,
  ): void {
    super.on(event, handler);
  }
  override off(
    event:
      | 'message'
      | 'open'
      | 'close'
      | 'error'
      | 'state'
      | 'compatibility_error',
    handler: (...args: any[]) => void,
  ): void {
    super.off(event, handler);
  }
}
