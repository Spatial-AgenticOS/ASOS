import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import PairShell from "../../pages/PairShell";
import ChatPanel from "../../pages/phone/ChatPanel";
import {
  clearAllPhoneBearers,
  setPhoneBearer,
} from "../../lib/phoneBearerStore";

const { browserNodeInstances } = vi.hoisted(() => ({
  browserNodeInstances: [],
}));

vi.mock("../../node/BrowserNode", () => ({
  default: class MockBrowserNode {
    constructor(opts) {
      this.opts = opts;
      this.connect = vi.fn(async () => {
        this.opts?.onPhase?.("connected");
        this.opts?.onPhase?.("registered");
      });
      this.startSensors = vi.fn(async () => {});
      this.startCamera = vi.fn(async () => {});
      this.stopCamera = vi.fn(async () => {});
      this.startMic = vi.fn(async () => {});
      this.stopMic = vi.fn(async () => {});
      this.stop = vi.fn(async () => {});
      this._send = vi.fn(async () => {});
      browserNodeInstances.push(this);
    }
  },
}));

function TestRoutes() {
  return (
    <Routes>
      <Route path="/pair" element={<div>Pair landing</div>} />
      <Route path="/pair/:device_id" element={<PairShell />}>
        <Route index element={<Navigate to="chat" replace />} />
        <Route path="chat" element={<ChatPanel />} />
      </Route>
    </Routes>
  );
}

describe("PairShell", () => {
  beforeEach(async () => {
    browserNodeInstances.length = 0;
    vi.stubGlobal("WebSocket", class {
      constructor() {
        this.readyState = 1;
        setTimeout(() => this.onopen?.(), 0);
      }
      send() {}
      close() {}
    });
    await clearAllPhoneBearers();
    await setPhoneBearer({
      paired_device_id: "device-1",
      phone_bearer: "bearer-1",
      pair_claim_marker: "claim-1",
    });
    localStorage.setItem("feral.pair_claim_marker", "claim-1");
  });

  afterEach(async () => {
    await clearAllPhoneBearers();
    vi.unstubAllGlobals();
  });

  it("renders shell with top bar and tabs, defaulting to chat", async () => {
    const { findByTestId, findByRole } = render(
      <MemoryRouter initialEntries={["/pair/device-1"]}>
        <TestRoutes />
      </MemoryRouter>,
    );

    expect(await findByTestId("pair-shell")).toBeInTheDocument();
    expect(await findByTestId("pair-top-bar")).toBeInTheDocument();
    expect(await findByTestId("pair-capability-tabs")).toBeInTheDocument();
    expect(await findByTestId("phone-chat-panel")).toBeInTheDocument();
    expect(await findByRole("tab", { name: /chat/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(browserNodeInstances).toHaveLength(1);
    });
  });
});
