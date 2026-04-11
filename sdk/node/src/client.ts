/**
 * FeralClient — HTTP + WebSocket client for the FERAL Brain API.
 *
 * @example
 * ```ts
 * const client = new FeralClient('http://localhost:9090');
 * const health = await client.health();
 * const response = await client.chat('What can you do?');
 * ```
 */

import type { DashboardData, SystemInfo, FeralMessage } from './types';

export class FeralClient {
  private baseUrl: string;
  private wsUrl: string;

  constructor(baseUrl: string = 'http://localhost:9090') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.wsUrl = this.baseUrl.replace('http://', 'ws://').replace('https://', 'wss://') + '/v1/session';
  }

  async health(): Promise<{ status: string; version: string }> {
    const res = await fetch(`${this.baseUrl}/api/health`);
    return res.json();
  }

  async getDashboard(): Promise<DashboardData> {
    const res = await fetch(`${this.baseUrl}/api/dashboard`);
    return res.json();
  }

  async getSystemInfo(): Promise<SystemInfo> {
    const res = await fetch(`${this.baseUrl}/api/system/info`);
    return res.json();
  }

  async listSkills(): Promise<Array<Record<string, unknown>>> {
    const res = await fetch(`${this.baseUrl}/api/skills`);
    const data = await res.json();
    return data.skills || data;
  }

  async searchMemory(query: string, limit = 10): Promise<Array<Record<string, unknown>>> {
    const res = await fetch(`${this.baseUrl}/api/memory/search?q=${encodeURIComponent(query)}&limit=${limit}`);
    const data = await res.json();
    return data.results || [];
  }

  async createNote(content: string, tags: string[] = []): Promise<Record<string, unknown>> {
    const res = await fetch(`${this.baseUrl}/api/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, tags }),
    });
    return res.json();
  }

  async chat(message: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      const parts: string[] = [];
      let resolved = false;

      const timeout = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          ws.close();
          resolve(parts.join('') || '[timeout]');
        }
      }, 60000);

      ws.onopen = () => {
        ws.onmessage = (event) => {
          try {
            const msg: FeralMessage = JSON.parse(event.data as string);
            if (msg.type === 'greeting' || (msg.type === 'text_response' && (msg.payload as Record<string, string>)?.text?.includes('connected'))) {
              ws.send(JSON.stringify({
                type: 'text_command',
                session_id: msg.session_id,
                payload: { text: message },
              }));
              return;
            }
            if (msg.type === 'text_response' && !resolved) {
              resolved = true;
              clearTimeout(timeout);
              ws.close();
              resolve((msg.payload as Record<string, string>)?.text || '');
            } else if (msg.type === 'stream_delta') {
              const payload = msg.payload as Record<string, unknown>;
              if (payload.is_final && !resolved) {
                resolved = true;
                clearTimeout(timeout);
                ws.close();
                resolve(parts.join(''));
              } else {
                parts.push((payload.delta as string) || '');
              }
            }
          } catch {}
        };
      };

      ws.onerror = (err) => {
        if (!resolved) {
          resolved = true;
          clearTimeout(timeout);
          reject(new Error('WebSocket error'));
        }
      };
    });
  }
}
