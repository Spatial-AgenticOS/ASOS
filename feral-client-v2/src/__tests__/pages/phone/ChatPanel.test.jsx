import { describe, it, expect, vi } from "vitest";
import { act, fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ChatPanel from "../../../pages/phone/ChatPanel";

function buildShell() {
  const listeners = new Set();
  return {
    shell: {
      deviceId: "device-1",
      sendFrame: vi.fn(),
      subscribeFrame: (listener) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    },
    pushFrame: (frame) => {
      listeners.forEach((listener) => listener(frame));
    },
  };
}

describe("ChatPanel", () => {
  it("sends chat_request and renders incoming chat_response", async () => {
    const { shell, pushFrame } = buildShell();
    const { getByLabelText, getByRole, findByText } = render(
      <MemoryRouter>
        <ChatPanel shell={shell} />
      </MemoryRouter>,
    );

    fireEvent.change(getByLabelText(/chat input/i), {
      target: { value: "hello brain" },
    });
    fireEvent.click(getByRole("button", { name: /send/i }));

    expect(shell.sendFrame).toHaveBeenCalledWith(
      "chat_request",
      expect.objectContaining({
        text: "hello brain",
        channel: "chat",
      }),
    );

    act(() => {
      pushFrame({
        type: "chat_response",
        payload: { text: "hello phone" },
      });
    });

    expect(await findByText("hello phone")).toBeInTheDocument();
  });
});
