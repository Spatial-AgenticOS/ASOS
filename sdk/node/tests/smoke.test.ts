/**
 * Smoke tests for the public `@feral/sdk` Node package.
 *
 * These exercise only the public surface that `sdk/node/src/index.ts`
 * advertises: the `FeralClient` HTTP+WS client, the `definePlugin`
 * helper, and the `FeralNode` class. Network calls are intentionally
 * out of scope here; deeper integration tests can add a brain mock
 * later.
 *
 * The point is to fail loudly when:
 *   - a top-level export goes missing,
 *   - `FeralClient`'s constructor stops accepting a plain string, or
 *   - the URL-rewriting logic for ws:// drifts (this has bitten the
 *     web client at least twice — keep it pinned here too).
 */

import { describe, it, expect } from "vitest";

describe("@feral/sdk public surface", () => {
  it("imports cleanly and exposes the documented entry points", async () => {
    const sdk = await import("@feral/sdk");
    expect(sdk).toBeTruthy();
    expect(typeof sdk.FeralClient).toBe("function");
    expect(typeof sdk.definePlugin).toBe("function");
    expect(typeof sdk.FeralNode).toBe("function");
  });

  it("FeralClient instantiates with the default brain URL", async () => {
    const { FeralClient } = await import("@feral/sdk");
    const client = new FeralClient();
    // The class fields are private, so we only assert observable
    // behaviour: methods exist and are callable signatures.
    expect(typeof client.health).toBe("function");
    expect(typeof client.chat).toBe("function");
    expect(typeof client.getDashboard).toBe("function");
    expect(typeof client.listSkills).toBe("function");
  });

  it("FeralClient accepts a custom http base URL and rewrites to ws", async () => {
    // Construct via reflection so we can read the (private) wsUrl field
    // without forcing an export of internal state. If the rewrite logic
    // changes, this will fail loudly.
    const { FeralClient } = await import("@feral/sdk");
    const client = new FeralClient("https://brain.example.com/");
    const internal = client as unknown as { baseUrl: string; wsUrl: string };
    expect(internal.baseUrl).toBe("https://brain.example.com");
    expect(internal.wsUrl).toBe("wss://brain.example.com/v1/session");
  });

  it("FeralClient rewrites http → ws for the realtime path", async () => {
    const { FeralClient } = await import("@feral/sdk");
    const client = new FeralClient("http://localhost:9090");
    const internal = client as unknown as { wsUrl: string };
    expect(internal.wsUrl).toBe("ws://localhost:9090/v1/session");
  });

  it("definePlugin returns a structured plugin definition", async () => {
    const { definePlugin } = await import("@feral/sdk");
    const plugin = definePlugin({
      name: "smoke-plugin",
      version: "0.0.1",
      tools: [],
    });
    expect(plugin).toBeTruthy();
    expect(plugin.name).toBe("smoke-plugin");
    expect(Array.isArray(plugin.tools)).toBe(true);
  });

  it("FeralNode is a constructible class", async () => {
    const { FeralNode } = await import("@feral/sdk");
    expect(typeof FeralNode).toBe("function");
    // We do not actually open a websocket here; just assert the class
    // shape so a refactor that drops the `FeralNode` named export trips
    // this test instead of a downstream user.
    expect(FeralNode.prototype).toBeTruthy();
  });
});
