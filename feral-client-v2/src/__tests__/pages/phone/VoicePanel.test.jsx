import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import VoicePanel from "../../../pages/phone/VoicePanel";

vi.mock("../../../pages/phone/VoiceFullscreen", () => {
  const MockFullscreen = ({ open, onClose }) => (
    open ? (
      <div data-testid="voice-fullscreen">
        <button data-testid="voice-fullscreen-close" onClick={onClose} type="button">
          Close
        </button>
      </div>
    ) : null
  );
  return {
    VoiceFullscreen: MockFullscreen,
    default: MockFullscreen,
  };
});

function buildShell() {
  return {
    deviceId: "device-1",
    voice_config: { mode: "openai_realtime" },
    node: {
      startMic: vi.fn(async () => {}),
      stopMic: vi.fn(async () => {}),
    },
    sendFrame: vi.fn(),
    subscribeFrame: () => () => {},
  };
}

describe("VoicePanel", () => {
  it("starts voice session and mic from Start voice CTA", async () => {
    const shell = buildShell();
    const { getByTestId } = render(
      <MemoryRouter>
        <VoicePanel shell={shell} />
      </MemoryRouter>,
    );

    fireEvent.click(getByTestId("start-voice-button"));

    await waitFor(() => {
      expect(shell.node.startMic).toHaveBeenCalledTimes(1);
    });

    expect(shell.sendFrame).toHaveBeenCalledWith(
      "voice_session_start",
      expect.objectContaining({
        voice_mode: "openai_realtime",
        sample_rate: 24000,
        channels: 1,
        language_hint: "en-US",
      }),
    );
  });

  it("stops mic and sends user_close interrupt on fullscreen close", async () => {
    const shell = buildShell();
    const { getByTestId } = render(
      <MemoryRouter>
        <VoicePanel shell={shell} />
      </MemoryRouter>,
    );

    fireEvent.click(getByTestId("start-voice-button"));
    await waitFor(() => {
      expect(getByTestId("voice-fullscreen")).toBeInTheDocument();
    });
    fireEvent.click(getByTestId("voice-fullscreen-close"));

    await waitFor(() => {
      expect(shell.node.stopMic).toHaveBeenCalledTimes(1);
    });
    expect(shell.sendFrame).toHaveBeenCalledWith("voice_interrupt", expect.objectContaining({
      reason: "user_close",
    }));
  });
});
