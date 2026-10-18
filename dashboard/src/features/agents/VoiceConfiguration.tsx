import { Plus } from "lucide-react";
import { Field } from "../../components/ui";
import type { AgentConfig } from "../../contracts/schemas";
import { VOICES } from "../../lib/config";
import "./editor.css";
import { ModelSelect } from "./ModelSelect";

import type { AgentEditorProps } from "./AgentEditor";
export function VoiceConfiguration({
  config,
  cf,
  connections,
  isAdmin,
  startModal,
  editor,
  setEditor,
}: Pick<
  AgentEditorProps,
  | "config"
  | "cf"
  | "connections"
  | "isAdmin"
  | "startModal"
  | "editor"
  | "setEditor"
>) {
  const connectionSelect = (
    key: "stt_connection_id" | "llm_connection_id" | "tts_connection_id",
    provider: string | string[],
    label: string,
  ) => {
    const providers = Array.isArray(provider) ? provider : [provider];
    const available = connections.filter(
      (c) => c.active && providers.includes(c.provider),
    );
    const missing = config[key] && !available.some((c) => c.id === config[key]);
    return (
      <div className="connection-picker">
        <Field
          label={label}
          hint={
            !available.length
              ? `Add ${providers.map((p) => (p === "openai" ? "OpenAI" : p[0].toUpperCase() + p.slice(1))).join(" or ")} credentials to connect this part of your agent.`
              : undefined
          }
        >
          <select
            value={config[key] || ""}
            disabled={!available.length}
            onChange={(e) => {
              cf(key, e.target.value || null);
              if (key === "llm_connection_id") cf("llm_model", "");
            }}
          >
            <option value="">
              {available.length
                ? "Choose a saved connection"
                : "No compatible connections yet"}
            </option>
            {missing && (
              <option value={config[key] || ""} disabled>
                Previous connection unavailable
              </option>
            )}
            {available.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.provider === "openai" ? "OpenAI" : c.provider} ·{" "}
                {c.test_status === "valid"
                  ? "Verified"
                  : c.test_status === "failed"
                    ? "Check credentials"
                    : "Not verified"}
              </option>
            ))}
          </select>
        </Field>
        {missing && (
          <p className="field-error">
            This connection is unavailable. Select or add a replacement.
          </p>
        )}
        {isAdmin ? (
          <button
            type="button"
            className="text-button"
            onClick={() =>
              startModal("connection", {
                provider: providers[0],
                name: "",
                _agentField: key,
                _providers: providers,
              })
            }
          >
            <Plus size={14} /> Add connection
          </button>
        ) : (
          <p className="muted">
            Ask a workspace administrator to add credentials.
          </p>
        )}
      </div>
    );
  };

  return (
    <>
      <h3>Understanding the caller</h3>
      <div className="form-grid">
        <Field label="Speech recognition">
          <select
            value={config.stt_engine}
            onChange={(e) => {
              cf("stt_engine", e.target.value as AgentConfig["stt_engine"]);
              cf("stt_connection_id", null);
            }}
          >
            <option value="deepgram">Deepgram Nova-3</option>
            <option value="groq">Groq Whisper Turbo</option>
          </select>
        </Field>
        {connectionSelect(
          "stt_connection_id",
          config.stt_engine,
          "ASR connection",
        )}
      </div>
      <hr />
      <h3>Generating a response</h3>
      {connectionSelect(
        "llm_connection_id",
        ["groq", "openai"],
        "Language model connection",
      )}
      <ModelSelect
        connectionId={config.llm_connection_id}
        revision={
          connections.find((c) => c.id === config.llm_connection_id)?.revision
        }
        value={config.llm_model || ""}
        onChange={(value) => cf("llm_model", value)}
      />
      <hr />
      <h3>Speaking to the caller</h3>
      <div className="form-grid">
        <Field label="Voice provider">
          <select
            value={config.tts_engine}
            onChange={(e) => {
              setEditor({
                ...editor,
                config: {
                  ...config,
                  tts_engine: e.target.value,
                  voice_id:
                    e.target.value === "kokoro"
                      ? "af_bella"
                      : "aura-2-thalia-en",
                  tts_connection_id: null,
                },
              });
            }}
          >
            <option value="kokoro">Kokoro · Local</option>
            <option value="deepgram">Deepgram Aura-2</option>
          </select>
        </Field>
        <Field label="Voice">
          <select
            value={config.voice_id}
            onChange={(e) => cf("voice_id", e.target.value)}
          >
            {Object.entries(VOICES)
              .filter(([key]) =>
                config.tts_engine === "deepgram"
                  ? key.startsWith("aura")
                  : !key.startsWith("aura"),
              )
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </select>
        </Field>
      </div>
      {config.tts_engine === "deepgram" &&
        connectionSelect("tts_connection_id", "deepgram", "TTS connection")}
      <p className="muted">
        Credentials are managed in Connections. Only saved connections from this
        workspace can be used.
      </p>
    </>
  );
}
