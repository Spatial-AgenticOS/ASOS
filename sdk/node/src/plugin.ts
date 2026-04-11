/**
 * definePlugin — Declare a FERAL plugin with tools, UI components, and device adapters.
 *
 * @example
 * ```ts
 * const myPlugin = definePlugin({
 *   name: 'weather',
 *   description: 'Real-time weather',
 *   tools: [
 *     {
 *       name: 'current',
 *       description: 'Get current weather',
 *       parameters: { city: { type: 'string', description: 'City name' } },
 *       handler: async (args) => ({ temp: 72, city: args.city }),
 *     },
 *   ],
 * });
 * ```
 */

export interface ToolParameter {
  type: 'string' | 'number' | 'boolean' | 'array' | 'object';
  description: string;
  required?: boolean;
  default?: unknown;
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, ToolParameter>;
  handler: (args: Record<string, unknown>) => Promise<unknown>;
}

export interface PluginDefinition {
  name: string;
  version?: string;
  description?: string;
  tools: ToolDefinition[];
}

export function definePlugin(def: PluginDefinition): PluginDefinition & {
  toManifest: () => Record<string, unknown>;
  execute: (endpoint: string, args: Record<string, unknown>) => Promise<unknown>;
} {
  return {
    ...def,
    toManifest() {
      return {
        skill_id: def.name,
        version: def.version || '1.0.0',
        description: def.description || '',
        brand: { name: def.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), icon: 'puzzle' },
        endpoints: def.tools.map(t => ({
          id: t.name,
          method: 'POST',
          url: `plugin://${def.name}/${t.name}`,
          description: t.description,
          params: Object.entries(t.parameters).map(([name, p]) => ({
            name,
            type: p.type,
            description: p.description,
            required: p.required ?? true,
          })),
        })),
        trigger_phrases: [],
        categories: ['plugin'],
      };
    },
    async execute(endpoint: string, args: Record<string, unknown>) {
      const tool = def.tools.find(t => t.name === endpoint);
      if (!tool) throw new Error(`Unknown endpoint: ${endpoint}`);
      return tool.handler(args);
    },
  };
}
