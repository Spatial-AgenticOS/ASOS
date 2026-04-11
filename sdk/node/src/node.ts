/**
 * TheoraNode — Register as a hardware/device node on the THEORA mesh.
 *
 * @example
 * ```ts
 * const node = new TheoraNode({
 *   nodeId: 'my-sensor',
 *   nodeType: 'sensor',
 *   capabilities: ['temperature', 'humidity'],
 *   brainUrl: 'ws://localhost:9090/v1/daemon',
 * });
 *
 * node.onInvoke(async (action, params) => {
 *   if (action === 'read') return { temp: 22.5 };
 * });
 *
 * await node.connect();
 * node.sendTelemetry({ temperature: 22.5, humidity: 45 });
 * ```
 */

export interface NodeConfig {
  nodeId: string;
  nodeType: string;
  capabilities: string[];
  brainUrl?: string;
}

type InvokeHandler = (action: string, params: Record<string, unknown>) => Promise<unknown>;

export class TheoraNode {
  private config: Required<NodeConfig>;
  private ws: WebSocket | null = null;
  private invokeHandler: InvokeHandler | null = null;

  constructor(config: NodeConfig) {
    this.config = {
      brainUrl: 'ws://localhost:9090/v1/daemon',
      ...config,
    };
  }

  onInvoke(handler: InvokeHandler): void {
    this.invokeHandler = handler;
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.config.brainUrl);

      this.ws.onopen = () => {
        this.ws!.send(JSON.stringify({
          type: 'node_register',
          payload: {
            node_id: this.config.nodeId,
            node_type: this.config.nodeType,
            capabilities: this.config.capabilities,
          },
        }));
        resolve();
      };

      this.ws.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data as string);
          if (msg.type === 'node.invoke' && this.invokeHandler) {
            const { action, params } = msg.payload || {};
            const result = await this.invokeHandler(action, params || {});
            this.ws?.send(JSON.stringify({
              type: 'node.invoke_result',
              payload: { action, result },
            }));
          }
        } catch {}
      };

      this.ws.onerror = () => reject(new Error('WebSocket connection failed'));
    });
  }

  sendTelemetry(data: Record<string, number | string | boolean>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({
      type: 'telemetry',
      payload: { device: this.config.nodeId, data },
    }));
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
  }
}
