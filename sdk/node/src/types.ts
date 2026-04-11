/** Core message types for FERAL WebSocket protocol. */

export interface FeralMessage {
  type: string;
  session_id?: string;
  hop?: string;
  payload?: Record<string, unknown>;
  timestamp?: number;
}

export interface TextCommand {
  type: 'text_command';
  payload: { text: string };
  session_id?: string;
}

export interface TextResponse {
  type: 'text_response';
  payload: { text: string };
}

export interface StreamDelta {
  type: 'stream_delta';
  payload: { delta: string; is_final: boolean };
}

export interface SkillEndpoint {
  id: string;
  method: string;
  url: string;
  description: string;
  params: Array<{
    name: string;
    type: string;
    description: string;
    required: boolean;
  }>;
  ui_hint?: string;
}

export interface SkillManifest {
  skill_id: string;
  version: string;
  description: string;
  brand: { name: string; icon: string; color?: string };
  endpoints: SkillEndpoint[];
  trigger_phrases: string[];
  categories: string[];
}

export interface HUPAction {
  action: string;
  params: Record<string, unknown>;
  device_id?: string;
}

export interface HUPTelemetry {
  device: string;
  data: Record<string, number | string | boolean>;
  timestamp?: number;
}

export interface DashboardData {
  devices: Array<{ node_id: string; type: string; connected: boolean }>;
  device_count: number;
  session_count: number;
  health: Record<string, number>;
  memory: Record<string, unknown>;
  skills_count: number;
  llm_available: boolean;
}

export interface SystemInfo {
  version: string;
  config: Record<string, unknown>;
  memory: Record<string, unknown>;
  orchestrator?: {
    multi_agent_enabled: boolean;
    active_subagents: number;
  };
}
