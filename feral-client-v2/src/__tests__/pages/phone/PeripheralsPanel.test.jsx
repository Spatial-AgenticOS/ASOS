import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import PeripheralsPanel from "../../../pages/phone/PeripheralsPanel";

function setUserAgent(value) {
  Object.defineProperty(window.navigator, "userAgent", {
    value,
    configurable: true,
  });
}

function setBluetooth(value) {
  Object.defineProperty(window.navigator, "bluetooth", {
    value,
    configurable: true,
  });
}

describe("PeripheralsPanel", () => {
  beforeEach(() => {
    setUserAgent("Mozilla/5.0");
    setBluetooth(undefined);
  });

  it("shows iOS unsupported message when bluetooth is unavailable", () => {
    setUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Safari/605.1.15");
    setBluetooth(undefined);

    const { getByText } = render(
      <MemoryRouter>
        <PeripheralsPanel shell={{ sendFrame: vi.fn() }} />
      </MemoryRouter>,
    );

    expect(
      getByText(/Web Bluetooth not supported on iOS — use the FERAL iOS app\./i),
    ).toBeInTheDocument();
  });

  it("shows Add device action when bluetooth is available", () => {
    setUserAgent("Mozilla/5.0 (Linux; Android 14) Chrome/125.0 Mobile");
    setBluetooth({ requestDevice: vi.fn(async () => ({ id: "dev-1", name: "Band" })) });

    const { getByRole } = render(
      <MemoryRouter>
        <PeripheralsPanel shell={{ sendFrame: vi.fn(), deviceId: "device-1" }} />
      </MemoryRouter>,
    );

    expect(getByRole("button", { name: /add device/i })).toBeInTheDocument();
  });
});
