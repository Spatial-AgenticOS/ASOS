/**
 * @theora/sdk — Build plugins, tools, and device adapters for THEORA.
 *
 * @example
 * ```ts
 * import { TheoraClient, definePlugin } from '@theora/sdk';
 *
 * const client = new TheoraClient('http://localhost:9090');
 * const response = await client.chat('Hello!');
 * ```
 */

export { TheoraClient } from './client';
export { definePlugin, type PluginDefinition, type ToolDefinition } from './plugin';
export { TheoraNode, type NodeConfig } from './node';
export type {
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
} from './types';
