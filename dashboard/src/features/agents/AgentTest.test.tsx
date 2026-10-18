import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { AgentTest } from "./AgentTest";

const agent = {
  id: "saved-agent",
  name: "Reception Test Agent",
  revision: 2,
  config: { stt_engine: "deepgram", voice_id: "af_bella" },
};
function audioFixture() {
  const stop = vi.fn();
  const track = { enabled: true, getSettings: () => ({ noiseSuppression: true }) };
  const microphone = {
    getAudioTracks: () => [track],
    getTracks: () => [{ stop }],
  };
  const getUserMedia = vi.fn(async () => microphone);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  const close = vi.fn(async () => {});
  const node = () => ({
    connect: vi.fn().mockReturnThis(),
    disconnect: vi.fn(),
    frequency: { value: 0 },
    Q: { value: 0 },
    gain: { value: 0 },
  });
  vi.stubGlobal(
    "AudioContext",
    class {
      destination = {};
      audioWorklet = { addModule: vi.fn(async () => {}) };
      resume = vi.fn(async () => {});
      close = close;
      createMediaStreamSource = node;
      createBiquadFilter = node;
      createGain = node;
    },
  );
  vi.stubGlobal(
    "AudioWorkletNode",
    class {
      port = { onmessage: null };
      connect = vi.fn().mockReturnThis();
      disconnect = vi.fn();
    },
  );
  const sent: any[] = [];
  const sockets: any[] = [];
  vi.stubGlobal(
    "WebSocket",
    class {
      static OPEN = 1;
      readyState = 1;
      bufferedAmount = 0;
      onopen?: () => void;
      onmessage?: (event: any) => void;
      onclose: any;
      send(value: string) {
        sent.push(JSON.parse(value));
      }
      close = vi.fn();
      constructor() {
        sockets.push(this);
        queueMicrotask(() => this.onopen?.());
      }
    },
  );
  return { stop, close, sent, sockets, getUserMedia, microphone, track };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("dashboard test streams the selected agent and releases call resources when leaving", async () => {
  const f = audioFixture();
  const person = userEvent.setup();
  const view = render(
    <AgentTest agent={agent} voice="Bella · American" onClose={() => {}} />,
  );
  expect(view.container.querySelector("iframe")).toBeNull();
  await person.click(screen.getByRole("button", { name: /Start call/ }));
  await screen.findByRole("button", { name: /End call/ });
  expect(f.sent.find((m) => m.event === "start")).toMatchObject({
    agent_id: "saved-agent",
    draft: true,
  });
  await person.click(screen.getByRole("button", { name: "Mute mic" }));
  expect(f.track.enabled).toBe(false);
  expect(screen.getByRole("button", { name: "Unmute mic" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText("Microphone muted")).toBeTruthy();
  await person.click(screen.getByRole("button", { name: "Unmute mic" }));
  expect(f.track.enabled).toBe(true);
  act(() => {
    f.sockets[0].onmessage({
      data: JSON.stringify({
        type: "transcript",
        text: "What time does reception open?",
      }),
    });
    f.sockets[0].onmessage({
      data: JSON.stringify({ type: "token", delta: "Let me help you." }),
    });
  });
  expect(screen.getByText("What time does reception open?")).toBeTruthy();
  expect(screen.getByText("Let me help you.")).toBeTruthy();
  view.unmount();
  expect(f.stop).toHaveBeenCalledOnce();
  expect(f.close).toHaveBeenCalledOnce();
  expect(f.sockets[0].close).toHaveBeenCalledOnce();
  expect(f.sent.at(-1).event).toBe("stop");
});

test("leaving while microphone permission is pending stops any late stream", async () => {
  const f = audioFixture();
  let allow!: (value: any) => void;
  f.getUserMedia.mockImplementation(
    () =>
      new Promise((resolve) => {
        allow = resolve;
      }),
  );
  const person = userEvent.setup();
  const view = render(
    <AgentTest agent={agent} voice="Bella" onClose={() => {}} />,
  );
  await person.click(screen.getByRole("button", { name: /Start call/ }));
  await waitFor(() => expect(f.getUserMedia).toHaveBeenCalledOnce());
  view.unmount();
  await act(async () => allow(f.microphone));
  expect(f.stop).toHaveBeenCalledOnce();
  expect(f.sockets).toHaveLength(0);
});
