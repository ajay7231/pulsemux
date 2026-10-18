import {
  AudioLines,
  BookOpen,
  CalendarClock,
  ClipboardList,
  ShieldCheck,
} from "lucide-react";
import { Empty, Field } from "../../components/ui";
import type { AgentConfig } from "../../contracts/schemas";
import "./editor.css";
import { VoiceConfiguration } from "./VoiceConfiguration";

import type { AgentEditorProps } from "./AgentEditor";
type TextConfigKey = {
  [K in keyof AgentConfig]: AgentConfig[K] extends string ? K : never;
}[keyof AgentConfig];

export function AgentConfiguration({
  agentTab,
  config,
  cf,
  connections,
  collections,
  isAdmin,
  startModal,
  editor,
  setEditor,
  templates,
}: Pick<
  AgentEditorProps,
  | "agentTab"
  | "config"
  | "cf"
  | "connections"
  | "collections"
  | "isAdmin"
  | "startModal"
  | "editor"
  | "setEditor"
  | "templates"
>) {
  const configField = (
    key: TextConfigKey,
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

  return (
    <>
      {agentTab === "Identity" && (
        <>
          <div className="form-grid">
            <Field label="Agent name">
              <input
                value={editor.name}
                placeholder="e.g. Appointment concierge"
                onChange={(e) => setEditor({ ...editor, name: e.target.value })}
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
              Templates provide a starting point. Review the instructions for
              your hospital.
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
              Operating rules always prevent invented bookings, prescriptions,
              credential disclosure, and unsupported clinical claims.
            </p>
          </div>
        </>
      )}
      {agentTab === "Voice & models" && (
        <VoiceConfiguration
          {...{
            config,
            cf,
            connections,
            isAdmin,
            startModal,
            editor,
            setEditor,
          }}
        />
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
              Appointment changes create staff requests. This release does not
              change an external hospital scheduling system.
            </p>
          </div>
        </>
      )}
      {agentTab === "Call settings" && (
        <>
          <div className="form-grid">
            {(
              [
                ["max_duration_seconds", "Maximum call duration (seconds)"],
                ["silence_timeout_seconds", "Inactivity timeout (seconds)"],
                ["end_pause_ms", "End-of-turn pause (milliseconds)"],
              ] as const
            ).map(([key, label]) => (
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
              Continuous listening, interruption handling, automatic goodbye,
              and background-noise suppression remain available in the
              simulator.
            </p>
          </div>
        </>
      )}
    </>
  );
}
