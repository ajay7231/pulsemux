import { ArrowLeft, AudioLines, Mic, Phone, ShieldCheck } from "lucide-react";
import { useEffect, useRef } from "react";
import {
  createCallSimulator,
  type CallController,
} from "../../../../worker-py/web/call.js";
import "./test-call.css";
import { PlivoLocalTest } from "./PlivoLocalTest";

type Agent = {
  id: string;
  name: string;
  revision: number;
  config: Record<string, any>;
};

// The call controller owns disabled state. A React disabled prop also suppresses
// synthetic clicks after the controller enables the underlying DOM button.
function initiallyDisableCallControl(button: HTMLButtonElement | null) {
  if (button) button.disabled = true;
}

export function AgentTest({
  agent,
  voice,
  onClose,
}: {
  agent: Agent;
  voice: string;
  onClose: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const controller = useRef<CallController | null>(null);
  useEffect(() => {
    if (!root.current) return;
    const call = createCallSimulator(root.current, { agent, draft: true });
    controller.current = call;
    return () => {
      call.destroy();
      controller.current = null;
    };
  }, [agent]);

  return (
    <div className="agent-test" ref={root}>
      <button className="text-button test-back" onClick={onClose}>
        <ArrowLeft size={16} /> Back to agent
      </button>
      <div className="page-heading">
        <div>
          <h1>{agent.name}</h1>
          <p>Test conversation</p>
        </div>
        <div className="actions">
          <PlivoLocalTest agentId={agent.id} />
          <span className="test-draft">Draft · revision {agent.revision}</span>
        </div>
      </div>
      <div className="test-context">
        <ShieldCheck size={17} />
        <span>
          This test uses your saved agent settings. Conversations appear in Call
          history.
        </span>
      </div>
      <div className="test-workspace">
        <section className="card test-call" aria-label="Test call controls">
          <div className="section-heading">
            <h2>Test call</h2>
            <span data-call="connection-status" className="test-connection">
              CALL OFFLINE
            </span>
          </div>
          <div className="test-call-center">
            <div data-call="orb-core" className="orb">
              <Mic size={32} />
            </div>
            <h3 data-call="status-title" aria-live="polite">
              Ready when you are
            </h3>
            <p data-call="status-desc">
              Start a call and speak naturally. The agent listens between turns.
            </p>
            <div className="test-call-buttons">
              <button
                data-call="btn-record"
                className="button primary"
                onClick={() => void controller.current?.toggleCall()}
              >
                <Phone size={16} />
                <span data-call="btn-record-text">Start call</span>
              </button>
              <button
                data-call="btn-mute"
                className="button"
                ref={initiallyDisableCallControl}
                aria-pressed="false"
                onClick={() => controller.current?.toggleMute()}
              >
                Mute mic
              </button>
            </div>
            <div className="test-duration">
              Call duration <strong data-call="call-duration">00:00</strong>
            </div>
          </div>
          <div className="test-audio-settings">
            <div className="test-meter" aria-hidden="true">
              <div data-call="mic-level" />
            </div>
            <div className="test-room">
              <span data-call="noise-status">Microphone off</span>
              <span>
                Room <span data-call="noise-level">— dB</span>
              </span>
            </div>
            <label className="test-noise">
              <input
                data-call="noise-suppression"
                type="checkbox"
                defaultChecked
              />{" "}
              Reduce background noise
            </label>
            <p
              data-call="call-notice"
              role="status"
              aria-live="polite"
              className="test-call-notice"
            />
          </div>
          <div className="test-saved-settings">
            <span>Saved voice</span>
            <strong>{voice}</strong>
            <span>Speech recognition</span>
            <strong>
              {agent.config.stt_engine === "groq"
                ? "Groq Whisper"
                : "Deepgram Nova-3"}
            </strong>
          </div>
          <div data-call="triage-badge" className="test-triage">
            <span data-call="triage-label">CLINICAL TRIAGE STANDBY</span>
          </div>
          <input
            data-call="select-stt"
            type="hidden"
            value={agent.config.stt_engine}
            readOnly
          />
          <input
            data-call="select-voice"
            type="hidden"
            value={agent.config.voice_id}
            readOnly
          />
        </section>
        <section
          className="card test-transcript"
          aria-label="Live test transcript"
        >
          <div className="section-heading">
            <div>
              <h2>Live transcript</h2>
            </div>
            <button
              className="text-button"
              data-call="btn-export"
              ref={initiallyDisableCallControl}
              onClick={() => controller.current?.downloadMeasurements()}
            >
              Export timings
            </button>
          </div>
          <div className="test-transcript-body">
            <div className="test-transcript-empty">
              <AudioLines size={28} />
              <h3>No messages yet</h3>
              <p>Start a call to see what you and your agent say.</p>
            </div>
            <div
              data-call="messages-container"
              className="test-messages"
              role="log"
              aria-label="Conversation messages"
              aria-live="polite"
            />
            <aside
              data-call="interim-container"
              className="test-interim"
              aria-label="Provisional speech recognition"
              hidden
            >
              <div className="test-interim-heading">
                <span>Hearing you</span>
                <span>Not final</span>
              </div>
              <p data-call="interim-text" />
            </aside>
          </div>
          <form
            className="test-message-form"
            onSubmit={(event) => {
              event.preventDefault();
              controller.current?.sendTextMessage();
            }}
          >
            <input
              data-call="user-text-input"
              aria-label="Message your agent"
              placeholder="Or type a message during the call…"
              disabled
            />
            <button
              className="button"
              data-call="btn-send"
              type="submit"
              disabled
            >
              Send
            </button>
          </form>
        </section>
      </div>
      <div className="test-metrics" aria-label="Call performance">
        {[
          ["hud-stt", "Speech recognition"],
          ["hud-ttft", "First response"],
          ["hud-tts", "Voice generation"],
          ["hud-total", "Turn duration"],
          ["hud-speech-playback", "Speech → playback"],
          ["hud-commit-playback", "Commit notice → playback"],
        ].map(([id, label]) => (
          <div key={id}>
            <span data-call={id === "hud-tts" ? "hud-tts-label" : undefined}>
              {label}
            </span>
            <strong data-call={id}>— ms</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
