import { ChevronLeft, Play, ShieldCheck, Zap } from "lucide-react";
import React from "react";
import { Badge, Button } from "../../components/ui";
import type { AgentConfig, ConfigUpdate } from "../../contracts/schemas";
import { editableAgent } from "../../lib/agents";
import { api } from "../../lib/api";
import type { Row } from "../../lib/types";
import { agentService } from "../../services/platform";
import { AgentConfiguration } from "./AgentConfiguration";
import "./editor.css";

export type AgentEditorProps = {
  startModal: (name: string, initial?: Row) => void;
  setEditor: React.Dispatch<React.SetStateAction<Row | null>>;
  editor: Row;
  busy: boolean;
  canEdit: boolean;
  run: (fn: () => Promise<void>) => Promise<void>;
  refresh: () => void;
  setNotice: React.Dispatch<React.SetStateAction<string>>;
  unsaved: boolean;
  config: AgentConfig;
  setAgentTab: React.Dispatch<React.SetStateAction<string>>;
  setError: React.Dispatch<React.SetStateAction<string>>;
  setSimulator: React.Dispatch<React.SetStateAction<Row | null>>;
  isAdmin: boolean;
  agentTab: string;
  templates: Row[];
  cf: ConfigUpdate;
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
          <p>{unsaved ? "Unsaved changes" : "Saved draft"}</p>
        </div>
        <div className="actions">
          <Button
            kind={unsaved || !editor.id ? "primary" : ""}
            disabled={busy || !canEdit}
            onClick={() =>
              void run(async () => {
                const saved = await agentService.save(
                  {
                    name: editor.name,
                    description: editor.description,
                    config: editor.config,
                    ...(editor.id ? { revision: editor.revision } : {}),
                  },
                  editor.id,
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
            disabled={busy || !canEdit || !editor.id || unsaved}
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
            kind={unsaved || !editor.id ? "" : "primary"}
            disabled={busy || !editor.id || !isAdmin || unsaved}
            onClick={() =>
              void run(async () => {
                const saved = await agentService.publish(editor.id);
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
        <aside className="editor-nav" aria-label="Agent configuration sections">
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
              aria-current={agentTab === tab ? "step" : undefined}
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
              <h2>{agentTab}</h2>
            </div>
          </div>
          <AgentConfiguration
            {...{
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
            }}
          />
        </section>
      </div>
    </>
  );
}
