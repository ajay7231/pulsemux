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
  const worklets: any[] = [];
  vi.stubGlobal(
    "AudioWorkletNode",
    class {
      port = { onmessage: null };
      connect = vi.fn().mockReturnThis();
      disconnect = vi.fn();
      constructor() { worklets.push(this); }
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
  return { stop, close, sent, sockets, worklets, getUserMedia, microphone, track };
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

test("recognition preview updates outside history and disappears on final transcript", async () => {
  const f = audioFixture();
  const person = userEvent.setup();
  render(<AgentTest agent={agent} voice="Bella" onClose={() => {}} />);
  await person.click(screen.getByRole("button", { name: /Start call/ }));
  const preview = screen.getByLabelText("Provisional speech recognition") as HTMLElement;
  const history = screen.getByRole("log", { name: "Conversation messages" });
  const emit = (value: any) => act(() => f.sockets[0].onmessage({data: JSON.stringify(value)}));
  emit({type: "transcript_interim", text: "I have been feeling"});
  expect(preview.hidden).toBe(false);
  expect(history.children).toHaveLength(0);
  emit({type: "transcript_interim", text: "I have been feeling dizzy."});
  expect(preview.textContent).toContain("I have been feeling dizzy.");
  expect(history.children).toHaveLength(0);
  emit({type: "transcript", text: "I have been feeling dizzy."});
  expect(preview.hidden).toBe(true);
  expect(history.children).toHaveLength(1);
  emit({type: "transcript_interim", turn_id: "stale", text: "Old recognition"});
  expect(preview.hidden).toBe(true);
  expect(screen.queryByText("Old recognition")).toBeNull();
});

test("server acknowledgement gates media and mute blocks real worklet frames", async () => {
  const f = audioFixture();
  const person = userEvent.setup();
  render(<AgentTest agent={agent} voice="Bella" onClose={() => {}} />);
  await person.click(screen.getByRole("button", { name: /Start call/ }));
  const frame = () => f.worklets[0].port.onmessage({data: new Float32Array(160)});
  act(frame);
  expect(f.sent.filter(m => m.event === "media")).toHaveLength(0);
  expect(screen.getByText("CALL CONNECTING")).toBeTruthy();
  act(() => f.sockets[0].onmessage({data: JSON.stringify({type: "call_started"})}));
  expect(screen.getByText("CALL CONNECTED")).toBeTruthy();
  act(frame);
  expect(f.sent.filter(m => m.event === "media")).toHaveLength(1);
  await person.click(screen.getByRole("button", {name: "Mute mic"}));
  act(frame);
  expect(f.sent.filter(m => m.event === "media")).toHaveLength(1);
  expect(f.track.enabled).toBe(false);
  await person.click(screen.getByRole("button", {name: "Unmute mic"}));
  act(frame);
  expect(f.sent.filter(m => m.event === "media")).toHaveLength(2);
});

test("transcribing and thinking reflect pipeline events and mute clears preview", async () => {
  const f = audioFixture();
  const person = userEvent.setup();
  render(<AgentTest agent={agent} voice="Bella" onClose={() => {}} />);
  await person.click(screen.getByRole("button", {name: /Start call/}));
  const emit = (value: any) => act(() => f.sockets[0].onmessage({data: JSON.stringify(value)}));
  emit({type: "call_started"});
  act(() => { for (let i = 0; i < 25; i++) f.worklets[0].port.onmessage({data: new Float32Array(160)}); });
  emit({type: "turn_committed"});
  expect(screen.getByRole("heading", {name: "Transcribing…"})).toBeTruthy();
  emit({type: "transcript", text: "Hello."});
  expect(screen.getByRole("heading", {name: "Assistant is thinking…"})).toBeTruthy();
  emit({type: "turn_complete", total_turn_ms: 42});
  expect(screen.getByRole("heading", {name: "Listening"})).toBeTruthy();
  emit({type: "transcript_interim", text: "Provisional words"});
  await person.click(screen.getByRole("button", {name: "Mute mic"}));
  expect(screen.getByRole("heading", {name: "Microphone muted"})).toBeTruthy();
  expect((screen.getByLabelText("Provisional speech recognition") as HTMLElement).hidden).toBe(true);
  emit({type: "transcript_interim", text: "Late preview"});
  expect(screen.queryByText("Late preview")).toBeNull();
});

test("recognition failure releases resources and reconnect starts a fresh call", async () => {
  const f = audioFixture();
  const person = userEvent.setup();
  render(<AgentTest agent={agent} voice="Bella" onClose={() => {}} />);
  await person.click(screen.getByRole("button", {name: /Start call/}));
  const oldMessage = f.sockets[0].onmessage;
  act(() => oldMessage({data: JSON.stringify({type: "call_ended", reason: "recognition_failure"})}));
  expect(screen.getByRole("heading", {name: "Disconnected"})).toBeTruthy();
  expect(f.stop).toHaveBeenCalledOnce();
  expect(f.close).toHaveBeenCalledOnce();
  expect(f.worklets[0].disconnect).toHaveBeenCalledOnce();
  expect(f.worklets[0].port.onmessage).toBeNull();
  await person.click(screen.getByRole("button", {name: /Reconnect/}));
  expect(f.sockets).toHaveLength(2);
  expect(screen.getByRole("heading", {name: "Reconnecting…"})).toBeTruthy();
  act(() => oldMessage({data: JSON.stringify({type: "call_ended"})}));
  expect(screen.getByRole("button", {name: /End call/})).toBeTruthy();
  act(() => f.sockets[1].onmessage({data: JSON.stringify({type: "call_started"})}));
  expect(screen.getByText("CALL CONNECTED")).toBeTruthy();
  expect(f.sent.filter(m => m.event === "start")).toHaveLength(2);
  expect(f.sent.filter(m => m.type === "user_text")).toHaveLength(0);
});
