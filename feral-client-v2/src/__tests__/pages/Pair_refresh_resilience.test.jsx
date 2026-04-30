import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import {
  clearAllPhoneBearers,
  setPhoneBearer,
} from "../../lib/phoneBearerStore";

const browserNodeSpies = vi.hoisted(() => ({
  connect: vi.fn().mockResolvedValue(undefined),
  startSensors: vi.fn().mockResolvedValue(undefined),
  stop: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../node/BrowserNode", () => ({
  default: class MockBrowserNode {
    constructor(opts = {}) {
      this.opts = opts;
    }

    async connect() {
      this.opts.onPhase?.("connected");
      this.opts.onPhase?.("registered");
      return browserNodeSpies.connect();
    }

    async startSensors() {
      return browserNodeSpies.startSensors();
    }

    async stop() {
      return browserNodeSpies.stop();
    }

    async startMic() {}
    async stopMic() {}
    async startCamera() {}
    async stopCamera() {}
  },
}));

import Pair from "../../pages/Pair";

function renderAt(url) {
  window.history.replaceState({}, "", url);
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Pair />
    </MemoryRouter>,
  );
}

describe("Pair refresh resilience", () => {
  beforeEach(async () => {
    browserNodeSpies.connect.mockClear();
    browserNodeSpies.startSensors.mockClear();
    browserNodeSpies.stop.mockClear();
    await clearAllPhoneBearers();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
        text: () => Promise.resolve("{}"),
      })),
    );
  });

  it("renders paired view directly when phone bearer is already persisted", async () => {
    await setPhoneBearer({
      paired_device_id: "paired-1",
      phone_bearer: "d".repeat(64),
      pair_claim_marker: "claim-restore-1",
    });

    renderAt("/pair?t=restored-token");

    await waitFor(() => {
      expect(browserNodeSpies.connect).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(browserNodeSpies.startSensors).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Pair this device/i })).not.toBeInTheDocument();
    });
    expect(browserNodeSpies.connect).toHaveBeenCalledTimes(1);
  });

  it("renders the pair form when no persisted marker exists", async () => {
    renderAt("/pair?t=pair-token-123");

    expect(await screen.findByRole("heading", { name: /Pair this device/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Paired/i })).not.toBeInTheDocument();
  });
});
