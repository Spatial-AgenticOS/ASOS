import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import VoicePanel from "../../../pages/phone/VoicePanel";

function buildShell() {
  return {
    deviceId: "device-1",
    node: {
      startMic: vi.fn(async () => {}),
      stopMic: vi.fn(async () => {}),
    },
    sendFrame: vi.fn(),
    subscribeFrame: () => () => {},
  };
}

describe("VoicePanel", () => {
  it("toggles mic state and sends voice_interrupt", async () => {
    const shell = buildShell();
    const { getByRole, findByRole } = render(
      <MemoryRouter>
        <VoicePanel shell={shell} />
      </MemoryRouter>,
    );

    fireEvent.click(getByRole("button", { name: /tap mic off/i }));

    await waitFor(() => {
      expect(shell.node.startMic).toHaveBeenCalledTimes(1);
    });

    const activeToggle = await findByRole("button", { name: /tap mic on/i });
    expect(activeToggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(getByRole("button", { name: /interrupt/i }));
    expect(shell.sendFrame).toHaveBeenCalledWith(
      "voice_interrupt",
      expect.objectContaining({ reason: "user_interrupt" }),
    );
  });
});
