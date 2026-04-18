/*
 * Public entrypoint for @feral-ai/node-sdk.
 * Re-exports the FeralNode class, capability enum, schemas, and helpers.
 */

export { FeralNode } from "./node";
export type {
  ActionHandler,
  FeralNodeOptions,
} from "./node";
export { Capability, tierFor } from "./capability";
export type { CapabilityName } from "./capability";
export { discoverBrain } from "./discovery";
export { pair, loadKey, saveKey, generateCode } from "./pairing";
export type { PairOptions } from "./pairing";
export * as schemas from "./schemas";
export { HUP_VERSION } from "./schemas";
