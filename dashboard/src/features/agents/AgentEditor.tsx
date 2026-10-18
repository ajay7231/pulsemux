import {
  AudioLines,
  BookOpen,
  CalendarClock,
  ChevronLeft,
  ClipboardList,
  Play,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  Zap,
} from "lucide-react";
import React from "react";
import { Badge, Button, Empty, Field } from "../../components/ui";
import { editableAgent } from "../../lib/agents";
import { api } from "../../lib/api";
import { VOICES } from "../../lib/config";
import type { Row } from "../../lib/types";
import "./editor.css";
import { ModelSelect } from "./ModelSelect";

type AgentEditorProps = {
  startModal: (name: string, initial?: Row) => void;
  setEditor: React.Dispatch<React.SetStateAction<Row | null>>;
  editor: Row;
  busy: boolean;
  canEdit: boolean;
  run: (fn: () => Promise<void>) => Promise<void>;
  refresh: () => void;
  setNotice: React.Dispatch<React.SetStateAction<string>>;
  unsaved: boolean;
  config: Row;
  setAgentTab: React.Dispatch<React.SetStateAction<string>>;
  setError: React.Dispatch<React.SetStateAction<string>>;
  setSimulator: React.Dispatch<React.SetStateAction<Row | null>>;
  isAdmin: boolean;
  agentTab: string;
  templates: Row[];
  cf: (key: string, value: any) => void;
  connections: Row[];
  collections: Row[];
};
export function AgentEditor({
  startModal,
  setEditor,
  editor,
  busy,
  canEdit,
  run,
  refresh,
  setNotice,
  unsaved,
  config,
  setAgentTab,
  setError,
  setSimulator,
  isAdmin,
  agentTab,
  templates,
  cf,
  connections,
  collections,
}: AgentEditorProps) {
  const configField = (
    key: string,
    label: string,
    hint?: string,
    area = false,
  ) => (
    <Field label={label} hint={hint}>
      {area ? (
        <textarea
          rows={key === "instructions" ? 8 : 4}
          value={config[key] ?? ""}
          onChange={(e) => cf(key, e.target.value)}
        />
      ) : (
        <input
          value={config[key] ?? ""}
          onChange={(e) => cf(key, e.target.value)}
        />
      )}
    </Field>
  );
  const connectionSelect = (
    key: string,
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
              <option value={config[key]} disabled>
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
      <div className="page-heading">
        <div>
          <button className="back-link" onClick={() => setEditor(null)}>
            <ChevronLeft size={15} />
            All agents
          </button>
          <h1>
            {editor.id ? editor.name : "Create an agent"}{" "}
            {editor.id && <Badge value={editor.status} />}
          </h1>
          <p>Shape the conversation. Test it before your patients hear it.</p>
        </div>
        <div className="actions">
          <Button
            disabled={busy || !canEdit}
            onClick={() =>
              void run(async () => {
                const saved = await api(
                  "/agents" + (editor.id ? "/" + editor.id : ""),
                  editor.id ? "PUT" : "POST",
                  {
                    name: editor.name,
                    description: editor.description,
                    config: editor.config,
                    ...(editor.id ? { revision: editor.revision } : {}),
                  },
                );
                setEditor(editableAgent(saved));
                refresh();
                setNotice("Draft saved. Test this revision before publishing.");
              })
            }
          >
            Save draft
          </Button>
          <Button
            disabled={busy || !editor.id || unsaved}
            onClick={() => {
              if (
                !config.stt_connection_id ||
                !config.llm_connection_id ||
                !config.llm_model ||
                (config.tts_engine === "deepgram" && !config.tts_connection_id)
              ) {
                setAgentTab("Voice & models");
                setError(
                  "Complete the speech recognition connection, language model, and voice settings before testing.",
                );
                return;
              }
              void run(async () => {
                await api("/agents/" + editor.id + "/validate", "POST");
                setSimulator({
                  id: editor.id,
                  draft: true,
                  name: editor.name,
                  revision: editor.revision,
                  config: structuredClone(editor.config),
                });
              });
            }}
          >
            <Play size={15} />
            Test agent
          </Button>
          <Button
            kind="primary"
            disabled={busy || !editor.id || !isAdmin || unsaved}
            onClick={() =>
              void run(async () => {
                const saved = await api(`/agents/${editor.id}/publish`, "POST");
                setEditor(editableAgent(saved));
                refresh();
                setNotice("Agent published. New calls will use this version.");
              })
            }
          >
            <Zap size={15} />
            Publish agent
          </Button>
        </div>
      </div>
      <div className="agent-workspace">
        <aside className="editor-nav">
          {[
            "Identity",
            "Behavior",
            "Voice & models",
            "Knowledge",
            "Actions & safety",
            "Call settings",
          ].map((tab, i) => (
            <button
              key={tab}
              className={agentTab === tab ? "selected" : ""}
              onClick={() => setAgentTab(tab)}
            >
              <span>{String(i + 1).padStart(2, "0")}</span>
              {tab}
            </button>
          ))}
          <div className="editor-note">
            <ShieldCheck size={20} />
            <strong>Changes stay in draft</strong>
            <p>
              Published versions remain fixed for active calls. Save and test
              before publishing.
            </p>
            {editor.tested_revision === editor.revision && editor.id && (
              <Badge value="tested" />
            )}
          </div>
        </aside>
        <section className="card editor-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">AGENT CONFIGURATION</span>
              <h2>{agentTab}</h2>
            </div>
            <SlidersHorizontal size={20} />
          </div>
          {agentTab === "Identity" && (
            <>
              <div className="form-grid">
                <Field label="Agent name">
                  <input
                    value={editor.name}
                    placeholder="e.g. Appointment concierge"
                    onChange={(e) =>
                      setEditor({ ...editor, name: e.target.value })
                    }
                  />
                </Field>
                {configField("department", "Department")}
              </div>
              <Field label="Description">
                <textarea
                  rows={3}
                  value={editor.description}
                  placeholder="What will this agent help your team with?"
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      description: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Workflow template">
                <select
                  value={config.template}
                  onChange={(e) => {
                    const t = templates.find((t) => t.id === e.target.value)!;
                    setEditor({
                      ...editor,
                      config: {
                        ...config,
                        template: t.id,
                        greeting: t.greeting,
                        instructions: t.instructions,
                      },
                    });
                  }}
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="info-panel">
                <CalendarClock size={21} />
                <p>
                  {templates.find((t) => t.id === config.template)?.description}{" "}
                  Templates provide a starting point. Review the instructions
                  for your hospital.
                </p>
              </div>
            </>
          )}
          {agentTab === "Behavior" && (
            <>
              {configField(
                "greeting",
                "Opening greeting",
                "Variables use double braces: {{hospital_name}}, {{patient_name}}, {{appointment_date}}.",
                true,
              )}
              {configField(
                "instructions",
                "Conversation instructions",
                "Define what to ask, what information to collect, and when to involve staff.",
                true,
              )}
              <Field label="Tone">
                <select
                  value={config.tone}
                  onChange={(e) => cf("tone", e.target.value)}
                >
                  {["warm", "professional", "calm"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </Field>
              <div className="info-panel">
                <ShieldCheck size={20} />
                <p>
                  Operating rules always prevent invented bookings,
                  prescriptions, credential disclosure, and unsupported clinical
                  claims.
                </p>
              </div>
            </>
          )}
          {agentTab === "Voice & models" && (
            <>
              <h3>Understanding the caller</h3>
              <div className="form-grid">
                <Field label="Speech recognition">
                  <select
                    value={config.stt_engine}
                    onChange={(e) => {
                      cf("stt_engine", e.target.value);
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
                  connections.find((c) => c.id === config.llm_connection_id)
                    ?.revision
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
                connectionSelect(
                  "tts_connection_id",
                  "deepgram",
                  "TTS connection",
                )}
              <p className="muted">
                Credentials are managed in Connections. Only saved connections
                from this workspace can be used.
              </p>
            </>
          )}
          {agentTab === "Knowledge" && (
            <>
              <p className="muted">
                Attach collections this agent can reference. Only approved,
                unexpired documents are included when publishing.
              </p>
              {collections.length ? (
                collections.map((c) => (
                  <label className="check-card" key={c.id}>
                    <input
                      type="checkbox"
                      checked={config.collection_ids.includes(c.id)}
                      onChange={(e) =>
                        cf(
                          "collection_ids",
                          e.target.checked
                            ? [...config.collection_ids, c.id]
                            : config.collection_ids.filter(
                                (id: string) => id !== c.id,
                              ),
                        )
                      }
                    />
                    <BookOpen size={20} />
                    <div>
                      <strong>{c.name}</strong>
                      <p>{c.description || "Hospital reference collection"}</p>
                    </div>
                  </label>
                ))
              ) : (
                <Empty title="No knowledge collections yet">
                  Create a collection in Knowledge, add documents, and have an
                  administrator approve them.
                </Empty>
              )}
            </>
          )}
          {agentTab === "Actions & safety" && (
            <>
              {[
                ["request_callback", "Create staff callback requests"],
                ["record_outcome", "Record appointment attendance"],
                ["opt_out", "Respect automated-call opt-out requests"],
                ["transfer", "Transfer callers to hospital staff"],
              ].map(([key, label]) => (
                <label className="check-card" key={key}>
                  <input
                    type="checkbox"
                    checked={config.tools.includes(key)}
                    onChange={(e) =>
                      cf(
                        "tools",
                        e.target.checked
                          ? [...config.tools, key]
                          : config.tools.filter((v: string) => v !== key),
                      )
                    }
                  />
                  <div>
                    <strong>{label}</strong>
                  </div>
                </label>
              ))}
              {config.tools.includes("transfer") &&
                configField(
                  "transfer_number",
                  "Staff transfer number",
                  "Include country code, e.g. +919876543210.",
                )}
              {configField(
                "emergency_instructions",
                "Urgent-symptom escalation instructions",
                "Have an authorized clinical lead review these instructions before publishing.",
                true,
              )}
              <div className="info-panel">
                <ClipboardList size={20} />
                <p>
                  Appointment changes create staff requests. This release does
                  not change an external hospital scheduling system.
                </p>
              </div>
            </>
          )}
          {agentTab === "Call settings" && (
            <>
              <div className="form-grid">
                {[
                  ["max_duration_seconds", "Maximum call duration (seconds)"],
                  ["silence_timeout_seconds", "Inactivity timeout (seconds)"],
                  ["end_pause_ms", "End-of-turn pause (milliseconds)"],
                ].map(([key, label]) => (
                  <Field key={key} label={label}>
                    <input
                      type="number"
                      value={config[key]}
                      onChange={(e) => cf(key, Number(e.target.value))}
                    />
                  </Field>
                ))}
              </div>
              <div className="info-panel">
                <AudioLines size={20} />
                <p>
                  Continuous listening, interruption handling, automatic
                  goodbye, and background-noise suppression remain available in
                  the simulator.
                </p>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
