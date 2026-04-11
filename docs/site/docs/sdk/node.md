---
id: node
title: Node SDK
sidebar_position: 2
slug: /sdk/node
---

# Node / TypeScript SDK

The `@theora/sdk` package provides a TypeScript client for the THEORA Brain API, plugin helpers, and a hardware node class.

```bash
npm install @theora/sdk
```

## TheoraClient

```typescript
import { TheoraClient } from '@theora/sdk';

const client = new TheoraClient('http://localhost:9090');

// Health check
const health = await client.health();
console.log(health.version);

// Chat
const reply = await client.chat('What can you do?');
console.log(reply);

// Dashboard
const dashboard = await client.getDashboard();
console.log(dashboard.skills_count);

// System info
const info = await client.getSystemInfo();

// Skills
const skills = await client.listSkills();

// Memory
const results = await client.searchMemory('project deadlines');
await client.createNote('Ship v1.3 by Friday', ['work']);
```

### Constructor

```typescript
new TheoraClient(baseUrl?: string)  // default: 'http://localhost:9090'
```

### Methods

| Method | Return | Description |
|:-------|:-------|:------------|
| `health()` | `Promise<{ status, version }>` | Brain health status |
| `getDashboard()` | `Promise<DashboardData>` | Aggregated dashboard data |
| `getSystemInfo()` | `Promise<SystemInfo>` | Version, memory stats, provider info |
| `chat(message)` | `Promise<string>` | Send a message via WebSocket, get the response |
| `listSkills()` | `Promise<Array<Record>>` | All registered skills |
| `searchMemory(query, limit?)` | `Promise<Array<Record>>` | Search the agent's memory |
| `createNote(content, tags?)` | `Promise<Record>` | Create a persistent memory note |

## definePlugin

Create plugins using the `definePlugin` helper:

```typescript
import { definePlugin } from '@theora/sdk';

const weatherPlugin = definePlugin({
  name: 'weather',
  description: 'Real-time weather data',
  version: '0.1.0',
  tools: [
    {
      name: 'current',
      description: 'Get current weather for a city',
      parameters: {
        city: { type: 'string', description: 'City name', required: true },
      },
      handler: async ({ city }) => {
        return { city, temp_f: 72, condition: 'sunny' };
      },
    },
  ],
});
```

### PluginDefinition

```typescript
interface PluginDefinition {
  name: string;
  description: string;
  version?: string;
  tools: ToolDefinition[];
}

interface ToolDefinition {
  name: string;
  description: string;
  parameters?: Record<string, {
    type: string;
    description?: string;
    required?: boolean;
  }>;
  handler: (args: Record<string, unknown>) => Promise<unknown>;
}
```

## TheoraNode

Connect hardware or virtual devices to the Brain:

```typescript
import { TheoraNode } from '@theora/sdk';

const node = new TheoraNode({
  nodeId: 'my-sensor',
  nodeType: 'sensor',
  capabilities: ['temperature', 'humidity'],
  brainUrl: 'ws://localhost:9090/v1/node',
});

await node.connect();

// Send telemetry
setInterval(async () => {
  await node.sendTelemetry({
    temperature_c: 22.5,
    humidity_pct: 45,
  });
}, 5000);

// Listen for commands
node.onCommand(async (action, params) => {
  console.log('Received command:', action, params);
  return { ok: true };
});
```

### NodeConfig

```typescript
interface NodeConfig {
  nodeId: string;
  nodeType: string;
  capabilities: string[];
  brainUrl?: string;  // default: 'ws://localhost:9090/v1/node'
  apiKey?: string;     // default: 'dev-secret-key'
}
```

## Types

The SDK exports the full set of wire-protocol types:

```typescript
import type {
  TheoraMessage,
  TextCommand,
  TextResponse,
  StreamDelta,
  SkillManifest,
  SkillEndpoint,
  HUPAction,
  HUPTelemetry,
  DashboardData,
  SystemInfo,
} from '@theora/sdk';
```

See the [Python SDK](./python.md) for the equivalent Python API.
